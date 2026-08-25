# Tarang — Live Demo Issue List (Updated)

Five categories, exact issues, exact fixes. Ordered by dependency, not by category order — fix top to bottom.

---

## 1. Sensor Calibration

### ECG
| # | Issue | Fix |
|---|---|---|
| 1.1 | `centered = raw_adc - 2048.0f` assumes fixed ADC midpoint. Electrode contact/gel/temperature drift breaks this. | Replace with EMA baseline tracker. |
| 1.2 | Baseline tracker alpha was specified wrong: `alpha=0.0005` at fs=250Hz gives ~0.02Hz cutoff, not the claimed ~0.125Hz. | Use `alpha = 1 - exp(-2*pi*fc/fs)`. For fc=0.15Hz, fs=250Hz → alpha≈0.00377. |
| 1.3 | Uncorrected DC offset fed into NLMS before correction saturates filter taps, triggers resets. | Apply corrected baseline tracker (1.2) before NLMS input, not after. |
| 1.4 | **Doc conflict**: this checklist names an AD8232 analog front-end with a 2–4s DC-settle issue. Earlier architecture doc describes ECG acquisition as direct IADC0 sampling (no named AFE IC). | Confirm which is actually on the board — AD8232 discrete AFE, or direct IADC0. If AD8232 is real and undocumented in the architecture doc, that doc needs a correction, not just this checklist. |

### PPG (MAX30102)
| # | Issue | Fix |
|---|---|---|
| 1.5 | `estimated_bpm = (peaks/4.0f)*60.0f` — fixed 4s window peak count only produces multiples of 15 BPM. | Switch to IBI-based BPM: `bpm = 60000 / mean(inter-beat-interval_ms)`. |
| 1.6 | 3-point local-max peak detection with no refractory period double-counts the dicrotic notch as a separate beat. | Add 280ms refractory lock between accepted peaks. |
| 1.7 | Fixed `LED_PA=0x36` (~11mA) clips on firm contact/thin skin, drowns in noise on thick skin or poor contact. | Closed-loop AGC on LED drive current, target range 7.0–12.5mA per this doc (reconcile against earlier-proposed 100k–180k ADC-count target — pick one target system, not both). |
| 1.8 | `r_ratio = rms/dc` computed on raw unfiltered signal — mains hum, respiration, baseline wander inflate AC RMS. | Bandpass 0.5–5.0Hz before computing RMS for the ratio. |
| 1.9 | SpO2 formula (`110-25R` or any substitute polynomial) is unvalidated — no reference pulse-ox to regress against. | Don't present SpO2 as calibrated/accurate until a reference device is used to fit the curve. Flag as unvalidated in any judge-facing material. |
| 1.10 | I2C NACK on MAX30102 power-up halts the sensor driver permanently (see Category 4 below — same root sensor, separate failure mode). | See Category 4. |

### IMU (MPU6050)
| # | Issue | Fix |
|---|---|---|
| 1.11 | No static bias calibration — gyro/accel offset injects phantom motion into NLMS reference and motion gating. | 64-sample boot-time average, subtract from live readings, preserve 1g on gravity axis. |
| 1.12 | Boot calibration has no stationarity check — averaging while the device is handled/moved bakes motion into the "bias." | Reject and retry the calibration window if sample-to-sample variance exceeds a threshold. |
| 1.13 | `az_bias` correction subtracts 16384 LSB assuming ±2g full-scale (FS_SEL=0). Silently wrong if `ACCEL_CONFIG` is set differently elsewhere. | Confirm actual `ACCEL_CONFIG` register value before trusting this constant. |
| 1.14 | Accelerometer zero-g bias distorts NLMS reference vector further when the pod is mounted at an angle (gravity component not purely on one axis). | High-pass filter (~0.1Hz) acceleration before feeding NLMS, so the static 1g gravity vector is subtracted regardless of mount angle. This is in addition to 1.11–1.12, not a replacement for them. |

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

## Not in the 5 named categories, but flagged from the audit — decide if in scope for this demo

- **Hardcoded dashboard values**: patient name/allergies/blood type/bed, firmware version string, device name fallback, battery-100%-fallback, alarm thresholds. None of these are live data. Fine for a demo if judges know it's a demo patient record — worth a one-line disclosure if presenting this as a finished product rather than a prototype.
- **Unutilized GATT data**: `vitals_timestamp` (hardware ms, currently ignored in favor of server time — losing true BLE transmission jitter data), `analytics_prr50`, `event_glitch_ticker`, `manufacturer_name_string` (0x2A29), `system_id` (0x2A23, hardware EUI64) — all transmitted but not surfaced or used. Not bugs, just unused capability. Low priority unless you want more "everything is real telemetry" surface area for judges.