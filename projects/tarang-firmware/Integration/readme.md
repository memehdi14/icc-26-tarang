# TARANG Integrated Multi-Sensor Firmware

This directory contains the functional-validation firmware for **Project TARANG** (ECG + PPG + IMU + NLMS + DSP + Tier 1/2 TFLite Micro CNNs + Clinical Event Engine + BLE) running on the **Silicon Labs EFR32MG26 (BRD2709A / BRD2608A)**.

The authoritative pipeline, wire contract, known limitations, deployment flow,
and validation gates are in
**[TARANG_END_TO_END_ARCHITECTURE.md](TARANG_END_TO_END_ARCHITECTURE.md)**.
This is research firmware and is not a certified diagnostic medical device.

---

## 1. Hardware Pinout & Wiring Specification

All 3 biometric and motion sensors connect to the EFR32MG26 via dedicated analog inputs, a shared I2C bus (`sl_i2cspm_mikroe` on `I2C1`), and hardware GPIO external interrupts.

| Component | Signal | EFR32MG26 Pin / Pad | Mode / Logic | Details & Notes |
| :--- | :--- | :--- | :--- | :--- |
| **ECG Front-End** | Analog Signal | `AIN0` (`iadcPosInputPadAna0`) | Single-Ended Analog | Dedicated positive analog input pad to IADC0 |
| | GND / Ref | `GND` (`iadcNegInputGnd`) | Ground Reference | Negative IADC input tied to GND (single-ended mode) |
| **MAX30102 (PPG)** | I2C SCL | `PC05` | Shared I2C Clock | `sl_i2cspm_mikroe` (`I2C1`) at 100 kHz Standard Mode |
| | I2C SDA | `PC07` | Shared I2C Data | `sl_i2cspm_mikroe` (`I2C1`) at 100 kHz Standard Mode |
| | INT (Interrupt) | `PC06` | Active-LOW (`Falling Edge`) | Open-drain interrupt; internal pull-up enabled via `gpioModeInputPull` |
| | VCC / GND | `3V3` / `GND` | Power Supply | 3.3V DC Power and Ground |
| **MPU6050 (IMU)** | I2C SCL | `PC05` | Shared I2C Clock | Shared `sl_i2cspm_mikroe` bus with MAX30102 |
| | I2C SDA | `PC07` | Shared I2C Data | Shared `sl_i2cspm_mikroe` bus with MAX30102 |
| | INT (Interrupt) | `PC00` | Active-HIGH (`Rising Edge`) | DATA_RDY interrupt line triggering at 100 Hz |
| | AD0 | `GND` | I2C Address Select | Sets 7-bit I2C Address to `0x68` (driver also detects alternate address `0x69`) |
| | VCC / GND | `3V3` / `GND` | Power Supply | 3.3V DC Power and Ground |
| **VCOM Serial UART**| TX (MCU Out) | `PB02` | EUSART0 TX | Connected to J-Link CDC UART virtual COM port |
| | RX (MCU In) | `PB03` | EUSART0 RX | Connected to J-Link CDC UART virtual COM port |

> [!NOTE]
> **Validation power policy**: ECG remains at 250 Hz nominal, PPG at 100 Hz,
> and IMU at 100 Hz. The application currently uses a 10 ms wake timer and
> does not claim measured EM2 residency. See
> [WHY_POWER_OPTIMIZATION_IS_DEFERRED.md](WHY_POWER_OPTIMIZATION_IS_DEFERRED.md).

---

## 2. 4-Tier Arrhythmia Detection Architecture

```
                       [ RAW SAMPLES: 250 Hz ECG ]
                                    │
                                    ▼
       ┌─────────────────────────────────────────────────────────┐
       │ Tier 0: Streaming DSP & Pan-Tompkins Peak Detector      │
       │  - 0.5–40 Hz Morphology BP + 5–15 Hz QRS BP             │
       │  - 300 ms Hard Refractory (blocks T-wave double counts) │
       │  - 30-beat suspicious-rate monitor                      │
       └────────────────────────────┬────────────────────────────┘
                                    │ Beat Emitted (~1 Hz)
                       Is beat suspicious?
                       ┌────────────┴────────────┐
                  NO   │                         │  YES
                       ▼                         ▼
             [ Classify as Normal N ]  ┌───────────────────────────┐
                                       │ Tier 1: Gate CNN (INT8)   │
                                       │  - 130 ECG + 4 RR inputs  │
                                       │  - Arena: 16 KB           │
                                       └─────────────┬─────────────┘
                                                     │ P(abnormal) > 0.25
                                        ┌────────────┴────────────┐
                                   NO   │                         │  YES
                                        ▼                         ▼
                              [ Classify as N ]         ┌──────────────────┐
                                                        │ Tier 2: SV Head  │
                                                        │  - 2 Out Tensors │
                                                        │    P(V) & P(S)   │
                                                        │  - Arena: 24 KB  │
                                                        └────────┬─────────┘
                                                                 │
                                              ┌──────────────────┴──────────────────┐
                                              │                                     │
                                              ▼                                     ▼
                                       P(V) > 0.60                           P(S) > 0.35
                                      ┌───────────────┐                     ┌───────────────┐
                                      │ Class V (PVC) │                     │ Class S (PAC) │
                                      └───────┬───────┘                     └───────┬───────┘
                                              │                                     │
                                              └──────────────────┬──────────────────┘
                                                                 │
                                                                 ▼
                                                ┌──────────────────────────────────┐
                                                │ Tier 3: Clinical Event Engine    │
                                                │  - AFib (CoV, pRR50, RMSSD)      │
                                                │  - Bigeminy / Trigeminy / Pairs  │
                                                │  - Brady / Tachy / VT            │
                                                └────────────────┬─────────────────┘
                                                                 │
                                                                 ▼
                                                      [ BLE Packet & Telemetry ]
```

---

## 3. Building and Flashing

### Build with CMake
```powershell
cd cmake_gcc
cmake --preset project
cmake --build --preset default_config
```

### Flash with Simplicity Commander
```powershell
commander flash build/base/Integration.hex --device EFR32MG26B510F3200IM48
```

---

## 4. Host Software & Live Telemetry

* **Live Multi-Sensor Waveform Visualizer**:
  ```powershell
  python tarang_live_plot.py --port COM11
  ```
* **Serial CSV Logger**:
  ```powershell
  python log_vcom.py --port COM11
  ```
* **Release Locked COM Port**:
  ```powershell
  powershell -File find_com_blocker.ps1
  ```

---

## 5. End-to-End Verification

For the original model/DSP verification methodology, consult
**[TESTING_GUIDE.md](TESTING_GUIDE.md)**. Its historical measurements must be
rerun against the current NLMS-enabled build:
1. **Stage 0**: Pure-Python TFLite Model Sanity Check (`verify_model_stage0.py`)
2. **Stage 1**: Offline DSP & Gate Replay (`verify_stage1_dsp_replay.py`)
3. **Stage 2**: Host C++ Wrapper Unit Test (`test_ai_offline.c`)
4. **Stage 3**: Firmware Boot Log & Tensor Arena Validation
5. **Stage 4 & 5**: Live Signal Validation & Energy Profiler
