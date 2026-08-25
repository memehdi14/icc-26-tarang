#!/usr/bin/env python3
"""
TARANG AD8232 (IADC0) Live Terminal ECG Validator & CSV Logger
==============================================================
Streams live ECG data from the TARANG board over VCOM serial, prints real-time
telemetry metrics in the terminal, and logs the full session to a timestamped CSV.

Hardware Chain:
  AD8232 AFE -> IADC0 (AIN0 Pad) @ 250 Hz (LETIMER0 -> PRS CH0 -> LDMA Ping-Pong)

Validated Metrics:
  - Sample rate (verifies 250.0 Hz timer accuracy)
  - 12-bit ADC range & Lead-Off detection (0 or 4095 saturation)
  - Clean filtered signal & MWI (Moving Window Integrator)
  - R-Peak detections, instantaneous HR (bpm), and RR intervals (ms)
  - ISSUE-DSP-04 diagnostic (T-wave double-trigger & suspicious beat rate)

Usage:
  python validate_ecg.py
  python validate_ecg.py --id TRG-2026-0005
  python validate_ecg.py --port COM11 --id KD
  python validate_ecg.py --replay captures/kedarecg/kedarecg_20260820_030110.csv
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
from vcom_stream import VCOMTelemetryStream, ECGFrame, BeatEvent, auto_detect_serial_port

INTEGRATION_VALIDATION_DIR = Path(__file__).resolve().parent
CAPTURES_BASE = INTEGRATION_VALIDATION_DIR / "captures"
PLOT_SCRIPT = INTEGRATION_VALIDATION_DIR / "plot_tarang.py"


def build_csv_path(volunteer_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", volunteer_id.strip()) or "VOLUNTEER"
    vol_dir = CAPTURES_BASE / safe_id
    vol_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return vol_dir / f"{safe_id}_ecg_{ts}.csv"


def write_csv_header(f, writer, volunteer_id: str, port: str, baud: int):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    f.write("# TARANG AD8232 (IADC0) ECG Capture\n")
    f.write(f"# Date: {ts}\n")
    f.write(f"# Port: {port} @ {baud} baud\n")
    f.write(f"# Volunteer ID: {volunteer_id}\n")
    f.write(f"# Sensor: AD8232 (IADC0 @ 250 Hz)\n")
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
    parser = argparse.ArgumentParser(description="TARANG AD8232 (IADC0) Live Terminal ECG Validator & Logger")
    parser.add_argument("--port", help="Serial port (e.g. COM11, auto-detected if omitted)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--id", "--volunteer-id", dest="volunteer_id", default="ECG_TEST",
                        help="Volunteer / Test ID (default: ECG_TEST)")
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
    print("  TARANG SENSOR 1 VALIDATION: AD8232 ECG (IADC0 @ 250 Hz)")
    print(f"  ID        : {args.volunteer_id}")
    print(f"  Source    : {'REPLAY: ' + Path(args.replay).name if args.replay else f'{port} @ {args.baud} baud'}")
    print(f"  CSV Log   : {csv_path}")
    print("=" * 80)
    print("  Target Sampling Rate : 250.0 Hz (LETIMER0 Compare=130 on LFRCO 32768 Hz)")
    print("  Press Ctrl+C at any time to finish and generate session summary.\n")

    t0 = time.time()
    last_ticker = t0
    last_flush = t0
    record_count = 0
    ecg_samples = 0
    total_beats = 0
    suspicious_beats = 0
    sat_high_count = 0
    sat_low_count = 0

    last_raw = 2048
    last_clean = 2048
    last_mwi = 0.0
    last_th = 0.0
    last_hr = 0.0
    last_rr = 0.0
    last_sqi = 1.0
    last_beat_info = ""

    sample_timestamps = collections.deque(maxlen=250)
    recent_raw_window = collections.deque(maxlen=250)
    valid_rr_window = collections.deque(maxlen=5)
    all_raw_samples = []
    all_clean_samples = []
    all_rr_intervals = []

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

                ecg_frames, _, _, beat, _, debug_text = stream.parse_line(line)

                if ecg_frames:
                    for frame in ecg_frames:
                        ecg_samples += 1
                        sample_timestamps.append(now)
                        recent_raw_window.append(frame.raw_adc)
                        all_raw_samples.append(frame.raw_adc)
                        all_clean_samples.append(frame.clean_adc)

                        last_raw = frame.raw_adc
                        last_clean = frame.clean_adc
                        last_mwi = frame.mwi
                        last_th = frame.threshold

                        if frame.raw_adc >= 4080:
                            sat_high_count += 1
                        elif frame.raw_adc <= 15:
                            sat_low_count += 1

                # Check rolling lead status (last 1s)
                recent_railed = any(s >= 4080 or s <= 15 for s in recent_raw_window) if recent_raw_window else False

                if beat:
                    # Bug 4: Gate detection on lead status — ignore beats if electrodes are railed/disconnected
                    if not recent_railed and 300.0 <= beat.rr_ms <= 2000.0:
                        total_beats += 1
                        all_rr_intervals.append(beat.rr_ms)
                        valid_rr_window.append(beat.rr_ms)

                        # Bug 1 & 4: Compute smoothed HR from median of last 3-5 valid RR intervals
                        sorted_rr = sorted(valid_rr_window)
                        med_rr = sorted_rr[len(sorted_rr) // 2]
                        smoothed_hr = 60000.0 / med_rr if med_rr > 0 else beat.hr_bpm
                        last_hr = smoothed_hr
                        last_rr = beat.rr_ms
                        last_sqi = beat.sqi

                        last_beat_info = f"HR={smoothed_hr:5.1f}bpm RR={beat.rr_ms:4.0f}ms [{beat.cls_name}]"
                        if beat.rr_ms < 350.0:
                            suspicious_beats += 1
                    elif recent_railed:
                        # Dropped during lead-off
                        pass

                # Live terminal update every 0.5s
                if now - last_ticker >= 0.5:
                    last_ticker = now

                    # Measure actual sample rate
                    if len(sample_timestamps) >= 10:
                        dt = sample_timestamps[-1] - sample_timestamps[0]
                        hz = (len(sample_timestamps) - 1) / dt if dt > 0 else 0.0
                    else:
                        hz = 0.0

                    lead_state = "RAILED" if recent_railed else "OK (ATTACHED)"
                    susp_pct = (suspicious_beats / max(1, total_beats)) * 100.0

                    summary = (
                        f"\r[{elapsed:5.1f}s] "
                        f"ECG: {ecg_samples:5d} ({hz:5.1f} Hz) | "
                        f"ADC Raw: {last_raw:4d} Clean: {last_clean:4d} MWI: {last_mwi:4.0f} | "
                        f"Lead: {lead_state:<13} | "
                        f"Beats: {total_beats:3d} (Susp: {suspicious_beats} / {susp_pct:4.1f}%)"
                    )
                    if last_beat_info:
                        summary += f" | {last_beat_info}"
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
            susp_pct = (suspicious_beats / max(1, total_beats)) * 100.0
            avg_hz = ecg_samples / max(0.1, duration)

            # Step 1: Baseline stability metrics (overall mean, first 2s, last 2s)
            overall_mean = (sum(all_raw_samples) / len(all_raw_samples)) if all_raw_samples else 0.0
            n_2s = int(250 * 2)  # 500 samples @ 250 Hz
            first_2s_mean = (sum(all_raw_samples[:n_2s]) / len(all_raw_samples[:n_2s])) if len(all_raw_samples) >= n_2s else overall_mean
            last_2s_mean = (sum(all_raw_samples[-n_2s:]) / len(all_raw_samples[-n_2s:])) if len(all_raw_samples) >= n_2s else overall_mean
            drift_delta = abs(last_2s_mean - first_2s_mean)

            # Bug 2: Filter valid RR intervals (300ms to 2000ms) to prevent ZeroDivisionError
            valid_rr = [r for r in all_rr_intervals if 300.0 <= r <= 2000.0]
            mean_hr = (sum(60000.0 / r for r in valid_rr) / len(valid_rr)) if valid_rr else 0.0
            mean_rr = (sum(valid_rr) / len(valid_rr)) if valid_rr else 0.0
            min_rr = min(valid_rr) if valid_rr else 0.0
            max_rr = max(valid_rr) if valid_rr else 0.0

            print("\n" + "=" * 80)
            print("  TARANG ECG VALIDATION SESSION SUMMARY (Step 1 & 2)")
            print("=" * 80)
            print(f"  Volunteer ID         : {args.volunteer_id}")
            print(f"  Duration             : {duration:.1f} seconds")
            print(f"  Total ECG Samples    : {ecg_samples} (Measured Average: {avg_hz:.2f} Hz, Target: 250.0 Hz)")
            print("-" * 80)
            print(f"  [BASELINE DRIFT METRICS - Issue 1.1 & 1.2]")
            print(f"    Raw ADC Mean (Total): {overall_mean:.1f} (Ideal: ~2048 for centered 12-bit)")
            print(f"    First 2s Mean       : {first_2s_mean:.1f}")
            print(f"    Last 2s Mean        : {last_2s_mean:.1f}")
            print(f"    Baseline Drift (|Delta|): {drift_delta:.1f} counts")
            print("-" * 80)
            print(f"  [BEAT DETECTION & BPM METRICS - Step 2]")
            print(f"    Detected Beats      : {total_beats}")
            print(f"    Average Heart Rate  : {mean_hr:.1f} bpm")
            print(f"    RR Interval (Mean)  : {mean_rr:.1f} ms (Min: {min_rr:.0f} ms, Max: {max_rr:.0f} ms)")
            print(f"    Suspicious Beats    : {suspicious_beats} ({susp_pct:.2f}% of total beats) [Target: <0.1%]")
            print(f"    Rail Saturation     : High={sat_high_count}, Low={sat_low_count}")
            print("-" * 80)
            print(f"  CSV Saved To         : {csv_path}")
            print("=" * 80)

            # Issue Diagnostic Flags
            if abs(avg_hz - 250.0) > 10.0 and not args.replay:
                print(f"  [!] WARNING: Measured rate {avg_hz:.1f} Hz deviates from 250 Hz clock!")
            if susp_pct > 10.0:
                print(f"  [!] ALERT [ISSUE-DSP-04]: Suspicious beat rate is {susp_pct:.1f}% (> 10% threshold) - check T-wave detector!")
            if sat_high_count > 50 or sat_low_count > 50:
                print(f"  [!] ALERT: Significant electrode rail saturation / lead-off detected!")
            print("=" * 80 + "\n")

    if ecg_samples > 0 and not args.no_plot and not args.replay:
        generate_plots(csv_path, args.volunteer_id)


if __name__ == "__main__":
    main()
