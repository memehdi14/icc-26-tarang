# 05. Raspberry Pi Clinical Hub & Web Dashboard

## 1. Hub Architecture Overview

The **Tarang Raspberry Pi Clinical Hub** functions as the local bedside telemetry server, bridge gateway, and interactive touchscreen workstation:

```
+-----------------------------------------------------------------------------------------+
|                               TARANG RASPBERRY PI HUB                                   |
|                                                                                         |
|  [Tarang Pod BLE] ---> [ble_gateway.py (Bleak async client)]                           |
|                               |                                                         |
|            Bond-aware pairing, NVM3 epoch check, BlueZ cache purge on reconnect        |
|                               |                                                         |
|                               v  (Internal HTTP / In-Memory Queue)                      |
|                        [FastAPI Backend (:8000)] <---> [SQLite Database]                |
|                               |                                                         |
|                               +------------------+                                      |
|                               |                  |                                      |
|                               v (REST API)       v (WebSocket Stream)                   |
|                        +----------------------------------------+                       |
|                        | Next.js 14 Bedside Web App (:3000)     |                       |
|                        | - 60 FPS Canvas ECG & PPG Strip        |                       |
|                        | - Audio Alarms & Severity Badges       |                       |
|                        | - Patient & Session Management         |                       |
|                        +--------------------+-------------------+                       |
|                                             |                                           |
|                                             v                                           |
|                        [Chromium Fullscreen Kiosk Mode]                                 |
|                        [5-inch LCD Display (848x480)]                                   |
+-----------------------------------------------------------------------------------------+
```

---

## 2. Bluetooth Gateway (`ble_gateway.py`)

The BLE gateway is implemented using Python's `bleak` asynchronous BLE library:

### 2.1 Key Operational Features:
- **Auto-Discovery & Pairing:** Scans for advertising packets matching the Tarang device name or GATT service UUID (`128-bit UUID`).
- **Bond Epoch Validation:** On first connect, reads the `vitals_bond_epoch` characteristic from the EFR32. If the epoch has changed since the last known bond (stored in `_bond_registry`), purges the stale BlueZ LTK and re-pairs fresh, preventing `0x0206` (PIN/Key Missing) disconnection loops.
- **Bonded Security & Fallback Subscription:** Negotiates BLE pairing and requests notifications on Service C (Clinical Events). If bonding or link encryption is delayed or fails (e.g. stale bond after pod reflash), the gateway gracefully falls back to unbonded streaming of Service A vitals (HR, SpO2), guaranteeing clinical continuity.
- **BlueZ Cache Purge on Reconnect:** After every disconnect (`BLE link disconnected by peer/controller`), calls `bluetoothctl remove <addr>` before the next scan-and-connect cycle. This eliminates the stale device object that causes `BleakClient.connect()` to hang 35 seconds on a D-Bus call that never completes.
- **Resilient Reconnection Engine:** Implements an exponential backoff auto-reconnection loop. If Bluetooth connection drops (e.g. patient walks out of range), the gateway retains current session state and automatically resumes ingestion upon re-entry.
- **Binary Packet Deserialization:** Unpacks binary telemetry frames using Python `struct.unpack`, validating packet sequence IDs to detect any missing packets before pushing to the backend queue.

### 2.2 Analytics Defaults (Corrected)
`GatewaySession` initializes analytics with baseline values aligned to the firmware's actual idle defaults:
```python
self._analytics_values = {
    "sdnn": 0.0,              # 0 until first 60s rollup from firmware
    "rmssd": 0.0,             # 0 until first 60s rollup from firmware
    "prr50": 0.0,
    "pvc_burden_pct": 0.0,
    "pac_burden_pct": 0.0,
    "ai_duty_cycle_pct": 0.8,  # 0.8% firmware baseline (duty_x10=8)
    "em2_sleep_pct": 99.0,     # 99% sleep complement of 0.8% duty
}
```
Previously initialized with stale hardcoded values (`sdnn=44, rmssd=38, duty=1.2%`) which were flushed to the DB on the first analytics notification, overwriting the correctly-seeded startup record.

### 2.3 WebSocket Session Guard (Fixed)
The frontend WebSocket handler filters packets by session ID. `analytics_5min` messages were previously dropped if the packet's session ID didn't exactly match the current session, causing SDNN/RMSSD/duty to never update after the initial page load. Fixed by adding `analytics_5min` to the pass-through list:
```typescript
if (currentSessionId && packetSessionId && packetSessionId !== currentSessionId) {
    if (raw.type !== 'vitals_sample' && raw.type !== 'diagnostics'
        && raw.type !== 'analytics_5min') return;  // ← analytics now passes through
}
```

---

## 3. Asynchronous FastAPI Backend (`main.py`)

The backend runs on **FastAPI + Uvicorn** on port `8000`:

### 3.1 Interactive API Documentation & Schemas:
- **Swagger UI (Interactive API Explorer):** `http://<RPI_IP>:8000/docs` (Custom-styled with Tarang clinical design tokens).
- **ReDoc (Specification Reference):** `http://<RPI_IP>:8000/redoc`
- **OpenAPI Schema:** `http://<RPI_IP>:8000/openapi.json`
- **WebSocket Telemetry Stream:** `ws://<RPI_IP>:8000/ws/telemetry`

### 3.2 Core API Endpoints:
- **Mode A Real-Time ECG Flow:**
  - `POST /api/events` — Ingests 4.0s (1,000 samples @ 250 Hz) Lead-I ECG arrhythmia events directly from BLE gateway.
  - `GET /api/events/latest` — Queries the most recent clinical event with beat annotations and confidence scores.
  - `GET /api/events/{id}/snippet` — Retrieves full 1,000-sample waveform array for a specific event snapshot.
- **Analytics & HRV Rollups:**
  - `POST /api/analytics` — Ingest 60s analytics packet (SDNN, RMSSD, PVC/PAC burden, AI duty cycle, EM2 sleep).
  - `GET /api/analytics/latest` — Returns the most recent analytics record. Falls back to `{ aiDutyCyclePct: 0.8, em2SleepPct: 99.0 }` if no record exists yet.
  - `GET /api/analytics/history` — Historical analytics series for trend charting.
- **Clinical Actions & Alarms:**
  - `POST /api/clinical-actions/page-physician` — Dispatches emergency physician page and creates an auditable clinical log.
- **Vitals & Telemetry:**
  - `GET /api/vitals/latest` — 2.5s Heart Rate & SpO2 live readings.
  - `GET /api/telemetry/history` — Longitudinal 5-minute rolling buffer of ECG telemetry.
- **Diagnostics & Health:**
  - `GET /api/diagnostics/latest` — Link RSSI, battery %, BLE latency, and sensor hardware SQI.
  - `POST /api/diagnostics/update` — BLE Gateway diagnostic sync hook.
  - `GET /api/health` — Rapid system health, database connection, and gateway connectivity probe.
- **Patient & Session Management:**
  - `GET /api/patients` & `POST /api/patients` — Clinical patient records.
  - `GET /api/sessions` & `POST /api/sessions` — Recording session controls.

### 3.3 Startup Seeding (`seed_defaults()`)
On first boot (empty database), the backend seeds:
- Default patient record (Demo Patient).
- Active monitoring session.
- **`Analytics5Min` baseline record** with `ai_duty_cycle_pct=0.8`, `em2_sleep_pct=99.0`, HRV fields zeroed. This prevents the UI showing 0.0% duty cycle and 0% EM2 before the first BLE analytics packet arrives (~15 seconds into connection).

### 3.4 Persistent Storage (SQLite):
- Stores raw telemetry chunks, detected arrhythmia event timestamps, classification labels, and confidence metrics for post-hoc clinical review.
- Analytics rollups stored in `analytics_5min` table (indexed by device_id and timestamp).
- `WAL` mode enabled: Write-Ahead Logging allows concurrent reads from the frontend while the BLE gateway writes.

---

## 4. Next.js 14 Bedside Clinical Dashboard & Kiosk Deployment

Located in `projects/tarang-rpi/dashboard/frontend`:

### 4.1 UI Design System & Aesthetics:
- **Dark Mode Clinical Theme:** Deep slate background (`#0B0F17`) with high-contrast physiological waveforms (Emerald Green for ECG, Crimson Red for PPG Plethysmogram, Gold/Amber for Arrhythmia warnings).
- **60 FPS HTML5 Canvas Rendering:** Directly renders rolling ECG strip sweeps on HTML5 `<canvas>`, bypassing React DOM re-render overhead for buttery-smooth waveform motion.
- **Audio Alarm Engine & Autoplay Bypass:** Web Audio API sound generator emitting standardized IEC 60601-1-8 medical alarm tones upon detection of Ventricular Ectopy ($V$) or Lead-Off events.
  - *Kiosk Autoplay Policy:* Launched via `start_kiosk.sh` with `--autoplay-policy=no-user-gesture-required` so critical audio alarms play immediately upon system power-up without requiring an initial touch interaction.

### 4.2 Live Analytics Display:
- **AI Duty Cycle:** Shows the EFR32's actual AI inference CPU fraction from the 60s rollup. Updates every minute via the `analytics_5min` WebSocket message.
- **EM2 Deep Sleep %:** Complement of the AI duty cycle with 0.1% granularity (e.g. duty=0.8% → sleep=99.2%).
- **SDNN / RMSSD (HRV):** Computed by the clinical engine's 30-beat rolling RR buffer and transmitted as `uint16_t ms` values. Expected range: SDNN 30–100ms, RMSSD 15–45ms for healthy sinus rhythm.
- **PVC/PAC Burden %:** Cumulative ectopic beat count since session start, divided by total beat count.

---

## 5. Architectural & Implementation Trade-Off Analysis ("Why This vs. Why Not That")

### 5.1 Bedside Gateway: Raspberry Pi Dedicated Hub vs. Smartphone/Tablet App vs. Direct-to-Cloud Ingestion

| Platform Architecture | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **Dedicated Raspberry Pi Hub (Chosen)** | Yes | **ADOPTED** | Operates as a permanent 24/7 bedside medical fixture with deterministic hardware peripherals, touchscreen kiosk display, zero OS background throttling, and complete local operational autonomy during hospital network outages. |
| **Consumer Smartphone/Tablet App** | Yes | **REJECTED** | Mobile OS power-saving managers (iOS Background App Refresh / Android Doze) aggressively kill or throttle long-running Bluetooth background tasks, violating clinical telemetry reliability standards. |
| **Direct Patch-to-Cloud Cellular (LTE-M/NB-IoT)** | Yes | **REJECTED** | High peak transmission currents ($> 250\text{ mA}$) drain wearable patch batteries in hours and fail completely inside hospital RF-shielded radiology/ICU wards. |

### 5.2 Backend Technology: FastAPI + WebSockets vs. Flask vs. Node.js Express vs. MQTT Broker

| Backend Stack | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **FastAPI + Async WebSockets (Chosen)** | Yes | **ADOPTED** | High-performance Python `asyncio` event loop native integration with `bleak` BLE client; automatic OpenAPI documentation, and sub-millisecond WebSocket broadcast latency across multiple ward screens. |
| **Flask + Gunicorn** | Yes | **REJECTED** | Synchronous WSGI model struggles with continuous bidirectional 250 Hz sample streaming without heavy third-party eventlet / gevent patching. |
| **Node.js Express** | Yes | **REJECTED** | Running Bluetooth low-level BlueZ bindings in Node.js on ARM Linux is notoriously unstable compared to Python's mature C-extension BLE libraries (`bleak` / `dbus-fast`). |
| **Standalone MQTT Broker (e.g. Mosquitto)** | Yes | **REJECTED** | Adds unnecessary extra daemon complexity for a single bedside appliance; WebSocket directly serves both frontend browser and remote telemetry streams. |

### 5.3 Waveform Rendering: HTML5 Canvas Direct Sweep vs. DOM SVG / React Charts vs. Electron Native Window

| Frontend Rendering Method | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **Direct HTML5 Canvas 2D Sweep (Chosen)** | Yes | **ADOPTED** | Renders 250 points/second at a steady 60 FPS with $< 5\%$ CPU utilization on Raspberry Pi GPU. Circular buffer sweep mimics standard clinical cardiac monitors. |
| **DOM-based SVG (e.g., Recharts / D3.js)** | Yes | **REJECTED** | Updating hundreds of SVG DOM nodes every 4ms creates massive browser garbage collection pauses, causing visible stuttering and skipped beats. |
| **Electron Native App** | Yes | **REJECTED** | High memory footprint (>250MB RAM) compared to Next.js lightweight production build running in native Chromium kiosk mode. |

---

## 6. Deployment & Kiosk Mode Operation

### 6.1 Starting the System on Raspberry Pi

1. **Standard Headless / Terminal Mode:**
   ```bash
   cd ~/icc-26-tarang/projects/tarang-rpi
   ./start_all.sh
   ```

2. **Fullscreen Touchscreen Kiosk Mode (Calibrated for 4.5/5-inch LCD):**
   ```bash
   cd ~/icc-26-tarang/projects/tarang-rpi
   ./start_kiosk.sh
   ```
   *Runs `reset_bluetooth.sh` first (HCI reset, `bluetoothctl remove`, 3s rescan), calibrates screen to `848x480` via `wlr-randr`, disables display power management sleep (`xset -dpms`), and launches Chromium with `--kiosk --force-device-scale-factor=0.68`.*

3. **Stopping All Services & Resetting Bluetooth:**
   ```bash
   cd ~/icc-26-tarang/projects/tarang-rpi
   ./stop_all.sh
   ```

4. **Optional Cloudflare Remote Access:**
   ```bash
   ./start_tunnel.sh
   ```

### 6.2 Git Deployment Workflow (Pi)
```bash
cd ~/icc-26-tarang
git pull origin prod
cd projects/tarang-rpi
./start_kiosk.sh
```
The `prod` branch is the stable deployment branch. All changes are pushed from the development workstation and pulled onto the Pi.
