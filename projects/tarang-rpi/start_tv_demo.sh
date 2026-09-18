#!/usr/bin/env bash
# ==============================================================================
# Tarang Dashboard — TV Demo Launcher (Linux / macOS / Git Bash / WSL)
# 
# Use this when:
#   - Raspberry Pi hosts the backend & frontend server
#   - Laptop is connected to the 65" TV via HDMI
# 
# Usage:
#   ./start_tv_demo.sh [url] [scale]
# 
# Examples:
#   ./start_tv_demo.sh                                       # Default: http://teamocelleon.local:3000, scale 2.0
#   ./start_tv_demo.sh http://teamocelleon.local:3000 1.75   # 1080p desktop layout with patient rail
#   ./start_tv_demo.sh http://10.181.53.123:3000 2.0         # Explicit Pi IP
#   ./start_tv_demo.sh http://localhost:3000 2.0             # If frontend runs locally on laptop
# ==============================================================================

set -e

# Default URL and Scale
URL="${1:-http://teamocelleon.local:3000}"
SCALE="${2:-2.0}"

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  echo "Usage: $0 [url] [scale]"
  echo "  url    Dashboard URL (default: http://teamocelleon.local:3000)"
  echo "  scale  Device scale factor (default: 2.0 for 1080p, 1.75 for full desktop, 2.5-3.0 for 4K)"
  echo ""
  echo "Examples:"
  echo "  $0"
  echo "  $0 http://teamocelleon.local:3000 1.75"
  echo "  $0 http://10.181.53.123:3000 2.0"
  exit 0
fi

# Detect Browser executable across Linux, macOS, and Windows/Git-Bash
BROWSER=""

if [[ "$OSTYPE" == "darwin"* ]]; then
  # macOS
  for b in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Chromium.app/Contents/MacOS/Chromium" \
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"; do
    if [[ -x "$b" ]]; then
      BROWSER="$b"
      break
    fi
  done
elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || -n "$WINDIR" ]]; then
  # Git Bash / MSYS on Windows
  for b in \
    "/c/Program Files/Google/Chrome/Application/chrome.exe" \
    "/c/Program Files (x86)/Google/Chrome/Application/chrome.exe" \
    "/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
    "/c/Program Files/Microsoft/Edge/Application/msedge.exe"; do
    if [[ -f "$b" ]]; then
      BROWSER="$b"
      break
    fi
  done
else
  # Linux (Ubuntu, Debian, Fedora, Arch)
  for b in google-chrome google-chrome-stable chromium chromium-browser microsoft-edge-stable brave-browser; do
    if command -v "$b" >/dev/null 2>&1; then
      BROWSER="$b"
      break
    fi
  done
fi

if [[ -z "$BROWSER" ]]; then
  echo "❌ Error: Could not find Google Chrome, Chromium, or Edge."
  echo "   Please install Chrome or set BROWSER=/path/to/browser manually."
  exit 1
fi

# Isolated throwaway user profile so scaling and autoplay flags are ALWAYS honored
PROFILE_DIR="${TMPDIR:-/tmp}/tarang_tv_demo_profile"
mkdir -p "$PROFILE_DIR"

echo "========================================================"
echo " 🫀 Tarang Clinical Workstation — TV Demo Launcher"
echo "========================================================"
echo "  Target URL : $URL"
echo "  Scale      : $SCALE (DPR zoom)"
echo "  Browser    : $BROWSER"
echo "  Profile    : $PROFILE_DIR"
echo "========================================================"
echo ""
echo "🚀 Launching fullscreen window..."
echo "💡 If it opens on your laptop screen instead of the TV:"
echo "   - Windows / Linux: Press F11 to unmaximize, drag to TV, press F11"
echo "   - macOS: Drag window to TV screen, click green maximize button"
echo ""

# Launch Chromium with flags
"$BROWSER" \
  --app="$URL" \
  --start-fullscreen \
  --window-size=1920,1080 \
  --force-device-scale-factor="$SCALE" \
  --autoplay-policy=no-user-gesture-required \
  --no-first-run \
  --no-default-browser-check \
  --user-data-dir="$PROFILE_DIR" \
  >/dev/null 2>&1 &

echo "✅ Launched successfully."
