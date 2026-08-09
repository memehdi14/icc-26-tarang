# Step-by-Step Sensor Reading Verification & Validation Guide

This guide provides a practical, step-by-step protocol for biomedical hardware & DSP engineers to verify whether raw telemetry readings (ECG, PPG, IMU) recorded by the **TARANG** board represent **true physiological human signals** or non-biological noise/artifacts.

---

## Quick Reference Flowchart

```
[1. Check Hardware & Baseline] ---> Is ADC within 500-3500 LSB (not 0 or 4095)?
                                        | Yes
[2. Physical Reference Test]   ---> Does Heart Rate match commercial oximeter within ±3 BPM?
                                        | Yes
[3. Optical & Tissue Sanity]   ---> Is PPG Red/IR Ratio 0.4 < R < 2.0?
                                        | Yes
[4. Spectral FFT Check]         ---> Is main FFT peak in 0.75 - 3.0 Hz (45-180 BPM) range?
                                        | Yes
[5. ECG-PPG Delay (PAT)]        ---> Does PPG lag ECG by 150ms - 300ms?
                                        | Yes
                              [VALIDATED PHYSIOLOGICAL SIGNAL]
```

---

## Step 1: Electrical & Hardware Contact Verification

Before analyzing heart rate, confirm the hardware analog front end (AFE) is in a linear, non-saturated operating state.

1. **ADC Dynamic Range & Saturation Check**:
   - Inspect raw ECG and PPG values in the CSV log.
   - **Railed High (4095 LSB / Max Counts)**: Photodiode/ECG electrode is saturated (too much LED drive current or ambient light leakage).
   - **Railed Low (0 LSB)**: Sensor disconnected, lead-off active, or power line broken.
   - **Valid Baseline**: Raw ECG DC level should settle around **500 to 2500 LSB** (for 12-bit ADC). Raw PPG RED/IR counts should settle between **5000 and 100,000 counts** (depending on AFE gain).

2. **Lead-Off / Touch Sensitivity Test**:
   - Record a 30-second log while finger/electrodes are **lifted off** the sensor.
   - Record a 30-second log while finger/electrodes are **firmly touching**.
   - **Validation Criteria**: Disconnected state will show random floating noise or flat 0/4095 line. Connected state will immediately show a stable baseline offset with micro-oscillations.

---

## Step 2: Optical PPG & Tissue Reflection Validation

PPG relies on light absorption fluctuations caused by arterial pulsation.

1. **Ambient Occlusion Test**:
   - Place a piece of opaque black tape over the optical sensor.
   - Read RED and IR raw counts.
   - **Validation Criteria**: Dark counts should drop significantly (e.g. < 500 counts). If counts remain high, ambient light leak or internal optical crosstalk (LED bleeding directly to photodiode through PCB substrate) is present.

2. **Red vs. Infrared Ratio ($R$) Sanity Check**:
   - Calculate the Ratio of Ratios ($R$) from the logged PPG data:
     $$R = \frac{\text{AC}_{\text{Red}} / \text{DC}_{\text{Red}}}{\text{AC}_{\text{IR}} / \text{DC}_{\text{IR}}}$$
   - **Validation Criteria**:
     - For human tissue and normal blood oxygenation ($90\% - 100\%\text{ SpO}_2$), **$0.4 \le R \le 1.2$**.
     - If $R > 2.0$ or $R < 0.2$, the signal is **not physiological** (e.g. object reflection, ambient AC lighting, or improper LED current balancing).

3. **Waveform Morphology Check**:
   - Plot 5 seconds of clean PPG data.
   - **Validation Criteria**:
     - Look for standard cardiac pulse morphology: rapid systolic upstroke, systolic peak, dicrotic notch, and diastolic decay.
     - Pure sine waves indicate electrical interference; square steps indicate quantization/bit-width clipping.

---

## Step 3: Physical Reference Dual-Device Validation

To verify accuracy against a ground truth:

1. **Dual-Probe Setup**:
   - Place a certified commercial fingertip pulse oximeter on index finger of the left hand.
   - Place TARANG PPG/ECG sensor on right hand index finger / wrist.
2. **Synchronous 60-Second Logging**:
   - Start TARANG logging (`python log_vcom.py`).
   - Note down reference Heart Rate (BPM) and $\text{SpO}_2\%$ from the commercial monitor every 10 seconds.
3. **Accuracy Tolerance**:
   - **Heart Rate**: TARANG estimated BPM must be within **$\pm 3\text{ BPM}$** of reference.
   - **SpO2**: TARANG estimated SpO2 must be within **$\pm 2\%$** of reference.

---

## Step 4: Spectral Frequency Domain Analysis (FFT)

Frequency domain transformation separates true cardiac pulses from motion and power line interference.

1. **Run Spectral Script**:
   - Execute `python projects/tarang-dsp/integration_validation/plot_integration_csvs.py`.
   - Inspect generated plot `plots/spectral_analysis.png`.
2. **Frequency Peak Identification**:
   - **Cardiac Peak ($f_{\text{HR}}$)**: Must show a sharp peak between **$0.75\text{ Hz}$** ($45\text{ BPM}$) and **$3.0\text{ Hz}$** ($180\text{ BPM}$).
   - **First Harmonic ($2 \times f_{\text{HR}}$)**: A secondary peak at exactly twice the cardiac frequency confirms physiological non-linearity.
   - **Mains Power Noise**: A peak at **$50\text{ Hz}$** (Europe/Asia) or **$60\text{ Hz}$** (USA) indicates AC grid coupling.
   - **Motion Artifacts**: Broad low-frequency noise broadband below **$0.5\text{ Hz}$**. Check IMU accelerometer variance to verify.

---

## Step 5: Cross-Sensor ECG to PPG Time Correlation (PAT)

1. **Pulse Arrival Time (PAT) Check**:
   - Plot synchronized ECG and PPG channels on the same time axis (see `plots/combined_dashboard.png`).
   - Identify an ECG R-peak (ventricular depolarization) at timestamp $t_{\text{R}}$.
   - Identify the corresponding PPG systolic foot (blood pulse arriving at finger) at timestamp $t_{\text{PPG}}$.
   - Compute delay: $\Delta t = t_{\text{PPG}} - t_{\text{R}}$.
2. **Validation Criteria**:
   - Physiological Transit Time $\Delta t$ **MUST be positive** and range between **$150\text{ ms}$ and $300\text{ ms}$**.
   - If $\Delta t < 0$, PPG is leading ECG, indicating clock desynchronization or misordered telemetry parsing.

---

## Validation Checklist Summary

| Test Step | Target Criterion | Status |
|---|---|---|
| **1. ADC Baseline** | $500 \le \text{DC} \le 3500\text{ LSB}$ (non-railed) | PASS / FAIL |
| **2. Red/IR Ratio ($R$)** | $0.4 \le R \le 1.2$ | PASS / FAIL |
| **3. Pulse Morphology** | Visible systolic peak & dicrotic notch | PASS / FAIL |
| **4. Dual-Probe HR** | Within $\pm 3\text{ BPM}$ of commercial oximeter | PASS / FAIL |
| **5. FFT Peak** | Dominant peak in $0.75 - 3.0\text{ Hz}$ band | PASS / FAIL |
| **6. ECG-PPG Delay (PAT)** | $150\text{ ms} \le \Delta t \le 300\text{ ms}$ | PASS / FAIL |
