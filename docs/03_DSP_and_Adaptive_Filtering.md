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
When total acceleration magnitude $\|\mathbf{a}\| = \sqrt{a_x^2 + a_y^2 + a_z^2}$ exceeds a safety threshold ($> 1.8g$), the system engages **Motion Gating**, tagging the current frame as `SIGNAL_DEGRADED` and suppressing false arrhythmia alarms until the baseline settles.

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
5. **Physiological Refractory Period:** Enforces a 200 ms lockout window post-detection, mathematically preventing duplicate triggers on elevated T-waves.

---

## 5. Architectural Trade-Off Analysis ("Why This vs. Why Not That")

### 5.1 Bandpass Topology: Causal IIR Biquads vs. FIR Equiripple vs. Wavelet Denoising vs. Offline `filtfilt`

| Filtering Approach | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **Causal 4th-Order IIR Biquad (Chosen)** | Yes | **ADOPTED** | Minimal computational load (only 4 multiplication/addition cycles per sample). Linear phase distortion is negligible for QRS morphology detection; zero group delay lookahead required for real-time streaming. |
| **FIR Linear-Phase Equiripple** | Yes | **REJECTED** | Requires $> 120$ filter taps to achieve sharp $0.5\text{ Hz}$ cutoff at $250\text{ Hz}$ sampling rate. Increases per-sample DSP compute by $30\times$ and adds a constant $240\text{ ms}$ group delay buffer. |
| **Wavelet Thresholding (DWT)** | Yes | **REJECTED** | High RAM buffer overhead (requires multi-scale decomposition of large sample blocks); non-deterministic processing spikes cause FreeRTOS task jitter. |
| **Offline Zero-Phase `filtfilt`** | Yes | **REJECTED** | Non-causal (requires forward and backward passes across entire multi-second buffers), making true real-time point-by-point sample streaming mathematically impossible. |

### 5.2 Motion Artifact Removal: NLMS vs. RLS vs. Standard LMS vs. Blind Source Separation (ICA)

| Motion Cancellation Algorithm | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **NLMS with 3-Axis IMU (Chosen)** | Yes | **ADOPTED** | Normalization by reference power $\|\mathbf{x}(n)\|^2$ guarantees mathematical stability across sudden intense movements. Runs in $\mathcal{O}(M)$ complexity ($M=16$ taps $\approx 32$ FLOPS), fitting easily into Cortex-M33 cycle budget. |
| **Recursive Least Squares (RLS)** | Yes | **REJECTED** | Requires $\mathcal{O}(M^2)$ matrix inversion at every sample ($256$ operations), consuming excessive battery power with negligible SNR improvement over tuned NLMS. |
| **Standard LMS (Un-normalized)** | Yes | **REJECTED** | Highly unstable under varying motion amplitudes: fixed step size $\mu$ either diverges during vigorous running or fails to adapt during subtle walking. |
| **Independent Component Analysis (ICA)**| Yes | **REJECTED** | Requires multichannel array (at least 4+ ECG channels) and batch matrix decompositions, incompatible with a single-lead chest patch. |

### 5.3 QRS Peak Detection: Pan-Tompkins Dual-Threshold vs. Neural Peak Detector vs. Wavelet Maxima

| Peak Detection Method | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **Pan-Tompkins Dual-Threshold (Chosen)** | Yes | **ADOPTED** | Decades of clinical validation, zero memory footprint, execution time $< 1.2 \mu\text{s}$ per sample. Dynamic signal/noise tracking adapts seamlessly to fluctuating R-wave amplitudes. |
| **Neural Peak Detector (1D-CNN)** | Yes | **REJECTED** | Running continuous deep learning inference on every single sample drains battery rapidly and risks catastrophic failure on out-of-distribution baseline wander. |
| **Continuous Wavelet Transform (CWT)**| Yes | **REJECTED** | Complex float arithmetic exceeds the real-time budget when running concurrently with BLE and sensor I2C communication. |

---

## 6. PPG SpO2 Extraction & Pulse Oximetry

The MAX30102 sensor samples Red ($660 \text{ nm}$) and Infrared ($880 \text{ nm}$) photoplethysmography at 100 Hz:

1. **AC/DC Component Separation:** Uses low-pass exponential moving averaging (EMA, $\alpha = 0.01$) to extract constant tissue absorption ($DC$), and high-pass subtraction to isolate pulsating arterial blood volume ($AC$).
2. **Ratio-of-Ratios ($R$):**
   $$R = \frac{AC_{Red} / DC_{Red}}{AC_{IR} / DC_{IR}}$$
3. **Empirical Calibration Curve:**
   $$\text{SpO}_2\% = 110.0 - 25.0 \times R$$
4. **Perfusion Index (PI):**
   $$PI = \left( \frac{AC_{IR}}{DC_{IR}} \right) \times 100\%$$
   *A reading with $PI < 0.3\%$ triggers an "Electro-Optical Contact Warning" on the bedside dashboard.*
