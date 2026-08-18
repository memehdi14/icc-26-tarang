#!/usr/bin/env bash
# ble_connect_test.sh — Raw bluetoothctl connection test for TARANG
# Usage: bash ble_connect_test.sh [MAC_ADDRESS]
# Default: 64:02:8F:64:26:14

ADDR="${1:-64:02:8F:64:26:14}"

echo "=== TARANG BLE Connection Test ==="
echo "Target: $ADDR"
echo ""

# Step 1: Clean any stale cache
echo "[1/4] Removing stale BlueZ cache..."
bluetoothctl remove "$ADDR" 2>/dev/null || true
sleep 1

# Step 2: Power cycle the adapter
echo "[2/4] Power cycling Bluetooth adapter..."
bluetoothctl power off
sleep 1
bluetoothctl power on
sleep 1

# Step 3: Scan briefly
echo "[3/4] Scanning for 5 seconds..."
timeout 5 bluetoothctl scan on 2>/dev/null &
sleep 6

# Step 4: Connect
echo "[4/4] Connecting to $ADDR..."
bluetoothctl connect "$ADDR"
sleep 3

# Check connection status
echo ""
echo "=== Connection Info ==="
bluetoothctl info "$ADDR"
