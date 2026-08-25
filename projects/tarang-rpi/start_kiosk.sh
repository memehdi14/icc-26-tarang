#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/dashboard/backend"
FRONTEND_DIR="$SCRIPT_DIR/dashboard/frontend"
ENV_FILE="${TARANG_ENV_FILE:-$SCRIPT_DIR/tarang.env}"
PYTHON="$BACKEND_DIR/venv/bin/python"
BACKEND_HEALTH_URL="http://127.0.0.1:8000/api/health"

echo "=========================================="
echo "  TARANG CLINICAL HUB — KIOSK MODE LAUNCHER"
echo "=========================================="

if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
else
    echo "[WARN] $ENV_FILE not found; using environment/default values."
fi

if [[ ! -x "$PYTHON" ]]; then
    echo "[ERROR] Python environment missing at $PYTHON"
    echo "Run ./setup_rpi.sh first."
    exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "[ERROR] curl is required for startup health checks."
    exit 1
fi

# Pre-cleanup: terminate any lingering processes from previous runs
echo "[0/4] Terminating previous instances and resetting bluetooth..."
pkill -f "uvicorn main:app" 2>/dev/null || true
pkill -f "ble_gateway.py" 2>/dev/null || true
pkill -f "next start" 2>/dev/null || true
pkill -f "next-server" 2>/dev/null || true
pkill -f "chromium" 2>/dev/null || true
if command -v hciconfig >/dev/null 2>&1; then
    sudo hciconfig hci0 reset 2>/dev/null || true
fi
sleep 1

PIDS=()
shutting_down=0

cleanup() {
    if [[ "$shutting_down" -eq 1 ]]; then
        return
    fi
    shutting_down=1
    echo
    echo "[TARANG] Stopping all services & closing Kiosk..."
    if [[ ${#PIDS[@]} -gt 0 ]]; then
        kill "${PIDS[@]}" 2>/dev/null || true
        wait "${PIDS[@]}" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

export PYTHONUNBUFFERED=1

echo "[1/4] Starting FastAPI backend on port 8000..."
cd "$BACKEND_DIR"
"$PYTHON" -u -m uvicorn main:app --host 0.0.0.0 --port 8000 &
PIDS+=("$!")

backend_ready=0
for _ in $(seq 1 30); do
    if curl --silent --fail "$BACKEND_HEALTH_URL" >/dev/null 2>&1; then
        backend_ready=1
        break
    fi
    sleep 1
done
if [[ "$backend_ready" -ne 1 ]]; then
    echo "[ERROR] Backend did not become healthy within 30 seconds."
    exit 1
fi

echo "[2/4] Starting frontend on port 3000..."
cd "$FRONTEND_DIR"
if [[ ! -f ".next/BUILD_ID" ]]; then
    echo "[INFO] Production build missing; running npm run build (takes ~30s)..."
    npm run build
fi
npm run start &
PIDS+=("$!")

echo "[INFO] Waiting for frontend to initialize on port 3000..."
for _ in $(seq 1 30); do
    if curl --silent --fail "http://localhost:3000" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
sleep 1

echo "[3/4] Starting paired BLE gateway..."
cd "$BACKEND_DIR"
"$PYTHON" -u ble_gateway.py &
PIDS+=("$!")

# Optional: Cloudflare Tunnel auto-start if configured
if [[ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]] && ! systemctl is-active --quiet cloudflared 2>/dev/null; then
    echo "[INFO] Launching Cloudflare Tunnel from token..."
    cloudflared tunnel run --token "$CLOUDFLARE_TUNNEL_TOKEN" &
    PIDS+=("$!")
fi

# Step 4: Fullscreen Chromium Kiosk on display
export DISPLAY="${DISPLAY:-:0}"
# Prevent screen from sleeping / blanking
if command -v xset >/dev/null 2>&1; then
    xset s off 2>/dev/null || true
    xset -dpms 2>/dev/null || true
    xset s noblank 2>/dev/null || true
fi

# Auto-calibrate display resolution for 800x480@60Hz LCD (Wayfire / Labwc / Wayland)
if command -v wlr-randr >/dev/null 2>&1; then
    echo "[INFO] Setting display resolution to 800x480@60Hz on HDMI-A-1..."
    wlr-randr --output HDMI-A-1 --custom-mode 800x480@60Hz 2>/dev/null || \
    wlr-randr --output HDMI-A-1 --mode 800x480 2>/dev/null || true
fi

echo "[4/4] Launching fullscreen Touchscreen Kiosk (calibrated for 800x480 LCD)..."
CHROME_FLAGS=(
    --kiosk
    --noerrdialogs
    --disable-infobars
    --check-for-update-interval=31536000
    --disable-session-crashed-bubble
    --disable-pinch
    --overscroll-history-navigation=0
    --touch-events=enabled
    --hide-scrollbars
    --force-device-scale-factor=0.68
    --no-sandbox
    --disable-gpu
    --user-data-dir=/tmp/chromium_kiosk_data
    --app=http://localhost:3000
)

if command -v chromium-browser >/dev/null 2>&1; then
    chromium-browser "${CHROME_FLAGS[@]}" &
    PIDS+=("$!")
elif command -v chromium >/dev/null 2>&1; then
    chromium "${CHROME_FLAGS[@]}" &
    PIDS+=("$!")
else
    echo "[WARN] Chromium browser not installed. Install with: sudo apt-get install -y chromium-browser"
fi

# Re-apply mode after Chromium window creates to guarantee full 800x480 viewport fit
(
    sleep 2
    if command -v wlr-randr >/dev/null 2>&1; then
        wlr-randr --output HDMI-A-1 --custom-mode 800x480@60Hz 2>/dev/null || true
    fi
) &

echo
echo "=========================================="
echo "  TARANG CLINICAL HUB RUNNING (KIOSK ACTIVE)"
echo "  Dashboard : http://localhost:3000"
echo "  API       : http://localhost:8000"
echo "  Display   : Fullscreen Touchscreen Kiosk"
echo "=========================================="
echo "Press Ctrl+C to stop all services."

# Keep all services running until user presses Ctrl+C
wait
