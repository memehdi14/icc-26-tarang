#!/usr/bin/env python3
"""
03_sampling_rate_check.py — Tarang bring-up Stage 8
Measure actual ESP32 sampling rate and jitter from a logged CSV.

Usage:
    python3 03_sampling_rate_check.py tarang_20250630_153000.csv

Pass criteria:
    ECG mean rate : 250.00 +/- 0.5 Hz
    ECG jitter p2p: < 4 ms (2 master ticks)
    ECG jitter std: < 1 ms
    IMU mean rate : 100.00 +/- 0.5 Hz
    imu_idx gaps  : always 1 (no drops)

Fail -> check:
    - WiFi/BLE still on (should be off in 05_ sketch)
    - Serial back-pressure (raise baud or split emit task)
    - Other USB devices on same hub
    - Power supply sag under load
"""
import sys
import numpy as np
import matplotlib.pyplot as plt

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

    t_us    = data['t_us']
    ecg_idx = data['ecg_idx'].astype(np.uint64)
    imu_idx = data['imu_idx'].astype(np.uint64)

    # ---- ECG analysis (per row = per ECG sample) ----
    dt_us = np.diff(t_us)
    dt_ms = dt_us / 1000.0
    rate_hz = 1e6 / dt_us

    mean_rate = float(np.mean(rate_hz))
    std_rate  = float(np.std(rate_hz))
    p2p_ms    = float(np.max(dt_ms) - np.min(dt_ms))
    std_ms    = float(np.std(dt_ms))

    # ---- IMU analysis (count unique imu_idx) ----
    unique_imu = np.unique(imu_idx)
    n_imu = len(unique_imu)
    duration_s = (t_us[-1] - t_us[0]) / 1e6
    imu_rate = (n_imu - 1) / duration_s if duration_s > 0 else 0

    # IMU idx gaps — should all be 1
    imu_first_seen_idx = []
    last = None
    for v in imu_idx:
        if v != last:
            imu_first_seen_idx.append(v)
            last = v
    imu_gaps = np.diff(imu_first_seen_idx)
    imu_drop_count = int(np.sum(imu_gaps != 1))

    # ---- Print report ----
    print('='*60)
    print('Tarang sampling-rate report —', path)
    print('='*60)
    print(f'Duration           : {duration_s:8.3f} s')
    print(f'ECG samples        : {len(t_us):8d}')
    print(f'ECG mean rate      : {mean_rate:8.3f} Hz   (target 250)')
    print(f'ECG std  rate      : {std_rate:8.3f} Hz')
    print(f'ECG dt mean        : {float(np.mean(dt_ms)):8.3f} ms   (target 4.0)')
    print(f'ECG dt std         : {std_ms:8.3f} ms')
    print(f'ECG dt p2p         : {p2p_ms:8.3f} ms')
    print(f'IMU unique idx     : {n_imu:8d}')
    print(f'IMU mean rate      : {imu_rate:8.3f} Hz   (target 100)')
    print(f'IMU idx drops      : {imu_drop_count:8d}   (expect 0)')
    print('='*60)
    verdict_ecg = 'PASS' if abs(mean_rate - 250) < 0.5 and p2p_ms < 4 else 'FAIL'
    verdict_imu = 'PASS' if abs(imu_rate - 100) < 0.5 and imu_drop_count == 0 else 'FAIL'
    print(f'ECG verdict        : {verdict_ecg}')
    print(f'IMU verdict        : {verdict_imu}')
    print('='*60)

    # ---- Plot dt histogram + timeline ----
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 6), constrained_layout=True)
    ax1.plot(dt_ms[:5000], lw=0.5, color='crimson')
    ax1.axhline(4.0, color='k', ls='--', lw=0.5, label='target 4 ms')
    ax1.set_title(f'{path}  —  first 5000 samples')
    ax1.set_ylabel('dt (ms)')
    ax1.legend(loc='upper right'); ax1.grid(alpha=0.3)

    ax2.hist(dt_ms, bins=200, color='navy', alpha=0.7)
    ax2.axvline(4.0, color='k', ls='--', lw=0.5)
    ax2.set_xlabel('dt (ms)')
    ax2.set_ylabel('count')
    ax2.grid(alpha=0.3)

    out = path.replace('.csv', '_sampling_rate.png')
    plt.savefig(out, dpi=120)
    print(f'[Tarang] Saved plot -> {out}')

if __name__ == '__main__':
    main()
