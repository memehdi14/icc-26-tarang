# Tarang Hardware Integration & Testing Guide

This guide details step-by-step instructions for wiring, flashing, and verifying the **integrated multi-sensor firmware** (ECG + PPG + IMU) on the **EFR32MG26 (BRD2709A)** hardware platform.

---

## 1. Physical Pinout & Wiring Diagram

All 3 sensors connect to the EFR32MG26 board via dedicated analog pads, shared I2C bus (`sl_i2cspm_mikroe`), and GPIO external interrupt lines.

### Hardware Connections Summary

| Component | Signal | EFR32MG26 Pin / Pad | Details & Notes |
| :--- | :--- | :--- | :--- |
| **ECG Front-End** | Analog Signal | `ANA0` (`iadcPosInputPadAna0`) | Dedicated AIN0 analog input pad |
| | GND / Ref | `GND` | Common ground reference |
| **MAX30102 (PPG)**| I2C SCL | `PC05` | Shared I2C Clock (`sl_i2cspm_mikroe`) |
| | I2C SDA | `PC07` | Shared I2C Data (`sl_i2cspm_mikroe`) |
| | INT (Interrupt)| `PC06` | Active-LOW open-drain (Internal Pull-Up enabled) |
| | VCC / GND | `3V3` / `GND` | Power supply |
| **MPU6050 (IMU)** | I2C SCL | `PC05` | Shared I2C Clock (`sl_i2cspm_mikroe`) |
| | I2C SDA | `PC07` | Shared I2C Data (`sl_i2cspm_mikroe`) |
| | INT (Interrupt)| `PC00` | Active-HIGH Data Ready (Rising Edge trigger) |
| | AD0 | `GND` | Sets 7-bit I2C Address to `0x68` |
| | VCC / GND | `3V3` / `GND` | Power supply |

> [!NOTE]
> **Shared I2C Bus:** Both MAX30102 (`0x57`) and MPU6050 (`0x68`) share the same I2C lines (`PC05`/`PC07`). Ensure pull-up resistors (2.2kΩ–4.7kΩ) are present on SCL/SDA lines if not already on the sensor breakout boards.

---

## 2. Serial Terminal Setup (VCOM)

To view real-time diagnostics and sample streams:
1. Connect the EFR32MG26 board to your PC via USB.
2. Open a serial terminal (PuTTY, Tera Term, Serial Monitor, or VS Code Serial Console).
3. Select the J-Link CDC UART port.
4. Configure terminal settings:
   - **Baud Rate:** `115200`
   - **Data Bits:** `8`
   - **Parity:** `None`
   - **Stop Bits:** `1`
   - **Flow Control:** `None`

---

## 3. Step-by-Step Testing Procedure

### Phase 1: Boot-Up & Initialization Check

1. Flash `Integration.out` / `Integration.hex` to the board using Simplicity Studio / Simplicity Commander.
2. Open the Serial Terminal.
3. Reset the board. You should see the boot banner:

```text
==========================================
  TARANG INTEGRATION v1.0
  ECG + PPG + IMU — All Sensors Combined
==========================================
[INIT] ECG: Starting LETIMER+PRS+IADC+DMADRV...
[INIT] ECG: Acquisition running
[INIT] PPG: Configuring MAX30102...
[PPG] Sensor config OK
[PPG] INT_STATUS1=0x00 INT_STATUS2=0x00 (cleared)
[PPG] PC06 interrupt armed. Falling edge -> PPG_RDY @ 100Hz
[INIT] PPG: OK — interrupts armed
[INIT] IMU: Configuring MPU6050...
[IMU] MPU6050 init complete. WHO_AM_I=0x68
[INIT] IMU: OK — DATA_RDY armed
==========================================
[INIT] All sensors initialized.
[INIT] Diagnostics print every ~2 seconds.
==========================================
```

---

### Phase 2: Sensor-by-Sensor Verification

#### 1. PPG (MAX30102) Check
- **Observation:** Every 1 second (100 samples), the PPG driver outputs a sample log:
  `[PPG] cnt=100 int=100 RED=184520 IR=195120`
- **Interactive Test:** Place a finger over the MAX30102 optical sensor.
  - Expect `RED` and `IR` values to change significantly (higher values when covered, pulsatile variations).
  - Verify `int` (interrupt count) matches `cnt` (sample count), confirming **per-sample zero-CPU hardware timing**.

#### 2. IMU (MPU6050) Check
- **Observation:** Every 1 second (100 samples), the IMU driver outputs accelerometer and gyroscope readings:
  `[IMU] cnt=100 ax=120 ay=-250 az=16400 gx=12 gy=-5 gz=8`
- **Interactive Test:**
  - **Flat at rest:** `az` should be around `+16384` (1g gravity vector), `ax`/`ay` near `0`.
  - **Tilt board 90°:** Gravity vector shifts to `ax` or `ay` (~`16384`).
  - **Rotate/Move:** Gyro values `gx`/`gy`/`gz` respond dynamically to rotation.

#### 3. ECG (IADC + DMADRV) Check
- **Observation:** Every ~2 seconds, the global diagnostic block reports DMADRV ping-pong status:
  `ECG: halves=4  samples=1000  overruns=0`
- **Verification:**
  - `halves=...` continuously increments (proof of continuous DMA transfer without CPU intervention).
  - `overruns=0`: Confirms CPU is keeping up with the 250 Hz sample rate.

---

### Phase 3: Multi-Sensor Combined Diagnostics

Every ~2 seconds, a full combined report is printed:

```text
--- TARANG DIAG ---
  ECG: halves=8  samples=2000  overruns=0
  PPG: cnt=200  RED=184100  IR=195300  found=1
  IMU: cnt=200  int=200  ax=110 ay=-240 az=16390  found=1
-------------------
```

---

## 4. Hardware Troubleshooting Matrix

| Symptom | Cause | Resolution |
| :--- | :--- | :--- |
| `[PPG] SENSOR CONFIG FAILED` | I2C transfer failed or MAX30102 not powered | Check 3.3V power to MAX30102. Check `PC05` (SCL) and `PC07` (SDA) wiring. |
| `[IMU] I2C read WHO_AM_I failed` | MPU6050 not responding on I2C | Verify MPU6050 power & I2C lines. Ensure AD0 pin is tied to GND (`0x68`). |
| `[IMU] WHO_AM_I mismatch: got 0xXX` | Non-standard MPU6050 chip ID | Some revisions return `0x70`. The driver handles both `0x68` and `0x70`. |
| `[PPG] FIFO OVERFLOW` | Main loop blocked by long delay or print | Ensure no `delay()` or blocking calls are added inside `app_process_action()`. |
| `ECG overruns > 0` | DMA buffer processing stalled | Check if higher-priority interrupts are starving the DMADRV callback. |
| No serial output at all | VCOM disabled or wrong baud rate | Check baud rate is `115200`. Verify `iostream_recommended_console` component in project. |

---

## 5. Next Integration Step: DSP & ML Pipeline

Once all 3 sensors pass hardware verification:
1. **Feed IMU Accel + ECG** into `tarang_nlms.c` for **real-time motion artifact cancellation**.
2. **Pass clean ECG** to `tarang_ml.c` for **arrhythmia inference**.
