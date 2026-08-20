# TARANG End-to-End Architecture, Data Contract, and Validation Plan

Status: Functional integration build; hardware and clinical validation pending

Date: 2026-08-20

Target: EFR32MG26B510F3200IM48 plus Raspberry Pi/BlueZ hub

## 1. What This Build Is

This build connects the real ECG, MAX30102 PPG, and MPU6050 IMU acquisition paths to ECG DSP, an IMU-referenced NLMS motion canceller, the two-stage INT8 AI cascade, the clinical event engine, encrypted/bonded BLE, the Raspberry Pi gateway, FastAPI/SQLite, and the dashboard.

It is a research and hackathon validation system. It is not a certified medical device, its SpO2 equation has not been calibrated for this optical/mechanical design, and its ECG AI and adaptive-filter behavior still require human-subject validation against reference instruments. The UI must display unavailable data as unavailable; it must never invent a plausible clinical value.

## 2. Current Status

| Layer | Current state | Remaining proof |
| --- | --- | --- |
| ECG acquisition | Implemented, 250 Hz nominal, IADC plus LDMA ping-pong | Long hardware run with zero overruns |
| PPG acquisition | Implemented, 100 Hz RED/IR | Reference-oximeter comparison |
| IMU acquisition | Implemented, 100 Hz, address 0x68 or 0x69 | Timestamp/staleness logging under motion |
| PPG metrics | Implemented with validity and motion gates | Device-specific SpO2 calibration |
| IMU-NLMS | Implemented ahead of ECG DSP/AI | Prove QRS preservation and motion benefit |
| ECG DSP | Implemented | Replay plus live R-peak accuracy |
| INT8 AI cascade | Connected; Gate and SV independently MVP-profiled on xG26 | DWT timing in full firmware and revalidation after NLMS distribution shift |
| Clinical engine | Connected to every classified beat | Protocol-level rhythm validation |
| BLE | Bonded/encrypted contract and reliable event indications implemented; short Pi session passed | Reconnect, stale-key recovery, event integrity, and long soak |
| Pi gateway | Scan, connect, pair, 14 subscriptions, decode, and publish demonstrated | Backpressure, restart recovery, and long BlueZ soak |
| Backend/database | Implemented; no fake patient or clinical seed data | Deployment, auth, backup, retention work |
| Frontend | Patient onboarding, initialization, workstation, diagnostics, and settings compile | Browser and operator acceptance test |

## 3. End-to-End Data Flow

```text
ECG analog input
  -> LETIMER0 -> PRS2 -> IADC0 -> LDMA ping-pong
  -> timestamp reconstruction
  -> synchronized MPU6050 reference
  -> three-axis NLMS (or safe bypass)
  -> morphology and QRS DSP
  -> R-peak and 130-sample beat window
  -> Tier-0 suspicion heuristic
  -> deferred Gate CNN -> deferred SV CNN when required
  -> clinical engine and 4-second cleaned ECG event history
  -> BLE notifications/confirmed indications
  -> Raspberry Pi Bleak/BlueZ gateway
  -> FastAPI validation and SQLite persistence
  -> REST/WebSocket
  -> patient workstation and event review UI

MAX30102 RED/IR -> 4-second rolling PPG estimator -> validated pulse/SpO2
MPU6050 accel  -> motion gate for PPG and synchronized reference for NLMS
```

The super-loop services data in this order:

1. Drain pending IMU samples and update its timestamped ring.
2. Pass the latest IMU high-pass motion level to the PPG quality gate.
3. Drain MAX30102 FIFO data and update PPG metrics when a complete window exists.
4. Drain completed ECG DMA halves in completion-time order.
5. Run queued AI inference outside acquisition callbacks.
6. Publish due BLE values and advance at most one confirmed event indication.

No I2C transaction, AI inference, HTTP request, or BLE transfer is performed inside the ECG DMA interrupt.

## 4. Sensor Acquisition

### 4.1 ECG

The ECG front end is an analog signal on `iadcPosInputPadAna0`; it is not a digital MAX30001 SPI path.

| Item | Implementation |
| --- | --- |
| Trigger | LETIMER0 underflow, top value 130 on 32.768 kHz LFRCO |
| Physical rate | Approximately 250.137 Hz; algorithms use the 250 Hz contract |
| Peripheral path | LETIMER0 output -> asynchronous PRS channel 2 -> IADC0 single trigger |
| ADC | Single-ended, VDD reference, 12-bit value retained |
| Transfer | LDMA, 128-word circular buffer, two 64-sample linked halves |
| CPU cadence | DMA completion every approximately 256 ms; current validation build also retains the LETIMER bookkeeping IRQ |
| Timestamp | DMA completion timestamp minus 4 ms per earlier sample in that half |
| Overrun detection | Incremented if a DMA half completes again before its previous contents are drained |

The 250.137 Hz versus 250 Hz nominal difference is about 0.055%. It is acceptable for initial integration but must be measured and either calibrated or represented by a precise timebase before clinical timing claims.

### 4.2 MAX30102 PPG

| Item | Implementation |
| --- | --- |
| Bus | Shared I2C1 through `sl_i2cspm_mikroe`, SCL PC05, SDA PC07 |
| Interrupt | Active-low PC06 |
| Sensor rate | 100 Hz RED and IR |
| Current interrupt mode | PPG-ready plus FIFO-almost-full enabled |
| Firmware buffer | 1024 RED samples and 1024 IR samples |
| Service limit | Up to 8 FIFO samples per process pass |
| Recovery | Consecutive I2C failure counter and sensor recovery path |

The validation build intentionally keeps direct 100 Hz behavior. FIFO batching is deferred until the metric outputs are stable enough to prove that batching does not alter timestamps or overflow behavior.

### 4.3 MPU6050 IMU

| Item | Implementation |
| --- | --- |
| Bus | Shared I2C1, SCL PC05, SDA PC07 |
| Interrupt | DATA_RDY on PC00 |
| Rate | 100 Hz (`SMPLRT_DIV=9`) |
| Address | Detects and then consistently uses 0x68 or alternate 0x69 |
| History | 64 timestamped samples, about 640 ms |
| Consumers | PPG motion rejection, NLMS causal interpolation, diagnostics |

The driver no longer detects 0x69 and then accidentally continues using 0x68. All later reads and writes use the detected address.

## 5. PPG DSP and Metrics

The PPG estimator uses a 400-sample, 4-second rolling window and recomputes once per 100 new samples, or once per second.

### 5.1 DC and AC terms

For RED and IR independently:

```text
DC = mean(samples)
AC_RMS = sqrt(mean((sample - DC)^2))
```

Perfusion index is derived from the IR channel:

```text
PI = 100 * IR_AC_RMS / IR_DC
```

Firmware stores PI as percent multiplied by 100.

### 5.2 Pulse rate

The zero-mean IR window is compared with delayed copies of itself. Normalized autocorrelation is evaluated over lags corresponding to 40 through 200 bpm. The strongest positive correlation selects the period:

```text
pulse_bpm = round(60 * 100 Hz / best_lag)
```

### 5.3 Estimated SpO2

The ratio of ratios is:

```text
R = (RED_AC_RMS / RED_DC) / (IR_AC_RMS / IR_DC)
SpO2_est = -45.060 * R^2 + 30.354 * R + 94.845
```

The output is bounded to 70-100%, but a bounded value is not automatically valid. The equation is a common empirical approximation, not calibration evidence for TARANG.

### 5.4 Validity gates

A PPG result is published only when all of the following are true:

- RED/IR DC values indicate a finger and are below the saturation ceiling.
- IR AC/DC is at least 0.0005.
- Autocorrelation is at least 0.35.
- Computed quality is at least 35/100.
- Pulse lies between 40 and 200 bpm.
- Ratio `R` lies between 0.2 and 2.0.
- IMU high-pass motion does not exceed 120 mg.

If the window fails, the BLE value is zero as the current wire-level unavailable sentinel. The Pi converts zero to `null`; the dashboard does not display it as a measurement.

## 6. IMU-Referenced NLMS ECG Cleaning

### 6.1 Why it is positioned before DSP and AI

The same cleaned ECG must drive R-peak detection, beat extraction, AI, and event waveforms. Cleaning only the displayed waveform would hide artifacts from the operator while leaving the detector and AI exposed to them. Cleaning only the AI window would make heart rate and AI disagree.

### 6.2 Synchronization

Every ECG sample has a reconstructed timestamp. The IMU ring returns the causal sample at or before that time and supports interpolation between adjacent IMU samples. The reference is fresh only when it is no more than 50 ms old. Stale references force bypass.

### 6.3 Filter

The filter uses three acceleration references and 32 taps per axis. A slow EWMA removes gravity. For ECG input `d[n]`, delayed acceleration vectors `x[n]`, and adaptive weights `w[n]`:

```text
artifact_hat[n] = transpose(w[n]) * x[n]
e[n]            = d[n] - artifact_hat[n]
w[n+1]          = w[n] + mu * e[n] * x[n] / (epsilon + ||x[n]||^2)
```

Current parameters:

| Parameter | Value |
| --- | ---: |
| References | X, Y, Z acceleration |
| Taps | 32 per reference |
| Step size `mu` | 0.01 |
| Gravity EWMA alpha | 0.01 |
| Motion activation | 15 mg |
| Warmup | 250 ECG samples, with fresh IMU observations |
| Correction low-pass alpha | 0.23 |
| Max correction | +/-700 ADC counts |
| QRS adaptation guard | Freeze adaptation when ECG derivative is at least 350 counts/sample |

### 6.4 Safety behavior

NLMS returns raw centered ECG when it is disabled, warming up, missing a fresh IMU reference, below the motion threshold, or in safety cooldown. It clamps correction and weights. If residual power exceeds 1.5 times input power for 50 samples, it clears adaptive state, bypasses cleaning, and enters a 2-second cooldown.

Diagnostics include active state, bypass reason, motion magnitude, input/residual/correction energy, suppression estimate, saturation count, and safety-reset count.

NLMS is enabled and its result currently feeds DSP through `TARANG_NLMS_APPLY_TO_DSP=1`. This is an engineering-validation choice, not evidence that the output is clinically better. Validation must compare bypass and active paths.

## 7. ECG DSP

The streaming detector applies:

1. Centering and selected NLMS output.
2. Fourth-order 0.5-40 Hz morphology bandpass.
3. Rolling 30-second z-score normalization.
4. 5-15 Hz QRS bandpass.
5. Derivative, square, and 38-sample moving-window integration (about 152 ms).
6. Adaptive signal/noise peak thresholds and search-back.
7. Refractory handling, 29-sample detection-delay compensation, and +/-15-sample recentering.
8. A 130-sample morphology window, 65 samples on each side of the R peak.

The configured detector refractory is 200 ms, while an additional hard 300 ms duplicate guard is present in the current implementation. The DSP has an 8-second warmup, and early normalization quality remains conservative while the 30-second rolling window fills.

Event history stores the latest 1000 cleaned, normalized samples as signed
`z-score * 1000`. Classification requires post-R samples and ECG is drained in
64-sample DMA halves, so the context ends after the event R peak and may include
up to the remainder of the current DMA half. It also stores the latest 16
classified beat annotations.

## 8. AI Cascade

### 8.1 Inputs

Each model receives:

- One normalized 130-sample ECG morphology window.
- Four RR features: previous RR, mean of the latest five RR values, their standard deviation, and local heart rate.

RR features are normalized using the generated training scaler. ECG and RR tensors are quantized using each TFLite tensor's scale and zero point.

### 8.2 Execution

Tier 0 uses timing and morphology heuristics to decide whether a beat is suspicious. Unsuspicious beats are classified as normal without running either CNN.

For suspicious beats:

1. Gate INT8 CNN runs. If `P(abnormal) <= 0.25`, the beat becomes N.
2. If the Gate passes, the SV INT8 CNN runs.
3. If `P(V) > 0.60`, the beat becomes V/PVC.
4. Else if `P(S) > 0.35`, the beat becomes S/PAC.
5. Otherwise it becomes N.

Detected beats enter a bounded four-entry deferred queue. DMA draining remains short; the super-loop runs model inference after current sensor work. A queue overflow is counted and must remain zero during validation.

The 30-beat suspicious-rate circuit breaker is monitor-only in this build (`TARANG_ENABLE_AI_CIRCUIT_BREAKER=0`). Automatically disabling AI at more than 20% suspicious beats could suppress genuine high abnormal burden. It may be re-enabled only after overload and clinical behavior are validated.

### 8.3 Measured Isolated MVP Performance

Simplicity Machine Learning profiled the canonical Gate and SV flatbuffers on a
physical BRD2608A (`EFR32MG26B510F3200IM68`) at 78 MHz with HW Accelerated
(MVP) kernels. The application target is the same xG26 CPU/MVP architecture in
the IM48 package.

| Metric | Gate | SV |
| --- | ---: | ---: |
| Inference time | **12.634 ms** | **10.010 ms** |
| Throughput | 79.15/s | 99.90/s |
| CPU cycles | 463,653 | 385,573 |
| MVP cycles | 558,363 | 434,004 |
| MVP stalls | 226,186 | 165,618 |
| CPU utilization | 45.4% | 47.0% |
| MVP layers | 11 | 12 |
| MACs | 707,776 | 539,360 |

The isolated worst-case serial cascade is `22.644 ms`. The dominant CPU
fallback is `MEAN` (`3.570 ms` Gate, `2.686 ms` SV); convolution and dense
compute is correctly accelerated on MVP. These measurements validate model
execution speed, not complete firmware latency. The full sensor/NLMS/BLE build
still requires DWT cycle timing with p50/p95/p99 reporting.

## 9. Clinical Engine

Every classified beat updates counts, RR history, HRV, patterns, and rhythm flags.

| Output | Method |
| --- | --- |
| Heart rate | Mean of up to the latest 8 RR intervals; unavailable until enough valid timing exists |
| PVC/PAC burden | Cumulative class count divided by total classified beats |
| SDNN | Standard deviation of the 30-RR rolling window |
| RMSSD | Root mean square of successive RR differences |
| pRR50 | Percent of successive RR differences greater than 50 ms |
| AF suspicion | CoV >12%, pRR50 >10%, RMSSD >30 ms, sustained for 30 beats, with V-bigeminy exclusion |
| Bigeminy/trigeminy | Alternating pattern checks over recent beat classes |
| V-run | At least 3 consecutive V beats |
| VT suspected | At least 5 consecutive V beats and HR >100 bpm |
| SVT-run | At least 3 consecutive S beats |

Rhythm status is a bitfield, not an enum:

| Bit | Meaning |
| ---: | --- |
| `0x01` | AF suspected |
| `0x02` | Sinus tachycardia |
| `0x04` | Sinus bradycardia |
| `0x08` | Bigeminy |
| `0x10` | Trigeminy |
| `0x20` | V-run |
| `0x40` | SVT-run |
| `0x80` | VT suspected; critical UI priority |

These are algorithmic flags and require clinician/reference review. They are not diagnoses.

## 10. BLE Contract

The EFR32 is the peripheral/GATT server. The Pi is the central/GATT client.
Bonding is enabled with persistent storage. The current Simplicity Studio GATT
configuration marks the custom vitals, analytics, and event data as bonded and
encrypted; standard discovery/device-information attributes remain readable.
No generated `autogen` or configuration file was hand-edited.

### 10.1 Services and values

| Service | Characteristic | UUID suffix | Payload | Cadence/transport |
| --- | --- | --- | --- | --- |
| Vitals `544e...4c75` | HR | `...d66a` | little-endian uint16 bpm; 0 unavailable | Every 2.5 s, notify |
| Vitals | SpO2 | `...d66b` | uint8 percent; 0 unavailable | Every 2.5 s, notify |
| Vitals | timestamp | `...d66c` | uint32 device ms | GATT value updated with vitals |
| Analytics `655f...4c75` | PVC burden | `...e77b` | uint8 percent | Every 5 min, notify |
| Analytics | PAC burden | `...e77c` | uint8 percent | Every 5 min, notify |
| Analytics | SDNN | `...e77d` | uint16 ms | Every 5 min, notify |
| Analytics | RMSSD | `...e77e` | uint16 ms | Every 5 min, notify |
| Analytics | pRR50 | `...e77f` | uint8 percent | Every 5 min, notify |
| Analytics | AI duty | `...e780` | uint8, percent x10 | Every 5 min, notify |
| Analytics | EM2 sleep | `...e781` | uint8 percent; currently 0/unknown | Every 5 min, notify |
| Events `7660...4c75` | rhythm | `...f88a` | uint8 rhythm bitfield | On event, notify |
| Events | metadata | `...f88b` | `<HBBI`: event id, flags, confidence, ms | On event, notify |
| Events | ECG chunk | `...f88c` | `<HH` sequence/total then int16 samples | On event, confirmed indication |
| Events | control | `...f88d` | reserved command byte; generated write/notify properties | Current gateway neither writes nor subscribes; firmware emits no control notifications |
| Events | annotations | `...f88e` | repeated `<HBB>` offset ms/class/confidence | On event, confirmed indication |
| Events | pattern ticker | `...f88f` | `<HI` pattern/timestamp | On event, notify |

The seven analytics characteristics are separate generated GATT values. Firmware no longer writes a legacy 9-byte packed structure into the 1-byte PVC characteristic.

### 10.2 Reliable ECG event transfer

The firmware derives samples per chunk from the negotiated MTU:

```text
samples_per_chunk = floor((MTU - 7) / 2), capped at 110
```

With default ATT MTU 23, this is 8 samples and 125 chunks for 1000 samples. Only one indication is in flight. The next ECG or annotation fragment is sent after GATT confirmation. A 5-second confirmation timeout aborts the transfer instead of leaving it stuck forever. Disconnect also clears transfer state.

The Pi accepts up to 160 chunks, validates every header, reassembles by sequence number, then converts int16 `z-score * 1000` back to floating normalized ECG.

## 11. Raspberry Pi Pairing and Gateway

BlueZ on this Pi requires the working order below:

1. Start discovery and keep it active.
2. Resolve the actual `TARANG-2614` BlueZ device object.
3. Connect to that object without asking Bleak to pair implicitly.
4. Pair on the active connection.
5. Stop discovery only after pairing succeeds.
6. Verify all three Tarang services and start the 14 subscriptions.

Stopping discovery before first connect caused BlueZ to delete the temporary device object and report `Device not available`. Repeated `pair <MAC>` without a stable connected object produced `ConnectionAttemptFailed` or `le-connection-abort-by-local`.

The production gateway and `ble_test.py` implement this order. Do not run another phone connection at the same time.

For a genuine stale-key mismatch, remove the Pi-side bond, clear the EFR32 bond through the controlled firmware/flash flow, reboot the wearable, and pair once. Repeatedly deleting only one peer recreates the mismatch. See `BLE_STALE_BOND_KEY_ISSUE.md`.

## 12. Pi to Backend to Dashboard

The gateway:

- Waits for backend health before scanning.
- Registers/identifies the configured device.
- Resolves the active monitoring session or uses `TARANG_SESSION_ID` when pinned.
- Converts BLE zero vitals to JSON `null`.
- Coalesces separate HR/SpO2 and seven analytics notifications.
- Reassembles ECG and annotation indication fragments.
- Sends bounded, retried HTTP deliveries to FastAPI.

FastAPI validates payloads, writes SQLite with WAL, foreign keys, and busy timeout enabled, and broadcasts session telemetry over WebSocket. A clean database starts with no fake patient and no fake clinical measurements.

The frontend flow is:

1. Patient worklist.
2. Add/select patient.
3. Select an available device.
4. Create monitoring session.
5. Initialization screen waits for backend, BLE state, and the first measured vitals packet.
6. Workstation shows real current values, event timeline, and normalized four-second event waveform.
7. Diagnostics and settings remain available through application navigation.
8. Stop session releases the device.

The initialization animation is a commissioning trace, not a fake live ECG. The live canvas remains in an armed/idle state until a real event waveform arrives.

## 13. API and Hospital Integration Boundary

Internal APIs support patients, devices, monitoring sessions, live telemetry, events, actions, diagnostics, health, and settings. The gateway writes through ingestion endpoints; the UI reads through session-scoped endpoints and WebSocket.

External systems should use the versioned boundary:

- `GET /api/v1/patients?mrn=`
- `PUT /api/v1/patients/{mrn}` for idempotent CRM/HIS upsert
- `GET /api/v1/devices?status=`
- `GET /api/v1/observations?patientId=&mrn=&sessionId=&from=&to=&limit=`
- `GET /api/v1/sessions/{session_id}/summary`
- `/openapi.json` for machine-readable integration

The response shapes are FHIR-inspired, not certified FHIR R4. A real hospital deployment needs an adapter for exact FHIR R4/HL7 v2/vendor requirements plus OAuth2/OIDC, tenant/site scoping, audit logging, consent, retention, encryption at rest, backups, key management, and a HIPAA-appropriate deployment agreement. SQLite and wildcard CORS are hackathon defaults, not production controls.

## 14. Startup and Deployment

### 14.1 Firmware

Build:

```powershell
cd projects/tarang-firmware/Integration
cmake --build cmake_gcc/build --target Integration -j 4
```

Generate GATT/component changes through Simplicity Studio, regenerate, rebuild, then flash the generated `Integration.hex` with Simplicity Commander or the Studio programmer. Do not hand-edit `autogen` or generated configuration files.

Expected boot evidence includes sensor detection, AI initialization, BLE security/bonding setup, device name `TARANG-2614`, and connectable advertising.

### 14.2 Pi setup and run

```bash
cd ~/icc-26-tarang/projects/tarang-rpi
chmod +x setup_rpi.sh start_all.sh update_rpi.sh
./setup_rpi.sh
```

Review `tarang.env`, then:

```bash
./start_all.sh
```

The launcher starts backend, verifies health, starts the production frontend, and starts the paired BLE gateway. Dashboard is `http://<pi-address>:3000`; OpenAPI is `http://<pi-address>:8000/docs`.

For isolated BLE validation:

```bash
cd ~/icc-26-tarang/projects/tarang-rpi
source dashboard/backend/venv/bin/activate
python ble_test.py 64:02:8F:64:26:14
```

## 15. Validation Plan for 10-20 Volunteers

This phase must be treated as engineering validation, not diagnosis. Obtain informed consent, avoid enrollment where the prototype creates unnecessary risk, de-identify exports, and have a clinician/research lead define the protocol.

### 15.1 Reference equipment

- Reference ECG or validated ECG recorder with a common time marker.
- Reference pulse oximeter with recorded SpO2 and pulse.
- A repeatable motion protocol and synchronized event log.
- Raw TARANG UART/diagnostic capture plus backend export.

### 15.2 Per-participant protocol

1. Sensor-off baseline to verify unavailable states.
2. Five minutes seated and still.
3. Controlled breathing and posture changes.
4. Repeated mild arm/wrist/torso movement defined in advance.
5. Electrode disturbance tests only within the approved safe protocol.
6. Disconnect/reconnect and Pi restart test.
7. Reference comparison at agreed timestamps.

Do not deliberately provoke dangerous arrhythmia or hypoxia.

### 15.3 Acceptance metrics

| Area | Required measurement |
| --- | --- |
| ECG DAQ | Zero DMA overrun; monotonic timestamps; expected sample count |
| IMU alignment | Fresh-reference percentage and timestamp error distribution |
| NLMS | R-peak timing delta, QRS amplitude ratio, input/residual motion-band energy, bypass/reset count |
| QRS detector | Sensitivity and positive predictive value within the agreed R-peak tolerance |
| AI | Confusion matrix, per-class sensitivity/specificity/precision, bypass versus NLMS-active comparison |
| PPG pulse | MAE versus reference pulse during accepted windows |
| SpO2 | Bias, limits of agreement, rejected-window rate, and subject-level failure analysis |
| BLE | Complete vitals delivery, exactly 1000 event samples, annotation completeness, reconnect time |
| Backend/UI | Correct patient/session ownership, no stale values, no fake fallback, complete event review |

NLMS passes only if it reduces motion artifact without materially shifting R-peak timing, attenuating QRS morphology beyond the agreed tolerance, or worsening AI results. If it fails, set `TARANG_NLMS_APPLY_TO_DSP=0` and retain the synchronized diagnostics for another iteration.

SpO2 must remain labeled estimated/research-only until device-specific calibration and validation are complete. A polynomial output that looks reasonable is not sufficient.

## 16. Why Power Optimization Is Not Applied Yet

The validation rates remain ECG 250 Hz, PPG 100 Hz, and IMU 100 Hz. IMU 20 Hz removes motion content above 10 Hz and weakens the NLMS reference. PPG FIFO batching changes interrupt, latency, pointer, and overflow behavior while the metric estimator is still being validated. Removing ECG wakeups changes time bookkeeping during the same pass that validates synchronization.

Power work is deferred, not rejected. After golden traces exist, optimize one change at a time and prove equivalent signal output. The full decision is in `WHY_POWER_OPTIMIZATION_IS_DEFERRED.md`.

## 17. Known Limitations and Next Gates

1. SpO2 is an uncalibrated estimate for this mechanical/optical design.
2. NLMS parameters are safety-bounded but not yet human-validated.
3. AI was trained for a preprocessing distribution that may shift with NLMS.
4. BLE transports event ECG, not a continuous raw ECG stream.
5. The event waveform is the latest four-second ring when transfer starts. It includes the post-R samples needed for classification and may end up to one DMA half later; it is not a fixed one-second-before/three-seconds-after capture.
6. There is no generated device-health GATT characteristic. Backend health is therefore connection/telemetry based; adding one must be done in Simplicity Studio.
7. EM2 percentage is reported as unknown/zero until measured residency exists.
8. Battery and peripheral RSSI are not supplied by the current firmware contract.
9. The ECG timebase uses 250 Hz math over a roughly 250.137 Hz hardware trigger.
10. A short Pi hardware-in-loop run successfully paired, verified GATT, enabled all 14 subscriptions, and posted vitals, analytics, diagnostics, and events. Long soak, forced reconnect, event-snippet integrity, and operator workflow tests remain pending.
11. SQLite, wildcard CORS, and no user authentication are hackathon choices, not production/HIPAA controls.

## 18. Verified in This Integration Pass

- EFR32 CMake/Ninja target builds successfully with ECG, PPG, IMU, NLMS, AI, and BLE enabled.
- Python gateway/protocol files compile.
- All 14 backend and BLE protocol tests pass.
- Next.js production build, lint, and TypeScript validation pass.
- Physical PPG/IMU acquisition and phone BLE connection were reported working by the operator before this final build.
- Raspberry Pi BlueZ/Bleak connected and verified GATT with all 14 Mode A subscriptions active.
- FastAPI returned success for live `/api/vitals`, `/api/analytics`, `/api/events`, and `/api/diagnostics/update` ingestion.
- Isolated xG26 MVP profiles measured Gate at `12.634 ms` and SV at `10.010 ms`.

The remaining truth tests are integrated timing, energy capture, long-duration reliability, reference-instrument signal validation, and controlled human-subject validation. This is ready for a supervised hackathon demonstration, not clinical or unattended production deployment.
