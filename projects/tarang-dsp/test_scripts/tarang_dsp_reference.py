"""
Tarang v16 — DSP Reference (block-level only, Phase 1)

Single-source-of-truth for streaming DSP. Each stateful block is implemented
as ONE single-sample step function with explicit (state_in, state_out).
process_frame/process_record (Phase 2) will be loops over these — no
vectorized/batch implementation exists anywhere.

NO filtfilt. NO whole-record mean subtraction. NO TensorFlow dependency.

Phase 1 scope: individual block step functions + their state dataclasses.
Phase 2 will assemble StreamingTarangDSP.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.signal import butter, sosfilt_zi


# ============================================================================
# Block 1: SOS morphology bandpass — single-sample step
# ============================================================================

@dataclass
class SOSState:
    """State for a cascade of biquad sections.

    Fields:
        sos:  [n_sections, 6] — each row is [b0, b1, b2, a0, a1, a2]
              (a0 is assumed 1.0; included for completeness)
        zi:   [n_sections, 2] — delay state per section [z1, z2]
    """
    sos: np.ndarray   # [K, 6]
    zi: np.ndarray    # [K, 2]

    def copy(self) -> "SOSState":
        return SOSState(self.sos.copy(), self.zi.copy())


def sos_design_bandpass(fs: float = 250.0, lo: float = 0.5, hi: float = 40.0,
                        order: int = 4) -> np.ndarray:
    """Design a causal Butterworth bandpass as SOS. Returns [K, 6]."""
    nyq = fs / 2.0
    sos = butter(order, [lo / nyq, hi / nyq], btype='band', output='sos')
    return np.asarray(sos, dtype=np.float64)


def sos_step(x: float, state: SOSState) -> tuple[float, SOSState]:
    """One sample in, one sample out, explicit state in and out.

    Implements the standard transposed-direct-form-II biquad cascade.

    For each section k with coefficients [b0, b1, b2, a1, a2] (a0=1):
        y = b0 * x + z1
        z1' = b1 * x + z2 - a1 * y
        z2' = b2 * x      - a2 * y
        x_next = y

    This is the ONLY implementation of the filter — no vectorized sibling.
    """
    y = float(x)
    new_zi = state.zi.copy()
    for k in range(len(state.sos)):
        b0, b1, b2, a0, a1, a2 = state.sos[k]
        z1, z2 = new_zi[k]
        y_k = b0 * y + z1
        new_zi[k, 0] = b1 * y + z2 - a1 * y_k
        new_zi[k, 1] = b2 * y - a2 * y_k
        y = y_k
    return float(y), SOSState(state.sos, new_zi)


def sos_zero_state(sos: np.ndarray) -> SOSState:
    """Initial state with all delays at zero."""
    return SOSState(sos=np.asarray(sos, dtype=np.float64),
                    zi=np.zeros((len(sos), 2), dtype=np.float64))


# ============================================================================
# Block 2: Optional 50 Hz notch — single-sample step
# ============================================================================

@dataclass
class NotchState:
    """State for a second-order IIR notch.

    H(z) = (1 - 2*cos(w0)*z^-1 + z^-2) / (1 - 2*r*cos(w0)*z^-1 + r^2*z^-2)

    Fields:
        b:  [b0, b1, b2] = [1, -2*cos(w0), 1]
        a:  [a0, a1, a2] = [1, -2*r*cos(w0), r^2]
        z:  [z1, z2]  delay state (transposed form II)
    """
    b: np.ndarray   # [3]
    a: np.ndarray   # [3]
    z: np.ndarray   # [2]

    def copy(self) -> "NotchState":
        return NotchState(self.b.copy(), self.a.copy(), self.z.copy())


def notch_design(fs: float = 250.0, f0: float = 50.0, r: float = 0.95) -> tuple[np.ndarray, np.ndarray]:
    """Design a second-order notch filter. Returns (b, a) as [3] arrays."""
    w0 = 2.0 * math.pi * f0 / fs
    cos_w0 = math.cos(w0)
    b = np.array([1.0, -2.0 * cos_w0, 1.0], dtype=np.float64)
    a = np.array([1.0, -2.0 * r * cos_w0, r * r], dtype=np.float64)
    return b, a


def notch_step(x: float, state: NotchState) -> tuple[float, NotchState]:
    """One sample in, one sample out (transposed direct form II)."""
    b0, b1, b2 = state.b
    a1, a2 = state.a[1], state.a[2]
    z1, z2 = state.z
    y = b0 * x + z1
    new_z1 = b1 * x + z2 - a1 * y
    new_z2 = b2 * x      - a2 * y
    new_z = np.array([new_z1, new_z2], dtype=np.float64)
    return float(y), NotchState(state.b, state.a, new_z)


def notch_zero_state(b: np.ndarray, a: np.ndarray) -> NotchState:
    return NotchState(b=np.asarray(b, dtype=np.float64),
                      a=np.asarray(a, dtype=np.float64),
                      z=np.zeros(2, dtype=np.float64))


# ============================================================================
# Block 3: Causal rolling z-score normalization — single-sample step
# ============================================================================

@dataclass
class RollingNormState:
    """Causal rolling z-score using a ring buffer + running sums.

    For window W (samples), maintains:
        ring[W]   : circular buffer of past samples
        S1        : running sum of last min(C, W) samples
        S2        : running sum of squares of last min(C, W) samples
        C         : valid count (0..W)
        idx       : write index into ring buffer
        epsilon   : floor for std (prevents divide-by-zero)

    Equations (spec 5.8):
        mu = S1 / C
        var = max(S2 / C - mu^2, 0)
        z = (x - mu) / max(sqrt(var), epsilon)

    Population std convention (ddof=0). Same convention must be used in
    firmware.
    """
    window: int
    ring: np.ndarray
    S1: float
    S2: float
    C: int
    idx: int
    epsilon: float

    def copy(self) -> "RollingNormState":
        return RollingNormState(self.window, self.ring.copy(), self.S1, self.S2,
                                self.C, self.idx, self.epsilon)


def rolling_norm_init(window: int, epsilon: float = 1e-8) -> RollingNormState:
    return RollingNormState(
        window=int(window),
        ring=np.zeros(int(window), dtype=np.float64),
        S1=0.0, S2=0.0, C=0, idx=0, epsilon=float(epsilon),
    )


def rolling_norm_step(x: float, state: RollingNormState) -> tuple[float, RollingNormState]:
    """One sample in, one z-scored sample out, explicit state in and out."""
    W = state.window
    x = float(x)

    # If buffer is full, subtract the oldest sample from running sums
    if state.C >= W:
        old = state.ring[state.idx]
        S1_new = state.S1 - old + x
        S2_new = state.S2 - old * old + x * x
        C_new = state.C  # stays at W
    else:
        S1_new = state.S1 + x
        S2_new = state.S2 + x * x
        C_new = state.C + 1

    # Write into ring buffer at current index
    new_ring = state.ring.copy()
    new_ring[state.idx] = x
    new_idx = (state.idx + 1) % W

    # Compute mean and variance
    mu = S1_new / C_new
    var = S2_new / C_new - mu * mu
    if var < 0.0:
        var = 0.0  # numerical guard against tiny negative from FP roundoff
    std = math.sqrt(var)
    if std < state.epsilon:
        std = state.epsilon

    z = (x - mu) / std
    return float(z), RollingNormState(W, new_ring, S1_new, S2_new, C_new, new_idx, state.epsilon)


# ============================================================================
# Block 4: Pan-Tompkins QRS-emphasis bandpass — single-sample step
# ============================================================================

@dataclass
class QRSBandpassState:
    """QRS-emphasis bandpass (~5-15 Hz) implemented as cascade of:
       - high-pass (low cutoff ~5 Hz)
       - low-pass  (high cutoff ~15 Hz)

    Both implemented as SOS cascades.
    """
    sos_hp: np.ndarray   # [K_hp, 6]
    sos_lp: np.ndarray   # [K_lp, 6]
    zi_hp: np.ndarray    # [K_hp, 2]
    zi_lp: np.ndarray    # [K_lp, 2]

    def copy(self) -> "QRSBandpassState":
        return QRSBandpassState(self.sos_hp.copy(), self.sos_lp.copy(),
                                self.zi_hp.copy(), self.zi_lp.copy())


def qrs_bandpass_design(fs: float = 250.0, lo: float = 5.0, hi: float = 15.0,
                        order: int = 2) -> tuple[np.ndarray, np.ndarray]:
    """Design QRS-emphasis bandpass as separate HP and LP SOS cascades."""
    nyq = fs / 2.0
    sos_hp = butter(order, lo / nyq, btype='high', output='sos')
    sos_lp = butter(order, hi / nyq, btype='low', output='sos')
    return np.asarray(sos_hp, dtype=np.float64), np.asarray(sos_lp, dtype=np.float64)


def qrs_bandpass_zero_state(sos_hp: np.ndarray, sos_lp: np.ndarray) -> QRSBandpassState:
    return QRSBandpassState(
        sos_hp=sos_hp, sos_lp=sos_lp,
        zi_hp=np.zeros((len(sos_hp), 2), dtype=np.float64),
        zi_lp=np.zeros((len(sos_lp), 2), dtype=np.float64),
    )


def qrs_bandpass_step(x: float, state: QRSBandpassState) -> tuple[float, QRSBandpassState]:
    """High-pass then low-pass, each as transposed direct form II SOS cascade."""
    y = float(x)
    new_zi_hp = state.zi_hp.copy()
    for k in range(len(state.sos_hp)):
        b0, b1, b2, a0, a1, a2 = state.sos_hp[k]
        z1, z2 = new_zi_hp[k]
        y_k = b0 * y + z1
        new_zi_hp[k, 0] = b1 * y + z2 - a1 * y_k
        new_zi_hp[k, 1] = b2 * y - a2 * y_k
        y = y_k

    new_zi_lp = state.zi_lp.copy()
    for k in range(len(state.sos_lp)):
        b0, b1, b2, a0, a1, a2 = state.sos_lp[k]
        z1, z2 = new_zi_lp[k]
        y_k = b0 * y + z1
        new_zi_lp[k, 0] = b1 * y + z2 - a1 * y_k
        new_zi_lp[k, 1] = b2 * y - a2 * y_k
        y = y_k

    return float(y), QRSBandpassState(state.sos_hp, state.sos_lp, new_zi_hp, new_zi_lp)


# ============================================================================
# Block 5: Pan-Tompkins derivative — single-sample step
# ============================================================================

@dataclass
class DerivativeState:
    """5-tap causal derivative per spec 5.9 Stage B.

    x_d[n] = (1/8T) * (x[n] + 2*x[n-1] - 2*x[n-3] - x[n-4])

    Delay line: x[n-1], x[n-2], x[n-3], x[n-4]
    """
    T: float
    delay: np.ndarray   # [4] — x[n-1], x[n-2], x[n-3], x[n-4]

    def copy(self) -> "DerivativeState":
        return DerivativeState(self.T, self.delay.copy())


def derivative_init(fs: float = 250.0) -> DerivativeState:
    return DerivativeState(T=1.0 / fs, delay=np.zeros(4, dtype=np.float64))


def derivative_step(x: float, state: DerivativeState) -> tuple[float, DerivativeState]:
    """Causal 5-tap derivative."""
    x1, x2, x3, x4 = state.delay
    y = (1.0 / (8.0 * state.T)) * (x + 2.0 * x1 - 2.0 * x3 - x4)
    new_delay = np.array([x, x1, x2, x3], dtype=np.float64)
    return float(y), DerivativeState(state.T, new_delay)


# ============================================================================
# Block 6: Pan-Tompkins squaring — single-sample step
# ============================================================================

@dataclass
class SquaringState:
    """Stateless squaring (kept as a struct for uniform API)."""
    pass

    def copy(self) -> "SquaringState":
        return SquaringState()


def squaring_init() -> SquaringState:
    return SquaringState()


def squaring_step(x: float, state: SquaringState) -> tuple[float, SquaringState]:
    """x_s[n] = x_d[n]^2"""
    return float(x * x), state


# ============================================================================
# Block 7: Moving-window integration — single-sample step
# ============================================================================

@dataclass
class MWIState:
    """Moving-window integration over N samples (spec 5.9 Stage D).

    x_MWI[n] = (1/N) * sum_{k=0..N-1} x_s[n-k]

    Implemented with a ring buffer and a running sum for O(1) per sample.
    """
    N: int
    ring: np.ndarray
    S: float           # running sum of last min(C, N) samples
    C: int             # valid count
    idx: int

    def copy(self) -> "MWIState":
        return MWIState(self.N, self.ring.copy(), self.S, self.C, self.idx)


def mwi_init(N: int) -> MWIState:
    return MWIState(N=int(N), ring=np.zeros(int(N), dtype=np.float64),
                    S=0.0, C=0, idx=0)


def mwi_step(x: float, state: MWIState) -> tuple[float, MWIState]:
    N = state.N
    x = float(x)
    if state.C >= N:
        old = state.ring[state.idx]
        S_new = state.S - old + x
        C_new = state.C
    else:
        S_new = state.S + x
        C_new = state.C + 1
    new_ring = state.ring.copy()
    new_ring[state.idx] = x
    new_idx = (state.idx + 1) % N
    y = S_new / C_new
    return float(y), MWIState(N, new_ring, S_new, C_new, new_idx)


# ============================================================================
# Block 8: Adaptive threshold + refractory + search-back
# ============================================================================

@dataclass
class AdaptiveThresholdState:
    """Pan-Tompkins adaptive thresholding (spec 5.9 Stage E-H).

    PHASE 2 REFACTOR: peak detection now uses LOCAL-MAX detection (downward
    zero-crossing of MWI derivative), not rising-edge threshold crossing.

    Rationale (Phase 1 follow-up v3, standing note #6):
      MWI output is always-positive and monotonically-decaying after the QRS.
      For such signals, the local maximum IS the QRS-driven peak (argmax in
      the local region). The previous implementation fired as soon as MWI
      rose above TH1, which would (a) report the peak too early (on the
      rising edge, not at the actual max), invalidating the 29-sample
      pre-correction derived in Phase 1, and (b) update SPKI/NPKI on every
      sample above threshold rather than on actual peak values.

      The fix: detect a peak when current MWI < previous MWI (signal starts
      decreasing). The previous sample is the local max. Apply threshold
      checks to that peak value, not the current sample.

    Maintains:
        SPKI:  running estimate of signal peak (QRS)
        NPKI:  running estimate of noise peak
        TH1:   primary threshold = NPKI + 0.25*(SPKI - NPKI)
        TH2:   search-back threshold = 0.5 * TH1

    Plus refractory + last-R tracking for seach-back.

    Fields:
        SPKI, NPKI, TH1, TH2
        refractory_samples_remaining: counts down from N_refractory
        last_R_sample_idx: absolute sample index of last accepted R-peak
        last_R_slope: slope at last accepted QRS (for T-wave rejection)
        current_sample_idx: absolute counter
        rr_history: list of recent RR intervals (samples)
        recent_rr_mean: mean of recent RR intervals (samples)
        candidate_buffer: list of (idx, value) candidates since last accepted peak
                          (for search-back)
        n_refractory: refractory period in samples
        gamma: search-back multiplier (e.g. 1.66)
        twave_alpha: T-wave rejection slope ratio threshold (e.g. 0.5)
        prev_mwi: previous MWI sample value (for local-max detection)
        prev_mwi_idx: absolute sample index of prev_mwi
    """
    SPKI: float
    NPKI: float
    TH1: float
    TH2: float
    refractory_samples_remaining: int
    last_R_sample_idx: int
    last_R_slope: float
    current_sample_idx: int
    rr_history: list
    recent_rr_mean: float
    candidate_buffer: list   # [(idx, value), ...]
    n_refractory: int
    gamma: float
    twave_alpha: float
    prev_mwi: float
    prev_mwi_idx: int
    default_rr_samples: int = 0  # fallback RR (samples) used to gate search-back
                                  # before any real beat has ever been found
    spki_max_step_ratio: float = 3.0  # clamp: a single peak can move SPKI by
                                       # at most this multiple of current SPKI

    def copy(self) -> "AdaptiveThresholdState":
        return AdaptiveThresholdState(
            self.SPKI, self.NPKI, self.TH1, self.TH2,
            self.refractory_samples_remaining, self.last_R_sample_idx,
            self.last_R_slope, self.current_sample_idx,
            list(self.rr_history), self.recent_rr_mean,
            list(self.candidate_buffer),
            self.n_refractory, self.gamma, self.twave_alpha,
            self.prev_mwi, self.prev_mwi_idx,
            self.default_rr_samples, self.spki_max_step_ratio,
        )


def adaptive_threshold_init(n_refractory: int = 50, gamma: float = 1.66,
                            twave_alpha: float = 0.5,
                            initial_spki: float = 0.0, initial_npki: float = 0.0,
                            default_rr_samples: int = 0,
                            spki_max_step_ratio: float = 3.0) -> AdaptiveThresholdState:
    return AdaptiveThresholdState(
        SPKI=initial_spki, NPKI=initial_npki,
        TH1=initial_npki + 0.25 * (initial_spki - initial_npki),
        TH2=0.5 * (initial_npki + 0.25 * (initial_spki - initial_npki)),
        refractory_samples_remaining=0,
        last_R_sample_idx=-1,
        last_R_slope=0.0,
        current_sample_idx=0,
        rr_history=[],
        recent_rr_mean=0.0,
        candidate_buffer=[],
        n_refractory=int(n_refractory),
        gamma=float(gamma),
        twave_alpha=float(twave_alpha),
        prev_mwi=0.0,
        prev_mwi_idx=-1,
        default_rr_samples=int(default_rr_samples),
        spki_max_step_ratio=float(spki_max_step_ratio),
    )


def adaptive_threshold_step(mwi_value: float, slope_estimate: float,
                            state: AdaptiveThresholdState) -> tuple[list, AdaptiveThresholdState]:
    """Process one MWI sample. Returns (list_of_accepted_peak_indices, new_state).

    PEAK DETECTION (Phase 2 refactor — local-max via downward zero-crossing):
      - Track previous MWI value and its absolute sample index
      - When current MWI < previous MWI (signal decreasing), the previous
        sample was a local maximum
      - Apply threshold logic to that PEAK VALUE, not the current sample

    This is the argmax-style logic for positive monotonic signals required
    by Phase 1 follow-up v3 standing note #6.

    A peak is "accepted" when:
      - peak value (previous MWI) > TH1
      - refractory period has elapsed
      - T-wave rejection: slope_estimate >= twave_alpha * last_R_slope
                          (when last_R_slope > 0 and timing is T-wave-like)

    Search-back triggers when:
      - current_sample_idx - last_R_sample_idx > gamma * recent_rr_mean
      - there is a candidate in candidate_buffer with value > TH2
      - the highest such candidate is accepted as a (retroactive) R-peak

    Returns list of accepted peak indices. Each index is the ABSOLUTE sample
    index of the MWI peak (previous sample's index, since detection happens
    one sample after the peak).
    """
    accepted: list[int] = []
    new_state = state.copy()

    idx = new_state.current_sample_idx
    val = float(mwi_value)
    prev_val = new_state.prev_mwi
    prev_idx = new_state.prev_mwi_idx

    # Update refractory counter
    if new_state.refractory_samples_remaining > 0:
        new_state.refractory_samples_remaining -= 1

    # === PEAK DETECTION: local max at prev_idx when val < prev_val ===
    # Phase 2 fix: require minimum decrease (hysteresis) to avoid firing on
    # noise fluctuations at the plateau. Without this, sample-to-sample noise
    # on the MWI peak plateau causes multiple spurious peak detections per QRS.
    # Hysteresis: signal must decrease by at least 1% of prev_val (or absolute
    # floor of 1e-6 for near-zero signals) to count as "starting to decay".
    hysteresis = max(0.01 * abs(prev_val), 1e-6)
    peak_detected = (prev_idx >= 0) and (val < prev_val - hysteresis)

    if peak_detected:
        peak_val = prev_val
        peak_idx = prev_idx

        # Buffer candidate if above TH2 (for potential search-back later)
        # Phase 2 fix: skip candidates within refractory window of last accepted peak.
        # Without this, the sample immediately after an accepted peak (which is still
        # part of the same QRS complex's MWI decay) gets buffered and later
        # re-accepted by search-back as a duplicate beat.
        if peak_val > new_state.TH2:
            within_refractory_of_last_R = (
                new_state.last_R_sample_idx >= 0 and
                (peak_idx - new_state.last_R_sample_idx) < new_state.n_refractory
            )
            if not within_refractory_of_last_R:
                new_state.candidate_buffer.append((peak_idx, peak_val))

        # Trim candidate buffer to recent window
        if new_state.recent_rr_mean > 0:
            max_age = int(2.0 * new_state.gamma * new_state.recent_rr_mean)
            new_state.candidate_buffer = [(i, v) for (i, v) in new_state.candidate_buffer
                                           if idx - i <= max_age]

        # Search-back check: too long since last R.
        # FIX (root-cause of catastrophic wholesale failures): the original
        # gate required last_R_sample_idx >= 0 AND recent_rr_mean > 0, both
        # of which are only set AFTER a beat has been accepted through the
        # primary TH1 path. If warm-up sets TH1 too high for a record's true
        # QRS amplitude, no primary detection ever fires, so this gate never
        # opens and the detector is stuck at warm-up values for the entire
        # record. Fix: allow search-back to bootstrap the very first beat by
        # measuring elapsed time from record start (idx=0) when no beat has
        # ever been found yet, and by falling back to a default assumed RR
        # (e.g. 1s @ fs ~ 60bpm) when recent_rr_mean hasn't been established.
        reference_idx = new_state.last_R_sample_idx if new_state.last_R_sample_idx >= 0 else 0
        effective_rr_mean = (new_state.recent_rr_mean if new_state.recent_rr_mean > 0
                             else max(new_state.default_rr_samples, 1))
        if ((idx - reference_idx) > new_state.gamma * effective_rr_mean and
            new_state.refractory_samples_remaining == 0 and
            len(new_state.candidate_buffer) > 0):
            best = max(new_state.candidate_buffer, key=lambda t: t[1])
            if best[1] > new_state.TH2:
                retro_idx = best[0]
                accepted.append(retro_idx)
                # FIX: clamp outlier contribution to SPKI (see spki_max_step_ratio
                # note below) so a single artifact can't permanently blow up
                # the threshold and strand the detector for the rest of the record.
                spki_cap = (new_state.spki_max_step_ratio * new_state.SPKI
                           if new_state.SPKI > 0 else best[1])
                capped_val = min(best[1], spki_cap) if spki_cap > 0 else best[1]
                new_state.SPKI = 0.125 * capped_val + 0.875 * new_state.SPKI
                new_state.TH1 = new_state.NPKI + 0.25 * (new_state.SPKI - new_state.NPKI)
                new_state.TH2 = 0.5 * new_state.TH1
                new_state.refractory_samples_remaining = new_state.n_refractory
                if new_state.last_R_sample_idx >= 0:
                    rr = retro_idx - new_state.last_R_sample_idx
                    if rr > 0:
                        new_state.rr_history.append(rr)
                        if len(new_state.rr_history) > 8:
                            new_state.rr_history = new_state.rr_history[-8:]
                        new_state.recent_rr_mean = float(np.mean(new_state.rr_history))
                new_state.last_R_sample_idx = retro_idx
                new_state.last_R_slope = slope_estimate
                new_state.candidate_buffer = []

        # Primary threshold check on the PEAK value (not current sample)
        if (peak_val > new_state.TH1 and
            new_state.refractory_samples_remaining == 0):
            # T-wave rejection
            twave_ok = True
            if new_state.last_R_slope > 0 and slope_estimate < new_state.twave_alpha * new_state.last_R_slope:
                if new_state.last_R_sample_idx >= 0:
                    time_since = peak_idx - new_state.last_R_sample_idx
                    if 50 <= time_since <= 100:
                        twave_ok = False

            if twave_ok:
                accepted.append(peak_idx)
                # FIX: same outlier clamp as search-back path — prevents a
                # single motion/saturation artifact from jumping SPKI (and
                # therefore TH1/TH2) far above all subsequent real QRS peaks,
                # which otherwise permanently strands the detector (this is
                # the mechanism behind the "significant drift" records where
                # recall collapses mid-record and never recovers).
                spki_cap = (new_state.spki_max_step_ratio * new_state.SPKI
                           if new_state.SPKI > 0 else peak_val)
                capped_val = min(peak_val, spki_cap) if spki_cap > 0 else peak_val
                new_state.SPKI = 0.125 * capped_val + 0.875 * new_state.SPKI
                new_state.TH1 = new_state.NPKI + 0.25 * (new_state.SPKI - new_state.NPKI)
                new_state.TH2 = 0.5 * new_state.TH1
                new_state.refractory_samples_remaining = new_state.n_refractory

                if new_state.last_R_sample_idx >= 0:
                    rr = peak_idx - new_state.last_R_sample_idx
                    if rr > 0:
                        new_state.rr_history.append(rr)
                        if len(new_state.rr_history) > 8:
                            new_state.rr_history = new_state.rr_history[-8:]
                        new_state.recent_rr_mean = float(np.mean(new_state.rr_history))

                new_state.last_R_sample_idx = peak_idx
                new_state.last_R_slope = slope_estimate
                new_state.candidate_buffer = []
            else:
                # T-wave: update noise estimate using peak value
                new_state.NPKI = 0.125 * peak_val + 0.875 * new_state.NPKI
                new_state.TH1 = new_state.NPKI + 0.25 * (new_state.SPKI - new_state.NPKI)
                new_state.TH2 = 0.5 * new_state.TH1
        elif peak_val > new_state.TH2 and peak_val <= new_state.TH1:
            # Noise peak (peak was between TH2 and TH1)
            new_state.NPKI = 0.125 * peak_val + 0.875 * new_state.NPKI
            new_state.TH1 = new_state.NPKI + 0.25 * (new_state.SPKI - new_state.NPKI)
            new_state.TH2 = 0.5 * new_state.TH1

    # Update prev_mwi for next call (this is the key state update)
    new_state.prev_mwi = val
    new_state.prev_mwi_idx = idx
    new_state.current_sample_idx = idx + 1
    return accepted, new_state


# ============================================================================
# Quick self-check: importable
# ============================================================================

if __name__ == "__main__":
    print("tarang_dsp_reference.py loaded.")
    print(f"  Blocks defined: SOS, Notch, RollingNorm, QRSBandpass, Derivative, Squaring, MWI, AdaptiveThreshold")
    print(f"  All step functions take (sample, state) and return (sample, new_state).")
    print(f"  No vectorized siblings exist.")


# ============================================================================
# PHASE 2: StreamingTarangDSP — assembled pipeline
# ============================================================================

from collections import deque
from dataclasses import dataclass, field
from typing import Optional


# Constants from spec Section 5.14 + Phase 1 follow-up v3
TARGET_FS = 250
WINDOW_LEN = 130
PRE_R = 65
POST_R = 65
# Phase 1 follow-up v3: cumulative group delay of detection branch Stages A-D
# at 10 Hz = 28.38 samples. Pre-correction = ceil(28.38) = 29. Zero safety margin.
DETECTION_DELAY_CORRECTION = 29
# Spec 5.10: recenter search radius = ±15 samples (60 ms)
RECENTER_WINDOW = 15
# Morphology ring buffer must hold enough history to extract beats at worst-case
# timing: refined_peak can be up to (mwi_peak - 44), and beat window extends
# (refined_peak - 65) to (refined_peak + 65). Plus we wait POST_R=65 samples
# after refined_peak before extracting. Total lookback: 44 + 65 + 65 = 174.
# Use 256 for safety.
MORPH_BUFFER_SIZE = 256


@dataclass(frozen=True)
class DSPConfig:
    """Frozen configuration for StreamingTarangDSP. Per spec Section 21."""
    target_fs: int = TARGET_FS
    morphology_low_hz: float = 0.5
    morphology_high_hz: float = 40.0
    morphology_order: int = 4
    notch_enabled: bool = False
    notch_hz: float = 50.0
    notch_r: float = 0.95
    normalization_window_sec: float = 30.0
    normalization_epsilon: float = 1e-8
    detector_low_hz: float = 5.0
    detector_high_hz: float = 15.0
    detector_order: int = 2
    detector_mwi_sec: float = 0.150
    refractory_sec: float = 0.200
    recenter_ms: float = 60.0
    pre_r: int = PRE_R
    post_r: int = POST_R
    nlms_mode: str = "bypass"
    nlms_order: int = 16
    nlms_mu: float = 0.01
    nlms_delta: float = 1e-6
    searchback_gamma: float = 1.66
    twave_alpha: float = 0.5


@dataclass
class BeatPacket:
    """A single detected beat. Per spec Section 21."""
    waveform: np.ndarray
    rr_raw: np.ndarray
    r_peak_index: int
    r_peak_timestamp_sec: float
    detector_candidate_index: int
    quality_state: str
    quality_flags: tuple
    detector_confidence: float
    motion_score: Optional[float]
    nlms_active: bool


class StreamingTarangDSP:
    """Assembled streaming DSP pipeline per spec Section 3.

    process_sample is the ONLY entry point that does DSP.
    process_frame and process_record are loops over process_sample —
    NO vectorized sibling implementation exists (Phase 2 guide rule).
    """

    def __init__(self, config: DSPConfig):
        self.config = config
        self.reset()

    def reset(self) -> None:
        c = self.config
        # Block 1: morphology bandpass
        self._sos_morph = sos_design_bandpass(
            fs=c.target_fs, lo=c.morphology_low_hz, hi=c.morphology_high_hz,
            order=c.morphology_order)
        self._sos_state = sos_zero_state(self._sos_morph)
        # Block 2: optional notch
        if c.notch_enabled:
            b, a = notch_design(fs=c.target_fs, f0=c.notch_hz, r=c.notch_r)
            self._notch_b, self._notch_a, self._notch_state = b, a, notch_zero_state(b, a)
        else:
            self._notch_b = self._notch_a = self._notch_state = None
        # Block 3: rolling normalizer
        self._norm_state = rolling_norm_init(
            window=int(c.normalization_window_sec * c.target_fs),
            epsilon=c.normalization_epsilon)
        # Block 4: QRS bandpass
        sos_hp, sos_lp = qrs_bandpass_design(
            fs=c.target_fs, lo=c.detector_low_hz, hi=c.detector_high_hz,
            order=c.detector_order)
        self._qrs_bp_state = qrs_bandpass_zero_state(sos_hp, sos_lp)
        # Block 5-7: derivative, squaring, MWI
        self._deriv_state = derivative_init(fs=c.target_fs)
        self._sq_state = squaring_init()
        self._mwi_N = max(1, int(round(c.detector_mwi_sec * c.target_fs)))
        self._mwi_state = mwi_init(N=self._mwi_N)
        # Block 8: adaptive threshold
        # default_rr_samples: fallback RR interval (1s @ fs, i.e. ~60bpm)
        # used only to gate the search-back timeout before any real beat has
        # been found — see fix note in adaptive_threshold_step. This value
        # is never used for actual RR tracking, only to let search-back
        # bootstrap the first beat instead of being permanently gated off.
        self._thresh_state = adaptive_threshold_init(
            n_refractory=max(1, int(round(c.refractory_sec * c.target_fs))),
            gamma=c.searchback_gamma, twave_alpha=c.twave_alpha,
            default_rr_samples=max(1, int(round(1.0 * c.target_fs))))
        # Warm-up flag: process_record will call warm_up() on first call
        self._warmed_up = False
        self._warmup_samples = max(100, int(2.0 * c.target_fs))  # 2 seconds
        # NLMS (bypass mode — implemented but inactive)
        self._nlms_active = False
        self._nlms_weights = np.zeros(c.nlms_order, dtype=np.float64) if c.nlms_mode != "bypass" else None
        self._nlms_delay = np.zeros(c.nlms_order, dtype=np.float64) if c.nlms_mode != "bypass" else None
        # Ring buffers (deque with maxlen)
        self._morph_buffer = deque(maxlen=MORPH_BUFFER_SIZE)
        self._filtered_buffer = deque(maxlen=MORPH_BUFFER_SIZE)
        self._norm_buffer = deque(maxlen=MORPH_BUFFER_SIZE)
        self._mwi_buffer = deque(maxlen=MORPH_BUFFER_SIZE)
        self._deriv_buffer = deque(maxlen=MORPH_BUFFER_SIZE)
        self._pending = []
        self._r_peak_history = []
        self._sample_idx = 0
        self._emitted_beats = []

    def process_sample(self, x: float, imu: Optional[dict] = None) -> list:
        """Process one ECG sample. Returns list of BeatPackets emitted this sample."""
        c = self.config
        # 1. Sanitize
        if not math.isfinite(x):
            x = 0.0
        x = float(x)
        # 2. (Resampling is the caller's responsibility — streaming assumes 250 Hz input)
        # 3. Morphology bandpass
        y_filt, self._sos_state = sos_step(x, self._sos_state)
        # 4. Optional notch
        if c.notch_enabled and self._notch_state is not None:
            y_filt, self._notch_state = notch_step(y_filt, self._notch_state)
        # 5. NLMS bypass — pass through
        y_post_nlms = y_filt
        self._nlms_active = False
        # 6. Morphology branch: rolling norm
        y_norm, self._norm_state = rolling_norm_step(y_post_nlms, self._norm_state)
        # 7. Push to buffers
        self._morph_buffer.append(y_norm)
        self._filtered_buffer.append(y_filt)
        self._norm_buffer.append(y_norm)
        # 8. Detection branch: QRS bandpass
        y_qrs, self._qrs_bp_state = qrs_bandpass_step(y_post_nlms, self._qrs_bp_state)
        # 9. Derivative
        y_deriv, self._deriv_state = derivative_step(y_qrs, self._deriv_state)
        self._deriv_buffer.append(y_deriv)
        # 10. Squaring
        y_sq, self._sq_state = squaring_step(y_deriv, self._sq_state)
        # 11. MWI
        y_mwi, self._mwi_state = mwi_step(y_sq, self._mwi_state)
        self._mwi_buffer.append(y_mwi)
        # 12. Adaptive threshold — local-max detection (Phase 2 refactor)
        slope_est = abs(y_deriv)
        peaks, self._thresh_state = adaptive_threshold_step(y_mwi, slope_est, self._thresh_state)
        # 13. Add accepted peaks to pending list
        for p_idx in peaks:
            mwi_val = self._get_buffer_value(self._mwi_buffer, p_idx)
            if mwi_val is not None:
                self._pending.append({
                    'mwi_peak_idx': p_idx,
                    'mwi_peak_val': mwi_val,
                    'spki_at_detection': self._thresh_state.SPKI,
                })
        # 14. Check pending for beat extraction
        emitted = []
        POST_R_WAIT = POST_R + RECENTER_WINDOW  # 65 + 14 = 79
        still_pending = []
        for pending in self._pending:
            if self._sample_idx >= pending['mwi_peak_idx'] + POST_R_WAIT:
                packet = self._extract_beat(pending)
                if packet is not None:
                    emitted.append(packet)
                    self._emitted_beats.append(packet)
            else:
                still_pending.append(pending)
        self._pending = still_pending
        self._sample_idx += 1
        return emitted

    def process_frame(self, samples: np.ndarray) -> list:
        """Loop over process_sample. NO vectorized sibling."""
        packets = []
        for x in samples:
            packets.extend(self.process_sample(float(x)))
        return packets

    def process_record(self, samples: np.ndarray) -> list:
        """Process an entire record. Returns list of BeatPackets emitted."""
        return self.process_frame(samples)

    def warm_up(self, samples: np.ndarray) -> None:
        """Initialize SPKI/NPKI from the first 2 seconds of signal.

        Standard Pan-Tompkins initialization: run the detection branch
        (bandpass -> derivative -> squaring -> MWI) on the first 2s of
        signal WITHOUT triggering detections. Then set:
          SPKI = max(MWI output in warm-up window)
          NPKI = median(MWI output in warm-up window)
          TH1  = NPKI + 0.25 * (SPKI - NPKI)
          TH2  = 0.5 * TH1

        This prevents the chicken-and-egg trap where TH1=0 causes
        noise-triggered false detections during startup.

        After warm_up, the filter state (SOS delays, MWI ring buffer,
        derivative delay line, rolling norm) is RESET to zero so the
        actual process_frame call starts fresh — only SPKI/NPKI/TH1/TH2
        are carried over.
        """
        c = self.config
        n_warmup = min(self._warmup_samples, len(samples))

        # Run detection branch on warm-up window (no peak detection)
        mwi_values = []
        for i in range(n_warmup):
            x = float(samples[i])
            if not math.isfinite(x):
                x = 0.0
            # Morphology bandpass
            y_filt, self._sos_state = sos_step(x, self._sos_state)
            # Notch (if enabled)
            if c.notch_enabled and self._notch_state is not None:
                y_filt, self._notch_state = notch_step(y_filt, self._notch_state)
            # NLMS bypass
            y_post = y_filt
            # Rolling norm
            y_norm, self._norm_state = rolling_norm_step(y_post, self._norm_state)
            # Detection branch
            y_qrs, self._qrs_bp_state = qrs_bandpass_step(y_post, self._qrs_bp_state)
            y_deriv, self._deriv_state = derivative_step(y_qrs, self._deriv_state)
            y_sq, self._sq_state = squaring_step(y_deriv, self._sq_state)
            y_mwi, self._mwi_state = mwi_step(y_sq, self._mwi_state)
            mwi_values.append(y_mwi)

        mwi_arr = np.array(mwi_values) if mwi_values else np.array([0.0])

        # Initialize SPKI/NPKI from warm-up statistics
        # Use 95th percentile for SPKI (robust to startup transient spikes)
        # and median for NPKI (noise floor)
        spki_init = float(np.percentile(mwi_arr, 95))
        npki_init = float(np.median(mwi_arr))
        # Guard against zero SPKI (all-silent warm-up)
        if spki_init < 1e-9:
            spki_init = 1.0  # small but non-zero default

        self._thresh_state.SPKI = spki_init
        self._thresh_state.NPKI = npki_init
        self._thresh_state.TH1 = npki_init + 0.25 * (spki_init - npki_init)
        self._thresh_state.TH2 = 0.5 * self._thresh_state.TH1
        self._thresh_state.refractory_samples_remaining = 0
        self._thresh_state.last_R_sample_idx = -1
        self._thresh_state.current_sample_idx = 0
        self._thresh_state.rr_history = []
        self._thresh_state.recent_rr_mean = 0.0
        self._thresh_state.candidate_buffer = []
        self._thresh_state.prev_mwi = 0.0
        self._thresh_state.prev_mwi_idx = -1

        # DO NOT RESET filter states — they must continue from where warm-up
        # left off so the MWI output stays consistent with the SPKI/NPKI
        # values computed during warm-up. Resetting filters causes a second
        # startup transient where MWI drops to zero and can't reach TH1.
        # Only clear detection-specific state (ring buffers, pending, history):
        self._pending = []
        self._r_peak_history = []
        self._sample_idx = 0

        self._warmed_up = True

    def _get_buffer_value(self, buffer: deque, abs_idx: int) -> Optional[float]:
        if len(buffer) == 0:
            return None
        if len(buffer) < MORPH_BUFFER_SIZE:
            offset = 0
        else:
            offset = self._sample_idx - MORPH_BUFFER_SIZE + 1
        rel_idx = abs_idx - offset
        if 0 <= rel_idx < len(buffer):
            return buffer[rel_idx]
        return None

    def _extract_beat(self, pending: dict) -> Optional[BeatPacket]:
        """Extract beat: pre-correct by 29, recenter ±15 first-sig-local-max, extract 130 samples."""
        from scipy.signal import find_peaks
        mwi_peak_idx = pending['mwi_peak_idx']
        mwi_peak_val = pending['mwi_peak_val']
        # 1. Pre-correction (Phase 1 v3 constant)
        candidate_corrected = mwi_peak_idx - DETECTION_DELAY_CORRECTION
        # 2. Recenter search — first-significant-local-max (signed morphology signal)
        lo = max(0, candidate_corrected - RECENTER_WINDOW)
        hi = min(self._sample_idx + 1, candidate_corrected + RECENTER_WINDOW + 1)
        morph_window = []
        window_indices = []
        for i in range(lo, hi):
            v = self._get_buffer_value(self._norm_buffer, i)
            morph_window.append(abs(v) if v is not None else 0.0)
            window_indices.append(i)
        if len(morph_window) == 0:
            return None
        morph_arr = np.array(morph_window)
        global_max = float(np.max(morph_arr))
        if global_max < 1e-12:
            refined_peak = candidate_corrected
        else:
            threshold = 0.5 * global_max
            peaks_idx, _ = find_peaks(morph_arr, height=threshold, prominence=0.05 * global_max)
            if len(peaks_idx) == 0:
                refined_peak = window_indices[int(np.argmax(morph_arr))]
            else:
                refined_peak = window_indices[int(peaks_idx[0])]
        # 3. Extract 130-sample beat window
        beat_start = refined_peak - PRE_R
        beat_end = refined_peak + POST_R
        if beat_start < 0 or beat_end > self._sample_idx + 1:
            return None
        waveform = np.zeros(WINDOW_LEN, dtype=np.float32)
        for i, abs_i in enumerate(range(beat_start, beat_end)):
            v = self._get_buffer_value(self._norm_buffer, abs_i)
            waveform[i] = float(v) if v is not None else 0.0
        # 4. RR features
        rr_raw = self._compute_rr_features(refined_peak)
        # Update R-peak history
        self._r_peak_history.append(refined_peak)
        if len(self._r_peak_history) > 8:
            self._r_peak_history = self._r_peak_history[-8:]
        # 5. Quality state
        quality_flags = []
        if refined_peak < int(self.config.normalization_window_sec * self.config.target_fs):
            quality_flags.append('STARTUP')
        spki = pending['spki_at_detection']
        if spki > 0 and mwi_peak_val < 0.5 * spki:
            quality_flags.append('LOW_AMP')
        quality_state = 'GOOD' if len(quality_flags) == 0 else 'LOW_CONFIDENCE'
        det_conf = float(mwi_peak_val / spki) if spki > 0 else 0.0
        return BeatPacket(
            waveform=waveform.reshape(-1, 1),
            rr_raw=rr_raw,
            r_peak_index=refined_peak,
            r_peak_timestamp_sec=float(refined_peak) / self.config.target_fs,
            detector_candidate_index=mwi_peak_idx,
            quality_state=quality_state,
            quality_flags=tuple(quality_flags),
            detector_confidence=det_conf,
            motion_score=None,
            nlms_active=False,
        )

    def _compute_rr_features(self, refined_peak: int) -> np.ndarray:
        """4 causal RR features per spec 5.12: [rr_prev_ms, rr_mean_5_ms, rr_std_5_ms, local_hr_bpm]."""
        history = self._r_peak_history  # does NOT include current refined_peak yet
        fs = self.config.target_fs
        if len(history) == 0:
            return np.array([0.0, 0.0, 0.0, 0.0], dtype=np.float32)
        rr_prev_samples = refined_peak - history[-1]
        rr_prev_ms = rr_prev_samples * 1000.0 / fs
        intervals_samples = []
        for i in range(1, len(history)):
            intervals_samples.append(history[i] - history[i-1])
        intervals_samples.append(rr_prev_samples)
        recent = intervals_samples[-5:]
        recent_ms = np.array([s * 1000.0 / fs for s in recent])
        rr_mean_ms = float(np.mean(recent_ms))
        rr_std_ms = float(np.std(recent_ms))
        local_hr_bpm = 60000.0 / max(rr_mean_ms, 1e-4)
        return np.array([rr_prev_ms, rr_mean_ms, rr_std_ms, local_hr_bpm], dtype=np.float32)

    def export_config(self) -> dict:
        """Export DSP config for the model contract (spec Section 19)."""
        c = self.config
        return {
            'pipeline_version': 'v16',
            'sample_rate_hz': c.target_fs,
            'window_length': WINDOW_LEN,
            'pre_r_samples': PRE_R,
            'post_r_samples': POST_R,
            'r_peak_index_in_window': PRE_R,
            'rr_feature_count': 4,
            'rr_feature_order': ['rr_previous_ms', 'rr_mean_5_ms', 'rr_std_5_ms', 'local_hr_bpm'],
            'morphology_bandpass': {
                'low_hz': c.morphology_low_hz, 'high_hz': c.morphology_high_hz,
                'order': c.morphology_order, 'sos': self._sos_morph.tolist(),
            },
            'notch': {
                'enabled': c.notch_enabled,
                'hz': c.notch_hz if c.notch_enabled else None,
                'r': c.notch_r if c.notch_enabled else None,
                'b': self._notch_b.tolist() if self._notch_b is not None else None,
                'a': self._notch_a.tolist() if self._notch_a is not None else None,
            },
            'normalization': {
                'window_sec': c.normalization_window_sec,
                'window_samples': int(c.normalization_window_sec * c.target_fs),
                'epsilon': c.normalization_epsilon,
            },
            'detector': {
                'low_hz': c.detector_low_hz, 'high_hz': c.detector_high_hz,
                'order': c.detector_order, 'mwi_sec': c.detector_mwi_sec,
                'mwi_N': self._mwi_N,
                'refractory_sec': c.refractory_sec,
                'refractory_samples': int(round(c.refractory_sec * c.target_fs)),
            },
            'recenter': {
                'pre_correction_samples': DETECTION_DELAY_CORRECTION,
                'search_radius_samples': RECENTER_WINDOW,
                'derivation': 'ceil(cumulative_group_delay_at_10Hz=28.38)=29, zero safety margin',
                'finder': 'first_significant_local_max (signed morphology signal)',
            },
            'nlms': {
                'mode': c.nlms_mode, 'order': c.nlms_order,
                'mu': c.nlms_mu, 'delta': c.nlms_delta,
            },
            'adaptive_threshold': {
                'searchback_gamma': c.searchback_gamma,
                'twave_alpha': c.twave_alpha,
                'peak_detection': 'local_max_via_downward_zero_crossing (Phase 2 refactor)',
            },
        }


# ============================================================================
# Spec Section 4 API: standalone utility functions
# ============================================================================

def resample_signal(x: np.ndarray, fs_in: int, fs_out: int = 250) -> np.ndarray:
    """Resample ECG signal from fs_in to fs_out using polyphase resampling.

    Per spec Section 3.2:
      g = gcd(fs_in, fs_out)
      L = fs_out / g  (upsample factor)
      M = fs_in  / g  (downsample factor)

    Uses scipy.signal.resample_poly with deterministic coefficients.

    Args:
        x: input signal (1D array)
        fs_in: source sample rate in Hz
        fs_out: target sample rate in Hz (default 250)

    Returns:
        Resampled signal at fs_out Hz

    Raises:
        ValueError: if fs_in <= 0 or fs_out <= 0
    """
    if fs_in <= 0 or fs_out <= 0:
        raise ValueError(f"Sample rates must be positive: fs_in={fs_in}, fs_out={fs_out}")
    if fs_in == fs_out:
        return np.asarray(x, dtype=np.float32)
    from math import gcd
    from scipy.signal import resample_poly as _resample_poly
    g = gcd(int(fs_in), int(fs_out))
    L = int(fs_out) // g  # upsample factor
    M = int(fs_in) // g   # downsample factor
    return _resample_poly(x, L, M).astype(np.float32)


def map_aami_symbol(symbol: str) -> str:
    """Map a PhysioNet annotation symbol to AAMI class.

    Per spec Section 6.2:
      N family: N, L, R, e, j
      S family: A, a, J, S
      V family: V, E
      All others: IGNORE

    Args:
        symbol: PhysioNet annotation symbol (e.g. 'N', 'V', 'A', '/')

    Returns:
        'N', 'S', 'V', or 'IGNORE'
    """
    mapping = {
        'N': 'N', 'L': 'N', 'R': 'N', 'e': 'N', 'j': 'N',
        'A': 'S', 'a': 'S', 'J': 'S', 'S': 'S',
        'V': 'V', 'E': 'V',
    }
    return mapping.get(symbol, 'IGNORE')


def plot_dsp_audit(record_id: str, raw: np.ndarray, morphology: np.ndarray,
                   detection_energy: np.ndarray, annotations: list,
                   candidates: list, refined_peaks: list, windows: list,
                   out_path: str, fs: int = 250) -> None:
    """Generate a window-alignment audit plot for manual review.

    Per spec Section 6.5: plots raw ECG, morphology signal, detection energy,
    annotation positions, candidate peaks, refined peaks, and 130-sample window
    boundaries for a sample of beats.

    Args:
        record_id: record name for the title
        raw: raw ECG signal (at 250 Hz)
        morphology: morphology-branch output (post-rolling-norm)
        detection_energy: detection-branch MWI output
        annotations: list of annotation sample indices
        candidates: list of detection candidate sample indices (pre-recenter)
        refined_peaks: list of refined peak sample indices (post-recenter)
        windows: list of (start, end) tuples for 130-sample beat windows
        out_path: file path to save the figure
        fs: sample rate (default 250 Hz)
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as _fm

    n_samples = len(raw)
    t = np.arange(n_samples) / fs

    fig, axes = plt.subplots(4, 1, figsize=(16, 12), sharex=True, constrained_layout=True)

    # Plot 1: Raw ECG
    axes[0].plot(t, raw, 'b-', linewidth=0.5, alpha=0.8, label='Raw ECG')
    axes[0].set_ylabel('Amplitude')
    axes[0].set_title(f'DSP Audit — {record_id}')
    axes[0].legend(loc='upper right')
    axes[0].grid(True, alpha=0.3)

    # Plot 2: Morphology signal (post-rolling-norm)
    axes[1].plot(t, morphology, 'g-', linewidth=0.5, alpha=0.8, label='Morphology (z-scored)')
    axes[1].set_ylabel('Z-score')
    axes[1].legend(loc='upper right')
    axes[1].grid(True, alpha=0.3)

    # Plot 3: Detection energy (MWI output)
    axes[2].plot(t, detection_energy, 'r-', linewidth=0.5, alpha=0.8, label='Detection energy (MWI)')
    axes[2].set_ylabel('MWI')
    axes[2].legend(loc='upper right')
    axes[2].grid(True, alpha=0.3)

    # Plot 4: Overlay — annotations, candidates, refined peaks, window boundaries
    axes[3].plot(t, morphology, 'g-', linewidth=0.3, alpha=0.4, label='Morphology (ref)')
    if annotations:
        for a in annotations:
            axes[3].axvline(x=a/fs, color='blue', linewidth=0.5, alpha=0.5)
        axes[3].axvline(x=annotations[0]/fs, color='blue', linewidth=0.5, alpha=0.5, label=f'Annotations ({len(annotations)})')
    if candidates:
        for c in candidates:
            axes[3].axvline(x=c/fs, color='orange', linewidth=0.5, alpha=0.6, linestyle='--')
        axes[3].axvline(x=candidates[0]/fs, color='orange', linewidth=0.5, alpha=0.6, linestyle='--', label=f'Candidates ({len(candidates)})')
    if refined_peaks:
        for r in refined_peaks:
            axes[3].axvline(x=r/fs, color='red', linewidth=0.8, alpha=0.8)
        axes[3].axvline(x=refined_peaks[0]/fs, color='red', linewidth=0.8, alpha=0.8, label=f'Refined peaks ({len(refined_peaks)})')
    if windows:
        for i, (ws, we) in enumerate(windows):
            axes[3].axvspan(ws/fs, we/fs, alpha=0.15, color='yellow')
        axes[3].axvspan(windows[0][0]/fs, windows[0][1]/fs, alpha=0.15, color='yellow', label=f'Beat windows ({len(windows)})')
    axes[3].set_ylabel('Z-score')
    axes[3].set_xlabel('Time (s)')
    axes[3].legend(loc='upper right', fontsize=8)
    axes[3].grid(True, alpha=0.3)

    plt.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close()


def match_detected_peaks_to_annotations(detected: list, annotations: list,
                                         tolerance_samples: int) -> dict:
    """Match detected peaks to annotations using greedy nearest-neighbor.

    Per spec Section 5.11:
      - One annotation can match at most one detected peak (and vice versa)
      - Unmatched detections = FP
      - Unmatched annotations = FN
      - Matched pairs = TP

    Args:
        detected: list of detected peak sample indices
        annotations: list of true annotation sample indices
        tolerance_samples: maximum allowed distance for a match (e.g. 150ms * 250/1000 = 37)

    Returns:
        dict with keys: 'tp', 'fp', 'fn', 'matches' (list of (det_idx, ann_idx, error_samples))
    """
    matched_ann = set()
    matched_det = set()
    matches = []

    for d_idx, d_peak in enumerate(detected):
        if len(annotations) == 0:
            break
        best_idx = -1
        best_diff = tolerance_samples + 1
        for j in range(len(annotations)):
            if j in matched_ann:
                continue
            diff = abs(annotations[j] - d_peak)
            if diff < best_diff:
                best_diff = diff
                best_idx = j
        if best_idx >= 0 and best_diff <= tolerance_samples:
            matched_ann.add(best_idx)
            matched_det.add(d_idx)
            matches.append((d_idx, best_idx, d_peak - annotations[best_idx]))

    tp = len(matched_det)
    fp = len(detected) - len(matched_det)
    fn = len(annotations) - len(matched_ann)

    return {'tp': tp, 'fp': fp, 'fn': fn, 'matches': matches}


def evaluate_detector(matches: dict) -> dict:
    """Compute detector metrics from match results.

    Args:
        matches: dict from match_detected_peaks_to_annotations

    Returns:
        dict with: precision, recall, f1, timing_errors_ms (list)
    """
    tp = matches['tp']
    fp = matches['fp']
    fn = matches['fn']
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)
    timing_errors_ms = [m[2] * 1000.0 / 250 for m in matches['matches']]
    return {
        'precision': precision,
        'recall': recall,
        'f1': f1,
        'timing_errors_ms': timing_errors_ms,
    }


# ============================================================================
# NLMS implementation (spec Section 3.5)
# ============================================================================

@dataclass
class NLMSState:
    """State for motion-gated Normalized Least Mean Squares filter.

    Per spec Section 3.5:
      d[n] = s[n] + v[n]  (ECG + motion artifact)
      x[n] = IMU reference vector (delay line, per axis)
      v_hat[n] = w^T[n] * x[n]  (estimated artifact)
      e[n] = d[n] - v_hat[n]  (cleaned signal)
      w[n+1] = w[n] + g[n] * mu * e[n] * x[n] / (delta + ||x[n]||^2)

    Optional leakage:
      w[n+1] = (1-lambda)*w[n] + g[n] * mu * e[n] * x[n] / (delta + ||x[n]||^2)

    Fields:
        weights:  [order] filter weights
        delay:    [order] reference delay line
        mu:       adaptation rate
        delta:    regularization (prevents division by zero)
        leakage:  leakage factor (0 = no leakage, 1 = full forget)
        order:    filter length
        active:   whether NLMS is currently active (False in bypass mode)
    """
    weights: np.ndarray
    delay: np.ndarray
    mu: float
    delta: float
    leakage: float
    order: int
    active: bool

    def copy(self) -> "NLMSState":
        return NLMSState(self.weights.copy(), self.delay.copy(),
                        self.mu, self.delta, self.leakage, self.order, self.active)


def nlms_init(order: int = 16, mu: float = 0.01, delta: float = 1e-6,
              leakage: float = 0.0, active: bool = False) -> NLMSState:
    """Initialize NLMS state. active=False means bypass mode."""
    return NLMSState(
        weights=np.zeros(order, dtype=np.float64),
        delay=np.zeros(order, dtype=np.float64),
        mu=mu, delta=delta, leakage=leakage, order=order, active=active)


def nlms_step(ecg_sample: float, imu_vector: Optional[np.ndarray],
              state: NLMSState) -> tuple[float, NLMSState]:
    """One sample of NLMS filtering.

    Args:
        ecg_sample: input ECG sample d[n]
        imu_vector: IMU reference vector (1D array, will be delayed internally).
                    If None or state.active=False, returns ecg_sample unchanged (bypass).
        state: NLMS state

    Returns:
        (cleaned_sample, new_state)

    In bypass mode (active=False): returns ecg_sample unchanged, weights stay zero.
    In active mode: applies LMS update rule per spec Section 3.5.
    """
    if not state.active or imu_vector is None:
        return float(ecg_sample), state.copy()

    # Update delay line with IMU reference
    new_delay = state.delay.copy()
    new_delay[1:] = new_delay[:-1]
    new_delay[0] = float(imu_vector[0]) if len(imu_vector) > 0 else 0.0

    # Compute estimated artifact
    v_hat = float(np.dot(state.weights, new_delay))

    # Error signal (cleaned ECG)
    e = float(ecg_sample) - v_hat

    # NLMS update with leakage
    x_norm_sq = float(np.dot(new_delay, new_delay))
    denom = state.delta + x_norm_sq
    if denom < 1e-12:
        denom = 1e-12

    new_weights = state.weights.copy()
    if state.leakage > 0:
        new_weights = (1.0 - state.leakage) * new_weights
    new_weights += state.mu * e * new_delay / denom

    # Bounded weight check (prevent divergence)
    w_norm = float(np.linalg.norm(new_weights))
    max_w_norm = 1e6  # hard limit
    if w_norm > max_w_norm:
        new_weights = new_weights * (max_w_norm / w_norm)

    new_state = NLMSState(new_weights, new_delay, state.mu, state.delta,
                          state.leakage, state.order, state.active)
    return e, new_state
