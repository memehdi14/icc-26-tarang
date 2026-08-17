#!/usr/bin/env python3
"""One-shot capture script: reads COM11 for ~25s, saves CSV, prints all lines."""
import serial
import time
import csv
import os
import sys

# Fix Windows console encoding for Unicode chars
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

PORT = "COM11"
BAUD = 115200
DURATION = 65  # seconds

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                       "tarang-dsp", "integration_validation", "captures", "LIVE_AI_TEST")
os.makedirs(OUT_DIR, exist_ok=True)
ts = time.strftime("%Y%m%d_%H%M%S")
CSV_PATH = os.path.join(OUT_DIR, f"LIVE_AI_TEST_{ts}.csv")

ser = serial.Serial(PORT, BAUD, timeout=0.5)
t0 = time.time()
count = 0

with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["unix_timestamp", "elapsed_sec", "raw_line"])
    while time.time() - t0 < DURATION:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace").rstrip()
        if not line:
            continue
        now = time.time()
        elapsed = now - t0
        count += 1
        print(line)
        writer.writerow([f"{now:.3f}", f"{elapsed:.3f}", line])

ser.close()
print(f"\n--- CAPTURE COMPLETE ---")
print(f"Records  : {count}")
print(f"Duration : {time.time()-t0:.1f}s")
print(f"CSV saved: {CSV_PATH}")
