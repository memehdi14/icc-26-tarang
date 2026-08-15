# TARANG BLE Telemetry Integration Guide for Raspberry Pi

This document details how to set up a Raspberry Pi to connect over Bluetooth Low Energy (BLE) to the TARANG EFR32 firmware and receive live 16-byte clinical telemetry event packets.

---

## 1. Protocol & Binary Packet Format

The EFR32 firmware transmits a **16-byte packed C struct** (`tarang_event_packet_t`) whenever a rhythm change, arrhythmia event, or ectopic burst is detected.

### Packet Struct Layout (16 Bytes)

| Offset | Size | Type | Field Name | Description |
|---|---|---|---|---|
| `0` | 4 B | `uint32` | `timestamp_ms` | Millisecond timestamp from device boot |
| `4` | 1 B | `uint8` | `beat_class` | `0` = N (Normal), `1` = S (PAC), `2` = V (PVC), `3` = Q (Noise) |
| `5` | 1 B | `uint8` | `confidence` | Beat classification confidence (0 to 255) |
| `6` | 2 B | `uint16` | `rr_interval_ms` | R-R interval in milliseconds |
| `8` | 1 B | `uint8` | `rhythm_flags` | Bitfield representing active rhythm conditions |
| `9` | 1 B | `uint8` | `pac_burden_pct` | Running PAC (S-beat) burden percentage (0–100%) |
| `10` | 1 B | `uint8` | `pvc_burden_pct` | Running PVC (V-beat) burden percentage (0–100%) |
| `11` | 1 B | `uint8` | `current_hr` | Current Heart Rate in BPM |
| `12` | 2 B | `uint16` | `sdnn_ms` | HRV SDNN metric in milliseconds |
| `14` | 2 B | `uint16` | `rmssd_ms` | HRV RMSSD metric in milliseconds |

### Rhythm Flags Bitfield (`rhythm_flags`)

* `0x00`: Normal Sinus Rhythm
* `0x01`: Atrial Fibrillation (AFib)
* `0x02`: Sinus Tachycardia
* `0x04`: Sinus Bradycardia
* `0x08`: Ventricular Bigeminy
* `0x10`: Ventricular Trigeminy
* `0x20`: Ventricular Run (V-Run)
* `0x40`: SVT Run
* `0x80`: **CRITICAL: Ventricular Tachycardia (VT) Suspected**

---

## 2. Raspberry Pi Setup Instructions

### Prerequisites
Make sure your Raspberry Pi has Bluetooth enabled and Python 3.9+ installed.

1. **Install System Dependencies (BlueZ)**:
   ```bash
   sudo apt update
   sudo apt install -y bluetooth bluez python3-pip python3-venv
   ```

2. **Set Up Python Virtual Environment & Install `bleak`**:
   ```bash
   python3 -m venv tarang_env
   source tarang_env/bin/activate
   pip install bleak
   ```

---

## 3. Running the Receiver Script

1. Copy [`tarang_rpi_receiver.py`](file:///c:/MMDPublic/Hackathons/TeamOcelleon/projects/tarang-firmware/Integration/tarang_rpi_receiver.py) to your Raspberry Pi.
2. Execute the script:
   ```bash
   python3 tarang_rpi_receiver.py
   ```

### Output Example
```text
Scanning for TARANG BLE device...
Found notification characteristic: 00002a37-0000-1000-8000-00805f9b34fb
Connected to TARANG device!
Subscribing to telemetry notifications...

=======================================================
  [TARANG CLINICAL TELEMETRY] Time: 45.210 s
=======================================================
  Heart Rate     : 72 BPM
  RR Interval    : 833 ms
  Beat Class     : N (Normal) (Conf: 245/255)
  Rhythm Status  : Normal Sinus Rhythm
  Ectopic Burden : PAC=0%  PVC=0%
  HRV Metrics    : SDNN=42 ms  RMSSD=38 ms
=======================================================
```
