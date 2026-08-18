#!/usr/bin/env bash
# ==============================================================================
# TARANG RASPBERRY PI ONE-TOUCH SETUP SCRIPT
# ==============================================================================
set -e

echo "=========================================="
echo "  🏥 TARANG Bedside Hub — Setup & Install "
echo "=========================================="

# 1. System packages & Bluetooth tools
echo "[1/4] Installing system dependencies & Bluetooth tools..."
sudo apt update
sudo apt install -y python3-pip python3-venv nodejs npm bluetooth bluez libbluetooth-dev

# Give current user bluetooth permissions without sudo
sudo usermod -aG bluetooth $USER || true

# 2. Python Virtual Environment & Backend Setup
echo "[2/4] Setting up Python backend virtual environment..."
cd "$(dirname "$0")/dashboard/backend"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. Next.js Frontend Setup
echo "[3/4] Installing Next.js frontend dependencies..."
cd "../frontend"
npm install
npm run build

echo "=========================================="
echo "  ✅ Setup complete!"
echo "  To start the system, run: ./start_all.sh"
echo "=========================================="
