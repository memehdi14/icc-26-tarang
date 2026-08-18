#!/usr/bin/env bash
# ==============================================================================
# TARANG RASPBERRY PI CODE UPDATE & REBUILD SCRIPT
# ==============================================================================
set -e

echo "=========================================="
echo "  🔄 Pulling Latest Tarang 'prod' Code   "
echo "=========================================="

cd "$(dirname "$0")/../.."
git fetch origin prod
git checkout prod
git pull origin prod

echo "[✓] Code updated from GitHub prod branch."

echo "Rebuilding frontend bundle..."
cd projects/tarang-rpi/dashboard/frontend
npm install
npm run build

echo "=========================================="
echo "  ✅ Update complete! Run ./start_all.sh  "
echo "=========================================="
