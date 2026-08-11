# Tarang Clinical — Full Stack Deployment Guide

Complete guide to running the Tarang clinical telemetry stack on a **Raspberry Pi 4** (or any Linux machine). The same stack also runs on Windows/macOS for local development.

---

## System Architecture

```
EFR32MG26 Wearable
       │
 BLE 5.3 Notifications
       ▼
ble_gateway.py  ──────────► FastAPI (port 8000)
                               │
                     ┌─────────┴──────────┐
                     │                    │
              SQLite DB             WebSocket /ws/telemetry
              (tarang_clinical.db)        │
                                    Next.js Dashboard
                                    (port 3000)
```

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11+ | `sudo apt install python3.11 python3-pip python3-venv` |
| Node.js | 20+ | `curl -fsSL https://deb.nodesource.com/setup_20.x \| sudo -E bash - && sudo apt install -y nodejs` |
| npm | bundled with Node | — |
| Git | any | `sudo apt install git` |

---

## Step 1 — Clone the Repository

```bash
git clone https://github.com/memehdi14/icc-26-tarang.git
cd icc-26-tarang
```

---

## Step 2 — Backend Setup

```bash
cd projects/tarang-rpi/dashboard/backend

# Create and activate a Python virtual environment
python3 -m venv venv
source venv/bin/activate          # Linux/macOS
# venv\Scripts\activate           # Windows PowerShell

# Install dependencies
pip install -r requirements.txt
```

### Start the Backend

```bash
# From: projects/tarang-rpi/dashboard/backend/
uvicorn main:app --host 0.0.0.0 --port 8000
```

You should see:
```
INFO:     Started server process
INFO:     Waiting for application startup.
[TARANG] Backend started. Database initialized.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

> **Database**: SQLite file is auto-created at `projects/tarang-rpi/dashboard/backend/tarang_clinical.db` on first run. No setup required.

### Verify Backend

```bash
curl http://localhost:8000/api/health
# → {"status":"ok"}

curl http://localhost:8000/api/patients/884219
# → {"name":"John Doe","bed":"ICU-04",...}

curl http://localhost:8000/api/diagnostics/latest
# → {"bleConnected":false,...}
```

---

## Step 3 — BLE Gateway (Real Hardware — Raspberry Pi Only)

> Skip this step if running on Windows/macOS for development. Use the mock gateway instead.

```bash
# In a NEW terminal, from project root:
cd projects/tarang-rpi/dashboard/backend
source venv/bin/activate

python ble_gateway.py
```

The gateway will:
1. Scan for a BLE device advertising "TARANG", "EFR32", or "SILABS"
2. Connect and subscribe to GATT characteristic `b4cf8877-ba1a-414c-a99d-de85a13fd66a`
3. Forward every 16-byte packet to `http://localhost:8000/api/telemetry/ingest`
4. Auto-reconnect if BLE drops

---

## Step 3 (Alt) — Mock BLE Gateway (Windows / macOS / Dev)

```bash
# In a NEW terminal:
cd projects/tarang-rpi/dashboard/backend
source venv/bin/activate   # or venv\Scripts\activate on Windows

python mock_ble_gateway.py
```

You will see live output like:
```
[MOCK-BLE] Starting mock telemetry gateway...
[     1.0s] HR= 74 BPM | RR= 812ms | Beat=  N | Flags=0x00 | Pkt#1
[     2.0s] HR= 75 BPM | RR= 800ms | Beat=PAC | Flags=0x00 | Pkt#2
```

---

## Step 4 — Frontend Setup

```bash
cd projects/tarang-rpi/dashboard/frontend

# Install Node dependencies
npm install

# Start the Next.js development server
npm run dev
```

Open your browser at **http://localhost:3000**

---

## Step 5 — Full Stack Launch Order

Run each in a separate terminal:

| # | Terminal | Command |
|---|----------|---------|
| 1 | Backend | `cd .../backend && source venv/bin/activate && uvicorn main:app --host 0.0.0.0 --port 8000` |
| 2 | Gateway | `python ble_gateway.py` *(RPi)* or `python mock_ble_gateway.py` *(dev)* |
| 3 | Frontend | `cd .../frontend && npm run dev` |

---

## Step 6 — RPi Auto-Start with systemd

Create systemd services to auto-start the backend and BLE gateway on boot.

### Backend Service

```bash
sudo nano /etc/systemd/system/tarang-backend.service
```

```ini
[Unit]
Description=Tarang Clinical FastAPI Backend
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/icc-26-tarang/projects/tarang-rpi/dashboard/backend
ExecStart=/home/pi/icc-26-tarang/projects/tarang-rpi/dashboard/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### BLE Gateway Service

```bash
sudo nano /etc/systemd/system/tarang-ble-gateway.service
```

```ini
[Unit]
Description=Tarang BLE Gateway
After=tarang-backend.service bluetooth.service
Requires=tarang-backend.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/icc-26-tarang/projects/tarang-rpi/dashboard/backend
ExecStart=/home/pi/icc-26-tarang/projects/tarang-rpi/dashboard/backend/venv/bin/python ble_gateway.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Enable and Start

```bash
sudo systemctl daemon-reload
sudo systemctl enable tarang-backend tarang-ble-gateway
sudo systemctl start tarang-backend tarang-ble-gateway

# Check status
sudo systemctl status tarang-backend
sudo systemctl status tarang-ble-gateway

# View logs
journalctl -u tarang-backend -f
journalctl -u tarang-ble-gateway -f
```

---

## Step 7 — Use PostgreSQL Instead of SQLite (Optional)

Install PostgreSQL:
```bash
sudo apt install postgresql postgresql-client
sudo -u postgres createuser tarang
sudo -u postgres createdb tarang_clinical -O tarang
sudo -u postgres psql -c "ALTER USER tarang PASSWORD 'yourpassword';"
```

Set the environment variable before starting the backend:
```bash
export TARANG_DATABASE_URL="postgresql://tarang:yourpassword@localhost:5432/tarang_clinical"
uvicorn main:app --host 0.0.0.0 --port 8000
```

No code changes needed — SQLAlchemy handles both backends identically.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check |
| `GET` | `api/telemetry/latest` | Latest telemetry event |
| `GET` | `/api/telemetry/history?minutes=5` | Last N minutes of events |
| `POST` | `/api/telemetry/ingest` | BLE gateway posts decoded packets |
| `WS` | `/ws/telemetry` | Live telemetry WebSocket push |
| `GET` | `/api/patients/{mrn}` | Fetch patient by MRN |
| `PUT` | `/api/patients/{mrn}` | Update patient info |
| `GET` | `/api/diagnostics/latest` | Latest device diagnostics |
| `POST` | `/api/diagnostics/update` | Update device state |
| `GET` | `/api/settings` | Get system settings |
| `PUT` | `/api/settings` | Save system settings |

Interactive API docs (auto-generated): **http://localhost:8000/docs**

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: fastapi` | Activate venv: `source venv/bin/activate` |
| `Address already in use` | Another process on 8000: `lsof -ti:8000 \| xargs kill` |
| BLE device not found | Run `bluetoothctl scan on`, ensure EFR32 is powered and advertising |
| CORS error in browser | Check backend is running and `NEXT_PUBLIC_API_URL` in `.env.local` is correct |
| Dashboard shows "Offline Mode" badge | Backend not reachable on port 8000 |
| `bleak` errors on Windows | BLE Gateway only works on RPi; use `mock_ble_gateway.py` on Windows |
