#!/usr/bin/env bash
# ==============================================================================
# TARANG CLINICAL HUB — CLEAN SHUTDOWN SCRIPT
# ==============================================================================

echo "Stopping all Tarang Clinical Hub services..."
sudo pkill -9 -f chromium-browser 2>/dev/null || true
sudo pkill -9 -f chromium 2>/dev/null || true
sudo pkill -9 -f node 2>/dev/null || true
sudo pkill -9 -f python3 2>/dev/null || true
sudo pkill -9 -f uvicorn 2>/dev/null || true
sudo pkill -9 -f next 2>/dev/null || true

echo "Resetting Bluetooth stack..."
sudo systemctl restart bluetooth 2>/dev/null || true

echo "✓ All Tarang services stopped cleanly."
