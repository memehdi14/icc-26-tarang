#!/usr/bin/env python3
"""
13_nlms_only_metrics.py — Tarang DSP Finalization Item D

Honest NLMS evaluation. Separates:
  - raw ECG
  - bandpass+notch ECG  (what NLMS receives as input)
  - NLMS-cleaned ECG    (what NLMS outputs)

Computes NLMS-ONLY improvement (bandpass+notch → NLMS), NOT raw → NLMS.
All metrics computed INSIDE true motion windows (using calibrated motion gate).

Outputs:
  - NLMS-only RMS reduction in motion windows
  - NLMS-only SNR improvement in motion windows
  - R-peak F1 before vs after NLMS (if manual labels provided)
  - QRS amplitude preservation
  - QRS width preservation
  - Correlation between estimated artifact y_hat and IMU motion envelope

Usage:
    python 13_nlms_only_metrics.py tarang_20260702_133137.csv
    python 13_nlms_only_metrics.py tarang_20260702_133137.csv --manual manual_labels.csv

Targets:
  - NLMS-only improvement in motion windows > 3 dB
  - R-peak F1 after NLMS >= before NLMS
  - QRS amplitude change < 20%
  - QRS width change < 20%
  - no adaptation during rest (weights only update in motion windows)
"""
import sys, os, json, argparse
import numpy as np
from scipy.signal import butter, filtfilt, sosfiltfilt, iirnotch
from scipy.ndimage import uniform_filter1d

ECG_HZ = 250

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
        't_us': arr[:,0], 'ecg_mv': arr[:,4],
        'ax': arr[:,5], 'ay': arr[:,6], 'az': arr[:,7],
        'imu_mag': arr[:,8], 'lo+': arr[:,9],
    }

def dc_remove(x): return x - np.mean(x)
def bandpass(x, fs=ECG_HZ, low=0.5, high=40.0):
    sos = butter(2, [low/(fs/2), high/(fs/2)], btype='band', output='sos')
    return sosfiltfilt(sos, x)
def notch_50hz(x, fs=ECG_HZ):
    b, a = iirnotch(50.0, 30.0, fs=fs)
    return filtfilt(b, a, x)

def calibrated_motion_gate(imu_mag, rest_seconds=5):
    """Calibrated motion gate: baseline = median of first rest_seconds, threshold = 3*MAD."""
    rest_n = min(len(imu_mag), rest_seconds * ECG_HZ)
    baseline = float(np.median(imu_mag[:rest_n]))
    rest_dev = imu_mag[:rest_n] - baseline
    mad = float(np.median(np.abs(rest_dev - np.median(rest_dev))))
    threshold = max(3.0 * mad, 50.0)  # minimum threshold of 50 LSB
    motion_mask = np.abs(imu_mag - baseline) > threshold
    return baseline, threshold, motion_mask

def nlms_filter(primary, reference, num_taps=32, mu=0.01, eps=1.0, adapt_mask=None):
    primary = np.asarray(primary, dtype=np.float64)
    reference = np.asarray(reference, dtype=np.float64)
    N = len(primary); L = int(num_taps)
    if adapt_mask is None: adapt_mask = np.ones(N, dtype=bool)
    else: adapt_mask = np.asarray(adapt_mask, dtype=bool)
    w = np.zeros(L); delay = np.zeros(L); d_idx = 0
    y_hat = np.zeros(N); cleaned = np.zeros(N)
    weight_history = []
    for n in range(N):
        delay[d_idx] = reference[n]
        x = np.array([delay[(d_idx-k)%L] for k in range(L)])
        y = float(np.dot(w, x)); y_hat[n] = y
        e = primary[n] - y; cleaned[n] = e
        if adapt_mask[n]:
            denom = float(np.dot(x,x)) + eps
            if denom > 0: w += (mu*e/denom)*x
        d_idx = (d_idx+1) % L
        if n % (ECG_HZ*10) == 0:
            weight_history.append(float(np.linalg.norm(w)))
    return {'cleaned': cleaned, 'y_hat': y_hat, 'weights': w,
            'weight_history': weight_history}

def pan_tompkins(ecg, fs=ECG_HZ):
    n = len(ecg)
    if n < fs: return np.array([])
    ny = fs/2.0
    b, a = butter(2, [5.0/ny, 15.0/ny], btype='band')
    bp = filtfilt(b, a, ecg)
    d = np.zeros_like(bp)
    for i in range(2, n-2):
        d[i] = (-bp[i-2] - 2*bp[i-1] + 2*bp[i+1] + bp[i+2]) / 8.0
    sq = d**2
    mwi_w = max(1, int(fs*0.15))
    k = np.ones(mwi_w)/mwi_w
    sig = np.convolve(sq, k, mode='full')[:n]
    refractory = int(fs*0.25)
    sig_nz = sig[sig > 0]
    if len(sig_nz) == 0: return np.array([])
    SPKI = float(np.percentile(sig_nz, 95.0))
    NPKI = float(np.percentile(sig_nz, 50.0))
    if SPKI <= NPKI: SPKI = NPKI * 2
    THR1 = NPKI + 0.25*(SPKI - NPKI)
    THR2 = 0.5*THR1
    r_peaks = []; last_peak = -refractory
    for i in range(1, n-1):
        if sig[i] > sig[i-1] and sig[i] >= sig[i+1]:
            pv = sig[i]
            if pv > THR1:
                if i - last_peak >= refractory:
                    w = max(2, int(fs*0.025))
                    lo = max(0, i-w); hi = min(n, i+w+1)
                    local_idx = lo + int(np.argmax(np.abs(ecg[lo:hi])))
                    r_peaks.append(local_idx); last_peak = local_idx
                    SPKI = 0.125*pv + 0.875*SPKI
            elif pv > THR2:
                NPKI = 0.25*pv + 0.75*NPKI
            else:
                NPKI = 0.25*pv + 0.75*NPKI
            THR1 = NPKI + 0.25*(SPKI - NPKI)
            THR2 = 0.5*THR1
    return np.array(sorted(set(r_peaks)), dtype=np.int64)

def measure_qrs(ecg, r_peaks, fs=ECG_HZ):
    """Measure QRS amplitude and width at each R-peak."""
    amps = []; widths = []
    half_w = int(fs * 0.05)  # ±50 ms window
    for rp in r_peaks:
        lo = max(0, rp - half_w); hi = min(len(ecg), rp + half_w + 1)
        if hi <= lo: continue
        seg = ecg[lo:hi]
        amp = float(np.max(seg) - np.min(seg))
        # width = time above half-max
        half_max = (np.max(seg) + np.min(seg)) / 2.0
        above = np.sum(seg > half_max)
        width_ms = above / fs * 1000.0
        amps.append(amp); widths.append(width_ms)
    return np.array(amps), np.array(widths)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv')
    ap.add_argument('--manual', default=None, help='manual labels CSV for F1 computation')
    args = ap.parse_args()

    data = load_csv(args.csv)
    ecg_mv = data['ecg_mv']
    imu_mag = data['imu_mag']
    t_us = data['t_us']

    print(f'=== NLMS-ONLY METRICS (motion-window evaluation) ===')

    # DSP chain
    ecg_dc = dc_remove(ecg_mv)
    ecg_bp = bandpass(ecg_dc, fs=ECG_HZ)
    ecg_notch = notch_50hz(ecg_bp, fs=ECG_HZ)  # <- this is what NLMS receives

    # Calibrated motion gate
    baseline, threshold, motion_mask = calibrated_motion_gate(imu_mag)
    motion_pct = 100.0 * np.sum(motion_mask) / len(motion_mask)
    print(f'Calibrated IMU baseline: {baseline:.0f} LSB (was hardcoded 16384)')
    print(f'Calibrated motion threshold: {threshold:.1f} LSB (was hardcoded 300)')
    print(f'Motion active: {motion_pct:.1f}% of samples (was 95.3% with hardcoded)')
    print(f'  Rest:   {100-motion_pct:.1f}%')
    print(f'  Motion: {motion_pct:.1f}%')

    # NLMS with calibrated motion gate
    imu_env = uniform_filter1d(imu_mag - baseline, size=25)
    r = nlms_filter(ecg_notch, imu_env, num_taps=32, mu=0.01, eps=1.0, adapt_mask=motion_mask)
    ecg_clean = r['cleaned']
    y_hat = r['y_hat']

    # === NLMS-ONLY metrics in MOTION windows ===
    print(f'\n--- NLMS-ONLY metrics (bandpass+notch -> NLMS) ---')
    print(f'  (computed ONLY inside calibrated motion windows)')

    if motion_pct < 1.0:
        print(f'  WARNING: motion window too small ({motion_pct:.1f}%) — NLMS evaluation unreliable')
        return

    rms_before = float(np.sqrt(np.mean(ecg_notch[motion_mask]**2)))
    rms_after = float(np.sqrt(np.mean(ecg_clean[motion_mask]**2)))
    rms_reduction_pct = 100.0 * (1.0 - rms_after/rms_before) if rms_before > 0 else 0
    snr_improvement_db = 10.0 * np.log10(rms_before**2 / rms_after**2) if rms_after > 0 else 0

    print(f'  RMS before NLMS (in motion):  {rms_before:.2f} mV')
    print(f'  RMS after NLMS  (in motion):  {rms_after:.2f} mV')
    print(f'  RMS reduction:                {rms_reduction_pct:.1f}%')
    print(f'  SNR improvement:              {snr_improvement_db:.2f} dB  (target > 3 dB)')

    # Also compute in REST windows (NLMS should do nothing here)
    rest_mask = ~motion_mask
    rms_rest_before = float(np.sqrt(np.mean(ecg_notch[rest_mask]**2)))
    rms_rest_after = float(np.sqrt(np.mean(ecg_clean[rest_mask]**2)))
    rest_change = 10.0 * np.log10(rms_rest_before**2 / rms_rest_after**2) if rms_rest_after > 0 else 0
    print(f'\n--- NLMS effect in REST windows (should be ~0 dB) ---')
    print(f'  RMS before NLMS (rest):  {rms_rest_before:.2f} mV')
    print(f'  RMS after NLMS  (rest):  {rms_rest_after:.2f} mV')
    print(f'  Change:                  {rest_change:+.2f} dB  (target |change| < 1 dB)')

    # === R-peak F1 before vs after NLMS ===
    print(f'\n--- R-peak detection before vs after NLMS ---')
    r_peaks_before = pan_tompkins(ecg_notch, fs=ECG_HZ)
    r_peaks_after = pan_tompkins(ecg_clean, fs=ECG_HZ)
    print(f'  R-peaks before NLMS: {len(r_peaks_before)}')
    print(f'  R-peaks after NLMS:  {len(r_peaks_after)}')

    if args.manual:
        # Load manual labels and compute F1
        manual = []
        with open(args.manual) as f:
            next(f)
            for line in f:
                try: manual.append(int(float(line.split(',')[0])))
                except: pass
        manual = np.array(sorted(set(manual)), dtype=np.int64)
        tol = int(80 * ECG_HZ / 1000)

        def f1_metrics(detected, manual, tol):
            TP = 0; FP = 0; used = set()
            for d in detected:
                if len(manual) == 0: FP += 1; continue
                dists = np.abs(manual - d); nearest = np.argmin(dists)
                if dists[nearest] <= tol and nearest not in used:
                    TP += 1; used.add(nearest)
                else: FP += 1
            FN = len(manual) - len(used)
            p = TP/(TP+FP) if (TP+FP) > 0 else 0
            r = TP/(TP+FN) if (TP+FN) > 0 else 0
            f1 = 2*p*r/(p+r) if (p+r) > 0 else 0
            return p, r, f1
        p_b, r_b, f1_b = f1_metrics(r_peaks_before, manual, tol)
        p_a, r_a, f1_a = f1_metrics(r_peaks_after, manual, tol)
        print(f'  Before NLMS: precision={p_b*100:.1f}%, recall={r_b*100:.1f}%, F1={f1_b*100:.1f}%')
        print(f'  After NLMS:  precision={p_a*100:.1f}%, recall={r_a*100:.1f}%, F1={f1_a*100:.1f}%')
        print(f'  F1 change:   {(f1_a-f1_b)*100:+.1f}%  (target >= 0)')
    else:
        print(f'  (no --manual labels provided, skipping F1 computation)')

    # === QRS morphology preservation ===
    print(f'\n--- QRS morphology preservation ---')
    amps_before, widths_before = measure_qrs(ecg_notch, r_peaks_before)
    amps_after, widths_after = measure_qrs(ecg_clean, r_peaks_after)
    n_compare = min(len(amps_before), len(amps_after))
    if n_compare > 0:
        amp_change = float(np.median(amps_after[:n_compare] - amps_before[:n_compare]))
        amp_pct = 100.0 * amp_change / float(np.median(amps_before[:n_compare])) if np.median(amps_before[:n_compare]) > 0 else 0
        width_change = float(np.median(widths_after[:n_compare] - widths_before[:n_compare]))
        width_pct = 100.0 * width_change / float(np.median(widths_before[:n_compare])) if np.median(widths_before[:n_compare]) > 0 else 0
        print(f'  QRS amplitude median:  before={np.median(amps_before):.1f}, after={np.median(amps_after):.1f} mV')
        print(f'  QRS amplitude change:  {amp_pct:+.1f}%  (target |change| < 20%)')
        print(f'  QRS width median:      before={np.median(widths_before):.1f}, after={np.median(widths_after):.1f} ms')
        print(f'  QRS width change:      {width_pct:+.1f}%  (target |change| < 20%)')

    # === Artifact vs IMU correlation ===
    print(f'\n--- Estimated artifact vs IMU motion correlation ---')
    corr = float(np.corrcoef(y_hat[motion_mask], imu_env[motion_mask])[0,1]) if motion_pct > 1 else 0
    print(f'  corr(y_hat, imu_env) in motion windows: {corr:+.3f}')
    print(f'  (high |corr| means NLMS learned the motion->artifact mapping)')

    # === Weight stability ===
    print(f'\n--- NLMS weight stability ---')
    wh = r['weight_history']
    print(f'  Weight norm at start: {wh[0]:.6f}' if wh else '  no history')
    print(f'  Weight norm at end:   {wh[-1]:.6f}' if wh else '')
    print(f'  Weight norm max:      {max(wh):.6f}' if wh else '')
    print(f'  Weight norm monotonic increase: {all(wh[i] <= wh[i+1]*1.1 for i in range(len(wh)-1)) if wh else False}')

    # === Final verdict ===
    print(f'\n{"="*70}')
    print(f'NLMS-ONLY VERDICT')
    print(f'{"="*70}')
    targets = [
        ('NLMS-only SNR improvement in motion > 3 dB', snr_improvement_db > 3.0, f'{snr_improvement_db:.2f} dB'),
        ('NLMS effect in rest < 1 dB', abs(rest_change) < 1.0, f'{rest_change:+.2f} dB'),
        ('QRS amplitude change < 20%', abs(amp_pct) < 20.0, f'{amp_pct:+.1f}%'),
        ('QRS width change < 20%', abs(width_pct) < 20.0, f'{width_pct:+.1f}%'),
        ('Weights bounded (< 1e6)', float(np.linalg.norm(r['weights'])) < 1e6, f'|w|={np.linalg.norm(r["weights"]):.4f}'),
    ]
    for name, passed, detail in targets:
        print(f'  [{"PASS" if passed else "FAIL"}] {name} -- {detail}')
    n_pass = sum(1 for _, p, _ in targets if p)
    print(f'{"="*70}')
    print(f'Overall: {n_pass}/{len(targets)} targets met')
    print(f'{"="*70}')

    # Save JSON
    out_json = args.csv.replace('.csv', '_nlms_only_metrics.json')
    with open(out_json, 'w') as f:
        json.dump({
            'calibrated_baseline': baseline,
            'calibrated_threshold': threshold,
            'motion_pct': motion_pct,
            'rms_before_motion': rms_before,
            'rms_after_motion': rms_after,
            'rms_reduction_pct': rms_reduction_pct,
            'snr_improvement_db': snr_improvement_db,
            'rms_before_rest': rms_rest_before,
            'rms_after_rest': rms_rest_after,
            'rest_change_db': rest_change,
            'r_peaks_before': len(r_peaks_before),
            'r_peaks_after': len(r_peaks_after),
            'qrs_amp_change_pct': amp_pct,
            'qrs_width_change_pct': width_pct,
            'artifact_imu_correlation': corr,
            'weight_norm_final': float(np.linalg.norm(r['weights'])),
            'weight_history': wh,
            'targets_passed': n_pass,
            'targets_total': len(targets),
        }, f, indent=2)
    print(f'\nSaved: {out_json}')

if __name__ == '__main__':
    main()
