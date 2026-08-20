# TARANG End-to-End Testing & Validation Guide

> [!IMPORTANT]
> Offline accuracy results recorded in this guide predate the final synchronized
> NLMS, real PPG metrics, and reliable BLE event-transfer integration. Current
> isolated MVP profiling was executed on 2026-08-20. Rerun integrated timing,
> energy, and clinical stages on the current build. Acceptance gates are defined in
> [TARANG_END_TO_END_ARCHITECTURE.md](TARANG_END_TO_END_ARCHITECTURE.md).

This document defines the staged end-to-end verification framework for the TARANG embedded firmware.

---

## Verification Status Matrix

| Stage | Focus Area | Execution Status | Key Findings / Metrics |
| :--- | :--- | :--- | :--- |
| **Stage 0** | Model Sanity Check & Real Beat Validation | ✅ **EXECUTED & PASSED** | - Flatbuffer tensor shapes, quant params, and dual heads validated.<br/>- **RR feature order verified against training code** (`Tarang_v15_FINAL_SUBMISSION.ipynb`).<br/>- Evaluated on real annotated INCART beats (`50 N`, `50 S`, `50 V`):<br/>  • **Class V (PVC):** Gate catch rate = $100\%$, $P(V) = 0.7822$ ($>0.60$), $P(S) = 0.1651$ ($<0.35$).<br/>  • **Class S (PAC):** Gate catch rate = $96\%$, $P(S) = 0.5274$ ($>0.35$), $P(V) = 0.4627$ ($<0.60$).<br/>  • **Class N (Normal):** Gate rejection rate = $94\%$, mean Gate $P = 0.0540$. |
| **Stage 1** | DSP & Gate Offline CSV Replay | ✅ **EXECUTED & PASSED** | - `kedartest.csv` detected 160 / 167 ground truth beats ($95.8\%$).<br/>- Root-cause analysis confirmed 5 misses were in the initial 3s startup window, 2 were low-amplitude dips; **0 missed by 300 ms refractory or T-wave suppression**.<br/>- Circuit breaker trips reliably on mains-hum/noise. |
| **Stage 2** | C++ AI Wrapper Build Validation | ✅ **COMPILED & LINKED** | `tarang_ai.cc` compiled and linked into `Integration.out` with `arm-none-eabi-gcc` with 0 warnings/errors (Flash: 182 KB, RAM: 512 KB). |
| **Stage 3** | Target Build, Flash & Boot | ✅ **BUILT AND FLASHED** | AI/ML SDK 3.0.1 multi-model Integration build boots with Gate and SV active. Generated buffers: Gate `42,480 B`, SV `42,768 B`, including separate 32 KB paging buffers. |
| **Stage 3A** | Isolated Hardware ML Profile | ✅ **EXECUTED & PASSED** | BRD2608A, xG26, 78 MHz, MVP: Gate `12.634 ms`, SV `10.010 ms`, worst-case serial cascade `22.644 ms`. |
| **Stage 4** | Live Signal and Transport Validation | 🟡 **FUNCTIONAL; VALIDATION PENDING** | BLE subscribed to 14 characteristics and delivered vitals/analytics/events through Raspberry Pi and FastAPI. Reference ECG/PPG validation and long soak remain pending. |
| **Stage 5** | Energy Profiler Power Characterization | ⏳ **PENDING HARDWARE CAPTURE** | Measure actual baseline, sensor, BLE, Gate, and Gate+SV energy. Do not substitute ML Profiler latency for AEM energy evidence. |

---

## Stage 0 — Model Sanity Check & Real Beat Evaluation

* **Scripts:**
  - Synthetic input test: [`verify_model_stage0.py`](../tests/verify_model_stage0.py)
  - Real human beat test (`kedartest.csv`): [`verify_model_real_beat.py`](../tests/verify_model_real_beat.py)
  - Real annotated database test (`INCART`): [`test_incart_abnormal_beats.py`](../tests/test_incart_abnormal_beats.py)
* **RR Feature Order (Confirmed from `Tarang_v15_FINAL_SUBMISSION.ipynb` Line 500–515):**
  - Index 0: `rr_prev_ms` (mean: $800.36$, scale: $206.59$)
  - Index 1: `rr_mean_5_ms` (mean: $796.74$, scale: $180.94$)
  - Index 2: `rr_std_5_ms` (mean: $57.82$, scale: $92.44$)
  - Index 3: `local_hr_bpm` (mean: $79.82$, scale: $22.11$)
* **Real Abnormal Beat Evaluation (INCART Database):**
  - **Class V (PVCs)** produce $P(V) = 0.7822$ ($>0.60$) and $P(S) = 0.1651$ ($<0.35$).
  - **Class S (PACs)** produce $P(S) = 0.5274$ ($>0.35$) and $P(V) = 0.4627$ ($<0.60$).
  - Priority rule in `tarang_pipeline.c` (`if P(V) > 0.60 -> V elif P(S) > 0.35 -> S`): PVCs are evaluated first and cannot be swallowed by PAC bias.

---

## Stage 1 — DSP & Gate Offline CSV Replay

* **Script:** [`verify_stage1_dsp_replay.py`](../tests/verify_stage1_dsp_replay.py) / [`diagnose_missed_beats.py`](../tests/diagnose_missed_beats.py)
* **Detailed Breakdown of `kedartest.csv` (160 / 167 detected):**
  1. **5 Peaks (Sample 5, 181, 308, 439, 574)**: Occur in the first 3.0 seconds ($<750$ samples), during the startup baseline calibration window.
  2. **2 Peaks (Sample 1686 at $t=6.74\text{s}$, Sample 23510 at $t=94.04\text{s}$)**: Severe low-amplitude respiration/baseline wander dips ($<50\%$ normal QRS height).
  3. **0 False Double Triggers**: Hard 300 ms refractory and tightened T-wave rejection completely eliminate T-wave double detection.

---

## Stage 2 & 3 — Target Firmware Build & Flash

* **Build Target Binary:**
  ```powershell
  cd cmake_gcc
  cmake --build --preset default_config
  ```
* **Flash with Simplicity Commander:**
  ```powershell
  commander flash build/base/Integration.hex --device EFR32MG26B510F3200IM48
  ```
* **Expected VCOM Boot Log:**
  ```
  [PIPELINE] Tarang pipeline initialized.
  [PIPELINE] Tier 0: DSP heuristics  — ACTIVE
  [PIPELINE] Tier 1: Gate CNN (40576 B) — ACTIVE
  [PIPELINE] Tier 2: SV Head (32064 B)  — ACTIVE
  [PIPELINE] Tier 3: Clinical Engine — ACTIVE
  [PIPELINE] Gate arena: 42480 bytes, SV arena: 42768 bytes
  ```
* **Pass Criteria:** No `FAILED (degraded mode)` messages.

---

## Stage 3A — Isolated MVP Model Profiling

Both canonical model files were profiled independently with Silicon Labs
Simplicity Machine Learning using **HW Accelerated (MVP)** kernels.

| Metric | Gate CNN | SV Head CNN |
| :--- | ---: | ---: |
| Model size | 40,576 B | 32,064 B |
| Profiler arena | 9 KB | 9 KB |
| Mean inference | **12.634 ms** | **10.010 ms** |
| Throughput | 79.15/s | 99.90/s |
| CPU cycles | 463,653 | 385,573 |
| MVP cycles | 558,363 | 434,004 |
| MVP stalls | 226,186 | 165,618 |
| CPU utilization | 45.4% | 47.0% |
| MVP layers | 11 | 12 |
| MACs | 707,776 | 539,360 |

The worst-case serial Gate+SV model time is `22.644 ms`. This is isolated
model evidence. It excludes sensor interrupts, NLMS, input preparation, BLE,
logging, and scheduler contention. Measure those effects on the actual platform
with DWT cycle counters before citing end-to-end inference latency.

The dominant CPU fallback is `MEAN`: `3.570 ms` in Gate and `2.686 ms` in SV.
Convolution and dense compute is correctly assigned to MVP. No model graph
change is required before validation.

---

## Stage 4 — Live Signal Validation (Hardware + ECG Lead)

* **Execution:**
  ```powershell
  python log_vcom.py
  ```
* **Procedure:** Enter the pseudonymous volunteer ID, close other serial
  consoles, reset the board when prompted, and stop with Ctrl+C after the
  planned rest/motion/recovery recording. The logger creates the plots when it
  closes the capture. Confirm `@V,1,250,100,100` is present and the final
  machine-record count is nonzero; otherwise the session is invalid.
* **Pass Criteria:**
  - `Beat:` telemetry lines output approximately 1 beat per real heartbeat.
  - Gate CNN runs only when Tier-0 flags a beat as suspicious.
  - Decision thresholds applied: `GATE_THR = 0.25`, `V_THR = 0.60`, `S_THR = 0.35`.

---

## Stage 5 — Power & Current Profiling (Simplicity Energy Profiler)

* **Tool:** Simplicity Studio Energy Profiler.
* **Pass Criteria:**
  - Record average current, average power, and total energy for boot, sensors,
    BLE-connected idle, normal live operation, Gate stress, and Gate+SV stress.
  - Confirm all sensor rails are inside the AEM measurement domain.
  - Gate execution should correlate with an approximately `12.634 ms` isolated
    reference and Gate+SV with approximately `22.644 ms`, allowing for real
    application contention.
  - Spike count matches firmware Gate/SV invocation counters exactly.
  - Label battery-life values as measured or modeled; never mix the two.
