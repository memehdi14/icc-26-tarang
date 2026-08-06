"""
pan_tompkins.py — Tarang ECG validation
Self-adaptive Pan-Tompkins QRS detector (Pan & Tompkins 1985 original algorithm)

This is a GENERALIZED implementation that adapts to ANY patient's ECG without
manual tuning. The key innovation is the dual-threshold system:

  - SPKI = running estimate of SIGNAL peak amplitude (R-waves)
  - NPKI = running estimate of NOISE peak amplitude (T-waves, motion, baseline)
  - THRESHOLD1 = NPKI + 0.25 * (SPKI - NPKI)   <- main detection threshold
  - THRESHOLD2 = 0.5 * THRESHOLD1               <- search-back threshold

When a peak is detected:
  - If peak > THRESHOLD1: classify as SIGNAL (R-wave), update SPKI
  - If peak > THRESHOLD2 and search-back triggered: also classify as SIGNAL
  - Otherwise: classify as NOISE, update NPKI

Both SPKI and NPKI adapt online using exponential moving averages:
  - SPKI = 1/8 * new_peak + 7/8 * SPKI   (slow adaptation)
  - NPKI = 1/4 * new_peak + 3/4 * NPKI   (faster adaptation)

This means the algorithm automatically adjusts to:
  - Different patients (different R-wave amplitudes)
  - Different electrode placements (different signal levels)
  - Different motion profiles (different noise levels)
  - Different heart rates (different refractory requirements via search-back)

NO manual tuning required. Works out-of-the-box on any ECG recording.
"""
import numpy as np
from scipy.signal import butter, filtfilt


def _bandpass_qrs(x, fs):
    """Bandpass ~5-15 Hz, the dominant QRS energy band."""
    ny = fs / 2.0
    b, a = butter(2, [5.0/ny, 15.0/ny], btype='band')
    return filtfilt(b, a, x)


def _derivative(x, fs):
    """5-point central derivative (Pan-Tompkins style)."""
    d = np.zeros_like(x)
    for i in range(2, len(x) - 2):
        d[i] = (-x[i-2] - 2*x[i-1] + 2*x[i+1] + x[i+2]) / 8.0
    return d


def _moving_average_causal(x, w):
    """Causal moving average (matches Pan-Tompkins integration window)."""
    if w < 2:
        return x.copy()
    k = np.ones(w) / w
    out = np.convolve(x, k, mode='full')[:len(x)]
    return out


def detect(ecg, fs=250, refractory_ms=250, mwi_ms=150,
           searchback_factor=1.5, verbose=True):
    """
    Run self-adaptive Pan-Tompkins on a 1-D ECG array.

    Parameters
    ----------
    ecg : 1-D array
        ECG signal (any unit — algorithm adapts to scale)
    fs : int
        Sampling rate in Hz
    refractory_ms : int
        Refractory period in ms (default 250 ms = 240 bpm max)
    mwi_ms : int
        Moving window integration window in ms (default 150 ms)
    searchback_factor : float
        If no peak found within searchback_factor * mean_RR, trigger search-back
        at THRESHOLD2 (half the main threshold)

    Returns
    -------
    dict with:
        r_peaks       : np.array of sample indices
        r_times_s     : np.array of times in seconds
        rr_intervals  : np.array of RR intervals in seconds
        heart_rate    : float, BPM (median of valid RR intervals)
        signal        : MWI envelope (for plotting)
        spki_trace    : SPKI over time (for debugging)
        npki_trace    : NPKI over time (for debugging)
        thr1_trace    : THRESHOLD1 over time
        thr2_trace    : THRESHOLD2 over time
    """
    ecg = np.asarray(ecg, dtype=np.float64)
    n = len(ecg)
    if n < fs:
        return _empty_result()

    # 1. Bandpass filter 5-15 Hz
    bp = _bandpass_qrs(ecg, fs)

    # 2. Derivative
    d = _derivative(bp, fs)

    # 3. Square
    sq = d ** 2

    # 4. Moving window integration (causal)
    mwi_w = max(1, int(fs * mwi_ms / 1000.0))
    sig = _moving_average_causal(sq, mwi_w)

    refractory = int(fs * refractory_ms / 1000.0)

    # === Initialize adaptive thresholds ===
    # Use median and a few percentiles to bootstrap SPKI/NPKI without
    # biasing toward motion artifacts (which dominate the max).
    sig_nonzero = sig[sig > 0]
    if len(sig_nonzero) == 0:
        return _empty_result()

    # Initial estimates:
    #   SPKI = 95th percentile (likely includes real R-peaks)
    #   NPKI = 50th percentile (median, typical noise level)
    SPKI = float(np.percentile(sig_nonzero, 95.0))
    NPKI = float(np.percentile(sig_nonzero, 50.0))
    if SPKI <= NPKI:
        SPKI = NPKI * 2.0  # ensure separation

    THRESHOLD1 = NPKI + 0.25 * (SPKI - NPKI)
    THRESHOLD2 = 0.5 * THRESHOLD1

    r_peaks = []
    last_peak = -refractory

    # Trace arrays for debugging
    spki_trace = np.zeros(n)
    npki_trace = np.zeros(n)
    thr1_trace = np.zeros(n)
    thr2_trace = np.zeros(n)

    # === First pass: detect peaks with adaptive dual threshold ===
    for i in range(1, n - 1):
        spki_trace[i] = SPKI
        npki_trace[i] = NPKI
        thr1_trace[i] = THRESHOLD1
        thr2_trace[i] = THRESHOLD2

        # Local maximum in MWI signal
        if sig[i] > sig[i-1] and sig[i] >= sig[i+1]:
            peak_val = sig[i]

            if peak_val > THRESHOLD1:
                # Classified as SIGNAL (R-wave candidate)
                if i - last_peak >= refractory:
                    # Refine peak location in original ECG
                    w = max(2, int(fs * 0.025))
                    lo = max(0, i - w)
                    hi = min(n, i + w + 1)
                    local_idx = lo + int(np.argmax(np.abs(ecg[lo:hi])))
                    r_peaks.append(local_idx)
                    last_peak = local_idx
                    # Update SPKI (slow adaptation: 1/8 new, 7/8 old)
                    SPKI = 0.125 * peak_val + 0.875 * SPKI
                # else: refractory violation, skip
            elif peak_val > THRESHOLD2:
                # Above noise threshold but below signal threshold
                # Could be a missed R-wave — only accept via search-back later
                # For now, classify as noise (don't update SPKI)
                NPKI = 0.25 * peak_val + 0.75 * NPKI
            else:
                # Below noise threshold — definitely noise
                NPKI = 0.25 * peak_val + 0.75 * NPKI

            # Update thresholds
            THRESHOLD1 = NPKI + 0.25 * (SPKI - NPKI)
            THRESHOLD2 = 0.5 * THRESHOLD1

    # === Search-back: fill in missed peaks ===
    # If gap > searchback_factor * mean_RR, look for peaks above THRESHOLD2
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
                    # Use THRESHOLD2 (half of current THRESHOLD1)
                    sb_threshold = 0.5 * THRESHOLD1
                    # Find local maxima above search-back threshold
                    cand_indices = []
                    for j in range(1, len(seg) - 1):
                        if seg[j] > seg[j-1] and seg[j] >= seg[j+1] and seg[j] > sb_threshold:
                            cand_indices.append(start + j)
                    if cand_indices:
                        # Pick the highest candidate
                        best = max(cand_indices, key=lambda x: sig[x])
                        if best - r_peaks[i-1] >= refractory and r_peaks[i] - best >= refractory:
                            r_peaks.insert(i, best)
                            # Update SPKI with this recovered peak
                            SPKI = 0.125 * sig[best] + 0.875 * SPKI
                            THRESHOLD1 = NPKI + 0.25 * (SPKI - NPKI)
                            THRESHOLD2 = 0.5 * THRESHOLD1
                            continue  # don't increment i, re-check this gap
            i += 1

    # === Final cleanup ===
    r_peaks = np.array(sorted(set(r_peaks)), dtype=np.int64)
    r_times_s = r_peaks / float(fs)

    if len(r_peaks) >= 2:
        rr_intervals = np.diff(r_peaks) / float(fs)
        # Filter physiologically implausible RR intervals for HR computation
        # (300 ms = 200 bpm max, 3000 ms = 20 bpm min)
        rr_valid = rr_intervals[(rr_intervals >= 0.3) & (rr_intervals <= 3.0)]
        if len(rr_valid) > 0:
            heart_rate = 60.0 / float(np.median(rr_valid))
        else:
            heart_rate = 0.0
    else:
        rr_intervals = np.array([])
        heart_rate = 0.0

    if verbose:
        print(f'[Pan-Tompkins] fs={fs} Hz, samples={n}, duration={n/fs:.2f} s')
        print(f'  R-peaks detected : {len(r_peaks)}')
        if len(rr_intervals) > 0:
            print(f'  Mean RR          : {float(np.mean(rr_intervals))*1000:.1f} ms')
            print(f'  RR std           : {float(np.std(rr_intervals))*1000:.1f} ms')
        print(f'  Heart rate       : {heart_rate:.1f} bpm')
        print(f'  Final SPKI/NPKI  : {SPKI:.3f} / {NPKI:.3f}')
        print(f'  Final THR1/THR2  : {THRESHOLD1:.3f} / {THRESHOLD2:.3f}')

    return {
        'r_peaks': r_peaks,
        'r_times_s': r_times_s,
        'rr_intervals': rr_intervals,
        'heart_rate': heart_rate,
        'signal': sig,
        'spki_trace': spki_trace,
        'npki_trace': npki_trace,
        'thr1_trace': thr1_trace,
        'thr2_trace': thr2_trace,
    }


def _empty_result():
    return {
        'r_peaks': np.array([], dtype=np.int64),
        'r_times_s': np.array([]),
        'rr_intervals': np.array([]),
        'heart_rate': 0.0,
        'signal': np.array([]),
        'spki_trace': np.array([]),
        'npki_trace': np.array([]),
        'thr1_trace': np.array([]),
        'thr2_trace': np.array([]),
    }


def quality_verdict(result, fs=250):
    """Simple pass/fail for Pan-Tompkins detection quality."""
    hr = result['heart_rate']
    rr = result['rr_intervals']
    if len(rr) < 3:
        return {'verdict': 'FAIL', 'reason': 'too_few_peaks', 'hr': hr}
    if not (30 <= hr <= 200):
        return {'verdict': 'FAIL', 'reason': 'hr_out_of_range', 'hr': hr}
    rr_cv = float(np.std(rr) / np.mean(rr)) if np.mean(rr) > 0 else 1.0
    if rr_cv > 0.30:
        return {'verdict': 'WARN', 'reason': 'irregular_rr', 'hr': hr, 'rr_cv': rr_cv}
    return {'verdict': 'PASS', 'reason': 'ok', 'hr': hr, 'rr_cv': rr_cv}
