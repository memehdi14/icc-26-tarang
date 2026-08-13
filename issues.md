# TARANG Technical Issues & Project Status Inventory

**Document:** `issues.md`
**Date:** 2026-08-13
**Project:** TARANG Continuous Cardiac Monitoring System
**Target Platform:** Silicon Labs EFR32MG26B510F3200IM48 (Cortex-M33 + MVP)

---

## Executive Overview

This document catalogs all currently identified bugs, architectural debt, sensor hardware risks, telemetry format discrepancies, and pending engineering tasks across the **TARANG** project repository.

Section 5 below adds new findings from an offline analysis of a live test capture (`kedartest.csv`, 112 s session, ECG + IMU only) run against the architecture spec.

---

## 1. Firmware & Hardware Layer Issues

### [ISSUE-FW-01] Shared I2C Bus Contention (`sl_i2cspm_mikroe`)
- **Location**: [`app.c`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/app.c), [`tarang_ppg.c`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/tarang_ppg.c), [`tarang_imu.c`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/tarang_imu.c)
- **Component**: Physical I2C Peripheral
- **Severity**: HIGH
- **Description**: Both the MAX30102 PPG sensor (`0x57`) and MPU6050 IMU (`0x68`) share the same I2C bus instance (`sl_i2cspm_mikroe` on PC05 SCL / PC07 SDA). At 100 Hz sampling rates with GPIO interrupt callbacks firing simultaneously, I2C bus contention, arbitration loss, or clock stretching can freeze sensor communication.
- **Current Mitigation**: [`i2c_bus_clear()`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/tarang_ppg.c#L115-L154) bit-bangs 9 clock pulses to release stuck SDA lines, and [`max30102_recover()`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/tarang_ppg.c#L185-L210) re-initializes the bus after 4 consecutive failures.
- **Recommended Action**: Separate PPG and IMU onto distinct hardware I2C peripherals (e.g., `I2C0` and `I2C1`) or implement mutex-protected I2C transaction queues.

---

### [ISSUE-FW-02] Unimplemented Deferred AI Pipeline Function (`tarang_pipeline_run_deferred`)
- **Location**: [`tarang_pipeline.h:L186`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/tarang_pipeline.h#L186), [`tarang_pipeline.c`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/tarang_pipeline.c)
- **Component**: Pipeline Orchestrator
- **Severity**: MEDIUM
- **Description**: `tarang_pipeline_run_deferred()` is declared in `tarang_pipeline.h` for a planned asynchronous beat queue execution model, but the function body is not implemented. Calling it will cause a link/runtime error.
- **Recommended Action**: Complete implementation of `pending_beats` ring buffer draining in the main superloop or remove the prototype declaration to avoid API confusion.

---

### [ISSUE-FW-03] 8-Second Startup Warm-up Latency in Streaming DSP
- **Location**: [`tarang_dsp.c:L541`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/tarang_dsp.c#L541), [`tarang_dsp.c:L605-L646`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/tarang_dsp.c#L605-L646)
- **Component**: Streaming Pan-Tompkins R-Peak Detector
- **Severity**: LOW (Design Tradeoff)
- **Description**: To prevent startup transients (such as ADC power-on steps or electrode placement spikes) from locking adaptive thresholds ($\text{SPKI}/\text{NPKI}/\text{TH}_1$), the DSP ignores beat detection during the first 8 seconds ($2000$ samples @ 250 Hz) while accumulating initial signal statistics.
- **Recommended Action**: Ensure host UI/telemetry tools display "Initializing DSP / Warming Up..." during the first 8 seconds of device boot.

---

## 2. Telemetry & Log Parser Discrepancies

### [ISSUE-TEL-01] Serial Output Format Divergence
- **Location**: [`app.c`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/app.c), [`tarang_ecg.c`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/tarang_ecg.c), [`plot_tarang.py`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-dsp/integration_validation/plot_tarang.py)
- **Component**: VCOM Diagnostic Logging
- **Severity**: MEDIUM
- **Description**: The firmware supports two logging output modes:
  1. Human-readable debug prints (`[ECG] raw=...`, `[IMU] cnt=...`) enabled when `TARANG_DEBUG_TELEMETRY = 0`.
  2. High-density CSV schema lines (`@S`, `@I`, `@P`, `@B`) enabled when `TARANG_DEBUG_TELEMETRY = 1`.
  Running [`plot_tarang.py`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-dsp/integration_validation/plot_tarang.py) against a log file recorded in human-readable debug mode causes a `No @S records found` error.
- **Status**: FIXED in [`tarang_live_plot.py`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/tarang_live_plot.py) by adding regex parsers for `raw_line` format. [`plot_tarang.py`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-dsp/integration_validation/plot_tarang.py) requires `@S` records.

---

### [ISSUE-TEL-02] Python Port Auto-Detection Fallback
- **Location**: [`log_vcom.py:L28-L40`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/log_vcom.py#L28-L40), [`tarang_live_plot.py:L104-L117`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/tarang_live_plot.py#L104-L117)
- **Component**: Python Loggers
- **Severity**: LOW
- **Description**: When no Silicon Labs or J-Link board is auto-detected on Windows, the scripts default to `COM11`. If another device is on `COM11` or `COM11` does not exist, an unhandled `SerialException` occurs.
- **Recommended Action**: Catch `SerialException`, list all available active COM ports, and prompt the user to select the correct port interactively.

---

## 3. Machine Learning & Clinical Engine Issues

### [ISSUE-ML-01] S-Class (Supraventricular / PAC) Precision Ceiling
- **Location**: [`tarang_pipeline.c:L296-L298`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/tarang_pipeline.c#L296-L298), [`tarang_clinical_engine.c:L314-L322`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/tarang_clinical_engine.c#L314-L322)
- **Component**: Tier-2 SV Head CNN & Clinical Engine
- **Severity**: MEDIUM
- **Description**: While Ventricular ectopic detection ($V$-class / PVC) achieves $91.8\%$ recall with $P(V) > 0.6000$, Supraventricular ectopic detection ($S$-class / PAC) suffers from a lower precision ceiling ($F1 \approx 0.20 \text{--} 0.35$) due to small model capacity constraints ($20\,\text{KB}$ INT8 budget) and subtle morphological differences in single-lead ECGs.
- **Mitigation**: The Tier-3 Clinical Event Engine uses lead-agnostic RR interval metrics ($\text{CoV} > 0.12$, $\text{pRR50} > 10\%$, $\text{RMSSD} > 30\,\text{ms}$) over 30 beats for Atrial Fibrillation (AFib) screening, bypassing single-beat PAC CNN misclassifications.

---

### [ISSUE-ML-02] Lead II vs Lead I Training Domain Mismatch
- **Location**: [`docs/architecture/02_Tarang_Architecture_Resolution_FINAL.md`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/docs/architecture/02_Tarang_Architecture_Resolution_FINAL.md)
- **Component**: Model Training Dataset
- **Severity**: HIGH (Resolved in Spec, Pending Retraining)
- **Description**: Historic v9 models were trained on MIT-BIH Lead II data, but TARANG hardware captures Lead I (across the wrist). This domain shift reduces PAC morphology classification accuracy.
- **Resolution Plan**: Re-train v16 models natively on Lead I datasets (PTB-XL channel 0 and CPSC2018 Lead I, $\approx 28,714$ records) as specified in `04_Tarang_v16_Deployment_Aligned_Spec.md`.

---

## 5. New Findings from Live Capture Analysis (`kedartest.csv`, 2026-08-13)

These were found by replaying a 112 s ECG+IMU capture through the documented architecture and comparing runtime diagnostic counters against the spec's stated design targets.

### [ISSUE-DSP-04] R-Peak Detector Over-Triggering on T-Wave / Secondary Excursion
- **Location**: [`tarang_dsp.c` — `adaptive_thresh_step()`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/tarang_dsp.c#L250-L361), T-wave reject window (50–100 samples post-R), [`extract_beat()`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/tarang_dsp.c#L392-L476)
- **Component**: Streaming Pan-Tompkins Beat Detector
- **Severity**: HIGH
- **Description**: In the captured session, [`PIPELINE`] diagnostics show `suspicious=109` of `total=134` beats (81%) — nearly three orders of magnitude above the architecture's stated `<0.1%` design target for resting, motionless subjects. IMU data for the same window confirms the subject was stationary (accel std ~40–56 counts against a ~17,300-count gravity baseline), ruling out motion artifact. An offline peak re-detection on the raw ECG trace found RR CoV ≈ 0.245 (vs. the 0.12 threshold used by both the "suspicious" heuristic and AFib screening) with several RR intervals under 350 ms — not physiologically plausible as true beat spacing. Visual inspection of the waveform shows a secondary excursion immediately following several R-spikes, consistent with the T-wave (or S-wave) occasionally re-crossing the detection band and being counted as a separate beat.
- **Downstream Impact**: Directly drives ISSUE-PWR-01 below, and inflates `CoV`/`pRR50`/`RMSSD` inputs to `check_afib()`, creating latent false-AFib risk if this pattern persists for 30 consecutive beats.
- **Recommended Fix**:
  1. Add a debug build flag to log `SPKI`, `NPKI`, `TH1`, `TH2`, and the T-wave-reject decision (accept/reject + slope ratio) per candidate peak, so the false triggers can be attributed to threshold-hysteresis vs. T-wave-reject-window misses.
  2. Re-validate the T-wave reject window (currently 50–100 samples / 200–400 ms post-R) and slope-ratio cutoff ($<0.5\times R_{\text{slope}}$) against this dataset's actual T-wave timing — the window may be too narrow for this subject's HR (~90–100 bpm, RR ~600–650 ms).
  3. Consider widening the refractory period slightly or adding a minimum-RR floor (e.g., reject any candidate peak <300 ms after the last accepted peak, independent of the T-wave check) as a cheap backstop against double-detection.
  4. Validate the fix against a MIT-BIH or PTB-XL reference recording with known R-peak annotations, not just this capture, to avoid overfitting the fix to one session.

---

### [ISSUE-PWR-01] Tier-1 Gate CNN Inference Rate Far Exceeds Power Budget
- **Location**: [`tarang_pipeline.c` — `tarang_pipeline_on_rpeak()`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/tarang_pipeline.c#L228-L350), [`tarang_ai_gate()`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/tarang_pipeline.c#L115-L123)
- **Component**: Pipeline Orchestrator / Power Model
- **Severity**: HIGH
- **Description**: A direct consequence of ISSUE-DSP-04. The architecture's 30+ day battery life claim depends on the Gate CNN running on `<0.1%` of beats. In this capture it ran on 109/134 beats (81%), i.e. `AI: triggers=109`. `gate_passed` stayed at 0 the entire session — the Gate CNN correctly rejected all 109 as normal — so no false clinical alarms were raised, but the MVP accelerator paid the ~5–12 ms inference cost on nearly every beat instead of almost never.
- **Recommended Fix**:
  1. Root-cause fix is ISSUE-DSP-04 — fixing the beat detector removes most of this load automatically.
  2. As a defensive backstop independent of the DSP fix, add a rate limiter/circuit breaker in `tarang_pipeline_on_rpeak()`: if the suspicious-beat rate over a rolling window (e.g., last 30 beats) exceeds some sanity ceiling (e.g., 20%), log a `TARANG_FAULT_DSP_UNSTABLE`-style diagnostic event and consider it a signal-quality fault rather than continuing to fire the Gate CNN on every beat.
  3. Surface `suspicious / total` as a running percentage in the periodic diagnostic print (currently only raw counts are printed) so this regression is visible in future field logs without offline analysis.

---

### [ISSUE-SENSOR-01] No PPG Telemetry Captured in Test Session
- **Location**: [`tarang_ppg.c` — `tarang_ppg_init()`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/tarang_ppg.c#L280-L350), [`tarang_ppg_is_found()`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/tarang_ppg.c#L494-L497)
- **Component**: PPG Optical Subsystem
- **Severity**: MEDIUM
- **Description**: `kedartest.csv` contains zero `[PPG]` log lines across the full 112 s session (27,861 ECG lines, 6,611 IMU lines, 0 PPG lines). Either the MAX30102 was not detected/connected for this run, or PPG output is not being routed to the debug log path. Either way, SpO2 is unavailable and the pipeline loses its secondary HR cross-validation source for this session.
- **Recommended Fix**:
  1. Print `tarang_ppg_is_found()` status explicitly at boot (not just on failure) so "PPG absent" is visible immediately in any log, human-readable or `@S` schema.
  2. Confirm MAX30102 power/wiring on the test rig used for this capture, and re-run with `TARANG_DEBUG_TELEMETRY` set to include `[PPG]` lines to confirm it's a hardware/setup issue and not a logging-path bug shared with ISSUE-TEL-01.

---

### [ISSUE-TEL-03] Host-Received Timestamps Unsuitable as RR Ground Truth
- **Location**: [`log_vcom.py`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/log_vcom.py), CSV column `unix_timestamp`
- **Component**: Python Logger / Offline Validation Tooling
- **Severity**: LOW
- **Description**: `unix_timestamp` in the CSV log is the host PC's serial-receive time, not the device's internal 250 Hz sample clock. In this capture, inter-sample host timestamps showed gaps up to 182 ms (435 gaps > 20 ms across ~27,861 samples) due to normal UART/OS scheduling jitter on the host side. This is expected and does not indicate a problem on-device (LETIMER0 is hardware-timed regardless of host logging), but it means any offline RR/CoV validation computed from `unix_timestamp` — including the analysis behind ISSUE-DSP-04 — is an approximation, not ground truth.
- **Recommended Fix**:
  1. When validating DSP/AI behavior offline, prefer the device's own sample counter / onboard RR fields (e.g., `rr_prev_ms` from `extract_beat()`) if logged, rather than recomputing RR from host arrival time.
  2. If not already logged, add `rr_prev_ms`, `rr_mean_5_ms`, and `local_hr_bpm` to the periodic `[PIPELINE]` debug print so onboard RR values can be directly compared against offline reconstructions without relying on host timing.

---

## 6. Summary Table of Open Issues

| Issue ID | Category | Description | Severity | Status |
|---|---|---|---|---|
| **ISSUE-FW-01** | Hardware/FW | Shared I2C bus contention on `sl_i2cspm_mikroe` between MAX30102 & MPU6050 | HIGH | Mitigated (bus clear & retries) |
| **ISSUE-FW-02** | Firmware | `tarang_pipeline_run_deferred()` function body missing | MEDIUM | Open (Dead code / pending) |
| **ISSUE-FW-03** | Firmware/DSP | 8-second initial warm-up startup delay before R-peaks emitted | LOW | By Design |
| **ISSUE-TEL-01** | Telemetry | Format divergence (`[ECG]` debug vs `@S` schema) | MEDIUM | Fixed in `tarang_live_plot.py` |
| **ISSUE-TEL-02** | Tooling | `COM11` default fallback when board not auto-detected | LOW | Open |
| **ISSUE-ML-01** | Machine Learning | $S$-class (PAC) F1 precision ceiling ($0.20\text{--}0.35$) | MEDIUM | Mitigated (RR-based AFib engine) |
| **ISSUE-ML-02** | Machine Learning | Lead II training vs Lead I hardware domain shift | HIGH | Planned (v16 Lead I retraining) |
| **ISSUE-DSP-04** | DSP | R-peak detector over-triggers on T-wave/secondary excursion (81% "suspicious" vs. <0.1% target) | HIGH | Open (new, this analysis) |
| **ISSUE-PWR-01** | Power/Pipeline | Gate CNN inference rate (81% of beats) far exceeds power-budget design target | HIGH | Open (downstream of ISSUE-DSP-04) |
| **ISSUE-SENSOR-01** | Sensor/Telemetry | No PPG data captured in test session (`kedartest.csv`) | MEDIUM | Open (new, this analysis) |
| **ISSUE-TEL-03** | Telemetry/Tooling | Host `unix_timestamp` unsuitable as RR ground truth for offline validation | LOW | Open (new, this analysis) |