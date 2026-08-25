#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/dashboard/backend"
FRONTEND_DIR="$SCRIPT_DIR/dashboard/frontend"
ENV_FILE="${TARANG_ENV_FILE:-$SCRIPT_DIR/tarang.env}"
PYTHON="$BACKEND_DIR/venv/bin/python"
BACKEND_HEALTH_URL="http://127.0.0.1:8000/api/health"

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

PIDS=()
shutting_down=0

cleanup() {
    if [[ "$shutting_down" -eq 1 ]]; then
        return
    fi
    shutting_down=1
    echo
    echo "[TARANG] Stopping services..."
    if [[ ${#PIDS[@]} -gt 0 ]]; then
        kill "${PIDS[@]}" 2>/dev/null || true
        wait "${PIDS[@]}" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

# Pre-cleanup: terminate any lingering processes from previous runs
echo "[0/3] Clearing any previous instances on ports 8000 & 3000..."
pkill -f "uvicorn main:app" 2>/dev/null || true
pkill -f "ble_gateway.py" 2>/dev/null || true
pkill -f "next start" 2>/dev/null || true
pkill -f "next-server" 2>/dev/null || true
sleep 1

export PYTHONUNBUFFERED=1

echo "[1/3] Starting FastAPI backend on port 8000..."
cd "$BACKEND_DIR"
"$PYTHON" -u -m uvicorn main:app --host 0.0.0.0 --port 8000 &
PIDS+=("$!")

backend_ready=0
for _ in $(seq 1 30); do
    if curl --silent --fail "$BACKEND_HEALTH_URL" >/dev/null; then
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
if [[ "${TARANG_FRONTEND_MODE:-production}" == "development" ]]; then
    npm run dev &
    FRONTEND_PID="$!"
    PIDS+=("$FRONTEND_PID")
else
    if [[ ! -f ".next/BUILD_ID" ]]; then
        echo "[INFO] Frontend production build missing; running npm run build..."
        npm run build
    fi
    npm run start &
    FRONTEND_PID="$!"
    PIDS+=("$FRONTEND_PID")
fi

echo "[INFO] Waiting for frontend to initialize on port 3000..."
frontend_ready=0
for _ in $(seq 1 20); do
    if curl --silent --fail "http://127.0.0.1:3000" >/dev/null 2>&1; then
        frontend_ready=1
        break
    fi
    sleep 1
done

if [[ "$frontend_ready" -ne 1 ]]; then
    echo "[WARN] Production server did not respond on port 3000; falling back to dev server..."
    kill "$FRONTEND_PID" 2>/dev/null || true
    npm run dev &
    PIDS+=("$!")
    for _ in $(seq 1 20); do
        if curl --silent --fail "http://127.0.0.1:3000" >/dev/null 2>&1; then
            frontend_ready=1
            break
        fi
        sleep 1
    done
fi
sleep 1

echo "[3/4] Starting paired BLE gateway..."
cd "$BACKEND_DIR"
"$PYTHON" -u ble_gateway.py &
PIDS+=("$!")

# Optional: Cloudflare Tunnel auto-start if configured and not already running as a system service
if [[ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]] && ! systemctl is-active --quiet cloudflared 2>/dev/null; then
    echo "[INFO] Launching Cloudflare Tunnel from token..."
    cloudflared tunnel run --token "$CLOUDFLARE_TUNNEL_TOKEN" &
    PIDS+=("$!")
fi

# Auto-open Chromium browser on attached TV / display
export DISPLAY="${DISPLAY:-:0}"
echo "[4/4] Auto-opening Chromium dashboard on display..."
CHROME_FLAGS=(
    --noerrdialogs
    --disable-infobars
    --check-for-update-interval=31536000
    --disable-session-crashed-bubble
    --no-sandbox
    --disable-gpu
    --password-store=basic
    --force-device-scale-factor="${TARANG_SCALE_FACTOR:-1.5}"
    --user-data-dir=/tmp/chromium_hub_data
    --app=http://127.0.0.1:3000
)

if [[ "${TARANG_KIOSK:-0}" == "1" ]]; then
    CHROME_FLAGS+=(--kiosk --hide-scrollbars)
else
    CHROME_FLAGS+=(--start-maximized)
fi

if command -v chromium-browser >/dev/null 2>&1; then
    chromium-browser "${CHROME_FLAGS[@]}" &
    PIDS+=("$!")
elif command -v chromium >/dev/null 2>&1; then
    chromium "${CHROME_FLAGS[@]}" &
    PIDS+=("$!")
fi

echo
echo "=========================================="
echo "  TARANG CLINICAL HUB RUNNING"
echo "  Dashboard : http://127.0.0.1:3000"
echo "  API       : http://127.0.0.1:8000"
echo "  BLE       : Connected to Tarang pod"
echo "  Display   : Auto-opened in Chromium"
echo "=========================================="
echo "Press Ctrl+C to stop all services."

# Keep all services running until user presses Ctrl+C
wait
