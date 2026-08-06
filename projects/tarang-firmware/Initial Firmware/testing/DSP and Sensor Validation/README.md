# Tarang DSP Bring-up Lab Protocol (ESP32 + Pi)

**Goal today**: validate ECG sensor → ESP32 ADC → IMU → synchronized stream →
Raspberry Pi logging/plotting → DSP → NLMS motion-artifact test. **ML is OUT OF SCOPE today.**

**Hardware**: AD8232 (analog) + MPU6050 (I2C 0x68) + ESP32 + Raspberry Pi.
**Voltage**: 3.3 V only. **Power**: USB power bank for body tests, never mains-tied.

---

## 0. Safety rules (read aloud before powering anything)

1. **Battery-only for body.** When electrodes touch skin, the entire AD8232 +
   ESP32 chain MUST be powered from a USB power bank, NOT a wall charger or
   mains-powered laptop USB port. Power banks are galvanically isolated.
2. **No Pi/laptop on ECG analog.** The AD8232 OUTPUT pin goes ONLY to ESP32
   GPIO34 (ADC1). Never to Raspberry Pi GPIO — Pi has no ADC and is not
   isolated.
3. **Pi is logger only.** Pi talks to ESP32 over USB serial. The USB ground
   is shared, but no analog path crosses between them.
4. **Use a simulator first.** Before strapping electrodes to a body, run the
   AD8232 with open input, then with a finger-test (one finger on each lead),
   then with a 1.5 V battery + 100 kΩ voltage divider as a fake ECG.
5. **Electrode placement**: right arm (RA), left arm (LA), right leg (RL).
   Never place electrodes across the chest laterally if you are unsure of
   the device's isolation. RA-LA-RL is Lead I and is safest.
6. **Stop on discomfort.** If the subject feels any sensation, remove
   electrodes immediately. AD8232 has lead-off detection — use it.

---

## 1. Wiring

### 1.1 AD8232 → ESP32

| AD8232 pin | ESP32 pin | Notes |
|------------|-----------|-------|
| 3.3V (VCC) | 3V3       | Never 5V — module is 3.3V |
| GND        | GND       | Common ground with ESP32 |
| OUTPUT     | GPIO34    | ADC1_CH6, input-only, no internal pull |
| LO+        | GPIO35    | Lead-off + indicator (active low) |
| LO-        | GPIO32    | Lead-off - indicator (active low) |
| SDN        | 3V3       | Active-high shutdown; tie high to enable |

Optional protection (only if you see noise):
- 100 nF cap from GPIO34 to GND (anti-alias LPF, fc ≈ 16 kHz — well above QRS)
- 1 kΩ series resistor between AD8232 OUTPUT and GPIO34 (limits current)

### 1.2 MPU6050 → ESP32

| MPU6050 pin | ESP32 pin | Notes |
|-------------|-----------|-------|
| VCC         | 3V3       | Most modules accept 5V, but 3V3 is safest for I/O |
| GND         | GND       | Common ground |
| SCL         | GPIO22    | Default ESP32 I2C SCL |
| SDA         | GPIO21    | Default ESP32 I2C SDA |
| AD0         | GND       | Sets I2C address to 0x68 (matches production) |
| INT         | (NC)      | Not used today — we poll |

Pull-ups: most MPU6050 modules have onboard 4.7 kΩ pull-ups to VCC. If I2C is
unstable, add external 4.7 kΩ from SDA→3V3 and SCL→3V3.

### 1.3 ESP32 → Raspberry Pi

| ESP32 | Pi | Notes |
|-------|----|----|
| USB port (micro-USB on most dev boards) | Pi USB port via data cable | Data cable, not charge-only! |

On the Pi the ESP32 will appear as `/dev/ttyUSB0` (most CP2102/CH340 boards)
or `/dev/ttyACM0` (native USB-Serial boards like ESP32-S2/S3). Check with:

```bash
ls /dev/ttyUSB* /dev/ttyACM*
dmesg | tail -20
```

**Common ground rule**: USB cable provides ground. No additional wire needed.

---

## 2. Bring-up stages

| Stage | Goal | Code |
|-------|------|------|
| 0 | Visual inspection + power check | (no code) |
| 1 | ESP32 serial sanity ("ESP32 alive") | `esp32/00_serial_sanity` |
| 2 | I2C scanner finds MPU6050 at 0x68 | `esp32/01_i2c_scanner` |
| 3 | Raw AD8232 ADC reads mid-rail (~2048) | `esp32/02_ad8232_raw_adc` |
| 4 | Lead-off detection works (LO+ LO- go high on disconnect) | (uses 02 sketch) |
| 5 | Combined ECG+IMU CSV stream at 250/100 Hz | `esp32/05_ecg_imu_250_100hz_csv` |
| 6 | Pi reads serial, saves CSV | `rpi/01_serial_logger.py` |
| 7 | Live plot ECG + IMU magnitude | `rpi/02_live_plot.py` |
| 8 | Sampling rate + jitter measurement | `rpi/03_sampling_rate_check.py` |
| 9 | Run DSP filters (DC, BP, notch, MA) | `rpi/04_dsp_compare.py` |
| 10 | Combined DSP validation: filter + NLMS + Pan-Tompkins | `rpi/06_combined_dsp_validation.py` |
| 11 | Tarang frame converter (256-sample frames + summary JSON) | `rpi/07_tarang_frame_converter.py` |
| 12 | ESP32 real-time lightweight DSP demo | `esp32/06_realtime_dsp_demo` |
| 13 | Pass/fail metrics report | `rpi/05_dsp_metrics.py` |

Each stage's exact goal/code/expected/failure/debug/next is in the chat
walkthrough.

---

## 3. Folder layout

```
~/tarang_data/
  tarang_YYYYMMDD_HHMMSS.csv                       # raw CSV from logger
  tarang_YYYYMMDD_HHMMSS_sampling_rate.png         # jitter report
  tarang_YYYYMMDD_HHMMSS_dsp_compare.png           # 5-panel DSP comparison
  tarang_YYYYMMDD_HHMMSS_dsp_compare.npz           # arrays for metrics
  tarang_YYYYMMDD_HHMMSS_combined_dsp.png          # 6-panel: raw+bp+nlms+imu+rr
  tarang_YYYYMMDD_HHMMSS_combined_dsp.npz          # arrays for frame converter
  tarang_YYYYMMDD_HHMMSS_combined_dsp_report.md    # full markdown report
  tarang_YYYYMMDD_HHMMSS_combined_dsp_results.csv  # per-frame summary CSV
  tarang_YYYYMMDD_HHMMSS_frames/                   # Tarang-compatible frames
    frame_0001.csv
    frame_0001_imu32.csv
    frame_0002.csv
    ...
    summary.json

tarang_bringup/
  esp32/
    00_serial_sanity/00_serial_sanity.ino              # Stage 1
    01_i2c_scanner/01_i2c_scanner.ino                  # Stage 3 / IMU detection
    02_ad8232_raw_adc/02_ad8232_raw_adc.ino            # Stage 2 raw ECG
    03_mpu6050_raw/03_mpu6050_raw.ino                  # Stage 4 raw IMU
    04_ecg_imu_combined/04_ecg_imu_combined.ino        # Stage 5 simplified
    05_ecg_imu_250_100hz_csv/05_ecg_imu_250_100hz_csv.ino  # Stage 5 production-like
    06_realtime_dsp_demo/06_realtime_dsp_demo.ino      # Stage 12 lightweight DSP
  rpi/
    01_serial_logger.py                                # Stage 6
    02_live_plot.py                                    # Stage 7
    03_sampling_rate_check.py                          # Stage 8
    04_dsp_compare.py                                  # Stage 9 + 11 (5-panel)
    05_dsp_metrics.py                                  # Stage 13 metrics
    06_combined_dsp_validation.py                      # Stage 10 end-to-end
    07_tarang_frame_converter.py                       # Stage 11 Tarang frames
    dsp.py                                             # filter helpers
    nlms.py                                            # NLMS implementation
    pan_tompkins.py                                    # Pan-Tompkins QRS detector
  README.md                                            # this file
```

---

## 4. Pi setup commands

```bash
sudo apt update
sudo apt install -y python3-pip python3-serial
pip3 install numpy scipy matplotlib pyserial

# Identify ESP32 port
ls /dev/ttyUSB* /dev/ttyACM*
dmesg | tail -20

# Add user to dialout group (avoid sudo for serial)
sudo usermod -a -G dialout $USER
# log out / log back in for group change to take effect

# Test connection (no ESP32 code yet, just verify port opens)
python3 -c "import serial; s=serial.Serial('/dev/ttyUSB0',921600,timeout=1); print(s); s.close()"
```

---

## 5. ESP32 setup

Use Arduino IDE or PlatformIO. Required:
- ESP32 board package (arduino-esp32 >= 2.0.x)
- Wire library (built-in)
- Select board: "ESP32 Dev Module"
- Upload speed: 921600
- Port: /dev/ttyUSB0 (Linux) or COM3 (Windows)

For Stage 5 (production-tight 250/100 Hz), the sketch is already configured to:
- Disable WiFi and BT (`WiFi.mode(WIFI_OFF); btStop();`)
- Pin sampler task to core 1 (Arduino loop runs on core 0)
- Use FreeRTOS vTaskDelayUntil for periodic wakeups

---

## 6. Pass/fail table (final)

| # | Check | Pass criteria |
|---|-------|---------------|
| 1 | I2C scan finds MPU6050 | 0x68 present |
| 2 | AD8232 raw ADC mid-rail | 2048 ± 100 (open input) |
| 3 | Lead-off flag works | LO+ LO- read 1 when leads disconnected |
| 4 | ECG raw signal non-trivial | RMS > 5 mV during finger test |
| 5 | ECG sampling rate | 250.00 ± 0.5 Hz mean |
| 6 | ECG jitter p2p | < 4 ms (2 master ticks) |
| 7 | IMU sampling rate | 100.00 ± 0.5 Hz mean |
| 8 | IMU idx no drops | imu_idx increments by 1 only |
| 9 | Bandpass reduces RMS | RMS(ecg_bp) < RMS(ecg_raw) |
| 10 | QRS visible after bandpass | qrs_visibility_score ≥ 0.5 |
| 11 | NLMS stable | No NaN/Inf in output |
| 12 | NLMS weights bounded | |w|_2 < 1e6 |
| 13 | Motion correlation detectable | |corr(ECG_env, IMU_env)| > 0.05 |

---

## 7. What to save to Tarang KB after the test

Append a section to `Tarang_Internal_Knowledge_Base_v2.md` (or your team wiki):

```
## YYYY-MM-DD ESP32+Pi DSP Bring-up Lab Session

### Hardware
- ECG module: AD8232 (analog)
- IMU module: MPU6050 (I2C 0x68)
- Acquisition: ESP32 (FreeRTOS, core 1, 500 Hz master tick)
- Logger: Raspberry Pi 4 / 5

### Results
- ECG sampling rate: ___ Hz (target 250)
- IMU sampling rate: ___ Hz (target 100)
- ECG jitter p2p: ___ ms
- QRS visibility (raw): ___
- QRS visibility (bandpass): ___
- QRS visibility (NLMS): ___
- Motion-noise correlation: ___
- NLMS settings: taps=32 mu=0.01 eps=1.0
- Final pass/fail: ___/13

### Artifacts
- CSV: tarang_YYYYMMDD_HHMMSS.csv
- Plot: tarang_YYYYMMDD_HHMMSS_dsp_compare.png
- Sampling rate plot: tarang_YYYYMMDD_HHMMSS_sampling_rate.png

### Notes / problems
- (any anomalies, debugging steps, surprising findings)

### Open questions for next session
- (anything that needs follow-up)
```

---

## 8. When sharing firmware for review

When you share ESP32 or EFR32 firmware code, the review will cover:
- Acquisition path (timer → ADC/IADC → DMA → buffer)
- Sample rate (configured vs measured)
- ISR vs main-loop separation
- Buffer ownership (double-buffering, lock-free vs mutex)
- Blocking calls (Serial.print, Wire.requestFrom, delay inside ISR)
- Timing jitter sources (WiFi, BLE, other tasks)
- DSP integration points (where raw becomes filtered)
- ECG/IMU synchronization (do they share a clock? a tick?)
- Telemetry impact on timing (does BLE TX starve the sampler?)

Patches will be concrete (diff-style), not vague advice.
