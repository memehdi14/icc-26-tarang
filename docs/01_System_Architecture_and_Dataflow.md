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
|  |  - Zero-CPU LETIMER -> LDMA Hardware Acquisition Pipeline         |                  |
|  |  - Real-Time DSP: 4th-Order Bandpass (0.5-40Hz) + Notch (50Hz)     |                  |
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
|  +--------------------------------+----------------------------------+                  |
|                                   v                                                     |
|  +-------------------------------------------------------------------+                  |
|  |  FastAPI Asynchronous Backend (Port 8000)                         |                  |
|  |  - WebSocket Telemetry Broadcaster (/ws/live-stream)              |                  |
|  |  - SQLite Session & Patient Storage                               |                  |
|  |  - REST Control API (/api/devices, /api/patients, /api/settings)  |                  |
|  +--------------------------------+----------------------------------+                  |
|                                   v                                                     |
|  +-------------------------------------------------------------------+                  |
|  |  Next.js 14 Real-Time Bedside Web Dashboard (Port 3000)           |                  |
|  |  - 60 FPS HTML5 Canvas Live ECG & Plethysmogram Strip              |                  |
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
| **Edge Compute** | EFR32MG26 (Cortex-M33 @ 78MHz) | LETIMER/LDMA Zero-CPU capture, DSP, Int8 AI | EM2 Deep Sleep >90% duty cycle |
| **Wireless Protocol**| 2.4 GHz BLE 5.2 (Silicon Labs Stack)| Stream raw samples, beats, and AI diagnostics | < 25 ms transport latency |
| **Clinical Hub** | Raspberry Pi 4/5 (Raspberry Pi OS) | GATT reception, buffering, REST/WS streaming | Zero sample-drop @ 250Hz |
| **User Interface** | Next.js 14, React, Tailwind CSS | Clinical strip chart, alarming, patient records | 60 FPS smooth rendering |

---

## 3. BLE Telemetry Protocol & Framing

The sensor node exposes a proprietary GATT Service (`128-bit UUID`) with dedicated characteristics for high-frequency waveforms, beat events, and diagnostic alerts:

### 3.1 Packet Formats

1. **ECG Raw Waveform Notification Packet (16–20 Bytes):**
   - `[0..1]`: Packet Sequence Number (`uint16_t`)
   - `[2..3]`: Millisecond Hardware Timestamp (`uint16_t`)
   - `[4..15]`: 6x 16-bit Filtered ECG Raw ADC Samples (24-bit aligned)
   - `[16]`: Lead-Off & Electrode Contact Status (`uint8_t`)
   - `[17..19]`: Motion Activity Index & Battery Status

2. **PPG & SpO2 Notification Packet (12 Bytes):**
   - `[0..1]`: PPG Sequence ID
   - `[2..5]`: AC/DC Red Channel Magnitude (`uint32_t`)
   - `[6..9]`: AC/DC IR Channel Magnitude (`uint32_t`)
   - `[10]`: Calculated SpO2 Percentage (`uint8_t`, e.g., 98%)
   - `[11]`: Perfusion Index (PI) indicator

3. **Beat & Arrhythmia Event Packet (8 Bytes - Triggered on R-Peak):**
   - `[0..1]`: R-Peak Sample Index / Timestamp
   - `[2..3]`: Instantaneous R-R Interval (ms)
   - `[4]`: Instantaneous Heart Rate (BPM)
   - `[5]`: Classification Label:
     - `0x00`: Normal Sinus Beat ($N$)
     - `0x01`: Supraventricular Ectopic Beat ($S$)
     - `0x02`: Ventricular Ectopic Beat ($V$)
     - `0xFF`: Noise / Motion Artifact Gated
   - `[6..7]`: Classifier Softmax Probability / Confidence (`uint16_t`)

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
- **BLE Notification to Bedside Screen Render:** $< 22 \text{ ms}$.
- **Total Glass-to-Glass Latency:** $\approx 45 \text{ ms}$ (fully satisfying IEC 60601-2-27 real-time cardiac monitoring standards).
- **Average Current Draw:** $14.2 \text{ mA}$ active streaming, scaling down to $< 1.8 \text{ mA}$ in power-optimized burst mode on 3.7V LiPo battery.
