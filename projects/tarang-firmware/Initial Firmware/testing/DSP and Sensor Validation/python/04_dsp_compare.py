#!/usr/bin/env python3
"""
04_dsp_compare.py — Tarang bring-up Stage 9 + 11
Run DC removal / baseline / bandpass / notch on raw ECG and compare side-by-side.

Usage:
    python3 04_dsp_compare.py tarang_20250630_153000.csv

Produces:
    <csv>_dsp_compare.png  — 4-panel: raw / dc-removed / bandpass / NLMS-cleaned
    <csv>_dsp_compare.npz — arrays for re-use by 05_dsp_metrics.py
"""
import sys, os
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import resample

from dsp import (dc_remove, baseline_wander_remove, bandpass,
                 notch_50hz, imu_magnitude, motion_noise_correlation,
                 qrs_visibility_score)
from nlms import nlms_filter, motion_gate

ECG_HZ = 250
IMU_HZ = 100

def load_csv_robust(path):
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
        return None
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

    data = load_csv_robust(path)
    if data is None:
        print('Empty CSV'); return

    t_us   = data['t_us']
    ecg_mv = data['ecg_mv']
    ax     = data['ax']
    ay     = data['ay']
    az     = data['az']
    imu_mag_csv = data['imu_mag']

    t = (t_us - t_us[0]) / 1000.0   # ms

    # === DSP chain ===
    ecg_dc       = dc_remove(ecg_mv)
    ecg_baseline = baseline_wander_remove(ecg_dc, fs=ECG_HZ, cutoff=0.5)
    ecg_bp       = bandpass(ecg_baseline, fs=ECG_HZ, low=0.5, high=40.0)
    ecg_notch    = notch_50hz(ecg_bp, fs=ECG_HZ)

    # === IMU motion reference ===
    # IMU was zero-order-held into every ECG row, so it's already at 250 Hz
    # in the CSV. But for true motion envelope we recompute magnitude here
    # in case the CSV's imu_mag field drifted.
    imu_mag = imu_magnitude(ax, ay, az)
    # Smooth to get motion envelope (100 ms window @ 250 Hz = 25 samples)
    from scipy.ndimage import uniform_filter1d
    imu_env = uniform_filter1d(imu_mag - 16384.0, size=25)

    # Motion gate
    adapt_mask = motion_gate(imu_mag, baseline=16384.0, threshold=300.0)
    motion_pct = 100.0 * np.sum(adapt_mask) / len(adapt_mask)

    # === NLMS ===
    # Primary = bandpass-cleaned ECG (so NLMS only fights motion, not mains)
    # Reference = motion envelope (resampled internally to N)
    print(f'[NLMS] taps=32 mu=0.01 eps=1.0 motion={motion_pct:.1f}% of samples')
    nlms_result = nlms_filter(
        primary=ecg_notch,
        reference=imu_env,
        num_taps=32,
        mu=0.01,
        eps=1.0,
        adapt_mask=adapt_mask,
    )

    # === Save arrays for metrics script ===
    out_npz = path.replace('.csv', '_dsp_compare.npz')
    np.savez(out_npz,
             t=t, ecg_raw=ecg_mv, ecg_dc=ecg_dc, ecg_baseline=ecg_baseline,
             ecg_bp=ecg_bp, ecg_notch=ecg_notch,
             ecg_nlms=nlms_result['cleaned'],
             nlms_y_hat=nlms_result['y_hat'],
             imu_mag=imu_mag, imu_env=imu_env, adapt_mask=adapt_mask)
    print(f'[Tarang] Saved arrays -> {out_npz}')

    # === Plot ===
    # Show first 8 seconds for clarity
    N_show = min(len(t), 8 * ECG_HZ)
    t_show = t[:N_show]

    fig, axs = plt.subplots(5, 1, figsize=(14, 10), sharex=True,
                             constrained_layout=True)
    axs[0].plot(t_show, ecg_mv[:N_show],      lw=0.5, color='k')
    axs[0].set_ylabel('RAW (mV)'); axs[0].grid(alpha=0.3)
    axs[0].set_title(f'{os.path.basename(path)} — first 8 s')

    axs[1].plot(t_show, ecg_dc[:N_show],      lw=0.5, color='gray')
    axs[1].set_ylabel('DC-removed'); axs[1].grid(alpha=0.3)

    axs[2].plot(t_show, ecg_bp[:N_show],      lw=0.5, color='crimson')
    axs[2].set_ylabel('Bandpass 0.5-40Hz'); axs[2].grid(alpha=0.3)

    axs[3].plot(t_show, ecg_notch[:N_show],   lw=0.5, color='darkorange')
    axs[3].set_ylabel('+ notch 50Hz'); axs[3].grid(alpha=0.3)

    axs[4].plot(t_show, nlms_result['cleaned'][:N_show], lw=0.5, color='navy')
    axs[4].set_ylabel('NLMS cleaned'); axs[4].grid(alpha=0.3)
    axs[4].set_xlabel('Time (ms)')

    # Shade motion regions on all axes
    for ax in axs:
        for i in range(0, N_show, 25):
            if adapt_mask[i]:
                ax.axvspan(t[i], t[min(i+25, N_show-1)],
                           color='yellow', alpha=0.15)

    out_png = path.replace('.csv', '_dsp_compare.png')
    plt.savefig(out_png, dpi=120)
    print(f'[Tarang] Saved plot -> {out_png}')
    plt.show()

if __name__ == '__main__':
    main()
