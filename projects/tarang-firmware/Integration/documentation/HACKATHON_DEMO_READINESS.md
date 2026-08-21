# TARANG Hackathon Demo Readiness Gate

**Scope:** current EFR32MG26 firmware, BLE GATT profile, Raspberry Pi gateway,
FastAPI/SQLite backend, and Next.js workstation.

**Goal:** a repeatable, supervised, judge-facing demo. This document does not
claim medical-device readiness, clinical accuracy, HIPAA compliance, or
unattended operation.

## Current Decision

**Do not call the system a 10/10 hackathon demo until the P0 items below are
closed and the final acceptance run passes.** The code compiles and the local
test suite passes, but the live RPi BLE link has repeatedly connected,
subscribed, then dropped after a few seconds.

## P0 - Must Fix Before Demo

### 1. BLE connection loop

**Observed behavior**

1. The RPi finds `TARANG-2614`.
2. GATT resolves and all 14 subscriptions succeed.
3. The link closes roughly three to four seconds later.
4. The gateway reconnects and repeats.

This still occurs with `TARANG_BLE_PAIR=false`; it is not solved by disabling
re-pairing and is not a battery-only fault.

**Likely pressure points to isolate**

- The firmware requests MTU, PHY, and connection-parameter updates directly
  in `sl_bt_evt_connection_opened` while BlueZ is resolving services and
  writing 14 CCCDs.
- The RPi subscribes to all 14 characteristics in one connection setup phase.
- The deployed binary may not match current source: observed immediate
  analytics updates are inconsistent with the checked-in source, which sends
  normal analytics on a five-minute cadence.

**Required evidence before changing more code**

- Firmware VCOM line: `[BLE] Connection closed: reason=0x....`
- Pi HCI trace from `sudo btmon -i hci0`, including `Disconnect Complete`.
- Firmware boot lines showing the exact current connection settings, warmup,
  and GATT database version.

**Required fix validation**

- Run a minimal baseline: bond reuse, no active pairing request, then connect
  with only HR and SpO2 subscriptions.
- Add subscriptions one at a time until the failing characteristic or link
  procedure is identified.
- Do not advertise the dashboard as live until the RPi maintains a continuous
  connection for at least 30 minutes.
- Test the same image on both USB and battery after USB is stable.

### 2. Source-to-device identity must be proved

The checked-in firmware delays vitals after a 3.5-second warmup and analytics
for five minutes. The observed RPi log receives analytics almost immediately.
That discrepancy means the flashed `.s37` may be stale, or a different build
configuration is being flashed.

**Required fix**

- Print a firmware build ID, Git commit, build timestamp, GATT revision, and
  enabled feature flags at boot.
- Confirm that exact ID in VCOM after every flash.
- Record the commit and `.s37` checksum in the demo run sheet.

### 3. Do not show simulated or unavailable data as live

The workstation currently has presentation fallbacks that can look like live
telemetry:

- The idle ECG panel is an animated flat line, not raw continuous ECG.
- Device diagnostics shows fixed fallback identity values.
- ECG and IMU diagnostic badges can render as healthy without a live health
  packet.
- The commissioning animation falls back to `75 BPM` if no HR is available.
- Battery state is inferred from absence of telemetry, not measured.

**Required fix**

- Show `Awaiting telemetry`, `Unavailable`, or `Event-only waveform` instead
  of normal/connected values without data.
- Add a clear `DEMO / SIMULATED` badge for the simulation endpoint and keep it
  out of the normal operator path.
- Do not call the flat idle canvas a continuous ECG trace.

### 4. Sensor health has no end-to-end transport

Firmware can build `tarang_health_packet_t`, but GATT has no device-health
characteristic and the gateway has no health subscription. Therefore ECG SQI,
lead-off, PPG finger presence, IMU health, I2C errors, ECG overruns, real RSSI,
and battery cannot reach the backend/UI.

**Required fix for a credible demo**

- Either add a Studio-managed encrypted/bonded Device Health GATT
  characteristic and subscribe to it at 1 Hz, or remove those fields from the
  UI for this demo.
- Never map device health onto an existing analytics UUID.
- Add the characteristic through Simplicity Studio, regenerate code, then
  update firmware protocol, gateway decoder, backend model, and UI together.

### 5. Event integrity is not fail-closed

The gateway can post a clinical event when the event timeout expires even if
the indicated ECG chunks have not completed. That leaves an event record with
no waveform; the UI then receives a 404 when it requests the snippet.

**Required fix**

- Persist an event as `pending_waveform` until chunk reassembly completes.
- Mark failed/expired transfer explicitly with reason and chunk counts.
- Never present an event as a captured waveform when the waveform is absent.

## P1 - Must Validate Before Judge Run

### Acquisition and timing

- ECG: verify 250 Hz over a timed five-minute capture, no LDMA overrun, no
  missed half-buffer, and plausible ADC amplitude with electrodes attached.
- PPG: verify MAX30102 part ID, FIFO overflow count, 100 Hz effective sample
  rate, finger-contact transition, and valid/invalid SpO2 behavior.
- IMU: verify 100 Hz rate, interrupt count tracks samples, acceleration/gyro
  axes respond to movement, and no repeated I2C recovery.
- Correlate all three streams using timestamps in a volunteer capture.

### DSP, NLMS, and AI

- ECG DSP must produce stable R peaks after its eight-second initialization.
- Verify NLMS bypass modes: warmup, no-motion, IMU stale, active motion, and
  safety cooldown. Preserve raw and cleaned ECG for each test.
- Verify that AI counters advance on actual detected beats. A VCOM line such
  as `tier0_evals=0` means the full detection/AI path was not exercised.
- Validate gate and SV inference latency from the actual board, not desktop
  replay alone.
- Validate event rate limiting and circuit-breaker behavior during noise and
  deliberate motion; a circuit breaker bypass classifies as normal and must
  be visible in logs.

### Graph-Based Evidence Required

Do not use VCOM counters as the only evidence for sensor/DSP claims. Capture
one short, pseudonymous validation CSV per condition using the compact VCOM
stream and generate plots with
`projects/tarang-dsp/integration_validation/plot_tarang.py`.

#### NLMS cancellation proof

Collect three 60-second recordings with the same electrode placement:

1. **Still baseline:** volunteer remains still; NLMS should report
   `no_motion` or inactive. Raw and cleaned ECG should be nearly identical.
2. **Controlled motion:** introduce repeatable arm/torso movement while
   preserving electrodes. Plot ECG raw, ECG cleaned, IMU acceleration/gyro,
   and NLMS state/suppression on a common time axis. Motion-correlated ECG
   artifact should reduce in the cleaned trace without flattening QRS peaks.
3. **Recovery:** stop motion. The cleaned trace should settle without a long
   baseline shift, oscillation, repeated safety reset, or lost R peaks.

**Pass criteria**

- The graph shows an identifiable movement interval and correlated IMU rise.
- The cleaned signal has lower motion-correlated artifact than raw ECG during
  that interval.
- QRS morphology remains visible; cancellation must not merely reduce all
  amplitude.
- The plot/report records NLMS bypass reason, motion magnitude, suppression,
  active sample count, and safety reset count.
- Do not claim a numeric noise-reduction percentage unless the plot computes
  the metric from a declared method and the same metric is shown beside the
  raw/cleaned trace.

#### ECG acquisition and DSP proof

For the still-baseline recording, graph raw ADC, cleaned ADC, morphology
bandpass, QRS-band signal, moving-window integrator, threshold, and detected
R peaks. The report must show the sample rate, capture duration, DMA overrun
count, and number of accepted/rejected beats.

**Pass criteria**

- 250 Hz timing is sustained for the captured duration.
- No ECG DMA overrun occurs.
- R peaks align to visible QRS complexes after warmup.
- No chart uses a synthetic waveform or an event simulation payload.

#### PPG proof

Graph Red and IR channels with a finger absent, finger present/still, and
finger present/moving. Include finger-present state, PPG SQI, motion rejection,
estimated pulse rate, and SpO2 estimate.

**Pass criteria**

- Finger absence produces unavailable/invalid PPG rather than a plausible
  SpO2 value.
- Finger contact produces a visible pulsatile Red/IR waveform.
- Motion rejection activates during movement and prevents the display from
  presenting the affected optical estimate as valid.

#### IMU proof

Graph all three accelerometer axes and all three gyro axes for still, gentle
movement, and vigorous movement. Include sample count, interrupt count, and
motion magnitude.

**Pass criteria**

- Sensor axes respond in the expected direction during each controlled motion.
- Sample and interrupt counters stay close over the recording.
- The IMU timestamp sequence supports the alignment used by NLMS.

#### AI and anomaly-event proof

For each controlled or replayed abnormal case, show the 130-sample model
window, detected R peak, RR features, Tier-0 reason, gate probability, SV
probabilities, final beat label, confidence, rhythm flags, and resulting
four-second event snippet.

**Pass criteria**

- The graph and VCOM log agree on timestamp and beat/event identity.
- The dashboard event waveform is the same event sent over BLE, not the
  `/api/events/simulate` waveform.
- Each demo claim identifies whether it was a live volunteer recording,
  hardware replay, or offline dataset replay.

### PPG interpretation limitation

The current PPG implementation uses a simple four-second peak count and
ratio-of-ratios estimate (`SpO2 = 110 - 25R`, clamped 70-100). It is suitable
for a proof-of-flow display only. Do not describe it as calibrated medical
pulse oximetry.

## P1 - Dashboard and Backend Integrity

### Live update contract

- HR and SpO2 are the only normal values designed to update every ~2.5 s.
- Analytics are intentionally five-minute rollups; the UI must label them
  that way and show timestamp/age.
- Raw continuous ECG/PPG/IMU do not travel over BLE to the UI today.
- Anomaly ECG is a four-second event snapshot sent through indications.
- Confirm WebSocket receives `vitals_sample`, `analytics_5min`,
  `clinical_event`, and `diagnostics` while the browser is open.
- Confirm REST bootstrap data and subsequent WebSocket data use the same
  session and device ID.

### Patient/session safety

- Start a session only after a patient and device are explicitly selected.
- Reject telemetry whose device does not match the active session.
- Close the prior active session before assigning its device to a new patient.
- Confirm each event, vital, and analytics row has the intended `session_id`.
- Include an unmistakable patient/device/session header on all judge screens.

### UI actions

- Patient create, selection, device assignment, start session, stop session,
  settings save, event waveform selection, and PDF export need one manual
  click-through each.
- `Page duty physician` currently queues an audit row only. Either integrate a
  real notification channel for the demo or label it `Record escalation`.
- Settings currently do not configure firmware thresholds, BLE timing, or
  onboard alarm behavior. Do not imply they do.

### Backend reliability

- SQLite is acceptable for a supervised local demo only; make a timestamped
  backup before the judging session.
- Verify backend restart behavior preserves sessions and historical events.
- Bound gateway queue drops and surface any drop count in the UI.
- Restore a hard failure when required GATT subscriptions cannot activate;
  warning-only operation can make the dashboard appear live while missing
  clinical data.

## P2 - Demo Quality and Power

### VCOM and validation build separation

- `TARANG_ENABLE_VALIDATION_STREAM` is enabled by default and emits compact
  ECG, PPG, and IMU validation output at 115200 baud.
- VCOM reception currently restricts energy mode.
- Create two explicit images: `validation` with VCOM stream enabled and
  `demo` with validation stream disabled. Do not silently use a capture build
  for a battery demonstration.
- Manage VCOM component settings only through Simplicity Studio; do not hand
  edit generated configuration files.

### Diagnostic honesty

- AI duty cycle is estimated from firmware timing and EM2 sleep is currently
  reported as zero, not measured power residency.
- Battery percentage and RSSI require actual measurement/transport before
  they may be shown as device telemetry.
- Avoid terms such as `clinical grade`, `continuous ECG`, `medical SpO2`, or
  `physician paged` unless the corresponding verified function exists.

## Security Boundary for a Hackathon

Keep the demo on an isolated trusted LAN. The API currently has no application
authentication/authorization and permissive CORS. It is not appropriate for
real patient data, a public network, or HIPAA claims.

Use pseudonymous volunteers, avoid names/MRNs in screenshots, and remove the
simulation endpoint from the visible demo flow unless clearly labelled.

## Final Acceptance Checklist

All boxes must pass in the same deployed build:

- [ ] Firmware build ID in VCOM matches the commit being demoed.
- [ ] Pi bond is already established; reconnect does not call pairing.
- [ ] `btmon` and VCOM record no disconnect for 30 minutes.
- [ ] All expected GATT subscriptions are active; no warning-only failures.
- [ ] HR and valid SpO2 change in the dashboard within five seconds.
- [ ] ECG/PPG/IMU VCOM counters advance at expected rates for five minutes.
- [ ] ECG DMA overrun count stays zero.
- [ ] PPG finger removed produces unavailable/standby rather than a plausible
      stale SpO2.
- [ ] IMU movement changes motion state and NLMS behavior is recorded.
- [ ] Raw-vs-cleaned ECG and aligned IMU graphs demonstrate NLMS behavior for
      still, controlled-motion, and recovery segments.
- [ ] ECG DSP graph demonstrates R-peak placement, threshold behavior, and no
      DMA overrun for the selected volunteer capture.
- [ ] PPG Red/IR graph demonstrates finger absence, valid contact, and motion
      rejection without presenting an invalid SpO2 as live.
- [ ] AI/event graph identifies the exact source of every displayed anomaly
      and ties the source event to the BLE/dashboard waveform.
- [ ] At least one controlled event produces a complete 4-second waveform,
      annotations, database record, UI display, and PDF export.
- [ ] Patient/session/device linkage is correct before and after restart.
- [ ] No visible UI field presents fallback, simulated, stale, or unavailable
      data as a verified live measurement.
- [ ] USB and battery runs both complete the same ten-minute stable demo.

## Definition of a 10/10 Hackathon Demo

A 10/10 demo is not a clinical certification. It is a stable, honest, and
repeatable end-to-end demonstration: real sensors acquire data, the wearable
remains connected to the Pi, the dashboard updates from the actual device,
anomaly evidence has a complete waveform, every visible operational claim is
backed by telemetry, and the team can explain the remaining clinical
validation work plainly.
