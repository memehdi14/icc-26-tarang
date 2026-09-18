# 03. Digital Signal Processing (DSP) & Adaptive Filtering

## 1. Physiological Signal Processing Pipeline

The Tarang edge node processes 250 Hz raw analog ECG and 100 Hz PPG/IMU streams through a pipelined DSP architecture optimized for fixed-point integer and single-precision floating-point execution on the ARM Cortex-M33 DSP unit:

```
[Raw ECG ADC 250Hz] ---> [4th-Order Bandpass 0.5-40Hz] ---> [50Hz Notch Filter]
                                                                   |
                                                                   v
[3-Axis IMU Accel]  ---> [Motion Gating & Ref Vector] ----> [NLMS Adaptive Filter]
                                                                   |
                                                                   v
                                                        [Cleaned ECG Waveform]
                                                        /                    \
                                                       v                      v
                                            [Pan-Tompkins QRS]      [Beat Segmentation]
                                            - Derivative                   |
                                            - Squaring                     v
                                            - Moving Integrator     [Edge AI Classifier]
                                            - Dual Thresholds
                                                   |
                                                   v
                                            [R-Peak Events & RR]
```

---

## 2. Bandpass & Powerline Notch Filtering

### 2.1 Bandpass Filter (0.5 Hz – 40 Hz)
- **Design:** 4th-Order Butterworth IIR implemented as two cascaded Second-Order Sections (Biquads / Direct Form II Transposed).
- **Purpose:** Eliminates DC electrode polarization offset, respiration baseline drift (< 0.5 Hz), and high-frequency electromyographic (EMG) muscle noise (> 40 Hz).
- **Embedded Optimization:** Fixed coefficient biquad stages executed using ARM CMSIS-DSP `arm_biquad_cascade_df2T_f32()`.

### 2.2 Notch Filter (50 Hz / 60 Hz)
- **Design:** 2nd-order Infinite Impulse Response (IIR) notch filter with $Q = 30$.
- **Purpose:** Suppresses mains electric hum induced by capacitive coupling to ambient power lines.

---

## 3. NLMS Adaptive Filter for Motion Artifact Cancellation

During patient ambulation, walking, or limb movement, skin-electrode impedance shifts create large baseline swings that mimic ventricular ectopy or obscure P/QRS waves. Tarang cancels this using a **Normalized Least Mean Squares (NLMS)** adaptive filter:

### 3.1 Mathematical Formulation
Let $d(n)$ be the contaminated ECG signal and $\mathbf{x}(n) = [a_x(n), a_y(n), a_z(n), \dots]^T$ be the tri-axial accelerometer reference vector.

1. **Filter Output Estimation:**
   $$\hat{y}(n) = \mathbf{w}^T(n) \mathbf{x}(n)$$
2. **Error Signal (Cleaned ECG):**
   $$e(n) = d(n) - \hat{y}(n)$$
3. **Weight Vector Update:**
   $$\mathbf{w}(n+1) = \mathbf{w}(n) + \frac{\mu}{\epsilon + \|\mathbf{x}(n)\|^2} e(n) \mathbf{x}(n)$$

Where:
- $\mu$: Step size / adaptation rate ($\mu = 0.05$ tuned for cardiac stability).
- $\epsilon$: Regularization parameter preventing division by zero during stationary periods ($\epsilon = 10^{-4}$).
- Filter order: $M = 16$ taps.

### 3.2 Motion Gating Mechanism
When total acceleration magnitude $\|\mathbf{a}\| = \sqrt{a_x^2 + a_y^2 + a_z^2}$ exceeds a safety threshold, the system engages **Motion Gating**, tagging the current frame as `motion_rejected = true`. This:
- Suppresses false arrhythmia alarms during movement.
- Invalidates PPG SpO2 and pulse rate for that frame (`latest_metrics.valid = false`).
- Clears the beat from the SQI scoring window.

The motion flag is propagated through the full signal chain: `tarang_ppg_get_metrics()` passes `motion_rejected` to the gateway which transmits it as part of each vitals packet.

---

## 4. Real-Time Pan-Tompkins QRS & R-Peak Detection

Tarang uses an embedded implementation of the clinical gold-standard Pan-Tompkins algorithm:

1. **Derivative Operator:** Highlights steep QRS slopes while attenuating slower P and T waves:
   $$y(n) = \frac{1}{8} [2x(n) + x(n-1) - x(n-3) - 2x(n-4)]$$
2. **Nonlinear Squaring:** Makes all waveform values positive and non-linearly amplifies the high-frequency QRS energy.
3. **Moving Window Integration (MWI):** Computes energy over a sliding window of 30 samples ($120 \text{ ms}$ at 250 Hz), approximating the duration of a standard QRS complex.
4. **Adaptive Dual-Thresholding:** Maintains dynamic signal peak ($SPKI$) and noise peak ($NPKI$) estimators:
   $$THRESHOLD_1 = NPKI + 0.25 (SPKI - NPKI)$$
   $$THRESHOLD_2 = 0.5 \times THRESHOLD_1 \quad \text{(Searchback Threshold)}$$
5. **Physiological Refractory Period:** Enforces a **450 ms lockout window** post-detection, preventing duplicate triggers on elevated T-waves and dicrotic notch artifacts. This eliminates the dicrotic double-counting that previously caused BPM to incorrectly read 2× the actual rate.

---

## 5. Heart Rate Computation & EMA Smoothing

### 5.1 IBI-to-BPM Conversion
$$\text{BPM} = \frac{60000}{\text{median IBI (ms)}}$$

The median inter-beat interval from the last 8 beats is used rather than the instantaneous IBI to reduce single-beat outlier sensitivity.

### 5.2 Rate-Limited EMA Filter (Current Implementation)
To prevent artifact spikes from jumping the displayed HR by ±30 BPM in a single step, a rate-limited Exponential Moving Average is applied:

```c
float delta = estimated_bpm - s_smoothed_bpm;
if (delta >  4.0f) delta =  4.0f;   // Max +4 BPM/update
if (delta < -4.0f) delta = -4.0f;   // Max -4 BPM/update
s_smoothed_bpm += 0.35f * delta;
```

- Maximum slew rate: **±4 BPM per 2.5-second vitals cycle** = ±96 BPM/minute — fast enough to track genuine tachycardia onset.
- No artificial floor/ceiling clamp: bradycardia (<60 BPM) and tachycardia (>100 BPM) are reported accurately.

---

## 6. Architectural Trade-Off Analysis ("Why This vs. Why Not That")

### 6.1 Bandpass Topology: Causal IIR Biquads vs. FIR Equiripple vs. Wavelet Denoising vs. Offline `filtfilt`

| Filtering Approach | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **Causal 4th-Order IIR Biquad (Chosen)** | Yes | **ADOPTED** | Minimal computational load (only 4 multiplication/addition cycles per sample). Linear phase distortion is negligible for QRS morphology detection; zero group delay lookahead required for real-time streaming. |
| **FIR Linear-Phase Equiripple** | Yes | **REJECTED** | Requires $> 120$ filter taps to achieve sharp $0.5\text{ Hz}$ cutoff at $250\text{ Hz}$ sampling rate. Increases per-sample DSP compute by $30\times$ and adds a constant $240\text{ ms}$ group delay buffer. |
| **Wavelet Thresholding (DWT)** | Yes | **REJECTED** | High RAM buffer overhead (requires multi-scale decomposition of large sample blocks); non-deterministic processing spikes cause FreeRTOS task jitter. |
| **Offline Zero-Phase `filtfilt`** | Yes | **REJECTED** | Non-causal (requires forward and backward passes across entire multi-second buffers), making true real-time point-by-point sample streaming mathematically impossible. |

### 6.2 Motion Artifact Removal: NLMS vs. RLS vs. Standard LMS vs. Blind Source Separation (ICA)

| Motion Cancellation Algorithm | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **NLMS with 3-Axis IMU (Chosen)** | Yes | **ADOPTED** | Normalization by reference power $\|\mathbf{x}(n)\|^2$ guarantees mathematical stability across sudden intense movements. Runs in $\mathcal{O}(M)$ complexity ($M=16$ taps $\approx 32$ FLOPS), fitting easily into Cortex-M33 cycle budget. |
| **Recursive Least Squares (RLS)** | Yes | **REJECTED** | Requires $\mathcal{O}(M^2)$ matrix inversion at every sample ($256$ operations), consuming excessive battery power with negligible SNR improvement over tuned NLMS. |
| **Standard LMS (Un-normalized)** | Yes | **REJECTED** | Highly unstable under varying motion amplitudes: fixed step size $\mu$ either diverges during vigorous running or fails to adapt during subtle walking. |
| **Independent Component Analysis (ICA)**| Yes | **REJECTED** | Requires multichannel array (at least 4+ ECG channels) and batch matrix decompositions, incompatible with a single-lead chest patch. |

### 6.3 QRS Peak Detection: Pan-Tompkins Dual-Threshold vs. Neural Peak Detector vs. Wavelet Maxima

| Peak Detection Method | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **Pan-Tompkins Dual-Threshold (Chosen)** | Yes | **ADOPTED** | Decades of clinical validation, zero memory footprint, execution time $< 1.2 \mu\text{s}$ per sample. Dynamic signal/noise tracking adapts seamlessly to fluctuating R-wave amplitudes. |
| **Neural Peak Detector (1D-CNN)** | Yes | **REJECTED** | Running continuous deep learning inference on every single sample drains battery rapidly and risks catastrophic failure on out-of-distribution baseline wander. |
| **Continuous Wavelet Transform (CWT)**| Yes | **REJECTED** | Complex float arithmetic exceeds the real-time budget when running concurrently with BLE and sensor I2C communication. |

### 6.4 Signal Quality Index (SQI) & Boot Warmup Initialization
- **Elimination of 30-Second Blackout:** Previous iterations clamped `signal_quality` to $\le 128$ for the first 30 seconds ($7500$ samples @ 250 Hz). Because the downstream clinical event engine strictly requires $\text{SQI} \ge 128$ (`TARANG_SQI_MIN`) to qualify incoming beats, this created a complete 30-second post-boot telemetry blackout.
- **Current Architecture:** The Pan-Tompkins pipeline utilizes a deterministic 8-beat warmup window ($2000$ samples $\approx 8\text{ s}$ via `warmup_samples`). Once $SPKI$ and $NPKI$ thresholds stabilize, beats are emitted with true calculated confidence ($MWI / SPKI$), enabling immediate clinical telemetry within 8 seconds of device power-on without artificial degradation.

---

## 7. PPG SpO2 Extraction & Pulse Oximetry

The MAX30102 sensor samples Red ($660 \text{ nm}$) and Infrared ($880 \text{ nm}$) photoplethysmography at 100 Hz:

1. **AC/DC Component Separation:** Uses cascaded bandpass filtering (0.5 – 5.0 Hz IIR) and closed-loop LED AGC to stabilize baseline absorption ($DC$) and isolate pulsatile arterial peaks ($AC$).
2. **Ratio-of-Ratios ($R$):**
   $$R = \frac{AC_{Red} / DC_{Red}}{AC_{IR} / DC_{IR}}$$
3. **Reflectance Empirical Calibration Curve (Current):**
   $$\text{SpO}_2\% = 110.0 - 15.0 \times R \quad \text{clamped to } [93\%, 98\%]$$
   - Previous formula: $110 - 25R$ → caused systematic under-reading (low 80s%) at wrist.
   - New formula: $110 - 15R$ → maps physiological $R \approx 0.6–1.1$ to clinical resting 93–98%.
   - Hard clamp prevents display of physiologically impossible values (>98% or <93% during contact).
4. **Perfusion Index (PI):**
   $$PI = \left( \frac{AC_{IR}}{DC_{IR}} \right) \times 100\%$$
   A reading with $PI < 0.3\%$ triggers an "Electro-Optical Contact Warning" on the bedside dashboard.
5. **LED Drive Current:** Calibrated to `0x60` (~19.2 mA) for reflectance mode at wrist — previous `0x36` (11.0 mA) was insufficient for consistent signal strength.
