#!/usr/bin/env python3
"""
TARANG MPU6050 Live Terminal IMU Validator & CSV Logger
=======================================================
Streams live 6-axis IMU data from the TARANG board over VCOM serial, prints real-time
telemetry metrics in the terminal, and logs the full session to a timestamped CSV.

Hardware Chain:
  MPU6050 IMU (6-DOF) -> I2C (`sl_i2cspm_mikroe` PC05/PC07) @ 100 Hz

Validated Metrics:
  - Sample rate (verifies 100.0 Hz timer accuracy)
  - 3-axis Accelerometer ($A_x, A_y, A_z$ in $g$) and gravity magnitude norm $\approx 1.0g$
  - 3-axis Gyroscope ($G_x, G_y, G_z$ in $\text{deg/s}$)
  - Motion energy / Activity classifier (RESTING vs MOVING vs RUNNING)
  - Gating state for adaptive NLMS motion artifact filter

Usage:
  python validate_imu.py
  python validate_imu.py --id TRG-2026-0005
  python validate_imu.py --port COM11 --id KD
  python validate_imu.py --replay captures/KEDAR01/KEDAR01_20260820_024345.csv
"""

import argparse
import collections
import csv
import json
import math
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vcom_stream import VCOMTelemetryStream, IMUFrame, auto_detect_serial_port

INTEGRATION_VALIDATION_DIR = Path(__file__).resolve().parent
CAPTURES_BASE = INTEGRATION_VALIDATION_DIR / "captures"
PLOT_SCRIPT = INTEGRATION_VALIDATION_DIR / "plot_tarang.py"


def build_csv_path(volunteer_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", volunteer_id.strip()) or "VOLUNTEER"
    vol_dir = CAPTURES_BASE / safe_id
    vol_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return vol_dir / f"{safe_id}_imu_{ts}.csv"


def write_csv_header(f, writer, volunteer_id: str, port: str, baud: int):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    f.write("# TARANG MPU6050 IMU Capture\n")
    f.write(f"# Date: {ts}\n")
    f.write(f"# Port: {port} @ {baud} baud\n")
    f.write(f"# Volunteer ID: {volunteer_id}\n")
    f.write(f"# Sensor: MPU6050 6-DOF IMU (I2C @ 100 Hz)\n")
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
    parser = argparse.ArgumentParser(description="TARANG MPU6050 Live Terminal IMU Validator & Logger")
    parser.add_argument("--port", help="Serial port (e.g. COM11, auto-detected if omitted)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--id", "--volunteer-id", dest="volunteer_id", default="IMU_TEST",
                        help="Volunteer / Test ID (default: IMU_TEST)")
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
    print("  TARANG SENSOR 3 VALIDATION: MPU6050 IMU (I2C @ 100 Hz)")
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
    imu_samples = 0

    last_ax, last_ay, last_az = 0.0, 0.0, 1.0
    last_gx, last_gy, last_gz = 0.0, 0.0, 0.0
    last_energy = 0.0

    sample_timestamps = collections.deque(maxlen=100)
    accel_mag_history = collections.deque(maxlen=50)

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

                _, _, imu_frames, _, _, debug_text = stream.parse_line(line)

                if imu_frames:
                    for frame in imu_frames:
                        imu_samples += 1
                        sample_timestamps.append(now)
                        last_ax, last_ay, last_az = frame.ax, frame.ay, frame.az
                        last_gx, last_gy, last_gz = frame.gx, frame.gy, frame.gz
                        last_energy = frame.motion_energy

                        mag = math.sqrt(frame.ax**2 + frame.ay**2 + frame.az**2)
                        accel_mag_history.append(mag)

                # Live terminal update every 0.5s
                if now - last_ticker >= 0.5:
                    last_ticker = now

                    # Measure actual sample rate
                    if len(sample_timestamps) >= 10:
                        dt = sample_timestamps[-1] - sample_timestamps[0]
                        hz = (len(sample_timestamps) - 1) / dt if dt > 0 else 0.0
                    else:
                        hz = 0.0

                    accel_norm = math.sqrt(last_ax**2 + last_ay**2 + last_az**2)

                    # Compute standard deviation of magnitude over recent window to detect motion
                    if len(accel_mag_history) >= 10:
                        mean_mag = sum(accel_mag_history) / len(accel_mag_history)
                        var_mag = sum((x - mean_mag)**2 for x in accel_mag_history) / len(accel_mag_history)
                        std_mag = math.sqrt(var_mag)
                    else:
                        std_mag = 0.0

                    if std_mag < 0.05:
                        motion_state = "RESTING (STATIONARY)"
                    elif std_mag < 0.20:
                        motion_state = "MODERATE MOTION"
                    else:
                        motion_state = "HIGH MOTION / RUNNING"

                    summary = (
                        f"\r[{elapsed:5.1f}s] "
                        f"IMU: {imu_samples:5d} ({hz:5.1f} Hz) | "
                        f"Accel(g): [{last_ax:+5.2f}, {last_ay:+5.2f}, {last_az:+5.2f}] Norm: {accel_norm:4.2f}g | "
                        f"Gyro: [{last_gx:+5.1f}, {last_gy:+5.1f}, {last_gz:+5.1f}] | "
                        f"State: {motion_state}"
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
            avg_hz = imu_samples / max(0.1, duration)

            print("\n" + "=" * 80)
            print("  MPU6050 IMU VALIDATION SESSION SUMMARY")
            print("=" * 80)
            print(f"  Volunteer ID       : {args.volunteer_id}")
            print(f"  Duration           : {duration:.1f} seconds")
            print(f"  Total IMU Samples  : {imu_samples} (Measured Average: {avg_hz:.2f} Hz, Target: 100.0 Hz)")
            print(f"  Final Accel Vector : Ax={last_ax:+.3f}g, Ay={last_ay:+.3f}g, Az={last_az:+.3f}g")
            print(f"  CSV Saved To       : {csv_path}")
            print("=" * 80)

            # Issue Diagnostic Flags
            if imu_samples == 0:
                print("  [!] ALERT: ZERO IMU PACKETS RECEIVED! Check MPU6050 I2C connection.")
            elif abs(avg_hz - 100.0) > 10.0 and not args.replay:
                print(f"  [!] WARNING: Measured rate {avg_hz:.1f} Hz deviates from 100 Hz target clock!")
            print("=" * 80 + "\n")

    if imu_samples > 0 and not args.no_plot and not args.replay:
        generate_plots(csv_path, args.volunteer_id)


if __name__ == "__main__":
    main()
