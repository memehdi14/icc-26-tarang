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

import argparse
import os
import time
import csv
from datetime import datetime
import serial
import serial.tools.list_ports

DEFAULT_BAUD = 115200
DEFAULT_PORT = "COM11"
CSV_DIR = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "tarang-dsp", "integration_validation", "captures",
))

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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="serial port, for example COM11")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    parser.add_argument("--output", type=os.path.abspath)
    parser.add_argument("--verbose", action="store_true",
                        help="print every high-rate telemetry record")
    args = parser.parse_args()
    port = args.port or find_serial_port()
    baud = args.baud

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = args.output or os.path.join(CSV_DIR, f"tarang_{ts}.csv")
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)

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
    last_flush = t0
    record_count = 0
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
                record_count += 1

                if args.verbose or not line.startswith("@"):
                    print(line)

                writer.writerow([f"{now:.3f}", f"{elapsed:.3f}", line])
                if now - last_flush >= 1.0:
                    f.flush()
                    if not args.verbose:
                        print(f"[CAPTURE] {record_count} records, {elapsed:.1f}s")
                    last_flush = now

        except KeyboardInterrupt:
            print("\n[LOG] Stopped logging.")
        finally:
            ser.close()
            print(f"[LOG] File saved: {csv_path}")

if __name__ == "__main__":
    main()
