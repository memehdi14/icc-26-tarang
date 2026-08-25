#!/usr/bin/env python3
"""
TARANG MAX30102 Live Terminal PPG Validator & CSV Logger
========================================================
Streams live PPG optical data from the TARANG board over VCOM serial, prints real-time
telemetry metrics in the terminal, and logs the full session to a timestamped CSV.

Hardware Chain:
  MAX30102 Optical Sensor -> I2C (`sl_i2cspm_mikroe` PC05/PC07) @ 100 Hz

Validated Metrics:
  - Sample rate (verifies 100.0 Hz timer accuracy)
  - Red & Infrared channel counts
  - Finger presence detection (ambient/zero vs pulse signal)
  - AC/DC ratio & estimated SpO2 (%)
  - I2C bus error / packet drop alert (ISSUE-FW-01 / ISSUE-SENSOR-01)

Usage:
  python validate_ppg.py
  python validate_ppg.py --id TRG-2026-0005
  python validate_ppg.py --port COM11 --id KD
  python validate_ppg.py --replay captures/KEDAR01/KEDAR01_20260820_024345.csv
"""

import argparse
import collections
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vcom_stream import VCOMTelemetryStream, PPGFrame, auto_detect_serial_port

INTEGRATION_VALIDATION_DIR = Path(__file__).resolve().parent
CAPTURES_BASE = INTEGRATION_VALIDATION_DIR / "captures"
PLOT_SCRIPT = INTEGRATION_VALIDATION_DIR / "plot_tarang.py"


def build_csv_path(volunteer_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", volunteer_id.strip()) or "VOLUNTEER"
    vol_dir = CAPTURES_BASE / safe_id
    vol_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return vol_dir / f"{safe_id}_ppg_{ts}.csv"


def write_csv_header(f, writer, volunteer_id: str, port: str, baud: int):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    f.write("# TARANG MAX30102 PPG Capture\n")
    f.write(f"# Date: {ts}\n")
    f.write(f"# Port: {port} @ {baud} baud\n")
    f.write(f"# Volunteer ID: {volunteer_id}\n")
    f.write(f"# Sensor: MAX30102 PPG (I2C @ 100 Hz)\n")
    f.write("#\n")
    writer.writerow(["unix_timestamp", "elapsed_sec", "raw_line"])
    f.flush()


def generate_plots(csv_path: Path, volunteer_id: str):
    if not PLOT_SCRIPT.exists():
        return
    try:
        output_dir = INTEGRATION_VALIDATION_DIR / "plots" / volunteer_id / csv_path.stem
        command = [
            sys.executable,
            str(PLOT_SCRIPT),
            str(csv_path),
            "--output-dir",
            str(output_dir),
            "--no-open",
        ]
        print(f"\n[PLOT] Generating validation plots in {output_dir} ...")
        import subprocess
        subprocess.run(command, check=False, timeout=25)
    except Exception as e:
        print(f"[PLOT] Plot generation note: {e}")


def main():
    parser = argparse.ArgumentParser(description="TARANG MAX30102 Live Terminal PPG Validator & Logger")
    parser.add_argument("--port", help="Serial port (e.g. COM11, auto-detected if omitted)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--id", "--volunteer-id", dest="volunteer_id", default="PPG_TEST",
                        help="Volunteer / Test ID (default: PPG_TEST)")
    parser.add_argument("--output", type=os.path.abspath, help="Override output CSV file path")
    parser.add_argument("--replay", help="Replay capture CSV file instead of live VCOM")
    parser.add_argument("--duration", type=float, default=0.0, help="Capture duration in seconds (0 = run until Ctrl+C)")
    parser.add_argument("--no-plot", action="store_true", help="Skip automatic plot generation")
    args = parser.parse_args()

    port = args.port or auto_detect_serial_port() or "COM11"
    csv_path = Path(args.output) if args.output else build_csv_path(args.volunteer_id)

    stream = VCOMTelemetryStream(port=port, baud=args.baud, replay_file=args.replay)
    try:
        stream.open()
    except Exception as e:
        print(f"[ERROR] Could not start stream: {e}")
        sys.exit(1)

    print("=" * 80)
    print("  TARANG SENSOR 2 VALIDATION: MAX30102 PPG (I2C @ 100 Hz)")
    print(f"  ID        : {args.volunteer_id}")
    print(f"  Source    : {'REPLAY: ' + Path(args.replay).name if args.replay else f'{port} @ {args.baud} baud'}")
    print(f"  CSV Log   : {csv_path}")
    print("=" * 80)
    print("  Target Sampling Rate : 100.0 Hz")
    print("  Press Ctrl+C at any time to finish and generate session summary.\n")

    t0 = time.time()
    last_ticker = t0
    last_flush = t0
    record_count = 0
    ppg_samples = 0
    zero_reads = 0

    last_red = 0
    last_ir = 0
    estimated_spo2 = 0.0

    sample_timestamps = collections.deque(maxlen=100)
    red_history = collections.deque(maxlen=50)
    ir_history = collections.deque(maxlen=50)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        write_csv_header(f, writer, args.volunteer_id, port, args.baud)

        try:
            for line in stream.stream_lines():
                now = time.time()
                elapsed = now - t0
                if args.duration > 0 and elapsed >= args.duration:
                    print(f"\n[LOG] Reached target duration of {args.duration:.1f}s.")
                    break

                record_count += 1
                writer.writerow([f"{now:.3f}", f"{elapsed:.3f}", line])

                _, ppg_frames, _, _, _, debug_text = stream.parse_line(line)

                if ppg_frames:
                    for frame in ppg_frames:
                        ppg_samples += 1
                        sample_timestamps.append(now)
                        last_red = frame.red
                        last_ir = frame.ir
                        red_history.append(frame.red)
                        ir_history.append(frame.ir)

                        if frame.red < 1000 or frame.ir < 1000:
                            zero_reads += 1

                # Live terminal update every 0.5s
                if now - last_ticker >= 0.5:
                    last_ticker = now

                    # Measure actual sample rate
                    if len(sample_timestamps) >= 10:
                        dt = sample_timestamps[-1] - sample_timestamps[0]
                        hz = (len(sample_timestamps) - 1) / dt if dt > 0 else 0.0
                    else:
                        hz = 0.0

                    is_finger_on = last_ir > 10000 and last_red > 10000
                    contact_state = "FINGER DETECTED" if is_finger_on else "NO CONTACT / OFF-FINGER"

                    # Calculate SpO2 estimate if finger is present
                    if is_finger_on and len(ir_history) >= 20:
                        ir_dc = sum(ir_history) / len(ir_history)
                        red_dc = sum(red_history) / len(red_history)
                        ir_ac = max(ir_history) - min(ir_history)
                        red_ac = max(red_history) - min(red_history)
                        if ir_dc > 0 and red_dc > 0 and ir_ac > 0:
                            r_ratio = (red_ac / red_dc) / (ir_ac / ir_dc)
                            spo2_calc = 110.0 - 25.0 * r_ratio
                            estimated_spo2 = max(70.0, min(100.0, spo2_calc))
                    else:
                        estimated_spo2 = 0.0

                    spo2_str = f"{estimated_spo2:5.1f}%" if (is_finger_on and estimated_spo2 > 0) else "--.-%"

                    summary = (
                        f"\r[{elapsed:5.1f}s] "
                        f"PPG: {ppg_samples:5d} ({hz:5.1f} Hz) | "
                        f"Red: {last_red:7d}  IR: {last_ir:7d} | "
                        f"SpO2: {spo2_str} | "
                        f"Contact: {contact_state:<22} | "
                        f"Zero reads: {zero_reads}"
                    )
                    sys.stdout.write(summary)
                    sys.stdout.flush()

                if now - last_flush >= 1.0:
                    f.flush()
                    last_flush = now

        except KeyboardInterrupt:
            print("\n\n[LOG] Capture stopped by operator (Ctrl+C).")
        finally:
            stream.close()
            duration = time.time() - t0
            avg_hz = ppg_samples / max(0.1, duration)

            print("\n" + "=" * 80)
            print("  MAX30102 PPG VALIDATION SESSION SUMMARY")
            print("=" * 80)
            print(f"  Volunteer ID       : {args.volunteer_id}")
            print(f"  Duration           : {duration:.1f} seconds")
            print(f"  Total PPG Samples  : {ppg_samples} (Measured Average: {avg_hz:.2f} Hz, Target: 100.0 Hz)")
            print(f"  Zero / Off Reads   : {zero_reads}")
            print(f"  CSV Saved To       : {csv_path}")
            print("=" * 80)

            # Issue Diagnostic Flags
            if ppg_samples == 0:
                print("  [!] ALERT [ISSUE-SENSOR-01]: ZERO PPG PACKETS RECEIVED!")
                print("      Check MAX30102 power, I2C bus wiring (PC05/PC07), and sensor init status.")
            elif abs(avg_hz - 100.0) > 10.0 and not args.replay:
                print(f"  [!] WARNING: Measured rate {avg_hz:.1f} Hz deviates from 100 Hz target clock!")
            print("=" * 80 + "\n")

    if ppg_samples > 0 and not args.no_plot and not args.replay:
        generate_plots(csv_path, args.volunteer_id)


if __name__ == "__main__":
    main()
