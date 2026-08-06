"""
nlms.py — Tarang bring-up Stage 10
Floating-point NLMS adaptive filter for validating the same algorithm as
the production tarang_nlms.c (which is Q15 fixed-point).

Inputs:
    primary   : noisy ECG (1-D float array, length N)
    reference : IMU-derived motion signal (1-D float array, length N or M)
    num_taps  : filter length L (default 32, matches production)
    mu        : step size (default 0.01, matches production TARANG_NLMS_DEFAULT_MU_Q15/32768)
    eps       : regularization (default 1.0)

Output:
    dict with:
      cleaned     : 1-D float array, length N  (the error signal — cleaned ECG)
      y_hat       : 1-D float array, length N  (the estimated artifact)
      weights     : final weight vector (length L)
      power_e_ema : running EMA of error power (for convergence check)
      power_x_ema : running EMA of reference power

How NLMS works (one paragraph):
    At each step n, the filter holds the last L reference samples in a delay
    line x[n]. It computes y_hat[n] = w^T * x[n] (estimated motion artifact).
    The error e[n] = primary[n] - y_hat[n] is the cleaned ECG. The weights
    are updated:  w[k] += mu * e[n] * x[n-k] / (||x||^2 + eps).
    The ||x||^2 normalization makes mu step-size independent of input scale,
    which is why NLMS is more stable than plain LMS.

Stability:
    - If ||x||^2 is huge, the effective step is tiny — slow but safe.
    - If ||x||^2 is tiny (eps dominates), the effective step is bounded
      by mu * e / eps — can blow up if eps is too small and e is large.
    - Production tarang_nlms.c uses eps_q15 to guard against this.
    - Here we use eps=1.0 which is generous; lower if convergence is too slow.

Stability rules of thumb:
    - Start with mu=0.01, L=32, eps=1.0
    - If weights blow up or output NaNs: cut mu by 10x, raise eps by 10x
    - If filter does nothing (weights stay near 0): raise mu by 10x
    - If filter destroys QRS (looks worse than raw): lower L to 8-16

Knowing if NLMS helped:
    - Compare std(cleaned) vs std(primary) — should drop in motion windows
    - Compare QRS visibility score (dsp.qrs_visibility_score) — should rise
    - Look at correlation between y_hat and reference — should grow toward 1
      in motion windows, stay near 0 in rest windows
    - If cleaned looks MORE noisy than primary: NLMS is amplifying noise.
      Cut mu, raise eps, lower L.

Adaptation gating (matches production tarang_nlms.c):
    The production code only adapts when motion_detected=true. This prevents
    the filter from learning the ECG itself during rest periods (which would
    destroy QRS morphology). Pass `adapt_mask` (bool array) to mimic this.
"""
import numpy as np

def nlms_filter(primary: np.ndarray,
                reference: np.ndarray,
                num_taps: int = 32,
                mu: float = 0.01,
                eps: float = 1.0,
                adapt_mask: np.ndarray = None,
                verbose: bool = True) -> dict:
    """
    Run NLMS over primary using reference as the artifact model.

    primary   : shape (N,)  — noisy ECG (centered, e.g. after DC removal)
    reference : shape (N,) or (M,) — motion signal. If shorter than N,
                 will be linearly resampled to N inside this function.
    adapt_mask: shape (N,) bool — True where adaptation is allowed.
                 Default: always True. Production uses motion-gated adaptation.
    """
    primary = np.asarray(primary, dtype=np.float64)
    reference = np.asarray(reference, dtype=np.float64)

    # Resample reference to match primary length (linear interp)
    if len(reference) != len(primary):
        if verbose:
            print(f'[NLMS] Resampling reference {len(reference)} -> {len(primary)}')
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

    # Filter state
    w = np.zeros(L, dtype=np.float64)              # weights
    delay = np.zeros(L, dtype=np.float64)          # circular delay line
    d_idx = 0

    y_hat   = np.zeros(N, dtype=np.float64)
    cleaned = np.zeros(N, dtype=np.float64)
    power_e_ema = np.zeros(N, dtype=np.float64)
    power_x_ema = np.zeros(N, dtype=np.float64)

    alpha = 1.0 / 256.0   # EMA smoothing (matches production)

    for n in range(N):
        # Push new reference into delay line
        delay[d_idx] = reference[n]

        # Build x vector (most-recent first)
        x = np.empty(L, dtype=np.float64)
        for k in range(L):
            x[k] = delay[(d_idx - k) % L]

        # Estimate artifact
        y = float(np.dot(w, x))
        y_hat[n] = y

        # Error = cleaned ECG
        e = primary[n] - y
        cleaned[n] = e

        # Power EMAs
        pe = e * e
        px = float(np.dot(x, x))
        if n == 0:
            power_e_ema[n] = pe
            power_x_ema[n] = px
        else:
            power_e_ema[n] = power_e_ema[n-1] + alpha * (pe - power_e_ema[n-1])
            power_x_ema[n] = power_x_ema[n-1] + alpha * (px - power_x_ema[n-1])

        # Weight update (NLMS) — only when adaptation is allowed
        if adapt_mask[n]:
            denom = px + eps
            if denom > 0:
                w += (mu * e / denom) * x

        # Advance delay line
        d_idx = (d_idx + 1) % L

    return {
        'cleaned': cleaned,
        'y_hat': y_hat,
        'weights': w,
        'power_e_ema': power_e_ema,
        'power_x_ema': power_x_ema,
    }


def motion_gate(imu_mag: np.ndarray,
                baseline: float = 16384.0,
                threshold: float = 300.0) -> np.ndarray:
    """
    Compute a boolean adapt_mask: True where |IMU magnitude - 1g baseline|
    exceeds threshold (in raw LSB). Matches production motion_detected logic.
    """
    dev = np.abs(imu_mag - baseline)
    return dev > threshold
