# TARANG End-to-End Testing & Validation Guide

This document defines the 5-stage end-to-end verification framework for the TARANG embedded firmware.

---

## Verification Status Matrix

| Stage | Focus Area | Execution Status | Key Findings / Metrics |
| :--- | :--- | :--- | :--- |
| **Stage 0** | Model Sanity Check & Real Beat Validation | ✅ **EXECUTED & PASSED** | - Flatbuffer tensor shapes, quant params, and dual heads validated.<br/>- **RR feature order verified against training code** (`Tarang_v15_FINAL_SUBMISSION.ipynb`).<br/>- Evaluated on real annotated INCART beats (`50 N`, `50 S`, `50 V`):<br/>  • **Class V (PVC):** Gate catch rate = $100\%$, $P(V) = 0.7822$ ($>0.60$), $P(S) = 0.1651$ ($<0.35$).<br/>  • **Class S (PAC):** Gate catch rate = $96\%$, $P(S) = 0.5274$ ($>0.35$), $P(V) = 0.4627$ ($<0.60$).<br/>  • **Class N (Normal):** Gate rejection rate = $94\%$, mean Gate $P = 0.0540$. |
| **Stage 1** | DSP & Gate Offline CSV Replay | ✅ **EXECUTED & PASSED** | - `kedartest.csv` detected 160 / 167 ground truth beats ($95.8\%$).<br/>- Root-cause analysis confirmed 5 misses were in the initial 3s startup window, 2 were low-amplitude dips; **0 missed by 300 ms refractory or T-wave suppression**.<br/>- Circuit breaker trips reliably on mains-hum/noise. |
| **Stage 2** | C++ AI Wrapper Build Validation | ✅ **COMPILED & LINKED** | `tarang_ai.cc` compiled and linked into `Integration.out` with `arm-none-eabi-gcc` with 0 warnings/errors (Flash: 182 KB, RAM: 512 KB). |
| **Stage 3** | Target Flash & Boot Log Check | ⏳ **READY TO FLASH** | Flash `Integration.hex` via Simplicity Commander and verify console logs (`gate_arena = 16 KB`, `sv_arena = 24 KB`). |
| **Stage 4** | Live Signal Validation | ⏳ **PENDING HARDWARE** | Real-time beat classification and clinical engine telemetry via `tarang_live_plot.py`. |
| **Stage 5** | Energy Profiler Power Characterization | ⏳ **PENDING HARDWARE** | Baseline current and ~12.7 ms CNN execution spikes. |

---

## Stage 0 — Model Sanity Check & Real Beat Evaluation

* **Scripts:**
  - Synthetic input test: [`verify_model_stage0.py`](verify_model_stage0.py)
  - Real human beat test (`kedartest.csv`): [`verify_model_real_beat.py`](verify_model_real_beat.py)
  - Real annotated database test (`INCART`): [`test_incart_abnormal_beats.py`](test_incart_abnormal_beats.py)
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

* **Script:** [`verify_stage1_dsp_replay.py`](verify_stage1_dsp_replay.py) / [`diagnose_missed_beats.py`](diagnose_missed_beats.py)
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
  [PIPELINE] Gate arena: 16384 bytes, SV arena: 24576 bytes
  ```
* **Pass Criteria:** No `FAILED (degraded mode)` messages.

---

## Stage 4 — Live Signal Validation (Hardware + ECG Lead)

* **Execution:**
  ```powershell
  python tarang_live_plot.py --port COM11
  ```
* **Pass Criteria:**
  - `Beat:` telemetry lines output approximately 1 beat per real heartbeat.
  - Gate CNN runs only when Tier-0 flags a beat as suspicious.
  - Decision thresholds applied: `GATE_THR = 0.25`, `V_THR = 0.60`, `S_THR = 0.35`.

---

## Stage 5 — Power & Current Profiling (Simplicity Energy Profiler)

* **Tool:** Simplicity Studio Energy Profiler.
* **Pass Criteria:**
  - Baseline resting current is flat and minimal (Tier-0 only).
  - Gate CNN invocation produces a sharp ~12.7 ms current spike.
  - Spike count matches console gate trigger count 1:1.
