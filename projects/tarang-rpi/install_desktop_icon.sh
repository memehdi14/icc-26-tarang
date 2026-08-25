#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$HOME/Desktop"
ICON_PATH="$SCRIPT_DIR/dashboard/frontend/public/tarang-logo.png"

mkdir -p "$DESKTOP_DIR"

# 1. Normal Mode Shortcut (start_all.sh - for TV / Large Monitors)
cat <<EOF > "$DESKTOP_DIR/Tarang_Hub.desktop"
[Desktop Entry]
Type=Application
Name=Tarang Clinical Hub
Comment=Start Tarang Dashboard in Normal Mode (TV / Monitor)
Exec=$SCRIPT_DIR/start_all.sh
Icon=$ICON_PATH
Path=$SCRIPT_DIR
Terminal=true
Categories=Healthcare;Medical;
StartupNotify=true
EOF

# 2. Touchscreen Kiosk Mode Shortcut (start_kiosk.sh - for 800x480 Touchscreen)
cat <<EOF > "$DESKTOP_DIR/Tarang_Kiosk.desktop"
[Desktop Entry]
Type=Application
Name=Tarang Kiosk Mode
Comment=Start Tarang in Fullscreen Touchscreen Kiosk Mode
Exec=$SCRIPT_DIR/start_kiosk.sh
Icon=$ICON_PATH
Path=$SCRIPT_DIR
Terminal=true
Categories=Healthcare;Medical;
StartupNotify=true
EOF

chmod +x "$DESKTOP_DIR/Tarang_Hub.desktop" "$DESKTOP_DIR/Tarang_Kiosk.desktop"
chmod +x "$SCRIPT_DIR/start_kiosk.sh" "$SCRIPT_DIR/start_all.sh" "$SCRIPT_DIR/stop_all.sh"

# Trust the desktop files on Raspberry Pi OS (Wayfire / PCManFM)
if command -v gio >/dev/null 2>&1; then
    gio set "$DESKTOP_DIR/Tarang_Hub.desktop" metadata::trusted true 2>/dev/null || true
    gio set "$DESKTOP_DIR/Tarang_Kiosk.desktop" metadata::trusted true 2>/dev/null || true
fi

echo "=========================================================="
echo "  [TARANG] Desktop Shortcuts Installed Successfully!"
echo "  1. 'Tarang Clinical Hub' -> Normal Mode (for TV / Screen)"
echo "  2. 'Tarang Kiosk Mode'    -> Fullscreen Touchscreen Kiosk"
echo "=========================================================="
