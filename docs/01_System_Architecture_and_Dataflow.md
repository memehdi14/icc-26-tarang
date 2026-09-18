# 01. Tarang System Architecture & End-to-End Dataflow

## 1. Executive Summary

**Project Tarang** is an ultra-low-power, edge-intelligent clinical telemetry patch and bedside hub designed for continuous cardio-respiratory monitoring. It integrates single-lead Electrocardiogram (ECG), photoplethysmography (PPG), and tri-axial inertial motion sensing (IMU) directly at the patient interface, running real-time adaptive motion artifact cancellation and on-device Edge AI inference on a **Silicon Labs EFR32MG26 (ARM Cortex-M33)** microcontroller.

Telemetry packets are streamed via **Bluetooth Low Energy (BLE 5.2)** to a **Raspberry Pi 4/5 Clinical Hub**, which hosts an asynchronous FastAPI backend, SQLite longitudinal telemetry database, and a Next.js 14 real-time bedside dashboard calibrated for 5-inch clinical touchscreens and remote clinical monitoring.

```
+-----------------------------------------------------------------------------------------+
|                                 TARANG HARDWARE SENSOR NODE                             |
|                                                                                         |
|  +---------------+      +-------------------+      +------------------+                 |
|  |  AD8232 ECG   |      |  MAX30102 PPG     |      |  MPU6050 IMU     |                 |
|  |  (250 Hz)     |      |  (100 Hz Red/IR)  |      |  (100 Hz Accel)  |                 |
|  +-------+-------+      +---------+---------+      +--------+---------+                 |
|          | Analog                 | I2C + INT               | I2C                       |
|          v                        v                         v                           |
|  +-------------------------------------------------------------------+                  |
|  |             Silicon Labs EFR32MG26 (ARM Cortex-M33 @ 78 MHz)       |                  |
|  |  - Zero-CPU LETIMER -> LDMA Hardware Acquisition Pipeline          |                  |
|  |  - Real-Time DSP: 4th-Order Bandpass (0.5-40Hz) + Notch (50Hz)    |                  |
|  |  - NLMS Adaptive Motion Cancellation (Accelerometer Reference)    |                  |
|  |  - Pan-Tompkins Real-Time QRS & R-Peak Detection                  |                  |
|  |  - Two-Stage Cascaded Edge AI (Int8 TFLite Micro via CMSIS-NN):   |                  |
|  |      * Stage 1: Noise & Normality Gate (gate_int8.tflite, 40.5KB) |                  |
|  |      * Stage 2: SVEB vs VEB Classifier (sv_int8.tflite, 32.0KB)   |                  |
|  +--------------------------------+----------------------------------+                  |
+-----------------------------------|-----------------------------------------------------+
                                    | BLE 5.2 GATT Custom Notifications
                                    | (20-byte legacy / 244-byte DLE)
                                    v
+-----------------------------------------------------------------------------------------+
|                            TARANG RASPBERRY PI CLINICAL HUB                             |
|                                                                                         |
|  +-------------------------------------------------------------------+                  |
|  |  Python BLE Gateway (bleak async client + event ring buffer)      |                  |
|  |  - Bond-aware pairing with NVM3 epoch validation                  |                  |
|  |  - BlueZ cache purge on every reconnect (prevents stale device)   |                  |
|  +--------------------------------+----------------------------------+                  |
|                                   v                                                     |
|  +-------------------------------------------------------------------+                  |
|  |  FastAPI Asynchronous Backend (Port 8000)                         |                  |
|  |  - WebSocket Telemetry Broadcaster (/ws/telemetry)                |                  |
|  |  - SQLite Session & Patient Storage                               |                  |
|  |  - REST Control API (/api/devices, /api/patients, /api/settings)  |                  |
|  +--------------------------------+----------------------------------+                  |
|                                   v                                                     |
|  +-------------------------------------------------------------------+                  |
|  |  Next.js 14 Real-Time Bedside Web Dashboard (Port 3000)           |                  |
|  |  - 60 FPS HTML5 Canvas Live ECG & Plethysmogram Strip             |                  |
|  |  - Instant Arrhythmia Alarms & Clinical Severity Color Coding     |                  |
|  |  - Fullscreen Touchscreen Kiosk Mode (848x480 resolution)         |                  |
|  +-------------------------------------------------------------------+                  |
+-----------------------------------------------------------------------------------------+
```

---

## 2. Key Subsystem Specifications

| Subsystem | Hardware / Framework | Key Functional Responsibility | Performance / Throughput |
| :--- | :--- | :--- | :--- |
| **Sensor Frontend** | AD8232, MAX30102, MPU6050 | Raw physiological & kinematic acquisition | 250 Hz ECG, 100 Hz PPG, 100 Hz IMU |
| **Edge Compute** | EFR32MG26 (Cortex-M33 @ 78MHz) | LETIMER/LDMA Zero-CPU capture, DSP, Int8 AI | EM2 Deep Sleep >96% duty cycle |
| **Wireless Protocol**| 2.4 GHz BLE 5.2 (Silicon Labs Stack)| Stream raw samples, beats, and AI diagnostics | < 25 ms transport latency |
| **Clinical Hub** | Raspberry Pi 4/5 (Raspberry Pi OS) | GATT reception, buffering, REST/WS streaming | Zero sample-drop @ 250Hz |
| **User Interface** | Next.js 14, React, Vanilla CSS | Clinical strip chart, alarming, patient records | 60 FPS smooth rendering |

---

## 3. BLE Telemetry Protocol & Security Architecture

The sensor node exposes three dedicated 128-bit primary GATT services with selective encryption:

### 3.1 GATT Services & Packet Formats

1. **Service A: Vitals Service (`544e937a-82f3-4395-b62b-b72bdea94c75`) [Unencrypted / Open Fallback]**
   - **Heart Rate (`b4cf...66a`):** Instantaneous HR (`uint16_t` BPM) — notified every 2.5s, and **immediately on finger contact state change** (no-lag skin detection).
   - **SpO2 (`b4cf...66b`):** Reflectance-calibrated SpO2 (`uint8_t` %). Formula: $\text{SpO}_2 = 110.0 - 15.0 \times R$, clamped to physiological range **93–98%**.
   - **Timestamp (`b4cf...66c`):** Millisecond hardware counter (`uint32_t`).
   - **Motion and Correlation (`b4cf...66d`):** IMU dynamic acceleration magnitude (mg) and Pearson correlation $r \times 1000$ (`int16_t`). Motion flag suppresses spurious arrhythmia during heavy patient movement.
   - **Bond Epoch (`b4cf...66e`):** NVM3 epoch counter read before trusting cached LTKs to prevent stale bond deadlocks after firmware reflash.

2. **Service B: Analytics Service (`655f937a-82f3-4395-b62b-b72bdea94c75`) [Periodic Rollups]**
   - **60-second** periodic notification rollups (not 5-minute): PVC Burden (`uint8_t` %), PAC Burden (`uint8_t` %), SDNN (`uint16_t` ms), RMSSD (`uint16_t` ms), pRR50 (`uint8_t` %), AI Duty Cycle × 10 (`uint8_t`, e.g. 8 = 0.8%), and EM2 Sleep % (`uint8_t`).
   - First rollup fires at **15 seconds** post-connection to populate the UI immediately.
   - AI duty cycle is computed as `(ai_time_us × 1000 + uptime_us/2) / uptime_us` with proper rounding and a minimum floor of 0.1% when AI has run.

3. **Service C: Clinical Event Service (`7660937a-82f3-4395-b62b-b72bdea94c75`) [AES-128-CCM Bonded & Encrypted]**
   - **Rhythm Status (`d6eb...88a`):** Bitfield flags (AFib, VT, Sinus Tach, Bigeminy, Trigeminy, Couplet, Triplet) — `bonded="true" encrypted="true"`.
   - **Event Meta (`d6eb...88b`):** Event ID, anomaly classification code, confidence score ($0–255$), hardware timestamp (`uint64_t`).
   - **ECG Snippet Chunks (`d6eb...88c`):** On-demand 2.5-second (500 samples @ 250 Hz) high-resolution diagnostic Lead-I ECG strip pushed in sequential 240-byte DLE frames.
   - **Beat Annotations (`d6eb...88d`):** Per-beat timing fiducials, classes ($N$, $S$, $V$), and confidence values.
   - **Event Ticker (`d6eb...88e`):** Real-time anomaly notification ticker for bedside UI priority interrupts.

### 3.2 Security Architecture: Why Selective Field-Level Encryption?
- **Link Security:** BLE Security Mode 1, Level 2 (Unauthenticated pairing with encryption), enforcing **AES-128-CCM** using the EFR32MG26 hardware cryptographic accelerator with a mandatory **16-byte (128-bit) minimum key size**.
- **Dual-Layer Enforcement:** Service C characteristics require both GATT attribute permissions (`bonded="true" encrypted="true"`) and firmware-level gate authorization (`tarang_service_c_authorized`) which verifies `security_mode >= Level 2` and `key_size >= 16`.
- **NVM3 Bond Epoch:** When firmware is reflashed, a bond epoch counter in NVM3 increments. The Pi gateway reads this via the Bond Epoch characteristic on first connect and purges stale LTKs before they cause a `0x0206` (PIN/Key Missing) disconnection deadlock.
- **BlueZ Runtime Cache Purge:** After any BLE disconnect, the gateway calls `bluetoothctl remove <addr>` to clear the stale device object from BlueZ before retrying, preventing the 35-second `BleakClient.connect()` timeout loop.
- **Selective Encryption Rationale:**
  - *Zero-Latency Triage:* Service A vitals (HR, SpO2) stream immediately upon connection without waiting for pairing handshakes.
  - *PHI Protection:* High-risk diagnostic ECG waveforms and rhythm events (Protected Health Information) are encrypted to meet HIPAA/GDPR standards.
  - *High Availability:* If bond keys become stale after pod reflash, vitals continue streaming in fallback mode while re-pairing is negotiated.

---

## 4. Architectural Trade-Off Analysis ("Why This vs. Why Not That")

### 4.1 Topology: Hybrid Edge-Hub vs. Pure Cloud vs. Edge-Only Standalone

| Architectural Option | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **Hybrid Edge-Hub (Chosen)** | Yes | **ADOPTED** | Edge node executes real-time filtering & AI inference locally without network dependency. Bedside hub provides local touchscreen GUI, high-capacity buffering, and reliable clinical alarm generation even during internet outages. |
| **Pure Cloud Streaming** | Yes | **REJECTED** | Continuous 250 Hz raw ECG streaming to cloud requires high-power Wi-Fi/LTE (draining small wearable battery in < 4 hours). Internet latency (100–500ms) or hospital Wi-Fi dropouts pose severe patient safety hazards for critical arrhythmia alerting. |
| **Pure Standalone Edge (No Hub)** | Yes | **REJECTED** | Displaying waveforms directly on a wearable screen increases weight, bulk, and power draw, degrading patient compliance. Microcontrollers lack memory for longitudinal multi-day waveform storage and clinical EHR interoperability. |

### 4.2 Wireless Protocol: BLE 5.2 GATT vs. Wi-Fi vs. Classic Bluetooth (SPP) vs. Zigbee / Matter

| Wireless Protocol | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **BLE 5.2 GATT (Chosen)** | Yes | **ADOPTED** | Average current draw $< 5 \text{ mA}$ during active radio transmission. Native hardware support on EFR32MG26 with Silicon Labs RAIL stack. 244-byte Data Length Extension (DLE) easily accommodates 250 Hz waveform throughput. |
| **Wi-Fi (802.11 b/g/n)** | Yes | **REJECTED** | Wi-Fi active TX current ($80–200 \text{ mA}$) exceeds the thermal and capacity budget of a coin-cell / 300mAh LiPo patch. Roaming disconnections between hospital APs cause data loss. |
| **Classic Bluetooth (SPP)** | Yes | **REJECTED** | High continuous power consumption and lack of modern smartphone / embedded OS GATT peripheral compatibility. |
| **Zigbee / Thread / Matter** | Yes | **REJECTED** | High protocol overhead and mesh routing latency are unsuitable for streaming continuous high-frequency physiological waveforms. |

### 4.3 Sampling Rate: 250 Hz ECG & 100 Hz PPG vs. 500/1000 Hz vs. 128 Hz

| Sampling Frequency | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **250 Hz ECG / 100 Hz PPG (Chosen)** | Yes | **ADOPTED** | 250 Hz captures all clinical QRS diagnostic features (Nyquist frequency 125 Hz covers clinical ECG diagnostic bandwidth of 0.05–100 Hz per IEC 60601-2-27). Minimizes DMA buffer size and ML tensor input dimensions (180 samples/beat). |
| **500 Hz – 1000 Hz** | Yes | **REJECTED** | Doubles/quadruples RAM consumption, DMA interrupts, and neural network input sizes with zero diagnostic gain for basic arrhythmia classification. |
| **128 Hz** | Yes | **REJECTED** | QRS fiducial point jitter ($> 8 \text{ ms}$ error per peak) severely corrupts Pan-Tompkins derivative accuracy and Heart Rate Variability (HRV) metrics. |

---

## 5. End-to-End Latency & Power Budget

- **Acquisition-to-Filter Latency:** $< 4 \text{ ms}$ (causal IIR 4th-order filter).
- **R-Peak to Inference Latency:** $< 18 \text{ ms}$ (2-beat buffer lookahead window + CMSIS-NN inference).
- **Finger Detection Latency:** **< 100 ms** — bypasses 4-second rolling buffer by reading raw IR sample directly (`ir_sample >= 12000u` threshold).
- **BLE Notification to Bedside Screen Render:** $< 22 \text{ ms}$.
- **Total Glass-to-Glass Latency:** $\approx 45 \text{ ms}$ (fully satisfying IEC 60601-2-27 real-time cardiac monitoring standards).
- **Average Current Draw:** $14.2 \text{ mA}$ active streaming, scaling down to $< 1.8 \text{ mA}$ in power-optimized burst mode on 3.7V LiPo battery.
- **Analytics Rollup Cadence:** Every **60 seconds** (first rollup at 15s post-connect). Updates SDNN, RMSSD, PVC/PAC burden, and AI duty cycle on the bedside dashboard.
