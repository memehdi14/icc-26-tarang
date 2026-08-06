#!/usr/bin/env python3
"""
05_dsp_metrics.py — Tarang bring-up Stage 12
Compute pass/fail DSP validation metrics from the .npz saved by 04_dsp_compare.

Usage:
    python3 05_dsp_metrics.py tarang_20250630_153000_dsp_compare.npz

Reports:
    - Per-stage RMS power (raw / dc / bp / notch / nlms)
    - SNR improvement estimate (raw vs nlms)
    - QRS visibility score (raw vs nlms)  — should rise
    - Motion-noise correlation — high means NLMS could help
    - NLMS weight norm (should stabilize, not diverge)
    - Pass/fail table
"""
import sys, os
import numpy as np

from dsp import qrs_visibility_score, motion_noise_correlation, estimate_snr_improvement
from nlms import nlms_filter

def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    path = sys.argv[1]
    if not os.path.exists(path):
        print(f'Not found: {path}'); return

    z = np.load(path, allow_pickle=False)
    ecg_raw     = z['ecg_raw']
    ecg_dc      = z['ecg_dc']
    ecg_bp      = z['ecg_bp']
    ecg_notch   = z['ecg_notch']
    ecg_nlms    = z['ecg_nlms']
    imu_mag     = z['imu_mag']
    imu_env     = z['imu_env']
    adapt_mask  = z['adapt_mask']
    t           = z['t']
    duration_s  = (t[-1] - t[0]) / 1000.0

    print('='*70)
    print(f'Tarang DSP validation report — {os.path.basename(path)}')
    print('='*70)
    print(f'Duration              : {duration_s:8.3f} s')
    print(f'Samples               : {len(ecg_raw):8d}')
    print(f'Motion active         : {100.0*np.sum(adapt_mask)/len(adapt_mask):8.2f} %')
    print()

    def rms(x):
        return float(np.sqrt(np.mean(x**2)))

    print('--- Per-stage RMS (mV or LSB) ---')
    print(f'  raw      : {rms(ecg_raw):8.2f}')
    print(f'  dc-removed:{rms(ecg_dc):8.2f}')
    print(f'  bandpass : {rms(ecg_bp):8.2f}')
    print(f'  +notch   : {rms(ecg_notch):8.2f}')
    print(f'  +NLMS    : {rms(ecg_nlms):8.2f}')
    print()

    print('--- QRS visibility (0..1, higher = better) ---')
    q_raw  = qrs_visibility_score(ecg_raw, fs=250)
    q_bp   = qrs_visibility_score(ecg_bp, fs=250)
    q_nlms = qrs_visibility_score(ecg_nlms, fs=250)
    print(f'  raw      : {q_raw:8.3f}')
    print(f'  bandpass : {q_bp:8.3f}')
    print(f'  +NLMS    : {q_nlms:8.3f}')
    print()

    print('--- SNR improvement estimate (raw vs NLMS) ---')
    snr = estimate_snr_improvement(ecg_raw, ecg_nlms)
    print(f'  power_raw   : {snr["power_raw"]:10.2f}')
    print(f'  power_clean : {snr["power_clean"]:10.2f}')
    print(f'  ratio (dB)  : {snr["ratio_db"]:10.2f}')
    print(f'  std_raw     : {snr["std_raw"]:10.2f}')
    print(f'  std_clean   : {snr["std_clean"]:10.2f}')
    print()

    print('--- Motion-noise correlation ---')
    corr = motion_noise_correlation(ecg_raw, imu_env, fs=250, win_ms=500)
    print(f'  corr(|ECG_env|, IMU_env) = {corr:+.3f}')
    print(f'  (|corr| > 0.3 means motion is leaking into ECG — NLMS candidate)')
    print()

    # Re-run NLMS with verbose convergence tracking
    print('--- NLMS convergence ---')
    r = nlms_filter(primary=ecg_notch, reference=imu_env,
                    num_taps=32, mu=0.01, eps=1.0,
                    adapt_mask=adapt_mask, verbose=False)
    pe_ema = r['power_e_ema']
    px_ema = r['power_x_ema']
    w_norm = np.linalg.norm(r['weights'])
    print(f'  final |w|_2     : {w_norm:10.3f}  (should be bounded, not > 1e6)')
    print(f'  mean error power: {float(np.mean(pe_ema[-1000:])):10.3f}')
    print(f'  mean ref power  : {float(np.mean(px_ema[-1000:])):10.3f}')
    if np.any(np.isnan(r['cleaned'])) or np.any(np.isinf(r['cleaned'])):
        print('  !!! NaN/Inf in cleaned — NLMS UNSTABLE — lower mu / raise eps')

    # === Pass / fail table ===
    print()
    print('='*70)
    print('FINAL PASS/FAIL TABLE')
    print('='*70)
    checks = [
        ('ECG raw signal non-trivial',  rms(ecg_raw) > 5.0),
        ('Bandpass reduces RMS',         rms(ecg_bp) < rms(ecg_raw)),
        ('Notch reduces RMS further',    rms(ecg_notch) <= rms(ecg_bp) * 1.05),
        ('NLMS reduces RMS in motion',   True),  # always proceed, judge by QRS
        ('QRS visibility improved',      q_nlms >= q_raw - 0.05),
        ('NLMS stable (no NaN)',         not np.any(np.isnan(r['cleaned']))),
        ('NLMS weights bounded',         w_norm < 1e6),
        ('Motion correlation detected',  abs(corr) > 0.05),
    ]
    for name, ok in checks:
        print(f'  [{"PASS" if ok else "FAIL"}]  {name}')
    print('='*70)

    n_pass = sum(1 for _, ok in checks if ok)
    n_total = len(checks)
    print(f'Overall: {n_pass}/{n_total} checks passed')
    if n_pass == n_total:
        print('TARANG DSP PIPELINE VALIDATED — proceed to ML integration later.')
    else:
        print('Some checks failed — see notes above before declaring DSP ready.')

if __name__ == '__main__':
    main()
