#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/dashboard/backend"
FRONTEND_DIR="$SCRIPT_DIR/dashboard/frontend"

echo "[1/5] Installing Raspberry Pi system dependencies..."
sudo apt-get update
sudo apt-get install -y \
    bluetooth \
    bluez \
    curl \
    git \
    nodejs \
    npm \
    python3 \
    python3-pip \
    python3-venv

sudo systemctl enable --now bluetooth
sudo usermod -aG bluetooth "$USER" || true

node_major="$(node --version | sed -E 's/^v([0-9]+).*/\1/')"
if [[ "$node_major" -lt 18 ]]; then
    echo "[ERROR] Node.js 18 or newer is required; found $(node --version)."
    echo "Install a current Node.js LTS release, then rerun this script."
    exit 1
fi

echo "[2/5] Creating Python environment..."
python3 -m venv "$BACKEND_DIR/venv"
"$BACKEND_DIR/venv/bin/python" -m pip install --upgrade pip
"$BACKEND_DIR/venv/bin/python" -m pip install -r "$BACKEND_DIR/requirements.txt"

echo "[3/5] Running backend and BLE protocol tests..."
cd "$BACKEND_DIR"
"$BACKEND_DIR/venv/bin/python" -m unittest discover -s tests -v

echo "[4/5] Installing and building frontend..."
cd "$FRONTEND_DIR"
npm ci
npm run build

echo "[5/5] Preparing local configuration..."
if [[ ! -f "$SCRIPT_DIR/tarang.env" ]]; then
    cp "$SCRIPT_DIR/tarang.env.example" "$SCRIPT_DIR/tarang.env"
    echo "Created $SCRIPT_DIR/tarang.env"
fi
chmod +x "$SCRIPT_DIR/start_all.sh" "$SCRIPT_DIR/update_rpi.sh" "$SCRIPT_DIR/start_tunnel.sh"

echo
echo "Setup complete."
echo "1. Review $SCRIPT_DIR/tarang.env"
echo "2. Log out and back in if Bluetooth group membership changed"
echo "3. Run $SCRIPT_DIR/start_all.sh"
