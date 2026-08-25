#!/usr/bin/env bash
echo "[TARANG] Terminating all running Tarang processes..."

pkill -9 -f "uvicorn" 2>/dev/null || true
pkill -9 -f "ble_gateway.py" 2>/dev/null || true
pkill -9 -f "next start" 2>/dev/null || true
pkill -9 -f "next-server" 2>/dev/null || true
pkill -9 -f "node" 2>/dev/null || true
pkill -9 -f "chromium" 2>/dev/null || true
pkill -9 -f "cloudflared" 2>/dev/null || true

if command -v hciconfig >/dev/null 2>&1; then
    hciconfig hci0 reset 2>/dev/null || true
fi

echo "[TARANG] All processes stopped. Ports 8000, 3000, and Bluetooth are clean."
