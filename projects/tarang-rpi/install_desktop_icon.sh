#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$HOME/Desktop"
ICON_PATH="$SCRIPT_DIR/dashboard/frontend/public/tarang-logo.png"

mkdir -p "$DESKTOP_DIR"

cat <<EOF > "$DESKTOP_DIR/Tarang_Kiosk.desktop"
[Desktop Entry]
Type=Application
Name=Tarang Clinical Hub
Comment=Start Tarang Fullscreen Clinical Kiosk
Exec=/bin/bash -c "cd '$SCRIPT_DIR' && ./start_kiosk.sh"
Icon=$ICON_PATH
Path=$SCRIPT_DIR
Terminal=true
Categories=Healthcare;Medical;
StartupNotify=true
EOF

chmod +x "$DESKTOP_DIR/Tarang_Kiosk.desktop"
chmod +x "$SCRIPT_DIR/start_kiosk.sh"
chmod +x "$SCRIPT_DIR/start_all.sh"
chmod +x "$SCRIPT_DIR/stop_all.sh"

# Trust the desktop file on modern Raspberry Pi OS (Debian 12 Bookworm / Wayfire / PCManFM)
if command -v gio >/dev/null 2>&1; then
    gio set "$DESKTOP_DIR/Tarang_Kiosk.desktop" metadata::trusted true 2>/dev/null || true
fi

echo "[TARANG] Desktop shortcut created and trusted at $DESKTOP_DIR/Tarang_Kiosk.desktop!"
echo "[TARANG] Icon path: $ICON_PATH"
echo "[TARANG] You can now double-tap the Tarang icon on your touchscreen to launch Kiosk directly."
