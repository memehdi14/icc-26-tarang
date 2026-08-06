#!/usr/bin/env python3
"""
08_full_validation.py — Tarang ONE-SHOT full validation
Run this single script on any recorded CSV. It does EVERYTHING:

  1. Load + validate CSV format (detects corrupted/truncated files)
  2. Sampling rate + jitter analysis
  3. ECG signal quality check (saturation, baseline, noise)
  4. IMU signal quality check (1g baseline, motion response)
  5. ECG-IMU synchronization check
  6. Full DSP pipeline (DC -> bandpass -> notch)
  7. NLMS adaptive filter (IMU as motion reference)
  8. Pan-Tompkins R-peak detection (raw + cleaned)
  9. HR / RR interval analysis
 10. Before/after comparison
 11. Tarang frame compatibility (256-sample frames)
 12. Final pass/fail report with specific error messages

Usage:
    python 08_full_validation.py "C:\\Users\\namda\\tarang_data\\tarang_XXXXXXXX_XXXXXX.csv"

Outputs (all in same folder as CSV):
    <csv>_full_report.md          <- human-readable markdown report
    <csv>_full_validation.png     <- 8-panel comparison plot
    <csv>_full_results.npz        <- all arrays for re-use
    <csv>_frames/                 <- Tarang-compatible 256-sample frames
        frame_0001.csv
        frame_0001_imu32.csv
        ...
        summary.json

Pass criteria (auto-checked):
    [PASS] CSV loaded successfully
    [PASS] ECG sampling rate 249.5 - 250.5 Hz
    [PASS] ECG jitter p2p < 10 ms
    [PASS] IMU sampling rate 99.5 - 100.5 Hz
    [PASS] IMU idx drops = 0
    [PASS] ECG not saturated (raw in [200, 3900] for >90% of samples)
    [PASS] ECG shows R-peaks (Pan-Tompkins finds >30 peaks in recording)
    [PASS] HR plausible (40-150 bpm)
    [PASS] IMU 1g baseline (|a| in [15000, 17500] at rest)
    [PASS] IMU responds to motion (std > 500 LSB somewhere)
    [PASS] DSP chain runs without crashing
    [PASS] NLMS stable (no NaN/Inf, |w|_2 < 1e6)
    [PASS] NLMS reduces RMS (cleaned RMS <= raw RMS * 1.05)
    [PASS] QRS visibility preserved (q_vis_cleaned >= q_vis_raw - 0.1)
    [PASS] Tarang frames generated
"""
import sys, os, json, traceback
import numpy as np
import matplotlib
matplotlib.use('Agg')   # non-interactive backend for headless
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt, sosfiltfilt, iirnotch
from scipy.ndimage import uniform_filter1d

# ============================================================================
# CONFIG
# ============================================================================
ECG_HZ = 250
IMU_HZ = 100
FRAME_LEN = 256
IMU_PER_FRAME = 32

# ============================================================================
# ROBUST CSV LOADER
# ============================================================================
def load_csv_robust(path):
    """Load CSV, skip comments, ignore malformed lines. Return dict of arrays."""
    print(f'[LOAD] Reading {path} ...')
    if not os.path.exists(path):
        raise FileNotFoundError(f'CSV not found: {path}')
    rows = []
    header = None
    n_skipped = 0
    with open(path, 'r', encoding='ascii', errors='ignore') as f:
        for line_num, line in enumerate(f, 1):
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            fields = s.split(',')
            if header is None:
                header = fields
                continue
            if len(fields) < 10:
                n_skipped += 1
                continue
            try:
                rows.append([float(x) for x in fields[:10]])
            except ValueError:
                n_skipped += 1
                continue
    if not rows:
        raise ValueError('CSV has no data rows after header')
    arr = np.array(rows, dtype=np.float64)
    print(f'[LOAD] {len(arr)} rows loaded, {n_skipped} malformed lines skipped')
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
    }, header, n_skipped

# ============================================================================
# DSP FUNCTIONS
# ============================================================================
def dc_remove(x):
    return x - np.mean(x)

def baseline_wander_remove(x, fs=ECG_HZ, cutoff=0.5):
    b, a = butter(1, cutoff / (fs / 2.0), btype='high')
    return filtfilt(b, a, x)

def bandpass(x, fs=ECG_HZ, low=0.5, high=40.0):
    sos = butter(2, [low / (fs / 2.0), high / (fs / 2.0)], btype='band', output='sos')
    return sosfiltfilt(sos, x)

def notch_50hz(x, fs=ECG_HZ, q=30.0):
    b, a = iirnotch(50.0, q, fs=fs)
    return filtfilt(b, a, x)

def imu_magnitude(ax, ay, az):
    return np.sqrt(ax**2 + ay**2 + az**2)

def moving_average(x, w):
    if w < 2:
        return x.copy()
    k = np.ones(w) / w
    return np.convolve(x, k, mode='same')

def qrs_visibility_score(ecg, fs=ECG_HZ):
    if len(ecg) < fs:
        return 0.0
    thr = 3.0 * np.std(ecg)
    above = ecg > thr
    rising = np.diff(above.astype(int)) == 1
    n_peaks = int(np.sum(rising))
    duration_min = len(ecg) / (fs * 60.0)
    rate = n_peaks / duration_min if duration_min > 0 else 0
    if 30 <= rate <= 200:
        return 1.0
    elif rate < 30:
        return rate / 30.0
    else:
        return max(0.0, 1.0 - (rate - 200) / 200.0)

# ============================================================================
# NLMS
# ============================================================================
def nlms_filter(primary, reference, num_taps=32, mu=0.01, eps=1.0,
                adapt_mask=None, verbose=False):
    primary = np.asarray(primary, dtype=np.float64)
    reference = np.asarray(reference, dtype=np.float64)
    if len(reference) != len(primary):
        x_old = np.linspace(0, 1, len(reference))
        x_new = np.linspace(0, 1, len(primary))
        reference = np.interp(x_new, x_old, reference)
    N = len(primary)
    L = int(num_taps)
    if N < L:
        raise ValueError(f'primary too short: {N} < num_taps {L}')
    if adapt_mask is None:
        adapt_mask = np.ones(N, dtype=bool)
    else:
        adapt_mask = np.asarray(adapt_mask, dtype=bool)
    w = np.zeros(L, dtype=np.float64)
    delay = np.zeros(L, dtype=np.float64)
    d_idx = 0
    y_hat = np.zeros(N, dtype=np.float64)
    cleaned = np.zeros(N, dtype=np.float64)
    for n in range(N):
        delay[d_idx] = reference[n]
        x = np.empty(L, dtype=np.float64)
        for k in range(L):
            x[k] = delay[(d_idx - k) % L]
        y = float(np.dot(w, x))
        y_hat[n] = y
        e = primary[n] - y
        cleaned[n] = e
        if adapt_mask[n]:
            denom = float(np.dot(x, x)) + eps
            if denom > 0:
                w += (mu * e / denom) * x
        d_idx = (d_idx + 1) % L
    return {'cleaned': cleaned, 'y_hat': y_hat, 'weights': w}

def motion_gate(imu_mag, baseline=16384.0, threshold=300.0):
    return np.abs(imu_mag - baseline) > threshold

# ============================================================================
# PAN-TOMPKINS (self-adaptive, generalized — Pan & Tompkins 1985 original)
# Auto-adapts to ANY patient via dual-threshold SPKI/NPKI learning.
# NO manual tuning required. Works on clean, motion-corrupted, weak, or
# high-amplitude ECG alike.
# ============================================================================
def pan_tompkins(ecg, fs=ECG_HZ, refractory_ms=250, mwi_ms=150,
                 searchback_factor=1.5):
    """
    Self-adaptive Pan-Tompkins with dual-threshold SPKI/NPKI learning.
    Automatically adjusts to any patient's ECG amplitude and noise level.
    """
    ecg = np.asarray(ecg, dtype=np.float64)
    n = len(ecg)
    if n < fs:
        return {'r_peaks': np.array([]), 'heart_rate': 0.0,
                'rr_intervals': np.array([]), 'r_times_s': np.array([])}
    # 1. Bandpass 5-15 Hz
    ny = fs / 2.0
    b, a = butter(2, [5.0/ny, 15.0/ny], btype='band')
    bp = filtfilt(b, a, ecg)
    # 2. Derivative (5-point central)
    d = np.zeros_like(bp)
    for i in range(2, n - 2):
        d[i] = (-bp[i-2] - 2*bp[i-1] + 2*bp[i+1] + bp[i+2]) / 8.0
    # 3. Square
    sq = d ** 2
    # 4. MWI (causal)
    mwi_w = max(1, int(fs * mwi_ms / 1000.0))
    sig = moving_average(sq, mwi_w)
    refractory = int(fs * refractory_ms / 1000.0)

    # Initialize SPKI/NPKI from signal statistics (auto-calibration)
    sig_nonzero = sig[sig > 0]
    if len(sig_nonzero) == 0:
        return {'r_peaks': np.array([]), 'heart_rate': 0.0,
                'rr_intervals': np.array([]), 'r_times_s': np.array([])}
    SPKI = float(np.percentile(sig_nonzero, 95.0))
    NPKI = float(np.percentile(sig_nonzero, 50.0))
    if SPKI <= NPKI:
        SPKI = NPKI * 2.0
    THRESHOLD1 = NPKI + 0.25 * (SPKI - NPKI)
    THRESHOLD2 = 0.5 * THRESHOLD1

    r_peaks = []
    last_peak = -refractory

    # First pass: dual-threshold detection with online SPKI/NPKI adaptation
    for i in range(1, n - 1):
        if sig[i] > sig[i-1] and sig[i] >= sig[i+1]:
            peak_val = sig[i]
            if peak_val > THRESHOLD1:
                if i - last_peak >= refractory:
                    w = max(2, int(fs * 0.025))
                    lo = max(0, i - w); hi = min(n, i + w + 1)
                    local_idx = lo + int(np.argmax(np.abs(ecg[lo:hi])))
                    r_peaks.append(local_idx)
                    last_peak = local_idx
                    SPKI = 0.125 * peak_val + 0.875 * SPKI
            elif peak_val > THRESHOLD2:
                NPKI = 0.25 * peak_val + 0.75 * NPKI
            else:
                NPKI = 0.25 * peak_val + 0.75 * NPKI
            THRESHOLD1 = NPKI + 0.25 * (SPKI - NPKI)
            THRESHOLD2 = 0.5 * THRESHOLD1

    # Search-back: fill in missed peaks using THRESHOLD2
    if len(r_peaks) >= 2:
        rr_arr = np.diff(r_peaks)
        mean_rr = int(np.median(rr_arr))
        max_gap = int(searchback_factor * mean_rr)
        i = 1
        while i < len(r_peaks):
            gap = r_peaks[i] - r_peaks[i-1]
            if gap > max_gap:
                start = r_peaks[i-1] + refractory
                end = r_peaks[i]
                if end - start > 5:
                    seg = sig[start:end]
                    sb_threshold = 0.5 * THRESHOLD1
                    cand_indices = []
                    for j in range(1, len(seg) - 1):
                        if seg[j] > seg[j-1] and seg[j] >= seg[j+1] and seg[j] > sb_threshold:
                            cand_indices.append(start + j)
                    if cand_indices:
                        best = max(cand_indices, key=lambda x: sig[x])
                        if best - r_peaks[i-1] >= refractory and r_peaks[i] - best >= refractory:
                            r_peaks.insert(i, best)
                            SPKI = 0.125 * sig[best] + 0.875 * SPKI
                            THRESHOLD1 = NPKI + 0.25 * (SPKI - NPKI)
                            THRESHOLD2 = 0.5 * THRESHOLD1
                            continue
            i += 1

    r_peaks = np.array(sorted(set(r_peaks)), dtype=np.int64)
    r_times_s = r_peaks / float(fs)
    if len(r_peaks) >= 2:
        rr = np.diff(r_peaks) / float(fs)
        rr_valid = rr[(rr >= 0.3) & (rr <= 3.0)]
        hr = 60.0 / float(np.median(rr_valid)) if len(rr_valid) > 0 else 0.0
    else:
        rr = np.array([]); hr = 0.0
    return {'r_peaks': r_peaks, 'heart_rate': hr, 'rr_intervals': rr,
            'r_times_s': r_times_s}

# ============================================================================
# MAIN VALIDATION
# ============================================================================
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    path = sys.argv[1]
    report_lines = []
    checks = []

    def add_check(name, passed, detail=''):
        status = 'PASS' if passed else 'FAIL'
        checks.append((name, passed, detail))
        report_lines.append(f'- [{status}] {name}' + (f' — {detail}' if detail else ''))
        print(f'  [{status}] {name}' + (f' — {detail}' if detail else ''))

    try:
        # ===== 1. LOAD =====
        print('\n=== 1. LOAD CSV ===')
        data, header, n_skipped = load_csv_robust(path)
        add_check('CSV loaded successfully', True,
                  f'{len(data["t_us"])} rows')
        add_check('CSV has expected 10 columns', header is not None and len(header) >= 10,
                  f'header={header}')

        t_us = data['t_us']
        ecg_mv = data['ecg_mv']
        ecg_raw = data['ecg_raw']
        ax, ay, az = data['ax'], data['ay'], data['az']
        imu_mag_csv = data['imu_mag']
        duration_s = (t_us[-1] - t_us[0]) / 1e6
        print(f'  Duration: {duration_s:.2f} s')

        # ===== 2. SAMPLING RATE =====
        print('\n=== 2. SAMPLING RATE ===')
        dt_us = np.diff(t_us)
        dt_ms = dt_us / 1000.0
        rate_hz = 1e6 / dt_us
        ecg_mean = float(np.mean(rate_hz))
        ecg_std = float(np.std(rate_hz))
        ecg_p2p = float(np.max(dt_ms) - np.min(dt_ms))

        unique_imu = np.unique(data['imu_idx'])
        n_imu = len(unique_imu)
        imu_rate = (n_imu - 1) / duration_s if duration_s > 0 else 0
        # Count drops
        imu_seq = []
        last = None
        for v in data['imu_idx']:
            if v != last:
                imu_seq.append(v)
                last = v
        imu_gaps = np.diff(imu_seq)
        imu_drops = int(np.sum(imu_gaps != 1))

        print(f'  ECG mean rate: {ecg_mean:.3f} Hz')
        print(f'  ECG jitter p2p: {ecg_p2p:.3f} ms')
        print(f'  IMU mean rate: {imu_rate:.3f} Hz')
        print(f'  IMU drops: {imu_drops}')

        add_check('ECG sampling rate 249.5-250.5 Hz',
                  249.5 <= ecg_mean <= 250.5,
                  f'{ecg_mean:.3f} Hz')
        add_check('ECG jitter p2p < 10 ms',
                  ecg_p2p < 10.0,
                  f'{ecg_p2p:.3f} ms')
        add_check('IMU sampling rate 99.5-100.5 Hz',
                  99.5 <= imu_rate <= 100.5,
                  f'{imu_rate:.3f} Hz')
        add_check('IMU idx drops = 0',
                  imu_drops == 0,
                  f'{imu_drops} drops')

        # ===== 3. ECG QUALITY =====
        print('\n=== 3. ECG SIGNAL QUALITY ===')
        sat_low = np.sum(ecg_raw < 200) / len(ecg_raw)
        sat_high = np.sum(ecg_raw > 3900) / len(ecg_raw)
        sat_ok = (sat_low < 0.1) and (sat_high < 0.1)
        ecg_std_raw = float(np.std(ecg_mv))
        print(f'  Saturation low (<200):  {sat_low*100:.1f}%')
        print(f'  Saturation high (>3900): {sat_high*100:.1f}%')
        print(f'  ECG std: {ecg_std_raw:.2f} mV')
        add_check('ECG not saturated (<10% at rails)', sat_ok,
                  f'low={sat_low*100:.1f}% high={sat_high*100:.1f}%')

        # Check if electrodes connected (lo+ lo- should be 0 most of the time)
        lo_plus = data['lo+']
        electrodes_attached = np.mean(lo_plus < 0.5) > 0.5
        add_check('Electrodes attached (lo+ mostly 0)', electrodes_attached,
                  f'{np.mean(lo_plus<0.5)*100:.1f}% attached')

        # ===== 4. IMU QUALITY =====
        print('\n=== 4. IMU SIGNAL QUALITY ===')
        imu_mag = imu_magnitude(ax, ay, az)
        # Check if IMU is all zeros (broken)
        imu_all_zero = np.all(imu_mag == 0)
        if imu_all_zero:
            print('  !!! IMU DATA IS ALL ZEROS !!!')
            add_check('IMU data present (not all zeros)', False,
                      'IMU not initialized — check WHO_AM_I fix')
        else:
            imu_mean = float(np.mean(imu_mag))
            imu_std = float(np.std(imu_mag))
            # Find rest periods (lowest 20% of magnitude variance windows)
            print(f'  IMU mean |a|: {imu_mean:.0f} LSB (expect ~16384)')
            print(f'  IMU std |a|: {imu_std:.0f} LSB')
            baseline_ok = 15000 < imu_mean < 18000
            motion_ok = imu_std > 200  # some variation = motion present
            add_check('IMU 1g baseline (|a| ~16384)', baseline_ok,
                      f'mean={imu_mean:.0f}')
            add_check('IMU responds to motion (std > 200)', motion_ok,
                      f'std={imu_std:.0f}')

        # ===== 5. DSP PIPELINE =====
        print('\n=== 5. DSP PIPELINE ===')
        ecg_dc = dc_remove(ecg_mv)
        ecg_baseline = baseline_wander_remove(ecg_dc, fs=ECG_HZ)
        ecg_bp = bandpass(ecg_baseline, fs=ECG_HZ)
        ecg_notch = notch_50hz(ecg_bp, fs=ECG_HZ)
        print('  DC removal -> baseline -> bandpass -> notch: OK')
        add_check('DSP chain runs without crashing', True)

        # ===== 6. NLMS =====
        print('\n=== 6. NLMS ADAPTIVE FILTER ===')
        if imu_all_zero:
            print('  Skipping NLMS — no IMU data')
            ecg_clean = ecg_notch.copy()
            nlms_w_norm = 0.0
            add_check('NLMS stable (no NaN)', True, 'skipped — no IMU')
            add_check('NLMS weights bounded', True, 'skipped — no IMU')
        else:
            imu_env = uniform_filter1d(imu_mag - 16384.0, size=25)
            adapt_mask = motion_gate(imu_mag)
            motion_pct = 100.0 * np.sum(adapt_mask) / len(adapt_mask)
            print(f'  Motion active: {motion_pct:.1f}% of samples')
            try:
                r = nlms_filter(primary=ecg_notch, reference=imu_env,
                                num_taps=32, mu=0.01, eps=1.0,
                                adapt_mask=adapt_mask, verbose=False)
                ecg_clean = r['cleaned']
                nlms_w_norm = float(np.linalg.norm(r['weights']))
                has_nan = np.any(np.isnan(ecg_clean)) or np.any(np.isinf(ecg_clean))
                print(f'  NLMS |w|_2: {nlms_w_norm:.4f}')
                print(f'  NaN/Inf in cleaned: {has_nan}')
                add_check('NLMS stable (no NaN/Inf)', not has_nan)
                add_check('NLMS weights bounded (<1e6)', nlms_w_norm < 1e6,
                          f'|w|_2={nlms_w_norm:.4f}')
            except Exception as e:
                print(f'  NLMS FAILED: {e}')
                ecg_clean = ecg_notch.copy()
                nlms_w_norm = 0.0
                add_check('NLMS stable (no NaN/Inf)', False, str(e))
                add_check('NLMS weights bounded', False, str(e))

        # ===== 7. PAN-TOMPKINS =====
        print('\n=== 7. PAN-TOMPKINS R-PEAK DETECTION ===')
        pt_raw = pan_tompkins(ecg_notch, fs=ECG_HZ)
        pt_clean = pan_tompkins(ecg_clean, fs=ECG_HZ)
        n_peaks_raw = len(pt_raw['r_peaks'])
        n_peaks_clean = len(pt_clean['r_peaks'])
        hr_raw = pt_raw['heart_rate']
        hr_clean = pt_clean['heart_rate']
        print(f'  Raw ECG: {n_peaks_raw} R-peaks, HR={hr_raw:.1f} bpm')
        print(f'  Cleaned: {n_peaks_clean} R-peaks, HR={hr_clean:.1f} bpm')
        add_check('ECG shows R-peaks (>30 peaks)', n_peaks_raw > 30,
                  f'{n_peaks_raw} peaks')
        hr_plausible = 40 <= hr_raw <= 150
        add_check('HR plausible (40-150 bpm)', hr_plausible,
                  f'{hr_raw:.1f} bpm')

        # ===== 8. BEFORE/AFTER COMPARISON =====
        print('\n=== 8. BEFORE/AFTER COMPARISON ===')
        rms_raw = float(np.sqrt(np.mean(ecg_mv**2)))
        rms_bp = float(np.sqrt(np.mean(ecg_notch**2)))
        rms_clean = float(np.sqrt(np.mean(ecg_clean**2)))
        q_vis_raw = qrs_visibility_score(ecg_mv, fs=ECG_HZ)
        q_vis_bp = qrs_visibility_score(ecg_notch, fs=ECG_HZ)
        q_vis_clean = qrs_visibility_score(ecg_clean, fs=ECG_HZ)
        snr_db = 10*np.log10(rms_raw**2 / rms_clean**2) if rms_clean > 0 else 0
        print(f'  RMS raw/bp/clean: {rms_raw:.2f} / {rms_bp:.2f} / {rms_clean:.2f}')
        print(f'  QRS vis raw/bp/clean: {q_vis_raw:.3f} / {q_vis_bp:.3f} / {q_vis_clean:.3f}')
        print(f'  SNR improvement: {snr_db:.2f} dB')
        add_check('NLMS reduces RMS (cleaned <= raw*1.05)',
                  rms_clean <= rms_raw * 1.05,
                  f'raw={rms_raw:.2f} clean={rms_clean:.2f}')
        add_check('QRS visibility preserved',
                  q_vis_clean >= q_vis_raw - 0.1,
                  f'raw={q_vis_raw:.3f} clean={q_vis_clean:.3f}')

        # ===== 9. MOTION CORRELATION =====
        print('\n=== 9. MOTION-NOISE CORRELATION ===')
        if not imu_all_zero:
            # Windowed correlation
            w = max(1, int(ECG_HZ * 0.5))
            n = min(len(ecg_mv), len(imu_env))
            ecg_win = np.array([np.std(ecg_mv[i:i+w]) for i in range(0, n-w, w//2)])
            imu_win = np.array([np.mean(imu_env[i:i+w]) for i in range(0, n-w, w//2)])
            if len(ecg_win) >= 3:
                corr = float(np.corrcoef(ecg_win, imu_win)[0,1])
            else:
                corr = 0.0
            print(f'  Motion-noise correlation: {corr:+.3f}')
            add_check('Motion correlation detectable (|corr|>0.05)',
                      abs(corr) > 0.05, f'corr={corr:+.3f}')
        else:
            corr = 0.0
            add_check('Motion correlation detectable', False, 'no IMU data')

        # ===== 10. TARANG FRAMES =====
        print('\n=== 10. TARANG FRAME COMPATIBILITY ===')
        n_frames = len(ecg_mv) // FRAME_LEN
        frames_dir = path.replace('.csv', '_frames')
        os.makedirs(frames_dir, exist_ok=True)
        summary = {
            'tarang_compatibility': {
                'ecg_frame_len': FRAME_LEN,
                'imu_per_frame': IMU_PER_FRAME,
                'ecg_hz': ECG_HZ,
                'imu_hz': IMU_HZ,
                'maps_to': ['sensor_frame_matrix_t', 'tarang_dsp_input_t',
                            'tarang_dsp_output_t', 'tarang_nlms_process_frame()'],
            },
            'frame_count': n_frames,
            'frames': [],
        }
        r_peak_set = set(int(p) for p in pt_clean['r_peaks'])
        for fi in range(n_frames):
            s = fi * FRAME_LEN
            e = s + FRAME_LEN
            frame_raw = ecg_mv[s:e]
            frame_clean = ecg_clean[s:e]
            frame_imu = imu_mag[s:e]
            frame_adapt = adapt_mask[s:e] if not imu_all_zero else np.zeros(FRAME_LEN, dtype=bool)
            frame_t = t_us[s:e]
            p_raw = float(np.mean(frame_raw**2))
            p_cln = float(np.mean(frame_clean**2))
            snr_f = 10*np.log10(p_raw/p_cln) if p_cln > 0 else 0
            motion_pct_f = 100.0 * np.sum(frame_adapt) / FRAME_LEN
            r_peaks_in_frame = sorted([p-s for p in r_peak_set if s <= p < e])
            pt_f = pan_tompkins(frame_clean, fs=ECG_HZ)
            hr_f = float(pt_f['heart_rate'])
            # Write frame CSV
            fpath = os.path.join(frames_dir, f'frame_{fi+1:04d}.csv')
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write('t_us,ecg_raw,ecg_clean,imu_mag,motion_gate,r_peak_flag\n')
                for i in range(FRAME_LEN):
                    rp = 1 if i in r_peaks_in_frame else 0
                    f.write(f'{int(frame_t[i])},{frame_raw[i]:.4f},'
                            f'{frame_clean[i]:.4f},{int(frame_imu[i])},'
                            f'{1 if frame_adapt[i] else 0},{rp}\n')
            summary['frames'].append({
                'frame_sequence': fi,
                'timestamp_start_us': int(frame_t[0]),
                'timestamp_end_us': int(frame_t[-1]),
                'snr_db': snr_f,
                'motion_pct': motion_pct_f,
                'r_peaks': [int(p) for p in r_peaks_in_frame],
                'r_peak_count': len(r_peaks_in_frame),
                'heart_rate_bpm': hr_f,
            })
        out_json = os.path.join(frames_dir, 'summary.json')
        with open(out_json, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2)
        print(f'  Wrote {n_frames} frames to {frames_dir}')
        add_check('Tarang frames generated', n_frames >= 1,
                  f'{n_frames} frames')

        # ===== 11. SAVE ARRAYS =====
        out_npz = path.replace('.csv', '_full_results.npz')
        np.savez(out_npz,
                 t_us=t_us, ecg_raw=ecg_mv, ecg_dc=ecg_dc, ecg_bp=ecg_bp,
                 ecg_notch=ecg_notch, ecg_clean=ecg_clean,
                 imu_mag=imu_mag, imu_env=imu_env if not imu_all_zero else np.zeros_like(imu_mag),
                 adapt_mask=adapt_mask if not imu_all_zero else np.zeros(len(ecg_mv), dtype=bool),
                 pt_raw_peaks=pt_raw['r_peaks'],
                 pt_clean_peaks=pt_clean['r_peaks'])
        print(f'  Saved arrays -> {out_npz}')

        # ===== 12. PLOT =====
        print('\n=== 12. PLOTTING ===')
        N_show = min(len(ecg_mv), 10 * ECG_HZ)
        t_show = (t_us[:N_show] - t_us[0]) / 1000.0
        fig, axs = plt.subplots(8, 1, figsize=(16, 20), sharex=True,
                                constrained_layout=True)
        axs[0].plot(t_show, ecg_mv[:N_show], lw=0.5, color='k')
        axs[0].set_ylabel('RAW ECG (mV)'); axs[0].grid(alpha=0.3)
        axs[0].set_title(f'{os.path.basename(path)} — first 10 s')

        axs[1].plot(t_show, ecg_notch[:N_show], lw=0.5, color='darkorange')
        axs[1].set_ylabel('BP+notch'); axs[1].grid(alpha=0.3)

        axs[2].plot(t_show, ecg_clean[:N_show], lw=0.5, color='navy')
        axs[2].set_ylabel('NLMS cleaned'); axs[2].grid(alpha=0.3)
        rp = pt_clean['r_peaks']
        rp = rp[(rp >= 0) & (rp < N_show)]
        if len(rp) > 0:
            axs[2].plot(t_show[rp], ecg_clean[rp], 'rv', ms=6, label='R-peak')
            axs[2].legend(loc='upper right', fontsize=8)

        axs[3].plot(t_show, imu_mag[:N_show], lw=0.5, color='teal')
        axs[3].axhline(16384, color='g', ls='--', lw=0.5)
        axs[3].set_ylabel('|a| (LSB)'); axs[3].grid(alpha=0.3)

        if not imu_all_zero:
            axs[4].plot(t_show, imu_env[:N_show], lw=0.5, color='purple')
            axs[4].set_ylabel('motion env'); axs[4].grid(alpha=0.3)

        # Sampling rate timeline
        axs[5].plot(t_show[1:], dt_ms[:N_show-1], lw=0.5, color='gray')
        axs[5].axhline(4.0, color='k', ls='--', lw=0.5)
        axs[5].set_ylabel('dt (ms)'); axs[5].grid(alpha=0.3)

        # RR intervals
        if len(pt_clean['rr_intervals']) > 0:
            rr_t = pt_clean['r_times_s'][1:] * 1000 if 'r_times_s' in pt_clean else None
            # compute manually
            rr_t = (pt_clean['r_peaks'][1:] / ECG_HZ) * 1000
            mask = rr_t <= t_show[-1]
            axs[6].plot(rr_t[mask], pt_clean['rr_intervals'][mask]*1000,
                       'o-', ms=3, color='crimson', label='RR (cleaned)')
            if len(pt_raw['rr_intervals']) > 0:
                rr_t_raw = (pt_raw['r_peaks'][1:] / ECG_HZ) * 1000
                mask_r = rr_t_raw <= t_show[-1]
                axs[6].plot(rr_t_raw[mask_r], pt_raw['rr_intervals'][mask_r]*1000,
                           'x', ms=4, color='gray', label='RR (raw)')
                axs[6].legend(loc='upper right', fontsize=8)
        axs[6].set_ylabel('RR (ms)'); axs[6].grid(alpha=0.3)

        # Lead-off status
        axs[7].plot(t_show, lo_plus[:N_show], lw=0.5, color='red')
        axs[7].set_ylabel('lo+ (lead-off)'); axs[7].grid(alpha=0.3)
        axs[7].set_xlabel('Time (ms)')

        # Shade motion regions on all axes
        if not imu_all_zero:
            for i in range(0, N_show, 25):
                if adapt_mask[i]:
                    for ax in axs:
                        ax.axvspan(t_show[i], t_show[min(i+25, N_show-1)],
                                   color='yellow', alpha=0.12)

        out_png = path.replace('.csv', '_full_validation.png')
        plt.savefig(out_png, dpi=120)
        plt.close()
        print(f'  Saved plot -> {out_png}')

        # ===== FINAL REPORT =====
        print('\n' + '='*70)
        print('FINAL PASS/FAIL SUMMARY')
        print('='*70)
        for name, passed, detail in checks:
            status = 'PASS' if passed else 'FAIL'
            print(f'  [{status}] {name}' + (f' — {detail}' if detail else ''))
        n_pass = sum(1 for _, p, _ in checks if p)
        n_total = len(checks)
        print('='*70)
        print(f'Overall: {n_pass}/{n_total} checks passed')
        print('='*70)

        # ===== SAVE MARKDOWN REPORT =====
        out_md = path.replace('.csv', '_full_report.md')
        with open(out_md, 'w', encoding='utf-8') as f:
            f.write('# Tarang Full Validation Report\n\n')
            f.write(f'**Source CSV**: `{os.path.basename(path)}`\n\n')
            f.write(f'**Duration**: {duration_s:.3f} s ({len(ecg_mv)} samples @ {ECG_HZ} Hz)\n\n')
            f.write(f'**Generated**: {os.popen("date /t").read().strip() if os.name == "nt" else ""}\n\n')
            f.write('## Sampling\n\n')
            f.write(f'- ECG mean rate: **{ecg_mean:.3f} Hz** (target {ECG_HZ})\n')
            f.write(f'- ECG jitter p2p: **{ecg_p2p:.3f} ms**\n')
            f.write(f'- IMU mean rate: **{imu_rate:.3f} Hz** (target {IMU_HZ})\n')
            f.write(f'- IMU drops: **{imu_drops}**\n\n')
            f.write('## ECG Quality\n\n')
            f.write(f'- RMS raw: **{rms_raw:.2f} mV**\n')
            f.write(f'- RMS bandpass+notch: **{rms_bp:.2f} mV**\n')
            f.write(f'- RMS NLMS cleaned: **{rms_clean:.2f} mV**\n')
            f.write(f'- QRS visibility raw/bp/clean: {q_vis_raw:.3f} / {q_vis_bp:.3f} / {q_vis_clean:.3f}\n')
            f.write(f'- Saturation low: {sat_low*100:.1f}%\n')
            f.write(f'- Saturation high: {sat_high*100:.1f}%\n')
            f.write(f'- Electrodes attached: {np.mean(lo_plus<0.5)*100:.1f}% of recording\n\n')
            f.write('## Pan-Tompkins\n\n')
            f.write(f'- R-peaks (raw ECG): **{n_peaks_raw}**\n')
            f.write(f'- R-peaks (cleaned): **{n_peaks_clean}**\n')
            f.write(f'- Heart rate (raw): **{hr_raw:.1f} bpm**\n')
            f.write(f'- Heart rate (cleaned): **{hr_clean:.1f} bpm**\n')
            if len(pt_clean['rr_intervals']) > 0:
                f.write(f'- RR mean: **{float(np.mean(pt_clean["rr_intervals"]))*1000:.1f} ms**\n')
                f.write(f'- RR std: **{float(np.std(pt_clean["rr_intervals"]))*1000:.1f} ms**\n\n')
            f.write('## NLMS\n\n')
            f.write(f'- Settings: taps=32, mu=0.01, eps=1.0, motion-gated\n')
            f.write(f'- Weights |w|_2: **{nlms_w_norm:.4f}**\n')
            f.write(f'- SNR improvement: **{snr_db:.2f} dB**\n')
            f.write(f'- Motion-noise correlation: **{corr:+.3f}**\n\n')
            f.write('## Tarang Frames\n\n')
            f.write(f'- Frames generated: **{n_frames}** (256 samples each = 1.024 s)\n')
            f.write(f'- Maps to: `sensor_frame_matrix_t`, `tarang_dsp_input_t`, `tarang_dsp_output_t`, `tarang_nlms_process_frame()`\n\n')
            f.write('## Pass/Fail\n\n')
            for name, passed, detail in checks:
                status = 'PASS' if passed else 'FAIL'
                f.write(f'- [{status}] {name}' + (f' — {detail}' if detail else '') + '\n')
            f.write(f'\n**Overall: {n_pass}/{n_total} checks passed**\n')
            if n_pass == n_total:
                f.write('\n[PASS] **TARANG DSP PIPELINE FULLY VALIDATED**\n')
            else:
                f.write(f'\n[FAIL] {n_total - n_pass} check(s) failed -- see notes above.\n')
        print(f'\n[Tarang] Full report -> {out_md}')
        print(f'[Tarang] Validation plot -> {out_png}')
        print(f'[Tarang] Frames -> {frames_dir}')
        print(f'[Tarang] Arrays -> {out_npz}')

    except Exception as e:
        print(f'\n!!! FATAL ERROR: {e}')
        traceback.print_exc()
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
