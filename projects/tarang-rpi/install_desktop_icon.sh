#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$HOME/Desktop"

mkdir -p "$DESKTOP_DIR"
cp "$SCRIPT_DIR/tarang_kiosk.desktop" "$DESKTOP_DIR/Tarang_Kiosk.desktop"
chmod +x "$DESKTOP_DIR/Tarang_Kiosk.desktop"
chmod +x "$SCRIPT_DIR/start_kiosk.sh"
chmod +x "$SCRIPT_DIR/start_all.sh"
chmod +x "$SCRIPT_DIR/stop_all.sh"

echo "[TARANG] Desktop shortcut created at $DESKTOP_DIR/Tarang_Kiosk.desktop!"
echo "[TARANG] You can now tap the Tarang icon on your touchscreen to launch Kiosk directly."
