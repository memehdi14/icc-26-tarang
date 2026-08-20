# TARANG Flow and NLMS Status

Validated in source/build: 2026-08-19

## Current status

The formerly missing end-to-end pieces are now implemented:

- MAX30102 RED/IR data produces rolling pulse, estimated SpO2, perfusion, quality, finger-presence, and motion-validity results. Invalid windows publish unavailable data instead of fake `98%`.
- MPU6050 X/Y/Z acceleration is timestamped at 100 Hz and causally interpolated onto the ECG timeline.
- A three-axis, 32-tap NLMS canceller runs before ECG DSP and AI, with warmup, motion/staleness bypass, QRS adaptation guard, correction clamps, degradation detection, reset, and cooldown.
- ECG DMA halves receive completion timestamps and are drained chronologically. AI inference is deferred outside DMA draining.
- Clinical events carry the real latest four-second cleaned ECG context and real beat annotations.
- ECG and annotation indications are MTU-aware, confirmation-driven, fragmented, and timeout-protected.
- BLE vitals and analytics match the generated GATT characteristic sizes. No fake HR, SpO2, or power measurement is sent.
- The Pi gateway follows active discovery -> connect -> pair -> stop discovery, subscribes to the 14 required values, and reassembles fragmented events.
- A clean backend database contains no fake patient or clinical seed values. The dashboard waits for real telemetry and does not draw a synthetic live ECG.

## Active validation configuration

| Signal/path | Setting |
| --- | --- |
| ECG | 250 Hz nominal |
| PPG | 100 Hz |
| IMU | 100 Hz |
| NLMS compiled | Yes |
| NLMS feeds DSP/AI | Yes (`TARANG_NLMS_APPLY_TO_DSP=1`) |
| Suspicious-rate AI breaker | Monitor-only (`TARANG_ENABLE_AI_CIRCUIT_BREAKER=0`) |
| Raw ECG UART stream | Off |
| Event ECG | 1000 normalized int16 samples, latest four-second context when transfer starts |

## What is not yet proven

Implementation and compilation are not clinical validation. The remaining gates are:

1. Run this exact firmware on the EFR32 and confirm zero ECG DMA overruns.
2. Complete the Raspberry Pi pair/subscription/event-transfer test.
3. Compare NLMS bypass versus active output for QRS timing, amplitude, and artifact energy.
4. Revalidate AI after NLMS because preprocessing can shift model inputs.
5. Calibrate and compare SpO2 against a reference oximeter.
6. Complete the consented 10-20 participant protocol.

The authoritative design, equations, BLE contract, deployment flow, limitations, and validation plan are documented in [TARANG_END_TO_END_ARCHITECTURE.md](TARANG_END_TO_END_ARCHITECTURE.md).

The reason power-rate and FIFO optimizations are intentionally deferred is documented in [WHY_POWER_OPTIMIZATION_IS_DEFERRED.md](WHY_POWER_OPTIMIZATION_IS_DEFERRED.md).
