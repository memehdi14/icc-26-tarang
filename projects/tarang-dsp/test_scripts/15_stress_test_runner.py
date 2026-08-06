#!/usr/bin/env python3
"""
15_stress_test_runner.py — Tarang DSP Finalization Item F

7-scenario stress-test protocol. Each scenario is a separate 60-second CSV
recording. This script runs analysis on all of them and produces a
comparative verdict table.

Protocol (record each scenario as a separate file):
  1. rest_still.csv      — 60 s, subject still, board flat on table
  2. mild_motion.csv     — 60 s, slow hand circles
  3. walking.csv         — 60 s, walking in place / arm swing
  4. loose_electrode.csv — 60 s, one electrode partially disconnected
  5. cable_tug.csv       — 60 s, gently tugging the electrode cable
  6. lead_off.csv        — 60 s, no electrodes connected (open input)
  7. noisy.csv           — 60 s, near a phone charger or other EMI source

Usage:
    # After recording all 7 files in ~/tarang_data/stress_tests/:
    python 15_stress_test_runner.py --batch ~/tarang_data/stress_tests/

    # Or analyze a single file:
    python 15_stress_test_runner.py rest_still.csv

Output:
    stress_test_report.md  — comparative verdict table
    stress_test_report.json — machine-readable
"""
import sys, os, json, argparse, glob
import numpy as np
from scipy.signal import butter, filtfilt, sosfiltfilt, iirnotch

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
        't_us': arr[:,0], 'ecg_raw': arr[:,3], 'ecg_mv': arr[:,4],
        'imu_mag': arr[:,8], 'lo+': arr[:,9],
    }

def analyze_scenario(path):
    """Run full analysis on one stress-test recording."""
    data = load_csv(path)
    ecg_mv = data['ecg_mv']; ecg_raw = data['ecg_raw']
    imu_mag = data['imu_mag']; lo_plus = data['lo+']
    t_us = data['t_us']
    duration_s = (t_us[-1] - t_us[0]) / 1e6

    # Sampling
    dt_us = np.diff(t_us)
    ecg_rate = 1e6 / np.mean(dt_us) if len(dt_us) > 0 else 0
    ecg_p2p_ms = (np.max(dt_us) - np.min(dt_us)) / 1000.0 if len(dt_us) > 0 else 0

    # Saturation
    sat_low = 100.0 * np.sum(ecg_raw < 200) / len(ecg_raw)
    sat_high = 100.0 * np.sum(ecg_raw > 3900) / len(ecg_raw)

    # Lead-off
    leadoff_pct = 100.0 * np.sum(lo_plus > 0.5) / len(lo_plus)

    # Calibrated motion gate
    rest_n = min(len(imu_mag), 5 * ECG_HZ)
    baseline = float(np.median(imu_mag[:rest_n]))
    rest_dev = imu_mag[:rest_n] - baseline
    mad = float(np.median(np.abs(rest_dev - np.median(rest_dev))))
    motion_thr = max(3.0 * mad * 1.4826, 50.0)
    motion_mask = np.abs(imu_mag - baseline) > motion_thr
    motion_pct = 100.0 * np.sum(motion_mask) / len(motion_mask)

    # DSP
    def bp(x):
        sos = butter(2, [0.5/(ECG_HZ/2), 40.0/(ECG_HZ/2)], btype='band', output='sos')
        return sosfiltfilt(sos, x - np.mean(x))
    def notch(x):
        b, a = iirnotch(50.0, 30.0, fs=ECG_HZ)
        return filtfilt(b, a, x)
    ecg_filt = notch(bp(ecg_mv))

    # Pan-Tompkins
    def pt(ecg, fs=ECG_HZ):
        n = len(ecg)
        if n < fs: return np.array([])
        ny = fs/2.0
        b, a = butter(2, [5.0/ny, 15.0/ny], btype='band')
        bp_s = filtfilt(b, a, ecg)
        d = np.zeros_like(bp_s)
        for i in range(2, n-2):
            d[i] = (-bp_s[i-2] - 2*bp_s[i-1] + 2*bp_s[i+1] + bp_s[i+2]) / 8.0
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

    r_peaks = pt(ecg_filt)
    if len(r_peaks) >= 2:
        rr = np.diff(r_peaks) / ECG_HZ * 1000  # ms
        rr_valid = rr[(rr >= 300) & (rr <= 3000)]
        hr = 60000.0 / np.median(rr_valid) if len(rr_valid) > 0 else 0
        rr_mean = float(np.mean(rr_valid)) if len(rr_valid) > 0 else 0
        rr_std = float(np.std(rr_valid)) if len(rr_valid) > 0 else 0
        rr_cv = rr_std / rr_mean if rr_mean > 0 else 1.0
    else:
        hr = 0; rr_mean = 0; rr_std = 0; rr_cv = 1.0

    # Per-scenario verdict logic
    if sat_low + sat_high > 5:
        verdict = 'FAIL_SATURATED'
    elif leadoff_pct > 30:
        verdict = 'FAIL_LEAD_OFF'
    elif ecg_rate < 249 or ecg_rate > 251:
        verdict = 'FAIL_SAMPLING'
    elif len(r_peaks) < 30:
        verdict = 'FAIL_NO_RPEAKS'
    elif rr_cv > 0.30:
        verdict = 'WARN_RR_UNSTABLE'
    elif motion_pct > 70 and rr_cv > 0.15:
        verdict = 'WARN_MOTION_DEGRADED'
    elif rr_cv < 0.15:
        verdict = 'PASS'
    else:
        verdict = 'MARGINAL'

    return {
        'file': os.path.basename(path),
        'duration_s': duration_s,
        'ecg_rate_hz': ecg_rate,
        'ecg_jitter_ms': ecg_p2p_ms,
        'saturation_pct': sat_low + sat_high,
        'leadoff_pct': leadoff_pct,
        'motion_pct': motion_pct,
        'r_peaks': len(r_peaks),
        'hr_bpm': hr,
        'rr_mean_ms': rr_mean,
        'rr_std_ms': rr_std,
        'rr_cv': rr_cv,
        'verdict': verdict,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv', nargs='?', help='single CSV file')
    ap.add_argument('--batch', help='folder containing multiple CSVs')
    args = ap.parse_args()

    if args.batch:
        files = sorted(glob.glob(os.path.join(args.batch, '*.csv')))
    elif args.csv:
        files = [args.csv]
    else:
        print(__doc__); return

    if not files:
        print('No CSV files found'); return

    print(f'=== STRESS TEST RUNNER ===')
    print(f'Analyzing {len(files)} files...')

    results = []
    for f in files:
        print(f'\n--- {os.path.basename(f)} ---')
        try:
            r = analyze_scenario(f)
            results.append(r)
            print(f'  Duration:      {r["duration_s"]:.1f} s')
            print(f'  ECG rate:      {r["ecg_rate_hz"]:.3f} Hz')
            print(f'  Saturation:    {r["saturation_pct"]:.1f}%')
            print(f'  Lead-off:      {r["leadoff_pct"]:.1f}%')
            print(f'  Motion:        {r["motion_pct"]:.1f}%')
            print(f'  R-peaks:       {r["r_peaks"]}')
            print(f'  HR:            {r["hr_bpm"]:.1f} bpm')
            print(f'  RR mean/std:   {r["rr_mean_ms"]:.0f} / {r["rr_std_ms"]:.0f} ms')
            print(f'  RR CV:         {r["rr_cv"]:.3f}')
            print(f'  VERDICT:       {r["verdict"]}')
        except Exception as e:
            print(f'  ERROR: {e}')
            results.append({'file': os.path.basename(f), 'verdict': 'ERROR', 'error': str(e)})

    # Comparative table
    print(f'\n{"="*120}')
    print(f'STRESS TEST COMPARATIVE REPORT')
    print(f'{"="*120}')
    print(f'{"file":<25} {"rate":>7} {"sat%":>6} {"lo%":>6} {"mo%":>6} {"rpk":>5} {"hr":>6} {"rr_cv":>6} {"verdict":<25}')
    print(f'{"-"*25} {"-"*7} {"-"*6} {"-"*6} {"-"*6} {"-"*5} {"-"*6} {"-"*6} {"-"*25}')
    for r in results:
        if 'error' in r:
            print(f'{r["file"]:<25} {"":>7} {"":>6} {"":>6} {"":>6} {"":>5} {"":>6} {"":>6} {r["verdict"]:<25}')
        else:
            print(f'{r["file"]:<25} {r["ecg_rate_hz"]:>7.2f} {r["saturation_pct"]:>6.1f} '
                  f'{r["leadoff_pct"]:>6.1f} {r["motion_pct"]:>6.1f} {r["r_peaks"]:>5} '
                  f'{r["hr_bpm"]:>6.1f} {r["rr_cv"]:>6.3f} {r["verdict"]:<25}')

    # Save markdown report
    out_md = 'stress_test_report.md'
    with open(out_md, 'w', encoding='utf-8') as f:
        f.write('# Tarang Stress Test Report\n\n')
        f.write(f'**Files analyzed**: {len(files)}\n\n')
        f.write('## Per-scenario results\n\n')
        f.write('| file | duration_s | rate_hz | sat% | lo% | mo% | r_peaks | hr_bpm | rr_mean_ms | rr_std_ms | rr_cv | verdict |\n')
        f.write('|---|---|---|---|---|---|---|---|---|---|---|---|\n')
        for r in results:
            if 'error' in r:
                f.write(f'| {r["file"]} | - | - | - | - | - | - | - | - | - | - | {r["verdict"]} ({r["error"]}) |\n')
            else:
                f.write(f'| {r["file"]} | {r["duration_s"]:.1f} | {r["ecg_rate_hz"]:.2f} | '
                        f'{r["saturation_pct"]:.1f} | {r["leadoff_pct"]:.1f} | {r["motion_pct"]:.1f} | '
                        f'{r["r_peaks"]} | {r["hr_bpm"]:.1f} | {r["rr_mean_ms"]:.0f} | '
                        f'{r["rr_std_ms"]:.0f} | {r["rr_cv"]:.3f} | {r["verdict"]} |\n')
        f.write('\n## Verdicts\n\n')
        verdict_counts = {}
        for r in results:
            v = r.get('verdict', 'ERROR')
            verdict_counts[v] = verdict_counts.get(v, 0) + 1
        for v, c in sorted(verdict_counts.items()):
            f.write(f'- **{v}**: {c} scenario(s)\n')
        f.write('\n## Acceptance\n\n')
        n_pass = verdict_counts.get('PASS', 0)
        n_total = len(results)
        if n_pass == n_total:
            f.write(f'**ALL {n_total} scenarios PASSED.**\n')
        else:
            f.write(f'**{n_pass}/{n_total} scenarios PASSED.** Failing scenarios must be debugged before DSP finalization.\n')
    print(f'\nSaved: {out_md}')

    out_json = 'stress_test_report.json'
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump({'results': results, 'verdict_counts': verdict_counts}, f, indent=2)
    print(f'Saved: {out_json}')

if __name__ == '__main__':
    main()
