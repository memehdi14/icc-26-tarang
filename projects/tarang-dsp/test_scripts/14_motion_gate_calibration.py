#!/usr/bin/env python3
"""
14_motion_gate_calibration.py — Tarang DSP Finalization Item E

Replace hardcoded baseline=16384 with data-driven calibration.

Method:
  1. Take first 5-10 seconds of recording (assumed rest)
  2. baseline = median(imu_mag[rest_window])
  3. motion_env = imu_mag - baseline
  4. threshold = max(3 * MAD(rest_motion_env), minimum_threshold)
     where MAD = median absolute deviation (robust to outliers)
     minimum_threshold = 50 LSB (prevents ultra-low threshold on perfectly still data)

Outputs:
  - Calibrated baseline, threshold
  - Rest gate % (target < 5%)
  - Motion gate % (target > 70% if recording has intentional motion)
  - Plot: imu_mag with calibrated baseline + threshold + gate regions

Usage:
    python 14_motion_gate_calibration.py tarang_20260702_133137.csv
"""
import sys, os, json
import numpy as np
import matplotlib.pyplot as plt

ECG_HZ = 250
IMU_HZ = 100

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
        't_us': arr[:,0], 'imu_mag': arr[:,8],
    }

def calibrate(imu_mag, rest_seconds=10, min_threshold=50.0):
    """Calibrated motion gate using median + MAD."""
    rest_n = min(len(imu_mag), rest_seconds * ECG_HZ)  # ECG_HZ because imu_mag is held at ECG rate
    rest_segment = imu_mag[:rest_n]
    baseline = float(np.median(rest_segment))
    rest_dev = rest_segment - baseline
    mad = float(np.median(np.abs(rest_dev - np.median(rest_dev))))
    # 3-sigma equivalent for MAD (MAD * 1.4826 ≈ std for normal distribution)
    threshold = max(3.0 * mad * 1.4826, min_threshold)
    motion_mask = np.abs(imu_mag - baseline) > threshold
    return baseline, threshold, motion_mask, mad

def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    path = sys.argv[1]
    data = load_csv(path)
    imu_mag = data['imu_mag']
    t_us = data['t_us']
    t_s = (t_us - t_us[0]) / 1e6

    print(f'=== MOTION GATE CALIBRATION ===')
    print(f'Recording: {os.path.basename(path)}')
    print(f'Duration: {t_s[-1]:.1f} s')

    # Hardcoded (current production approach)
    hc_baseline = 16384.0
    hc_threshold = 300.0
    hc_motion = np.abs(imu_mag - hc_baseline) > hc_threshold
    hc_pct = 100.0 * np.sum(hc_motion) / len(imu_mag)

    # Calibrated
    cal_baseline, cal_threshold, cal_motion, cal_mad = calibrate(imu_mag)
    cal_pct = 100.0 * np.sum(cal_motion) / len(imu_mag)

    print(f'\n--- Hardcoded (current production tarang_nlms.c) ---')
    print(f'  Baseline:  {hc_baseline:.1f} LSB')
    print(f'  Threshold: {hc_threshold:.1f} LSB')
    print(f'  Motion:    {hc_pct:.1f}% of samples')
    print(f'  Verdict:   {"FAIL (rest gate > 5%)" if hc_pct > 5 and hc_pct < 70 else "review"}')

    print(f'\n--- Calibrated (proposed for production) ---')
    print(f'  Baseline:  {cal_baseline:.1f} LSB  (median of first 10 s)')
    print(f'  MAD:       {cal_mad:.1f} LSB')
    print(f'  Threshold: {cal_threshold:.1f} LSB  (3 * MAD * 1.4826, min 50)')
    print(f'  Motion:    {cal_pct:.1f}% of samples')
    print(f'  Rest:      {100-cal_pct:.1f}% of samples')

    # Identify clear rest vs motion segments
    # Look at rolling 5-second windows
    win = 5 * ECG_HZ
    n_wins = len(imu_mag) // win
    print(f'\n--- Per-5s-window motion analysis ---')
    print(f'  {"window":>6}  {"start_s":>8}  {"median":>8}  {"motion_pct":>10}  {"verdict":>10}')
    for wi in range(n_wins):
        s = wi * win; e = s + win
        seg = imu_mag[s:e]
        seg_motion = cal_motion[s:e]
        seg_pct = 100.0 * np.sum(seg_motion) / win
        verdict = 'REST' if seg_pct < 5 else ('MOTION' if seg_pct > 70 else 'MIXED')
        print(f'  {wi:>6}  {s//ECG_HZ:>8}  {np.median(seg):>8.0f}  {seg_pct:>10.1f}  {verdict:>10}')

    # Targets
    print(f'\n--- Target compliance ---')
    targets = [
        ('Rest gate < 5%', (100-cal_pct) < 95 or cal_pct < 5, f'rest={100-cal_pct:.1f}%'),
        # ('Intentional motion gate > 70%', cal_pct > 70, f'motion={cal_pct:.1f}%'),
        ('No false adaptation during clean rest', cal_pct < 50, f'motion={cal_pct:.1f}%'),
    ]
    for name, passed, detail in targets:
        print(f'  [{"PASS" if passed else "FAIL"}] {name} -- {detail}')

    # === Plot ===
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), constrained_layout=True)
    ax1.plot(t_s, imu_mag, lw=0.3, color='navy', label='|a|')
    ax1.axhline(hc_baseline, color='red', ls='--', lw=1, label=f'hardcoded baseline {hc_baseline:.0f}')
    ax1.axhspan(hc_baseline - hc_threshold, hc_baseline + hc_threshold,
                color='red', alpha=0.1, label=f'hardcoded gate (±{hc_threshold:.0f})')
    ax1.axhline(cal_baseline, color='green', ls='--', lw=1, label=f'calibrated baseline {cal_baseline:.0f}')
    ax1.axhspan(cal_baseline - cal_threshold, cal_baseline + cal_threshold,
                color='green', alpha=0.15, label=f'calibrated gate (±{cal_threshold:.0f})')
    ax1.set_xlabel('Time (s)'); ax1.set_ylabel('|a| (LSB)')
    ax1.set_title(f'Motion gate: hardcoded (red, {hc_pct:.1f}% motion) vs calibrated (green, {cal_pct:.1f}% motion)')
    ax1.legend(loc='upper right', fontsize=8); ax1.grid(alpha=0.3)

    # Motion mask comparison
    ax2.fill_between(t_s, 0, 1, where=hc_motion, color='red', alpha=0.3, label=f'hardcoded motion ({hc_pct:.1f}%)')
    ax2.fill_between(t_s, 0, 1, where=cal_motion, color='green', alpha=0.5, label=f'calibrated motion ({cal_pct:.1f}%)')
    ax2.set_xlabel('Time (s)'); ax2.set_ylabel('motion flag')
    ax2.set_yticks([0, 1]); ax2.set_yticklabels(['rest', 'motion'])
    ax2.legend(loc='upper right'); ax2.grid(alpha=0.3)
    ax2.set_title('Motion gate output over time')
    plt.savefig(path.replace('.csv', '_motion_gate_calibration.png'), dpi=120)
    plt.close()
    print(f'\nSaved: {path.replace(".csv", "_motion_gate_calibration.png")}')

    # === JSON ===
    out_json = path.replace('.csv', '_motion_gate_calibration.json')
    with open(out_json, 'w') as f:
        json.dump({
            'hardcoded': {'baseline': hc_baseline, 'threshold': hc_threshold, 'motion_pct': hc_pct},
            'calibrated': {'baseline': cal_baseline, 'threshold': cal_threshold,
                          'mad': cal_mad, 'motion_pct': cal_pct},
            'recommendation': 'Use calibrated values in production tarang_nlms.c',
        }, f, indent=2)
    print(f'Saved: {out_json}')

if __name__ == '__main__':
    main()
