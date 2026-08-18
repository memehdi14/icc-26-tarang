#!/usr/bin/env bash
# ==============================================================================
# TARANG RASPBERRY PI ONE-CLICK LAUNCHER
# Launches Backend (8000), Frontend (3000), and BLE Gateway concurrently
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/dashboard/backend"
FRONTEND_DIR="$SCRIPT_DIR/dashboard/frontend"

echo "=========================================="
echo "  🏥 Launching TARANG Bedside Hub System  "
echo "=========================================="

cleanup() {
    echo ""
    echo "[!] Shutting down all Tarang processes..."
    kill $(jobs -p) 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM

# 1. Start FastAPI Backend
echo "[1/3] Starting FastAPI Backend on http://0.0.0.0:8000..."
cd "$BACKEND_DIR"
if [ -d "venv" ]; then
    source venv/bin/activate
fi
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Wait 2 seconds for backend initialization
sleep 2

# 2. Start Next.js Frontend
echo "[2/3] Starting Next.js Frontend Dashboard on http://0.0.0.0:3000..."
cd "$FRONTEND_DIR"
npm run dev -- -H 0.0.0.0 -p 3000 &
FRONTEND_PID=$!

# Wait 3 seconds for frontend server
sleep 3

# 3. Start BLE Gateway
echo "[3/3] Starting BLE Gateway (scanning for TARANG wearable)..."
cd "$BACKEND_DIR"
python3 ble_gateway.py &
GATEWAY_PID=$!

echo ""
echo "=========================================================="
echo "  🟢 TARANG HUB IS RUNNING!"
echo "  • Dashboard URL: http://localhost:3000"
echo "  • Backend API:   http://localhost:8000"
echo "  • BLE Gateway:   Active (Auto-connecting to TARANG Pod)"
echo "  Press Ctrl+C to stop all services."
echo "=========================================================="

wait
