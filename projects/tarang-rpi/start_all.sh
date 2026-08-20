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

echo "[2/3] Starting frontend on port 3000..."
cd "$FRONTEND_DIR"
if [[ "${TARANG_FRONTEND_MODE:-production}" == "development" ]]; then
    npm run dev &
else
    if [[ ! -d ".next" ]]; then
        echo "[INFO] Frontend production build missing; running npm run build..."
        npm run build
    fi
    npm run start &
fi
PIDS+=("$!")

echo "[3/3] Starting paired BLE gateway..."
cd "$BACKEND_DIR"
"$PYTHON" -u ble_gateway.py &
PIDS+=("$!")

# Check if kiosk mode requested via CLI flag --kiosk or env TARANG_KIOSK=1
if [[ "${TARANG_KIOSK:-0}" == "1" ]] || [[ "${1:-}" == "--kiosk" ]]; then
    sleep 2
    echo "[4/4] Launching fullscreen Chromium Kiosk on 5-inch display..."
    if command -v chromium-browser >/dev/null 2>&1; then
        chromium-browser --kiosk --noerrdialogs --disable-infobars --check-for-update-interval=31536000 --app=http://localhost:3000 &
        PIDS+=("$!")
    elif command -v chromium >/dev/null 2>&1; then
        chromium --kiosk --noerrdialogs --disable-infobars --app=http://localhost:3000 &
        PIDS+=("$!")
    fi
fi

echo
echo "=========================================="
echo "  TARANG CLINICAL HUB RUNNING"
echo "  Dashboard : http://localhost:3000"
echo "  API       : http://localhost:8000"
echo "  BLE       : Connected to Tarang pod"
if [[ "${TARANG_KIOSK:-0}" == "1" ]] || [[ "${1:-}" == "--kiosk" ]]; then
echo "  Kiosk     : Active on 5-inch screen"
fi
echo "=========================================="
echo "Press Ctrl+C to stop all services."

set +e
wait -n "${PIDS[@]}"
status=$?
set -e
echo "[ERROR] A Tarang service exited with status $status."
exit "$status"
