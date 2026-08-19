# Tarang Raspberry Pi Deployment

This guide runs the Tarang backend, dashboard, and paired BLE gateway on a Raspberry Pi using BlueZ.

## Architecture

```text
EFR32MG26 wearable
    |
    | bonded and encrypted BLE notifications/indications
    v
ble_gateway.py
    |
    | local HTTP
    v
FastAPI :8000 ----> SQLite
    |
    | REST + WebSocket
    v
Next.js :3000
```

The EFR32 is the BLE peripheral/GATT server. The Raspberry Pi is the BLE central/GATT client.

## Requirements

- Raspberry Pi OS with BlueZ
- Python 3.10 or newer
- Node.js 18 or newer
- EFR32 firmware with Security Manager and bonding enabled
- The phone disconnected while the Pi is testing the wearable

## First-Time Setup

From the repository root:

```bash
cd projects/tarang-rpi
chmod +x setup_rpi.sh start_all.sh update_rpi.sh
./setup_rpi.sh
```

The setup script:

1. Installs BlueZ, Python, Node.js, npm, curl, and Git.
2. Enables the Bluetooth service.
3. Creates `dashboard/backend/venv`.
4. Installs Python dependencies.
5. Runs backend and BLE protocol tests.
6. Installs and builds the frontend.
7. Creates `tarang.env` from `tarang.env.example` if needed.

Log out and back in after the first setup if the user was newly added to the `bluetooth` group.

## Configuration

Edit:

```text
projects/tarang-rpi/tarang.env
```

Recommended hackathon configuration:

```bash
TARANG_BACKEND_URL=http://127.0.0.1:8000
TARANG_BLE_ADDRESS=64:02:8F:64:26:14
TARANG_BLE_PAIR=true
TARANG_DEVICE_ID=tarang-efr32-demo
TARANG_SESSION_ID=
TARANG_CORS_ORIGINS=*
TARANG_FRONTEND_MODE=production
TARANG_LOG_LEVEL=INFO
```

### Gateway variables

| Variable | Default | Purpose |
|---|---:|---|
| `TARANG_BACKEND_URL` | `http://localhost:8000` | FastAPI destination |
| `TARANG_BLE_ADDRESS` | unset | Preferred EFR32 identity address |
| `TARANG_BLE_NAME_PREFIX` | `TARANG` | Name prefix used when address is unset |
| `TARANG_BLE_PAIR` | `true` | Pair before protected GATT discovery |
| `TARANG_BLE_SCAN_TIMEOUT` | `10` | Discovery timeout in seconds |
| `TARANG_BLE_CONNECT_TIMEOUT` | `35` | Pair/connect timeout in seconds |
| `TARANG_BLE_RECONNECT_DELAY` | `5` | Initial reconnect delay |
| `TARANG_DIAGNOSTICS_INTERVAL` | `10` | Diagnostics heartbeat interval |
| `TARANG_DEVICE_ID` | BLE address | Device identifier sent to the API |
| `TARANG_SESSION_ID` | active backend lookup | Monitoring session association |
| `TARANG_LOG_LEVEL` | `INFO` | Python logging level |

When `TARANG_SESSION_ID` is empty, the gateway follows the active backend session assigned to `TARANG_DEVICE_ID`. Set it explicitly only when the Pi must be pinned to one session.

## BLE-Only Validation

Before starting the complete stack, validate the wearable directly:

```bash
cd projects/tarang-rpi
source dashboard/backend/venv/bin/activate
python ble_test.py 64:02:8F:64:26:14
```

The test performs pairing before service enumeration, validates all three Tarang services, subscribes to HR, SpO2, and event metadata, and listens for notifications.

Use unsecured mode only while testing firmware that has no protected GATT attributes:

```bash
python ble_test.py 64:02:8F:64:26:14 --no-pair
```

Do not routinely run `bluetoothctl remove`. Removing the device deletes the Pi-side bond and forces key negotiation again.

## Start the Complete Hub

```bash
cd projects/tarang-rpi
./start_all.sh
```

The launcher starts services in this order:

1. FastAPI backend
2. Backend health verification
3. Production Next.js frontend
4. Paired BLE gateway

URLs:

- Dashboard: `http://<pi-address>:3000`
- API: `http://<pi-address>:8000`
- OpenAPI: `http://<pi-address>:8000/docs`

Press `Ctrl+C` to stop the complete process group.

## Run Components Separately

### Backend

```bash
cd projects/tarang-rpi/dashboard/backend
source venv/bin/activate
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

### Gateway

```bash
cd projects/tarang-rpi
set -a
source tarang.env
set +a
dashboard/backend/venv/bin/python dashboard/backend/ble_gateway.py
```

### Frontend

```bash
cd projects/tarang-rpi/dashboard/frontend
npm run start -- -H 0.0.0.0 -p 3000
```

## Expected Gateway Sequence

```text
Backend ready at http://127.0.0.1:8000
Scanning for configured device 64:02:8F:64:26:14
Connecting to TARANG-2614 (...), pairing=True
Connected and GATT verified
Subscribed to b4cf8877-...
...
9 Mode A subscriptions active
Vitals: HR=75 SpO2=98
```

On first connection, BlueZ performs SMP pairing. Later connections reuse the stored bond.

## Database

The default SQLite database is:

```text
projects/tarang-rpi/dashboard/database/tarang_clinical.db
```

Override it with:

```bash
TARANG_DATABASE_URL=sqlite:////absolute/path/tarang_clinical.db
```

SQLite WAL mode, foreign keys, and a five-second busy timeout are enabled automatically.

## Tests

```bash
cd projects/tarang-rpi/dashboard/backend
source venv/bin/activate
python -m unittest discover -s tests -v
```

The suite uses an isolated temporary database and does not modify the deployment database.

## Updating

The update script refuses to overwrite a dirty working tree and uses a fast-forward-only Git pull:

```bash
cd projects/tarang-rpi
./update_rpi.sh
```

It then updates Python dependencies, runs tests, installs exact frontend dependencies from `package-lock.json`, and rebuilds Next.js.

## Optional systemd Service

Create `/etc/systemd/system/tarang-hub.service` and replace the user/path if necessary:

```ini
[Unit]
Description=Tarang bedside hub
After=network-online.target bluetooth.service
Wants=network-online.target
Requires=bluetooth.service

[Service]
Type=simple
User=teamocelleon
WorkingDirectory=/home/teamocelleon/icc-26-tarang/projects/tarang-rpi
EnvironmentFile=/home/teamocelleon/icc-26-tarang/projects/tarang-rpi/tarang.env
ExecStart=/home/teamocelleon/icc-26-tarang/projects/tarang-rpi/start_all.sh
Restart=on-failure
RestartSec=5
KillMode=control-group
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tarang-hub
journalctl -u tarang-hub -f
```

## Troubleshooting

### Pairing fails immediately

Confirm the firmware boot log contains:

```text
[BLE] enable bonding: OK
```

Then inspect the firmware's `[BLE][SM] Bonding failed` reason. Do not delete the bond repeatedly without recording that reason.

### Required subscriptions fail

If GATT attributes require bonding, confirm `TARANG_BLE_PAIR=true`. The gateway treats HR, SpO2, and event metadata subscriptions as mandatory and reconnects instead of pretending the session is healthy.

### Device is not found

```bash
bluetoothctl
power on
scan on
```

Verify that `TARANG-2614` appears and that the configured identity address is correct.

### Bond keys are genuinely mismatched

Only after confirming a key mismatch, remove the bond from both peers:

```bash
bluetoothctl remove 64:02:8F:64:26:14
```

Erase the corresponding EFR32 bond through the firmware's maintenance flow or a controlled NVM reset, then pair once again. Removing only one side creates another mismatch.

### Pi connects but receives no data

- Disconnect the phone; the current firmware tracks one application connection.
- Confirm all required subscriptions succeeded.
- Confirm the firmware reports CCCD `SUBSCRIBED` events.
- Remember that the current BLE-only firmware checkpoint sends test vitals while ECG/AI flags are disabled.

### Backend is unavailable

```bash
curl --fail http://127.0.0.1:8000/api/health
```

The gateway waits for this endpoint before scanning and retries failed HTTP deliveries three times through a bounded queue.
