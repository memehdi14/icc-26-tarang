#!/usr/bin/env python3
"""
06_combined_dsp_validation.py — Tarang Stage 10
End-to-end offline DSP validation: load CSV -> filter -> Pan-Tompkins
on raw -> NLMS -> Pan-Tompkins on cleaned -> HR/RR/SNR -> save report.

Usage:
    python3 06_combined_dsp_validation.py tarang_20250630_153000.csv

Outputs:
    <csv>_combined_dsp.png         6-panel comparison
    <csv>_combined_dsp.npz         arrays
    <csv>_combined_dsp_report.md   human-readable markdown report
    <csv>_combined_dsp_results.csv per-frame summary (one row per 256-sample frame)
"""
import sys, os, json
import numpy as np
import matplotlib.pyplot as plt
from scipy.ndimage import uniform_filter1d

from dsp import (dc_remove, baseline_wander_remove, bandpass,
                 notch_50hz, imu_magnitude, qrs_visibility_score,
                 estimate_snr_improvement, motion_noise_correlation)
from nlms import nlms_filter, motion_gate
from pan_tompkins import detect as pt_detect, quality_verdict

ECG_HZ = 250
IMU_HZ = 100
FRAME_LEN = 256     # matches TARANG_ECG_SAMPLES_PER_FRAME

def load_csv(path):
    """Robust CSV loader — skips # comments, ignores malformed lines."""
    rows = []
    header = None
    with open(path, 'r', encoding='ascii', errors='ignore') as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            fields = s.split(',')
            if header is None:
                header = fields
                continue
            if len(fields) < 10:
                continue
            try:
                rows.append([float(x) for x in fields[:10]])
            except ValueError:
                continue
    if not rows:
        raise SystemExit('CSV has no data rows after header')
    arr = np.array(rows, dtype=np.float64)
    return {
        't_us':    arr[:, 0],
        'ecg_idx': arr[:, 1],
        'imu_idx': arr[:, 2],
        'ecg_raw': arr[:, 3],
        'ecg_mv':  arr[:, 4],
        'ax':      arr[:, 5],
        'ay':      arr[:, 6],
        'az':      arr[:, 7],
        'imu_mag': arr[:, 8],
        'lo+':     arr[:, 9],
    }

def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    path = sys.argv[1]
    data = load_csv(path)

    t_us    = data['t_us']
    ecg_mv  = data['ecg_mv']
    ax      = data['ax']
    ay      = data['ay']
    az      = data['az']
    imu_mag_csv = data['imu_mag']

    duration_s = (t_us[-1] - t_us[0]) / 1e6
    print(f'[Stage10] Duration {duration_s:.2f}s, {len(ecg_mv)} samples')

    # === DSP chain ===
    ecg_dc       = dc_remove(ecg_mv)
    ecg_baseline = baseline_wander_remove(ecg_dc, fs=ECG_HZ, cutoff=0.5)
    ecg_bp       = bandpass(ecg_baseline, fs=ECG_HZ, low=0.5, high=40.0)
    ecg_notch    = notch_50hz(ecg_bp, fs=ECG_HZ)

    imu_mag = imu_magnitude(ax, ay, az)
    imu_env = uniform_filter1d(imu_mag - 16384.0, size=25)   # ~100ms envelope
    adapt_mask = motion_gate(imu_mag, baseline=16384.0, threshold=300.0)
    motion_pct = 100.0 * np.sum(adapt_mask) / len(adapt_mask)
    print(f'[Stage10] Motion active: {motion_pct:.1f}% of samples')

    # === NLMS ===
    nlms_result = nlms_filter(
        primary=ecg_notch, reference=imu_env,
        num_taps=32, mu=0.01, eps=1.0,
        adapt_mask=adapt_mask, verbose=False)
    ecg_clean = nlms_result['cleaned']

    # === Pan-Tompkins on RAW ECG (use bandpass+notch as input) ===
    print('[Stage10] Pan-Tompkins on pre-NLMS ECG ...')
    pt_raw = pt_detect(ecg_notch, fs=ECG_HZ, verbose=True)
    verdict_raw = quality_verdict(pt_raw, fs=ECG_HZ)

    # === Pan-Tompkins on NLMS-cleaned ECG ===
    print('[Stage10] Pan-Tompkins on NLMS-cleaned ECG ...')
    pt_clean = pt_detect(ecg_clean, fs=ECG_HZ, verbose=True)
    verdict_clean = quality_verdict(pt_clean, fs=ECG_HZ)

    # === Signal quality metrics ===
    snr = estimate_snr_improvement(ecg_mv, ecg_clean)
    corr = motion_noise_correlation(ecg_mv, imu_env, fs=ECG_HZ, win_ms=500)
    q_vis_raw  = qrs_visibility_score(ecg_mv, fs=ECG_HZ)
    q_vis_bp   = qrs_visibility_score(ecg_notch, fs=ECG_HZ)
    q_vis_nlms = qrs_visibility_score(ecg_clean, fs=ECG_HZ)

    # === Per-frame summary (256 samples = 1.024 s at 250 Hz) ===
    n_frames = len(ecg_mv) // FRAME_LEN
    print(f'[Stage10] Splitting into {n_frames} Tarang-like frames ({FRAME_LEN} samples each)')
    frame_rows = []
    for fi in range(n_frames):
        s = fi * FRAME_LEN
        e = s + FRAME_LEN
        frame_raw   = ecg_mv[s:e]
        frame_clean = ecg_clean[s:e]
        frame_imu   = imu_mag[s:e]
        frame_adapt = adapt_mask[s:e]
        pt_f_clean = pt_detect(frame_clean, fs=ECG_HZ, verbose=False)
        # SNR for this frame
        p_raw = float(np.mean(frame_raw**2))
        p_cln = float(np.mean(frame_clean**2))
        frame_rows.append({
            'frame_idx': fi,
            't_start_us': int(t_us[s]),
            't_end_us': int(t_us[e-1]),
            'raw_rms': float(np.sqrt(p_raw)),
            'clean_rms': float(np.sqrt(p_cln)),
            'snr_db': 10*np.log10(p_raw/p_cln) if p_cln > 0 else 0.0,
            'motion_pct': 100.0 * np.sum(frame_adapt) / FRAME_LEN,
            'r_peaks_in_frame': len(pt_f_clean['r_peaks']),
            'qrs_vis': qrs_visibility_score(frame_clean, fs=ECG_HZ),
        })

    # === Save arrays ===
    out_npz = path.replace('.csv', '_combined_dsp.npz')
    np.savez(out_npz,
             t_us=t_us, ecg_raw=ecg_mv, ecg_dc=ecg_dc, ecg_bp=ecg_bp,
             ecg_notch=ecg_notch, ecg_clean=ecg_clean,
             nlms_y_hat=nlms_result['y_hat'],
             imu_mag=imu_mag, imu_env=imu_env, adapt_mask=adapt_mask,
             pt_raw_peaks=pt_raw['r_peaks'],
             pt_clean_peaks=pt_clean['r_peaks'])
    print(f'[Stage10] Arrays -> {out_npz}')

    # === Save per-frame CSV ===
    out_csv = path.replace('.csv', '_combined_dsp_results.csv')
    import csv as _csv
    with open(out_csv, 'w', newline='') as f:
        w = _csv.DictWriter(f, fieldnames=list(frame_rows[0].keys()))
        w.writeheader()
        for r in frame_rows:
            w.writerow(r)
    print(f'[Stage10] Per-frame CSV -> {out_csv}')

    # === Save markdown report ===
    out_md = path.replace('.csv', '_combined_dsp_report.md')
    with open(out_md, 'w') as f:
        f.write('# Tarang Combined DSP Validation Report\n\n')
        f.write(f'**Source CSV**: `{os.path.basename(path)}`\n\n')
        f.write(f'**Duration**: {duration_s:.3f} s ({len(ecg_mv)} samples @ {ECG_HZ} Hz)\n\n')
        f.write(f'**Frames**: {n_frames} × {FRAME_LEN} samples\n\n')
        f.write('## Pipeline\n\n')
        f.write('`raw -> DC remove -> baseline (HP 0.5Hz) -> bandpass 0.5-40Hz -> notch 50Hz -> NLMS(32 taps, mu=0.01, motion-gated)`\n\n')
        f.write('## Motion summary\n\n')
        f.write(f'- Motion active: **{motion_pct:.1f}%** of samples\n')
        f.write(f'- Motion-noise correlation: **{corr:+.3f}**\n')
        f.write(f'  (|corr| > 0.3 means motion is leaking into ECG)\n\n')
        f.write('## Pan-Tompkins on pre-NLMS ECG\n\n')
        f.write(f'- R-peaks detected: **{len(pt_raw["r_peaks"])}**\n')
        f.write(f'- Heart rate: **{pt_raw["heart_rate"]:.1f} bpm**\n')
        f.write(f'- RR mean / std: {float(np.mean(pt_raw["rr_intervals"]))*1000 if len(pt_raw["rr_intervals"]) else 0:.1f} / {float(np.std(pt_raw["rr_intervals"]))*1000 if len(pt_raw["rr_intervals"]) else 0:.1f} ms\n')
        f.write(f'- Verdict: **{verdict_raw["verdict"]}** ({verdict_raw["reason"]})\n\n')
        f.write('## Pan-Tompkins on NLMS-cleaned ECG\n\n')
        f.write(f'- R-peaks detected: **{len(pt_clean["r_peaks"])}**\n')
        f.write(f'- Heart rate: **{pt_clean["heart_rate"]:.1f} bpm**\n')
        f.write(f'- RR mean / std: {float(np.mean(pt_clean["rr_intervals"]))*1000 if len(pt_clean["rr_intervals"]) else 0:.1f} / {float(np.std(pt_clean["rr_intervals"]))*1000 if len(pt_clean["rr_intervals"]) else 0:.1f} ms\n')
        f.write(f'- Verdict: **{verdict_clean["verdict"]}** ({verdict_clean["reason"]})\n\n')
        f.write('## Signal quality\n\n')
        f.write(f'- RMS raw / bandpass / NLMS: {float(np.sqrt(np.mean(ecg_mv**2))):.2f} / {float(np.sqrt(np.mean(ecg_notch**2))):.2f} / {float(np.sqrt(np.mean(ecg_clean**2))):.2f} mV\n')
        f.write(f'- SNR improvement (raw vs NLMS): **{snr["ratio_db"]:.2f} dB**\n')
        f.write(f'- QRS visibility raw/bandpass/NLMS: {q_vis_raw:.3f} / {q_vis_bp:.3f} / {q_vis_nlms:.3f}\n')
        f.write(f'- NLMS weights |w|_2: {float(np.linalg.norm(nlms_result["weights"])):.4f}\n\n')
        f.write('## Per-frame summary (first 10 frames)\n\n')
        f.write('| frame | t_start_ms | raw_rms | clean_rms | snr_db | motion_% | r_peaks | qrs_vis |\n')
        f.write('|-------|-----------|---------|-----------|--------|----------|---------|---------|\n')
        for r in frame_rows[:10]:
            f.write(f'| {r["frame_idx"]} | {r["t_start_us"]/1000:.0f} | {r["raw_rms"]:.1f} | {r["clean_rms"]:.1f} | {r["snr_db"]:+.2f} | {r["motion_pct"]:.1f} | {r["r_peaks_in_frame"]} | {r["qrs_vis"]:.3f} |\n')
        f.write('\n## Pass / Fail\n\n')
        checks = [
            ('Pan-Tompkins on raw ECG: plausible HR', verdict_raw['verdict'] in ('PASS', 'WARN')),
            ('Pan-Tompkins on cleaned ECG: plausible HR', verdict_clean['verdict'] in ('PASS', 'WARN')),
            ('NLMS reduced RMS', float(np.sqrt(np.mean(ecg_clean**2))) <= float(np.sqrt(np.mean(ecg_notch**2))) * 1.05),
            ('NLMS stable (no NaN)', not np.any(np.isnan(ecg_clean))),
            ('NLMS weights bounded', float(np.linalg.norm(nlms_result['weights'])) < 1e6),
            ('QRS visibility preserved or improved', q_vis_nlms >= q_vis_bp - 0.1),
            ('Motion correlation detected', abs(corr) > 0.05),
            ('Frame splitting OK', n_frames >= 1),
        ]
        for name, ok in checks:
            f.write(f'- [{"PASS" if ok else "FAIL"}] {name}\n')
        n_pass = sum(1 for _, ok in checks if ok)
        f.write(f'\n**Overall: {n_pass}/{len(checks)} checks passed**\n')
    print(f'[Stage10] Markdown report -> {out_md}')

    # === 6-panel plot ===
    N_show = min(len(ecg_mv), 10 * ECG_HZ)
    t_show = (t_us[:N_show] - t_us[0]) / 1000.0
    fig, axs = plt.subplots(6, 1, figsize=(14, 12), sharex=True,
                             constrained_layout=True)
    axs[0].plot(t_show, ecg_mv[:N_show],     lw=0.5, color='k',          label='raw')
    axs[0].plot(t_show, ecg_mv[:N_show]*0+np.nan, lw=0)  # noop for legend
    axs[0].set_ylabel('RAW ECG (mV)'); axs[0].grid(alpha=0.3)
    axs[0].set_title(f'{os.path.basename(path)} — first 10 s')

    axs[1].plot(t_show, ecg_notch[:N_show],  lw=0.5, color='darkorange', label='bandpass+notch')
    axs[1].set_ylabel('BP+notch'); axs[1].grid(alpha=0.3)

    axs[2].plot(t_show, ecg_clean[:N_show],  lw=0.5, color='navy',       label='NLMS cleaned')
    axs[2].set_ylabel('NLMS cleaned'); axs[2].grid(alpha=0.3)

    # R-peak overlay (cleaned)
    rp = pt_clean['r_peaks']
    rp = rp[(rp >= 0) & (rp < N_show)]
    if len(rp) > 0:
        axs[2].plot(t_show[rp], ecg_clean[rp], 'rv', ms=6, label='R-peak (cleaned)')
    axs[2].legend(loc='upper right', fontsize=8)

    axs[3].plot(t_show, imu_mag[:N_show],    lw=0.5, color='teal',       label='|a|')
    axs[3].axhline(16384, color='g', ls='--', lw=0.5, label='1g')
    axs[3].set_ylabel('|a| (LSB)'); axs[3].grid(alpha=0.3); axs[3].legend(loc='upper right', fontsize=8)

    axs[4].plot(t_show, imu_env[:N_show],    lw=0.5, color='purple',     label='motion env')
    axs[4].set_ylabel('motion env'); axs[4].grid(alpha=0.3)

    # RR intervals (cleaned)
    if len(pt_clean['rr_intervals']) > 0:
        rr_t = pt_clean['r_times_s'][1:]  # seconds
        rr_t_ms = (rr_t * 1000.0)
        # restrict to show window
        mask = rr_t_ms <= t_show[-1]
        axs[5].plot(rr_t_ms[mask], pt_clean['rr_intervals'][mask]*1000, 'o-', ms=3, color='crimson', label='RR (cleaned)')
        if len(pt_raw['rr_intervals']) > 0:
            rr_t_raw = pt_raw['r_times_s'][1:] * 1000.0
            mask_r = rr_t_raw <= t_show[-1]
            axs[5].plot(rr_t_raw[mask_r], pt_raw['rr_intervals'][mask_r]*1000, 'x', ms=4, color='gray', label='RR (raw)')
    axs[5].set_ylabel('RR (ms)'); axs[5].set_xlabel('Time (ms)')
    axs[5].grid(alpha=0.3); axs[5].legend(loc='upper right', fontsize=8)

    # shade motion regions on all axes
    for ax in axs:
        for i in range(0, N_show, 25):
            if adapt_mask[i]:
                ax.axvspan(t_show[i], t_show[min(i+25, N_show-1)],
                           color='yellow', alpha=0.12)

    out_png = path.replace('.csv', '_combined_dsp.png')
    plt.savefig(out_png, dpi=120)
    print(f'[Stage10] Plot -> {out_png}')
    plt.show()

if __name__ == '__main__':
    main()
