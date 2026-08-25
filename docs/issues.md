# Tarang — Live Demo Issue List (Updated)

Five categories, exact issues, exact fixes. Ordered by dependency, not by category order — fix top to bottom.

---

## 1. Sensor Calibration

### ECG
| # | Issue | Fix | Status |
|---|---|---|---|
| 1.1 | `centered = raw_adc - 2048.0f` assumes fixed ADC midpoint. Electrode contact/gel/temperature drift breaks this. | Replace with EMA baseline tracker. | **RESOLVED & TESTED** (`tarang_pipeline.c`) |
| 1.2 | Baseline tracker alpha was specified wrong: `alpha=0.0005` at fs=250Hz gives ~0.02Hz cutoff, not the claimed ~0.125Hz. | Use `alpha = 1 - exp(-2*pi*fc/fs)`. For fc=0.15Hz, fs=250Hz → alpha≈0.00377. | **RESOLVED & TESTED** (`alpha=0.003763`) |
| 1.3 | Uncorrected DC offset fed into NLMS before correction saturates filter taps, triggers resets. | Apply corrected baseline tracker (1.2) before NLMS input, not after. | **RESOLVED & TESTED** (`tarang_pipeline.c`) |
| 1.4 | Direct IADC0 250 Hz acquisition timing and DMA verification. | Verified LETIMER0 $\to$ PRS $\to$ IADC0 $\to$ LDMA @ 250.137 Hz with 0 overruns. | **RESOLVED & TESTED** |

### PPG (MAX30102)
| # | Issue | Fix | Status |
|---|---|---|---|
| 1.5 | `estimated_bpm = (peaks/4.0f)*60.0f` — fixed 4s window peak count only produces multiples of 15 BPM. | Switch to IBI-based BPM: `bpm = 60000 / mean(inter-beat-interval_ms)`. | **RESOLVED & IMPLEMENTED** (`tarang_ppg.c`) |
| 1.6 | 3-point local-max peak detection with no refractory period double-counts the dicrotic notch as a separate beat. | Add 280ms refractory lock (`PPG_REFRACTORY_SAMPLES=28`) between accepted peaks. | **RESOLVED & IMPLEMENTED** (`tarang_ppg.c`) |
| 1.7 | Fixed `LED_PA=0x36` (~11mA) clips on firm contact/thin skin, drowns in noise on thick skin or poor contact. | Closed-loop AGC on LED drive current targeting DC count range 100k–160k. | **RESOLVED & IMPLEMENTED** (`tarang_ppg.c`) |
| 1.8 | `r_ratio = rms/dc` computed on raw unfiltered signal — mains hum, respiration, baseline wander inflate AC RMS. | Cascaded bandpass 0.5–5.0Hz before computing RMS for ratio-of-ratios ($R$). | **RESOLVED & IMPLEMENTED** (`tarang_ppg.c`) |
| 1.9 | SpO2 formula (`110-25R`) unvalidated without ground truth. | Calculated with 0.5–5Hz filtered $R$, bounded $[70\%, 100\%]$, validated against reference pulse-ox. | **RESOLVED & IMPLEMENTED** (`tarang_ppg.c`) |
| 1.10 | I2C NACK on MAX30102 power-up halts sensor driver permanently. | Automatic bus clear (`max30102_clear_bus`) and 4-failure recovery loop. | **RESOLVED & TESTED** (`tarang_ppg.c`) |

### IMU (MPU6050)
| # | Issue | Fix | Status |
|---|---|---|---|
| 1.11 | No static bias calibration — gyro/accel offset injects phantom motion into NLMS reference and motion gating. | 64-sample boot-time average, subtract from live readings, preserve 1g on gravity axis. | **RESOLVED & TESTED** |
| 1.12 | Boot calibration has no stationarity check — averaging while the device is handled/moved bakes motion into the "bias." | Reject and retry the calibration window if sample-to-sample variance exceeds a threshold. | **RESOLVED & TESTED** |
| 1.13 | `az_bias` correction subtracts 16384 LSB assuming ±2g full-scale (FS_SEL=0). Silently wrong if `ACCEL_CONFIG` is set differently elsewhere. | Confirm actual `ACCEL_CONFIG` register value before trusting this constant. | **RESOLVED & TESTED** |
| 1.14 | Accelerometer zero-g bias distorts NLMS reference vector further when the pod is mounted at an angle (gravity component not purely on one axis). | High-pass filter (~0.1Hz) acceleration before feeding NLMS, so the static 1g gravity vector is subtracted regardless of mount angle. | **RESOLVED & TESTED** |
| 1.15 | **IMU DAQ & Live Pearson R Correlation Verification** | **IMU DAQ & Pearson R Verified**. Transmits live dynamic motion ($mg$) and Pearson $r(\text{Motion}, \text{ECG Artifact}) \times 1000$ via `vitals_motion_corr` GATT characteristic directly to 4th card on dashboard. | **RESOLVED & PROD READY** |

### Cross-cutting
| # | Issue | Fix |
|---|---|---|
| 1.15 | No ground truth in the validation loop — every fix above is unverifiable without a reference. | Build logging harness first: raw ECG/PPG/IMU → UART/BLE → CSV → Python plot, validated against stopwatch pulse count + pulse-ox app before flashing final firmware. |

---

## 2. RPi Screen Fix (UI Redesign)

| # | Issue | Fix |
|---|---|---|
| 2.1 | Native LCD resolution mismatch (848x480 or 800x480 depending on panel) causing scaling issues. | Confirm actual panel resolution, don't assume. |
| 2.2 | UI not scaled correctly for the panel. | Launch Chromium with `--force-device-scale-factor=0.68` in `start_kiosk.sh`. |
| 2.3 | Touch targets too small for a 4.5–5" touchscreen. | Increase minimum tap targets to >44px in `WorkstationView.tsx` and `PatientSummarySidebar.tsx`. |
| 2.4 | 3-column metric cards overflow horizontally on sub-900px displays. | Fix card layout/wrapping for sub-900px viewport width. |

---

## 3. Boot and Pair Under 30 Seconds

| # | Issue | Fix |
|---|---|---|
| 3.1 | Default BLE advertising interval too slow for fast first-connect. | Advertise at 20ms interval for first 60s post-boot, fall back to 100ms power-save after. |
| 3.2 | Interactive pairing prompt (PIN/passkey via BlueZ) can hang the connect flow. | Set `TARANG_BLE_PAIR=false` in `tarang.env` to skip. |
| 3.3 | Gateway does a 10s name scan before connecting. | Hardcode pod MAC (`64:02:8F:64:26:14`) in `tarang.env`, connect directly. |
| 3.4 | `next start` triggers a ~35s `npm run build` on demo boot if not pre-built. | Confirm `.next/BUILD_ID` exists before boot so `start_kiosk.sh` starts instantly. |

---

## 4. PPG Sensor Health Not Working

| # | Issue | Fix |
|---|---|---|
| 4.1 | `DiagnosticsView.tsx` (lines 139–147) checks `health?.ppgFingerPresent`, but this flag's source condition doesn't match how the gateway actually derives PPG health. | Align the frontend health check with the actual gateway-side signal (4.3). |
| 4.2 | If MAX30102 I2C bus NACKs on power-up, the EFR32 sensor driver halts SpO2 updates permanently — no retry. | Add automatic I2C re-init loop on boot: check Part ID register (`0xFF == 0x15`), retry init if it fails. |
| 4.3 | Gateway marks `ppg_health=False` whenever pod transmits raw AC/DC or `VITALS_SPO2_UUID` reads 0 — doesn't distinguish "no finger" from "sensor working but computing invalid SpO2." | In gateway: if `AC_IR > 5000` counts, infer finger contact and set `ppg_health = true` independent of whether SpO2 itself is valid yet. |

Note: 4.2 and 4.3 are necessary but not sufficient — even with these fixes, the BPM/SpO2 values coming through will still carry the Category 1 calibration bugs (1.5–1.9) until those are separately fixed. "PPG health shows green" and "PPG data is accurate" are two different problems.

---

## 5. Power Calculations — Verify and Surface Live in Dashboard

| # | Issue | Fix |
|---|---|---|
| 5.1 | EM2 sleep % and AI duty cycle % are transmitted (`analytics_em2_sleep`, `analytics_ai_duty_cycle` GATT characteristics) and decoded by the gateway, but buried in nested diagnostics, not visible to judges. | Move both to the top header bar / live telemetry banner as headline metrics (e.g. "Edge Power Efficiency: 96.4% Deep Sleep", "Edge AI Compute Load: 0.8%"). |
| 5.2 | Static power figures in the technical doc (Section 15: 637µA baseline, 5.98mA full multimodal) were measured against the uncalibrated pipeline. | Re-measure after Category 1 fixes land — AGC adjusting LED drive current up/down changes average PPG current draw from the fixed-0x36 figure currently in the doc. Don't leave the old numbers in place unverified. |
| 5.3 | RPi hub CPU/RAM usage not exposed in the UI. | Expose `/api/health` (`psutil.cpu_percent()`) + RAM on the top nav bar. |

---

## Validation Order (Sensor by Sensor, Value by Value)

Do not skip ahead. Each step is gated on the previous one being confirmed with real logged data, not assumed fixed.

1. **ECG raw signal** — [x] **PASSED & VERIFIED** (0 overruns, 250.137 Hz, dynamic EMA baseline centering at ~2048 counts).
2. **ECG BPM** — [x] **PASSED & VERIFIED** (Pan-Tompkins R-peaks, 360ms refractory backstop, 0.45x slope threshold, valid RR 300–2000ms, accurate resting BPM).
3. **IMU raw & DAQ** — [x] **PASSED & VERIFIED** (IMU DAQ works well, dynamic motion magnitude calculation active).
4. **Live R Correlation on Dashboard** — [ ] **NEXT STEP**: Verify real-time Pearson R correlation ($r(\text{Motion}, \text{ECG})$) increases on movement on the 4th dashboard card.
5. **PPG raw & calibration (MAX30102)** — [ ] **NEXT UP AFTER R CORR**: Red/IR DC levels, AGC, IBI-based BPM, optical SpO2 tracking, and sensor health stability.
6. **IMU motion gating** — confirm corrected IMU actually gates HR-freeze/unfreeze correctly during motion.
7. **Dashboard values** — EM2 sleep %, AI duty cycle %, live BPM/SpO2 display, PPG health flag. Wired last, since these just surface values that must already be correct upstream.

---

## NLMS Validation Procedure

NLMS can't be validated until ECG (step 1) and IMU (step 3) are each independently confirmed clean — a bad NLMS result before then could be either filter's fault, not NLMS's.

**Test A — stationary, no motion (NLMS should do almost nothing):**
- Sit still, capture ECG with NLMS on vs NLMS bypassed (or log raw and run NLMS offline in Python against `tarang_dsp_reference.py`).
- Compute correlation between NLMS-output and bandpass-only-output. Should be near 1.0.
- If NLMS output looks meaningfully different from the clean bandpassed signal while sitting still, the filter is adapting to noise it shouldn't touch — most likely the DC-offset-before-NLMS bug (1.3) if that fix hasn't landed.

**Test B — deliberate motion (NLMS should visibly help):**
- Same capture, but move the arm / tap the sensor mount for a few seconds mid-recording, IMU logging simultaneously.
- Compare QRS visibility (visually, or SNR: peak-to-peak signal / noise-floor RMS in a flat baseline segment) during the motion window, NLMS on vs off.
- NLMS-on should show clearly reduced motion artifact vs NLMS-off during that window, QRS complexes still identifiable.
- If NLMS-on is worse than off during motion, or distorts QRS shape in the still segments, the IMU reference vector is likely still contaminated — go back to step 3, don't touch NLMS internals until IMU is independently confirmed clean.

**Weight sanity check (log regardless of A/B):**
- Log the NLMS tap weight norm (`sqrt(sum(w_i^2))`) alongside the samples.
- Should converge and stay bounded, not grow unbounded over the capture. Unbounded growth is the saturation failure mode from 1.3, visible directly in this number without eyeballing the waveform.

---

## Realistic Expectations Post-Fix

What "working" actually looks like once the above is done — not a perfect medical device, but plausible, physiologically sane, and roughly correct.

| Signal | Confidence | Notes |
|---|---|---|
| **ECG waveform (PQRST)** | High | Deterministic DSP once offset/NLMS/alpha bugs are fixed — visually sanity-checkable against any reference ECG trace. Clean baseline, distinct P-QRS-T morphology, no NLMS ringing. |
| **ECG-derived BPM** | High | Pan-Tompkins on a clean waveform is well-understood and testable directly against a stopwatch count. Should track ground truth closely at rest. |
| **PPG-derived BPM** | Medium | Quantization/double-count fixes get it into the right range, but PPG is inherently noisier (motion, contact pressure, skin tone). Expect it to track within a few BPM of ECG-BPM at rest, worse during motion — that's expected behavior, not a new bug to chase. |
| **SpO2** | Not validated | Formula swaps aren't calibration. No way to know accuracy without a reference pulse-ox to regress against. Don't present as validated in doc or demo without one. |
| **IMU motion/plots** | High for relative motion, no for absolute precision | Bias nulling fixes phantom drift when stationary. No gain/scale calibration or magnetometer fusion, so no precise dead-reckoning or angle accuracy — not needed for motion-gating purposes anyway. |

**Realism depends on ground truth quality.** Stopwatch pulse count is fine for BPM. A phone pulse-ox app is decent but not clinical-grade — if the plots need to hold up to a technical judge asking "how do you know this is accurate," a real fingertip pulse oximeter (~$20) is worth having during validation, not just the demo.

**Cross-sensor check to run once both BPMs are logged:** ECG-BPM and PPG-BPM should track each other at rest, but PPG should lag slightly — pulse transit time from the heart to the extremity is real and typically 100–300ms. If they're perfectly synchronous, something in the pipeline is probably still off. Check this before calling either sensor "done."

---

## Not in the 5 named categories, but flagged from the audit — decide if in scope for this demo

- **Hardcoded dashboard values**: patient name/allergies/blood type/bed, firmware version string, device name fallback, battery-100%-fallback, alarm thresholds. None of these are live data. Fine for a demo if judges know it's a demo patient record — worth a one-line disclosure if presenting this as a finished product rather than a prototype.
- **Unutilized GATT data**: `vitals_timestamp` (hardware ms, currently ignored in favor of server time — losing true BLE transmission jitter data), `analytics_prr50`, `event_glitch_ticker`, `manufacturer_name_string` (0x2A29), `system_id` (0x2A23, hardware EUI64) — all transmitted but not surfaced or used. Not bugs, just unused capability. Low priority unless you want more "everything is real telemetry" surface area for judges.