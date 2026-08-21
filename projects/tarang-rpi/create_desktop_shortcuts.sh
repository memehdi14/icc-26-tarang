#!/usr/bin/env bash
# ==============================================================================
# INSTALL TOUCHSCREEN DESKTOP SHORTCUTS FOR 5-INCH DISPLAY
# ==============================================================================

DESKTOP_DIR="$HOME/Desktop"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$DESKTOP_DIR"

# 1. Start Tarang Hub Shortcut
cat <<EOF > "$DESKTOP_DIR/Tarang-Hub.desktop"
[Desktop Entry]
Name=TARANG Clinical Hub
Comment=Start TARANG Medical Telemetry Kiosk
Exec=$SCRIPT_DIR/start_all.sh
Icon=utilities-system-monitor
Terminal=true
Type=Application
Categories=Medical;Healthcare;
EOF

chmod +x "$DESKTOP_DIR/Tarang-Hub.desktop"

# 2. Stop Tarang Hub Shortcut
cat <<EOF > "$DESKTOP_DIR/Stop-Tarang.desktop"
[Desktop Entry]
Name=STOP TARANG Hub
Comment=Stop all TARANG Services
Exec=$SCRIPT_DIR/stop_all.sh
Icon=process-stop
Terminal=false
Type=Application
Categories=Medical;Healthcare;
EOF

chmod +x "$DESKTOP_DIR/Stop-Tarang.desktop"
chmod +x "$SCRIPT_DIR/start_all.sh"
chmod +x "$SCRIPT_DIR/stop_all.sh"

echo "✓ Touchscreen desktop icons installed to $DESKTOP_DIR"
echo "  • Double-tap 'TARANG Clinical Hub' to start"
echo "  • Double-tap 'STOP TARANG Hub' to stop"
