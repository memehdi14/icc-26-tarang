#!/usr/bin/env python3
"""
TARANG VCOM Logger Forwarder
Allows running log_vcom.py directly from the integration_validation directory.
"""
import os
import sys
import subprocess

TARGET_SCRIPT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "tarang-firmware", "Integration", "log_vcom.py"
))

if __name__ == "__main__":
    if not os.path.isfile(TARGET_SCRIPT):
        print(f"[ERROR] Target script not found at: {TARGET_SCRIPT}")
        sys.exit(1)
    
    try:
        cmd = [sys.executable, TARGET_SCRIPT] + sys.argv[1:]
        sys.exit(subprocess.call(cmd))
    except KeyboardInterrupt:
        sys.exit(0)
