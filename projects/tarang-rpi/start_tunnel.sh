#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${TARANG_ENV_FILE:-$SCRIPT_DIR/tarang.env}"

if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

echo "=========================================="
echo "  TARANG CLOUDFLARE SECURE TUNNEL"
echo "=========================================="

# Check if cloudflared is installed
if ! command -v cloudflared >/dev/null 2>&1; then
    echo "[INFO] cloudflared not found. Installing cloudflared for Raspberry Pi..."
    ARCH="$(uname -m)"
    if [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]]; then
        CLOUDFLARED_BIN_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64"
    elif [[ "$ARCH" == "armv7l" || "$ARCH" == "armhf" ]]; then
        CLOUDFLARED_BIN_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm"
    else
        CLOUDFLARED_BIN_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
    fi

    sudo curl -fsSL "$CLOUDFLARED_BIN_URL" -o /usr/local/bin/cloudflared
    sudo chmod +x /usr/local/bin/cloudflared
    echo "[SUCCESS] cloudflared installed successfully."
fi

if [[ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]]; then
    echo "[INFO] Starting named Cloudflare Tunnel with configured token..."
    exec cloudflared tunnel run --token "$CLOUDFLARE_TUNNEL_TOKEN"
else
    echo "[INFO] No CLOUDFLARE_TUNNEL_TOKEN found in tarang.env."
    echo "[INFO] Starting Quick Secure Tunnel for Frontend (http://localhost:3000)..."
    echo "[INFO] This creates an encrypted HTTPS/WSS URL without requiring port forwarding!"
    echo "--------------------------------------------------------"
    exec cloudflared tunnel --url http://localhost:3000
fi
