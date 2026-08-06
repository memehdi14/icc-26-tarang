"""
dsp.py — Tarang bring-up Stage 9
Pure-Python DSP blocks for validating the ECG pipeline.

All functions take/return numpy arrays. No external libs beyond numpy + scipy.
"""
import numpy as np
from scipy.signal import butter, filtfilt, iirnotch, sosfiltfilt

ECG_HZ = 250

def dc_remove(x: np.ndarray) -> np.ndarray:
    """Subtract mean (cheapest DC removal)."""
    return x - np.mean(x)

def baseline_wander_remove(x: np.ndarray, fs: int = ECG_HZ,
                           cutoff: float = 0.5) -> np.ndarray:
    """High-pass at cutoff Hz to remove baseline wander / breathing."""
    b, a = butter(1, cutoff / (fs / 2.0), btype='high')
    return filtfilt(b, a, x)

def bandpass(x: np.ndarray, fs: int = ECG_HZ,
             low: float = 0.5, high: float = 40.0) -> np.ndarray:
    """Butterworth bandpass — preserves QRS morphology, kills motion + 50/60."""
    sos = butter(2, [low / (fs / 2.0), high / (fs / 2.0)], btype='band', output='sos')
    return sosfiltfilt(sos, x)

def notch_50hz(x: np.ndarray, fs: int = ECG_HZ, q: float = 30.0) -> np.ndarray:
    """IIR notch at 50 Hz (mains in India/EU)."""
    b, a = iirnotch(50.0, q, fs=fs)
    return filtfilt(b, a, x)

def notch_60hz(x: np.ndarray, fs: int = ECG_HZ, q: float = 30.0) -> np.ndarray:
    """IIR notch at 60 Hz (mains in US)."""
    b, a = iirnotch(60.0, q, fs=fs)
    return filtfilt(b, a, x)

def moving_average(x: np.ndarray, w: int = 5) -> np.ndarray:
    """Simple moving-average smoother. w=5 at 250 Hz = 20 ms window."""
    if w < 2:
        return x.copy()
    k = np.ones(w) / w
    return np.convolve(x, k, mode='same')

def imu_magnitude(ax: np.ndarray, ay: np.ndarray, az: np.ndarray) -> np.ndarray:
    """sqrt(ax^2 + ay^2 + az^2) in raw LSB."""
    return np.sqrt(ax.astype(np.float64)**2
                 + ay.astype(np.float64)**2
                 + az.astype(np.float64)**2)

def imu_motion_envelope(imu_mag: np.ndarray, fs_imu: int = 100,
                        win_ms: int = 100) -> np.ndarray:
    """
    Smooth |a| over win_ms to get a slow 'motion intensity' envelope.
    Subtracts 1g (16384 LSB at ±2g) so static readings become ~0.
    Returns motion envelope resampled to ECG rate (250 Hz) via linear interp.
    """
    w = max(1, int(fs_imu * win_ms / 1000.0))
    env = moving_average(imu_mag - 16384.0, w=w)
    return env  # caller resamples to ECG rate

def qrs_visibility_score(ecg_filtered: np.ndarray, fs: int = ECG_HZ) -> float:
    """
    Heuristic QRS visibility score:
      Count prominent peaks (above 3*std) per minute.
      Healthy adult: 60-100 bpm -> 1.0-1.67 Hz QRS rate.
      Score = 1.0 if 0.5-2.5 Hz peak rate, scaled otherwise.
    """
    if len(ecg_filtered) < fs:
        return 0.0
    thr = 3.0 * np.std(ecg_filtered)
    above = ecg_filtered > thr
    rising = np.diff(above.astype(int)) == 1
    n_peaks = int(np.sum(rising))
    duration_min = len(ecg_filtered) / (fs * 60.0)
    rate = n_peaks / duration_min if duration_min > 0 else 0
    if 30 <= rate <= 200:
        return 1.0
    elif rate < 30:
        return rate / 30.0
    else:
        return max(0.0, 1.0 - (rate - 200) / 200.0)

def estimate_snr_improvement(raw: np.ndarray, cleaned: np.ndarray) -> dict:
    """
    Compare raw vs cleaned signal power.
    Assumes cleaned has less noise -> lower std in quiet regions.
    Returns dict with power_raw, power_clean, ratio_db, etc.
    """
    p_raw = float(np.mean(raw**2))
    p_clean = float(np.mean(cleaned**2))
    ratio_db = 10.0 * np.log10(p_raw / p_clean) if p_clean > 0 else float('inf')
    return {
        'power_raw': p_raw,
        'power_clean': p_clean,
        'ratio_db': ratio_db,
        'std_raw': float(np.std(raw)),
        'std_clean': float(np.std(cleaned)),
    }

def motion_noise_correlation(ecg: np.ndarray, imu_env: np.ndarray,
                              fs: int = ECG_HZ,
                              win_ms: int = 500) -> float:
    """
    Compute correlation between |ECG envelope| (noise proxy) and IMU motion
    envelope, both windowed to win_ms. High correlation means motion is
    being injected into the ECG — good candidate for NLMS.
    """
    w = max(1, int(fs * win_ms / 1000.0))
    n = min(len(ecg), len(imu_env))
    ecg_win = np.array([np.std(ecg[i:i+w]) for i in range(0, n-w, w//2)])
    imu_win = np.array([np.mean(imu_env[i:i+w]) for i in range(0, n-w, w//2)])
    if len(ecg_win) < 3:
        return 0.0
    return float(np.corrcoef(ecg_win, imu_win)[0,1])
