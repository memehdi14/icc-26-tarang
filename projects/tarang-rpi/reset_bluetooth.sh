#!/usr/bin/env bash
# reset_bluetooth.sh — Permanent BlueZ reset used by start_all.sh / start_kiosk.sh
#
# Fixes: BleakClient.connect() timing out at 35s because BlueZ keeps a stale
# device object in "connecting" state after a hard kill of the previous gateway.
# dbus_fast's ConnectDevice call then hangs the full timeout with CancelledError.
#
# Strategy (in order of aggression):
#   1. hciconfig reset  — flushes HCI-level half-open connections
#   2. bluetoothctl remove — wipes the stale device object so BlueZ re-creates it
#   3. bluetooth service restart — if HCI is truly wedged (takes ~3s extra)
#   4. quick 5-second passive scan — lets BlueZ rediscover + cache the device
#      so the first ConnectDevice call has a fresh object to work with

BLE_ADDR="${TARANG_BLE_ADDRESS:-64:02:8F:64:26:14}"

echo "[BT] Resetting BlueZ state for $BLE_ADDR..."

# ── 1. HCI hardware-level reset ──────────────────────────────────────────────
if command -v hciconfig >/dev/null 2>&1; then
    hciconfig hci0 down 2>/dev/null || true
    sleep 0.3
    hciconfig hci0 up   2>/dev/null || true
    sleep 0.3
fi

# ── 2. Remove stale BlueZ device object ──────────────────────────────────────
if command -v bluetoothctl >/dev/null 2>&1; then
    bluetoothctl power on 2>/dev/null || true
    # 'remove' returns error if device isn't cached — suppress it
    bluetoothctl remove "$BLE_ADDR" 2>/dev/null || true
    sleep 0.5
fi

# ── 3. Restart bluetooth service if adapter is still unpowered ───────────────
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet bluetooth 2>/dev/null; then
    if ! bluetoothctl show 2>/dev/null | grep -q "Powered: yes"; then
        echo "[BT] Adapter not powered after reset — restarting bluetooth service..."
        sudo systemctl restart bluetooth 2>/dev/null || true
        sleep 3
    fi
fi

# ── 4. Power on + trust ───────────────────────────────────────────────────────
if command -v bluetoothctl >/dev/null 2>&1; then
    bluetoothctl power on 2>/dev/null || true
    bluetoothctl trust "$BLE_ADDR" 2>/dev/null || true
fi

# ── 5. Short passive scan so BlueZ rediscovers the pod fresh ─────────────────
# This gives BlueZ a live BDAddr->device mapping before BleakClient connects,
# preventing the 35-second ConnectDevice D-Bus stall.
if command -v bluetoothctl >/dev/null 2>&1; then
    echo "[BT] Scanning for $BLE_ADDR (up to 5s)..."
    bluetoothctl scan on 2>/dev/null &
    BT_SCAN_PID=$!
    for _i in $(seq 1 10); do
        sleep 0.5
        if bluetoothctl info "$BLE_ADDR" 2>/dev/null | grep -q "Device"; then
            echo "[BT] Pod found during scan."
            break
        fi
    done
    kill "$BT_SCAN_PID" 2>/dev/null || true
    wait "$BT_SCAN_PID" 2>/dev/null || true
    bluetoothctl scan off 2>/dev/null || true
fi

echo "[BT] Bluetooth reset complete — BlueZ is clean."
