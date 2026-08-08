#!/usr/bin/env python3
"""
TARANG Simple VCOM Logger & Terminal Streamer
==============================================
Reads VCOM serial output, prints everything to terminal screen live,
AND saves everything into a timestamped CSV file simultaneously.

Usage:
  python log_vcom.py
  python log_vcom.py --port COM11
"""

import sys
import os
import time
import csv
from datetime import datetime
import serial
import serial.tools.list_ports

DEFAULT_BAUD = 115200
DEFAULT_PORT = "COM11"
CSV_DIR = os.path.dirname(os.path.abspath(__file__))

def find_serial_port():
    ports = serial.tools.list_ports.comports()
    for p in ports:
        desc = (p.description or "").lower()
        mfg  = (p.manufacturer or "").lower()
        if any(kw in desc for kw in ["silicon labs", "jlink", "efr32", "vcom"]):
            print(f"[AUTO] Found TARANG board on {p.device}: {p.description}")
            return p.device
        if "silicon" in mfg:
            print(f"[AUTO] Found TARANG board on {p.device}: {p.description}")
            return p.device
    print(f"[AUTO] No board auto-detected, using {DEFAULT_PORT}")
    return DEFAULT_PORT

def main():
    port = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("COM") else find_serial_port()
    baud = DEFAULT_BAUD

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(CSV_DIR, f"vcom_log_{ts}.csv")

    print("=" * 60)
    print(f" TARANG VCOM LOGGER & TERMINAL STREAMER")
    print(f" Port : {port} @ {baud} baud")
    print(f" CSV  : {csv_path}")
    print("=" * 60)
    print("Press Ctrl+C to stop logging.\n")

    try:
        ser = serial.Serial(port, baud, timeout=1)
    except serial.SerialException as e:
        print(f"[ERROR] Could not open {port}: {e}")
        print("[TIP] Close Simplicity Studio Serial Console or other terminal programs accessing the port.")
        sys.exit(1)

    t0 = time.time()
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["unix_timestamp", "elapsed_sec", "raw_line"])
        f.flush()

        try:
            while True:
                line_bytes = ser.readline()
                if not line_bytes:
                    continue
                line = line_bytes.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue

                now = time.time()
                elapsed = now - t0

                # 1. Print live to screen
                print(line)

                # 2. Write to CSV file immediately
                writer.writerow([f"{now:.3f}", f"{elapsed:.3f}", line])
                f.flush()

        except KeyboardInterrupt:
            print("\n[LOG] Stopped logging.")
        finally:
            ser.close()
            print(f"[LOG] File saved: {csv_path}")

if __name__ == "__main__":
    main()
