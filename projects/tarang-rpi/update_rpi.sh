#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_DIR="$SCRIPT_DIR/dashboard/backend"
FRONTEND_DIR="$SCRIPT_DIR/dashboard/frontend"
PYTHON="$BACKEND_DIR/venv/bin/python"

cd "$REPO_ROOT"
if [[ -n "$(git status --porcelain)" ]]; then
    echo "[ERROR] Working tree has local changes. Commit or stash them before updating."
    exit 1
fi

echo "Pulling the current branch with fast-forward only..."
git pull --ff-only

if [[ ! -x "$PYTHON" ]]; then
    echo "[ERROR] Python environment missing. Run $SCRIPT_DIR/setup_rpi.sh first."
    exit 1
fi

echo "Updating backend dependencies and running tests..."
"$PYTHON" -m pip install -r "$BACKEND_DIR/requirements.txt"
cd "$BACKEND_DIR"
"$PYTHON" -m unittest discover -s tests -v

echo "Rebuilding frontend..."
cd "$FRONTEND_DIR"
npm ci
npm run build

echo "Update complete. Restart Tarang services to use the new build."
