#!/usr/bin/env python3
"""
11_rpeak_validation_report.py — Tarang DSP Finalization Item B

Compare Pan-Tompkins R-peaks to manual labels.
Computes TP, FP, FN, precision, recall, F1 within ±80 ms tolerance.

Usage:
    python 11_rpeak_validation_report.py tarang_20260702_133137.csv manual_labels.csv

Output:
    rpeak_validation_report.md  — human-readable report
    rpeak_validation.json       — machine-readable metrics
"""
import sys, os, json
import numpy as np
from scipy.signal import butter, filtfilt, sosfiltfilt, iirnotch

ECG_HZ = 250
TOLERANCE_MS = 80  # ±80 ms tolerance for R-peak matching

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
    return np.array(rows, dtype=np.float64)

def load_manual(path):
    """Load manual labels CSV. Returns array of sample indices."""
    indices = []
    with open(path, 'r') as f:
        next(f)  # skip header
        for line in f:
            s = line.strip()
            if not s: continue
            parts = s.split(',')
            try:
                indices.append(int(float(parts[0])))
            except (ValueError, IndexError):
                continue
    return np.array(sorted(set(indices)), dtype=np.int64)

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
                    r_peaks.append(local_idx)
                    last_peak = local_idx
                    SPKI = 0.125*pv + 0.875*SPKI
            elif pv > THR2:
                NPKI = 0.25*pv + 0.75*NPKI
            else:
                NPKI = 0.25*pv + 0.75*NPKI
            THR1 = NPKI + 0.25*(SPKI - NPKI)
            THR2 = 0.5*THR1
    return np.array(sorted(set(r_peaks)), dtype=np.int64)

def match_peaks(detected, manual, tolerance_samples):
    """Match detected peaks to manual peaks. Returns (TP, FP, FN, matches)."""
    TP = 0; FP = 0; FN = 0
    matches = []  # (det_idx, man_idx, error_samples)
    manual_used = set()
    for d in detected:
        # find nearest manual peak
        if len(manual) == 0:
            FP += 1; continue
        dists = np.abs(manual - d)
        nearest = np.argmin(dists)
        if dists[nearest] <= tolerance_samples and nearest not in manual_used:
            TP += 1
            manual_used.add(nearest)
            matches.append((d, manual[nearest], int(dists[nearest])))
        else:
            FP += 1
    FN = len(manual) - len(manual_used)
    return TP, FP, FN, matches

def main():
    if len(sys.argv) < 3:
        print(__doc__); return
    csv_path = sys.argv[1]
    manual_path = sys.argv[2]

    arr = load_csv(csv_path)
    ecg_mv = arr[:,4]
    manual = load_manual(manual_path)

    if len(manual) == 0:
        print(f'ERROR: No manual labels found in {manual_path}')
        return

    # Determine analysis window from manual labels
    win_start = max(0, manual[0] - ECG_HZ)  # 1 sec before first manual label
    win_end = min(len(ecg_mv), manual[-1] + ECG_HZ)  # 1 sec after last
    ecg_win = ecg_mv[win_start:win_end]

    print(f'=== R-PEAK VALIDATION REPORT ===')
    print(f'CSV: {os.path.basename(csv_path)}')
    print(f'Manual labels: {manual_path} ({len(manual)} peaks)')
    print(f'Analysis window: samples {win_start}-{win_end} ({(win_end-win_start)/ECG_HZ:.1f} s)')
    print(f'Tolerance: ±{TOLERANCE_MS} ms ({TOLERANCE_MS * ECG_HZ / 1000:.0f} samples)')

    # DSP + Pan-Tompkins
    from scipy.signal import butter, sosfiltfilt, iirnotch
    def bp(x):
        sos = butter(2, [0.5/(ECG_HZ/2), 40.0/(ECG_HZ/2)], btype='band', output='sos')
        return sosfiltfilt(sos, x - np.mean(x))
    def notch(x):
        b, a = iirnotch(50.0, 30.0, fs=ECG_HZ)
        return filtfilt(b, a, x)
    ecg_filt = notch(bp(ecg_win))
    detected = pan_tompkins(ecg_filt, fs=ECG_HZ)
    # shift detected back to absolute indices
    detected_abs = detected + win_start

    # Filter manual labels to window
    manual_in_win = manual[(manual >= win_start) & (manual < win_end)]

    tol_samples = int(TOLERANCE_MS * ECG_HZ / 1000)
    TP, FP, FN, matches = match_peaks(detected_abs, manual_in_win, tol_samples)

    precision = TP / (TP + FP) if (TP + FP) > 0 else 0
    recall = TP / (TP + FN) if (TP + FN) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    errors_ms = np.array([m[2] for m in matches]) / ECG_HZ * 1000 if matches else np.array([])

    print(f'\n--- Detection results ---')
    print(f'  Manual peaks (in window):   {len(manual_in_win)}')
    print(f'  Detected peaks (in window): {len(detected_abs)}')
    print(f'  True Positives (TP):        {TP}')
    print(f'  False Positives (FP):       {FP}')
    print(f'  False Negatives (FN):       {FN}')
    print(f'  Precision:                  {precision*100:.2f}%  (target >95%)')
    print(f'  Recall:                     {recall*100:.2f}%  (target >95%)')
    print(f'  F1 Score:                   {f1*100:.2f}%')
    if len(errors_ms) > 0:
        print(f'  Matching error mean:        {np.mean(errors_ms):.1f} ms')
        print(f'  Matching error std:         {np.std(errors_ms):.1f} ms')
        print(f'  Matching error max:         {np.max(errors_ms):.1f} ms')

    verdict = 'PASS' if (precision >= 0.95 and recall >= 0.95) else 'FAIL'
    print(f'\n  VERDICT: {verdict}')
    if verdict == 'FAIL':
        if precision < 0.95:
            print(f'    -> Precision too low: {FP} false positives. Likely causes:')
            print(f'       - T-wave double-detection (increase refractory)')
            print(f'       - Motion artifact triggering (improve filtering)')
            print(f'       - Noise spikes (check electrode contact)')
        if recall < 0.95:
            print(f'    -> Recall too low: {FN} missed peaks. Likely causes:')
            print(f'       - Low R-wave amplitude (check electrode placement)')
            print(f'       - Threshold too high (motion burst hijacked SPKI)')
            print(f'       - Refractory too long (decrease from 250 ms)')

    # Save markdown report
    out_md = 'rpeak_validation_report.md'
    with open(out_md, 'w') as f:
        f.write('# R-Peak Validation Report\n\n')
        f.write(f'**CSV**: `{os.path.basename(csv_path)}`\n\n')
        f.write(f'**Manual labels**: `{manual_path}` ({len(manual)} peaks total)\n\n')
        f.write(f'**Analysis window**: samples {win_start}-{win_end} ({(win_end-win_start)/ECG_HZ:.1f} s)\n\n')
        f.write(f'**Tolerance**: ±{TOLERANCE_MS} ms\n\n')
        f.write('## Detection Results\n\n')
        f.write(f'| Metric | Value |\n|---|---|\n')
        f.write(f'| Manual peaks (in window) | {len(manual_in_win)} |\n')
        f.write(f'| Detected peaks (in window) | {len(detected_abs)} |\n')
        f.write(f'| True Positives (TP) | {TP} |\n')
        f.write(f'| False Positives (FP) | {FP} |\n')
        f.write(f'| False Negatives (FN) | {FN} |\n')
        f.write(f'| Precision | {precision*100:.2f}% |\n')
        f.write(f'| Recall | {recall*100:.2f}% |\n')
        f.write(f'| F1 Score | {f1*100:.2f}% |\n')
        if len(errors_ms) > 0:
            f.write(f'| Matching error mean | {np.mean(errors_ms):.1f} ms |\n')
            f.write(f'| Matching error std | {np.std(errors_ms):.1f} ms |\n')
            f.write(f'| Matching error max | {np.max(errors_ms):.1f} ms |\n')
        f.write(f'\n## Verdict: **{verdict}**\n\n')
        f.write(f'Targets: precision >95%, recall >95%, F1 >95%.\n\n')
        if verdict == 'FAIL':
            f.write('## Failure Analysis\n\n')
            if precision < 0.95:
                f.write(f'- **Precision too low** ({precision*100:.2f}%): {FP} false positives.\n')
                f.write('  - T-wave double-detection → increase refractory period\n')
                f.write('  - Motion artifact triggering → improve filtering or add motion gate\n')
                f.write('  - Noise spikes → check electrode contact and shielding\n')
            if recall < 0.95:
                f.write(f'- **Recall too low** ({recall*100:.2f}%): {FN} missed peaks.\n')
                f.write('  - Low R-wave amplitude → check electrode placement and contact\n')
                f.write('  - Threshold too high → motion burst hijacked SPKI; add motion-aware thresholding\n')
                f.write('  - Refractory too long → decrease from 250 ms\n')
    print(f'\nSaved: {out_md}')

    out_json = 'rpeak_validation.json'
    with open(out_json, 'w') as f:
        json.dump({
            'csv': csv_path, 'manual_labels': manual_path,
            'window_start': win_start, 'window_end': win_end,
            'tolerance_ms': TOLERANCE_MS,
            'manual_count': len(manual_in_win), 'detected_count': len(detected_abs),
            'TP': TP, 'FP': FP, 'FN': FN,
            'precision': precision, 'recall': recall, 'f1': f1,
            'verdict': verdict,
            'matching_error_mean_ms': float(np.mean(errors_ms)) if len(errors_ms) > 0 else 0,
            'matching_error_std_ms': float(np.std(errors_ms)) if len(errors_ms) > 0 else 0,
            'matching_error_max_ms': float(np.max(errors_ms)) if len(errors_ms) > 0 else 0,
        }, f, indent=2)
    print(f'Saved: {out_json}')

if __name__ == '__main__':
    main()
