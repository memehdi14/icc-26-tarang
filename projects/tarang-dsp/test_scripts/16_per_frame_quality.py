#!/usr/bin/env python3
"""
16_per_frame_quality.py — Tarang DSP Finalization Item G

Tag every 256-sample Tarang frame with a quality verdict:
  GOOD          — clean ECG, no motion, R-peaks detected
  MOTION        — motion detected, NLMS active, may still be usable
  NOISY         — high ECG noise without motion (cable/electrode issue)
  LEAD_OFF      — lead-off flag high for >10% of frame
  SATURATED     — ADC saturated for >5% of frame
  LOW_CONFIDENCE — multiple issues, BLOCK from AI

Quality verdict is added to summary.json and per-frame CSV.

Usage:
    python 16_per_frame_quality.py tarang_20260702_133137.csv

Targets:
  - Every frame has a quality_verdict
  - BAD frames (SATURATED, LEAD_OFF, LOW_CONFIDENCE) blocked from AI
  - LOW_CONFIDENCE frames not classified as clinical events
"""
import sys, os, json
import numpy as np
from scipy.signal import butter, filtfilt, sosfiltfilt, iirnotch
from scipy.ndimage import uniform_filter1d

ECG_HZ = 250
FRAME_LEN = 256

def load_csv(path):
    rows = []; header = None
    with open(path, 'r', encoding='ascii', errors='ignore') as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith('#'): continue
            fields = s.split(',')
            if header is None: header = fields; continue
            if len(fields) < 10: continue
            try: rows.append([float(x) for x in fields[:10]])
            except ValueError: continue
    arr = np.array(rows, dtype=np.float64)
    return {
        't_us': arr[:,0], 'ecg_raw': arr[:,3], 'ecg_mv': arr[:,4],
        'ax': arr[:,5], 'ay': arr[:,6], 'az': arr[:,7],
        'imu_mag': arr[:,8], 'lo+': arr[:,9],
    }

def calibrate_motion_gate(imu_mag, rest_seconds=10):
    rest_n = min(len(imu_mag), rest_seconds * ECG_HZ)
    baseline = float(np.median(imu_mag[:rest_n]))
    rest_dev = imu_mag[:rest_n] - baseline
    mad = float(np.median(np.abs(rest_dev - np.median(rest_dev))))
    threshold = max(3.0 * mad * 1.4826, 50.0)
    return baseline, threshold, np.abs(imu_mag - baseline) > threshold

def classify_frame(ecg_raw, ecg_mv, imu_mag, lo_plus, motion_mask, r_peak_count):
    """Classify a single 256-sample frame."""
    # Saturation: ADC raw < 200 or > 3900
    sat_low_pct = 100.0 * np.sum(ecg_raw < 200) / len(ecg_raw)
    sat_high_pct = 100.0 * np.sum(ecg_raw > 3900) / len(ecg_raw)
    sat_pct = sat_low_pct + sat_high_pct

    # Lead-off
    leadoff_pct = 100.0 * np.sum(lo_plus > 0.5) / len(lo_plus)

    # Motion
    motion_pct = 100.0 * np.sum(motion_mask) / len(motion_mask)

    # ECG noise (RMS of high-pass filtered ECG)
    # If motion_pct is low but ECG RMS is high, it's "noise without motion"
    ecg_centered = ecg_mv - np.mean(ecg_mv)
    ecg_rms = float(np.sqrt(np.mean(ecg_centered**2)))

    # Verdict logic (priority order)
    if sat_pct > 5.0:
        verdict = 'SATURATED'
        ai_block = True
    elif leadoff_pct > 10.0:
        verdict = 'LEAD_OFF'
        ai_block = True
    elif motion_pct > 30.0 and ecg_rms > 100:
        verdict = 'MOTION'
        ai_block = False  # may still be usable with NLMS
    elif motion_pct < 10.0 and ecg_rms > 150:
        verdict = 'NOISY'
        ai_block = True
    elif r_peak_count == 0:
        verdict = 'LOW_CONFIDENCE'
        ai_block = True
    elif motion_pct > 10.0 and ecg_rms > 100:
        verdict = 'MOTION'  # milder motion
        ai_block = False
    else:
        verdict = 'GOOD'
        ai_block = False

    # Override: if multiple issues, LOW_CONFIDENCE
    issues = 0
    if sat_pct > 1: issues += 1
    if leadoff_pct > 5: issues += 1
    if motion_pct > 30: issues += 1
    if ecg_rms > 200: issues += 1
    if r_peak_count == 0: issues += 1
    if issues >= 3:
        verdict = 'LOW_CONFIDENCE'
        ai_block = True

    return {
        'verdict': verdict,
        'ai_block': ai_block,
        'saturation_pct': sat_pct,
        'leadoff_pct': leadoff_pct,
        'motion_pct': motion_pct,
        'ecg_rms': ecg_rms,
        'r_peak_count': r_peak_count,
    }

def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    path = sys.argv[1]
    data = load_csv(path)
    ecg_raw = data['ecg_raw']
    ecg_mv = data['ecg_mv']
    imu_mag = data['imu_mag']
    lo_plus = data['lo+']
    t_us = data['t_us']

    # DSP + Pan-Tompkins
    def bp(x):
        sos = butter(2, [0.5/(ECG_HZ/2), 40.0/(ECG_HZ/2)], btype='band', output='sos')
        return sosfiltfilt(sos, x - np.mean(x))
    def notch(x):
        b, a = iirnotch(50.0, 30.0, fs=ECG_HZ)
        return filtfilt(b, a, x)
    ecg_filt = notch(bp(ecg_mv))

    # Calibrated motion gate
    baseline, threshold, motion_mask = calibrate_motion_gate(imu_mag)

    # Simple R-peak detection per frame
    def pt_simple(ecg_segment, fs=ECG_HZ):
        if len(ecg_segment) < fs: return 0
        ny = fs/2.0
        b, a = butter(2, [5.0/ny, 15.0/ny], btype='band')
        bp_s = filtfilt(b, a, ecg_segment)
        d = np.zeros_like(bp_s)
        for i in range(2, len(bp_s)-2):
            d[i] = (-bp_s[i-2] - 2*bp_s[i-1] + 2*bp_s[i+1] + bp_s[i+2]) / 8.0
        sq = d**2
        mwi_w = max(1, int(fs*0.15))
        k = np.ones(mwi_w)/mwi_w
        sig = np.convolve(sq, k, mode='full')[:len(bp_s)]
        refractory = int(fs*0.25)
        sig_nz = sig[sig > 0]
        if len(sig_nz) == 0: return 0
        SPKI = float(np.percentile(sig_nz, 95.0))
        NPKI = float(np.percentile(sig_nz, 50.0))
        if SPKI <= NPKI: SPKI = NPKI * 2
        THR1 = NPKI + 0.25*(SPKI - NPKI)
        count = 0; last_peak = -refractory
        for i in range(1, len(sig)-1):
            if sig[i] > sig[i-1] and sig[i] >= sig[i+1] and sig[i] > THR1:
                if i - last_peak >= refractory:
                    count += 1; last_peak = i
        return count

    # Per-frame classification
    n_frames = len(ecg_mv) // FRAME_LEN
    print(f'=== PER-FRAME QUALITY VERDICT ===')
    print(f'Recording: {os.path.basename(path)}')
    print(f'Frames: {n_frames} (each {FRAME_LEN} samples = {FRAME_LEN/ECG_HZ:.3f} s)')

    frame_results = []
    verdict_counts = {'GOOD': 0, 'MOTION': 0, 'NOISY': 0,
                      'LEAD_OFF': 0, 'SATURATED': 0, 'LOW_CONFIDENCE': 0}
    ai_blocked = 0

    for fi in range(n_frames):
        s = fi * FRAME_LEN; e = s + FRAME_LEN
        frame_ecg_raw = ecg_raw[s:e]
        frame_ecg_mv = ecg_mv[s:e]
        frame_imu = imu_mag[s:e]
        frame_lo = lo_plus[s:e]
        frame_motion = motion_mask[s:e]
        frame_filt = ecg_filt[s:e]

        r_count = pt_simple(frame_filt)
        verdict_info = classify_frame(frame_ecg_raw, frame_ecg_mv, frame_imu,
                                       frame_lo, frame_motion, r_count)
        verdict_counts[verdict_info['verdict']] += 1
        if verdict_info['ai_block']:
            ai_blocked += 1
        frame_results.append({
            'frame_idx': fi,
            't_start_us': int(t_us[s]),
            't_end_us': int(t_us[e-1]),
            **verdict_info,
        })

    # Summary
    print(f'\n--- Verdict distribution ---')
    for v, c in verdict_counts.items():
        pct = 100.0 * c / n_frames if n_frames > 0 else 0
        print(f'  {v:15s}: {c:4d} frames ({pct:5.1f}%)')
    print(f'\n  AI-blocked frames: {ai_blocked} ({100*ai_blocked/n_frames:.1f}%)')
    print(f'  AI-eligible frames: {n_frames - ai_blocked} ({100*(n_frames-ai_blocked)/n_frames:.1f}%)')

    # Save updated summary.json
    out_dir = path.replace('.csv', '_frames')
    os.makedirs(out_dir, exist_ok=True)
    summary = {
        'frame_count': n_frames,
        'frame_len': FRAME_LEN,
        'verdict_counts': verdict_counts,
        'ai_blocked_frames': ai_blocked,
        'ai_eligible_frames': n_frames - ai_blocked,
        'frames': frame_results,
    }
    out_json = os.path.join(out_dir, 'quality_summary.json')
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    print(f'\nSaved: {out_json}')

    # Save per-frame CSV with verdict
    out_csv = path.replace('.csv', '_frame_quality.csv')
    with open(out_csv, 'w', encoding='utf-8') as f:
        f.write('frame_idx,t_start_us,t_end_us,verdict,ai_block,saturation_pct,leadoff_pct,motion_pct,ecg_rms,r_peak_count\n')
        for r in frame_results:
            f.write(f'{r["frame_idx"]},{r["t_start_us"]},{r["t_end_us"]},'
                    f'{r["verdict"]},{int(r["ai_block"])},'
                    f'{r["saturation_pct"]:.2f},{r["leadoff_pct"]:.2f},'
                    f'{r["motion_pct"]:.2f},{r["ecg_rms"]:.2f},{r["r_peak_count"]}\n')
    print(f'Saved: {out_csv}')

    # === Plot verdict over time ===
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(14, 5), constrained_layout=True)
    verdict_colors = {'GOOD': 'green', 'MOTION': 'orange', 'NOISY': 'gray',
                      'LEAD_OFF': 'red', 'SATURATED': 'darkred', 'LOW_CONFIDENCE': 'purple'}
    for fi, r in enumerate(frame_results):
        ax.bar(fi, 1, color=verdict_colors[r['verdict']], alpha=0.7)
    ax.set_xlabel('Frame index'); ax.set_ylabel('verdict')
    ax.set_yticks([])
    ax.set_title(f'Per-frame quality verdict — {n_frames} frames ({ai_blocked} AI-blocked)')
    # Legend
    from matplotlib.patches import Patch
    legend_elements = [Patch(facecolor=c, label=v) for v, c in verdict_colors.items() if verdict_counts[v] > 0]
    ax.legend(handles=legend_elements, loc='upper right', fontsize=8, ncol=3)
    plt.savefig(path.replace('.csv', '_frame_quality.png'), dpi=120)
    plt.close()
    print(f'Saved: {path.replace(".csv", "_frame_quality.png")}')

if __name__ == '__main__':
    main()
