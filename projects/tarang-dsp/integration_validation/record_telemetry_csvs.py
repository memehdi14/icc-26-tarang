#!/usr/bin/env python3
"""
TARANG Telemetry Dual-CSV Stream Recorder & Converter
======================================================
Captures streaming telemetry from the TARANG board over VCOM serial (or parses raw logs)
and outputs the official two consolidated schema CSVs:
  1. <timestamp>_<test_id>_samples.csv (250Hz sample stream with sample_idx)
  2. <timestamp>_<test_id>_beats.csv   (Sparse beat events stream)

Usage:
  Live capture:
    python record_telemetry_csvs.py --port COM11 --test Test1

  Convert existing raw log / telemetry file:
    python record_telemetry_csvs.py --input telemetry_log_20260808_175237.csv --test Test1
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False


# ─────────────────────────────────────────────────────────────────────────────
# Schema Definitions
# ─────────────────────────────────────────────────────────────────────────────

SAMPLES_CSV_HEADER = [
    "sample_idx",
    "timestamp_ms",
    "ecg_raw",
    "ecg_bandpassed",
    "ecg_zscored",
    "mwi_output",
    "threshold_th1",
    "ecg_valid",
    "imu_ax",
    "imu_ay",
    "imu_az",
    "imu_valid",
    "ppg_red",
    "ppg_ir",
    "ppg_valid",
]

BEATS_CSV_HEADER = [
    "timestamp_ms",
    "r_peak_sample_idx",
    "rr_prev_ms",
    "rr_mean_5_ms",
    "rr_std_5_ms",
    "local_hr_bpm",
    "signal_quality",
    "gate_p_abnormal",
    "sv_p_v",
    "sv_p_s",
    "beat_class",
    "confidence",
    "rhythm_flags",
    "current_hr",
    "sdnn_ms",
    "rmssd_ms",
    "prr50_pct",
    "pac_burden_pct",
    "pvc_burden_pct",
]


def find_serial_port(default_port: str = "COM11") -> str:
    """Find Silicon Labs / J-Link VCOM serial port or return default."""
    if not HAS_SERIAL:
        return default_port
    ports = serial.tools.list_ports.comports()
    for p in ports:
        desc = (p.description or "").lower()
        mfg = (p.manufacturer or "").lower()
        if any(kw in desc for kw in ["silicon labs", "jlink", "efr32", "vcom"]):
            print(f"[AUTO] Found TARANG board on {p.device}: {p.description}")
            return p.device
        if "silicon" in mfg:
            print(f"[AUTO] Found TARANG board on {p.device}: {p.description}")
            return p.device
    print(f"[AUTO] No board auto-detected, falling back to {default_port}")
    return default_port


class DualCSVTelemetryRecorder:
    """
    Manages dual-CSV outputs for TARANG session:
      - <timestamp>_<test_name>_samples.csv
      - <timestamp>_<test_name>_beats.csv
    """

    def __init__(self, output_dir: str | Path, test_name: str = "Test1", timestamp_str: Optional[str] = None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        if not timestamp_str:
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.samples_path = self.output_dir / f"{timestamp_str}_{test_name}_samples.csv"
        self.beats_path = self.output_dir / f"{timestamp_str}_{test_name}_beats.csv"

        self.samples_file = open(self.samples_path, "w", newline="", encoding="utf-8")
        self.beats_file = open(self.beats_path, "w", newline="", encoding="utf-8")

        self.samples_writer = csv.writer(self.samples_file)
        self.beats_writer = csv.writer(self.beats_file)

        self.samples_writer.writerow(SAMPLES_CSV_HEADER)
        self.beats_writer.writerow(BEATS_CSV_HEADER)

        # State tracking for nearest-past lookup (IMU / PPG -> ECG sample tick)
        self.last_imu = {"ax": 0.0, "ay": 0.0, "az": 1.0, "valid": 0}
        self.last_ppg = {"red": 0, "ir": 0, "valid": 0}

        self.sample_rows_written = 0
        self.beat_rows_written = 0

        print(f"[RECORDER] Samples CSV: {self.samples_path}")
        print(f"[RECORDER] Beats CSV  : {self.beats_path}")

    def process_line(self, raw_line: str) -> bool:
        """Parse raw line and route to appropriate CSV writer."""
        line = raw_line.strip()
        if not line or line.startswith("@SCHEMA"):
            return False

        if not line.startswith("@"):
            # Check for legacy printf lines e.g. [ECG] raw=...
            return self._process_legacy_printf(line)

        fields = [f.strip() for f in line.split(",")]
        rectype = fields[0]

        if rectype == "@S" and len(fields) >= 10:
            # @S,timestamp_ms,sample_idx,ecg_raw,ecg_bandpassed,ecg_zscored,mwi_output,threshold_th1,sqi,ecg_valid
            try:
                timestamp_ms = int(fields[1])
                sample_idx = int(fields[2])
                ecg_raw = int(fields[3])
                ecg_bandpassed = float(fields[4])
                ecg_zscored = float(fields[5])
                mwi_output = float(fields[6])
                threshold_th1 = float(fields[7])
                # sqi = float(fields[8])
                ecg_valid = int(fields[9])
            except ValueError:
                return False

            row = [
                sample_idx,
                timestamp_ms,
                ecg_raw,
                ecg_bandpassed,
                ecg_zscored,
                mwi_output,
                threshold_th1,
                ecg_valid,
                self.last_imu["ax"],
                self.last_imu["ay"],
                self.last_imu["az"],
                self.last_imu["valid"],
                self.last_ppg["red"],
                self.last_ppg["ir"],
                self.last_ppg["valid"],
            ]
            self.samples_writer.writerow(row)
            self.samples_file.flush()
            self.sample_rows_written += 1
            return True

        elif rectype == "@I" and len(fields) >= 10:
            # @I,timestamp_ms,sample_idx,imu_valid,ax,ay,az,gx,gy,gz
            try:
                self.last_imu["valid"] = int(fields[3])
                self.last_imu["ax"] = float(fields[4])
                self.last_imu["ay"] = float(fields[5])
                self.last_imu["az"] = float(fields[6])
            except ValueError:
                pass
            return True

        elif rectype == "@P" and len(fields) >= 6:
            # @P,timestamp_ms,sample_idx,ppg_valid,red,ir
            try:
                self.last_ppg["valid"] = int(fields[3])
                self.last_ppg["red"] = int(fields[4])
                self.last_ppg["ir"] = int(fields[5])
            except ValueError:
                pass
            return True

        elif rectype == "@B" and len(fields) >= 16:
            # @B,timestamp_ms,r_peak_sample_idx,rr_prev_ms,rr_mean_5_ms,rr_std_5_ms,local_hr_bpm,
            #    signal_quality,gate_p_abnormal,sv_p_v,sv_p_s,beat_class,confidence,rhythm_flags,
            #    current_hr,sdnn_ms,rmssd_ms,prr50_pct
            try:
                timestamp_ms = int(fields[1])
                r_peak_sample_idx = int(fields[2])
                rr_prev_ms = float(fields[3])
                rr_mean_5_ms = float(fields[4])
                rr_std_5_ms = float(fields[5]) if len(fields) > 18 else (float(fields[4]) * 0.1) # fallback if needed
                local_hr_bpm = float(fields[6]) if len(fields) > 18 else (60000.0 / max(rr_prev_ms, 1.0))

                # Handle gate_p_abnormal, sv_p_v, sv_p_s nullability
                gate_p = float(fields[7]) if float(fields[7]) >= 0 else 0.0
                raw_p_v = float(fields[8])
                raw_p_s = float(fields[9])

                # Leave blank/empty string when SV Head did not run (negative indicator)
                sv_p_v = f"{raw_p_v:.4f}" if raw_p_v >= 0 else ""
                sv_p_s = f"{raw_p_s:.4f}" if raw_p_s >= 0 else ""

                beat_class = int(fields[10])
                confidence = int(fields[11])
                rhythm_flags = int(fields[12])
                current_hr = int(fields[13])
                sdnn_ms = int(fields[14])
                rmssd_ms = int(fields[15])
                prr50_pct = int(fields[16]) if len(fields) > 16 else 0
                pac_burden = int(fields[17]) if len(fields) > 17 else 0
                pvc_burden = int(fields[18]) if len(fields) > 18 else 0

                row = [
                    timestamp_ms,
                    r_peak_sample_idx,
                    rr_prev_ms,
                    rr_mean_5_ms,
                    rr_std_5_ms,
                    local_hr_bpm,
                    int(fields[7]), # signal_quality
                    gate_p,
                    sv_p_v,
                    sv_p_s,
                    beat_class,
                    confidence,
                    rhythm_flags,
                    current_hr,
                    sdnn_ms,
                    rmssd_ms,
                    prr50_pct,
                    pac_burden,
                    pvc_burden,
                ]
                self.beats_writer.writerow(row)
                self.beats_file.flush()
                self.beat_rows_written += 1
                return True
            except (ValueError, IndexError):
                return False

        return False

    def _process_legacy_printf(self, line: str) -> bool:
        """Fallback parser for legacy [ECG] raw=123 lines."""
        m_ecg = re.search(r"\[ECG\]\s+raw=(\d+)", line)
        if m_ecg:
            raw_val = int(m_ecg.group(1))
            now_ms = int(time.time() * 1000)
            sample_idx = self.sample_rows_written
            row = [
                sample_idx,
                now_ms,
                raw_val,
                0.0,
                0.0,
                0.0,
                0.0,
                1,
                self.last_imu["ax"],
                self.last_imu["ay"],
                self.last_imu["az"],
                self.last_imu["valid"],
                self.last_ppg["red"],
                self.last_ppg["ir"],
                self.last_ppg["valid"],
            ]
            self.samples_writer.writerow(row)
            self.samples_file.flush()
            self.sample_rows_written += 1
            return True
        return False

    def close(self):
        self.samples_file.close()
        self.beats_file.close()
        print(f"[RECORDER] Closed session. Samples recorded: {self.sample_rows_written}, Beats recorded: {self.beat_rows_written}")


def record_live(port: str, baud: int, test_name: str, output_dir: str):
    """Connect to serial port and record live stream."""
    if not HAS_SERIAL:
        print("[ERROR] pyserial is required for live recording. Run: pip install pyserial")
        sys.exit(1)

    try:
        ser = serial.Serial(port, baud, timeout=1.0)
        print(f"[SERIAL] Connected to {port} @ {baud}")
    except serial.SerialException as e:
        print(f"[SERIAL] Error connecting to {port}: {e}")
        sys.exit(1)

    recorder = DualCSVTelemetryRecorder(output_dir=output_dir, test_name=test_name)
    print("[SERIAL] Recording... Press Ctrl+C to stop.")

    try:
        while True:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace")
            recorder.process_line(line)
    except KeyboardInterrupt:
        print("\n[SERIAL] Capture stopped by user.")
    finally:
        ser.close()
        recorder.close()


def convert_input_file(input_file: str, test_name: str, output_dir: str):
    """Convert raw input log file to standard dual CSV format."""
    input_path = Path(input_file)
    if not input_path.exists():
        print(f"[ERROR] Input file not found: {input_file}")
        sys.exit(1)

    recorder = DualCSVTelemetryRecorder(output_dir=output_dir, test_name=test_name)

    print(f"[CONVERT] Reading {input_path}...")
    lines_read = 0

    with input_path.open("r", encoding="utf-8", errors="replace") as f:
        first_line = f.readline()
        f.seek(0)
        if "raw_line" in first_line:
            reader = csv.DictReader(f)
            for row in reader:
                lines_read += 1
                raw_line = row.get("raw_line", "")
                if raw_line:
                    recorder.process_line(raw_line)
        else:
            for line in f:
                lines_read += 1
                recorder.process_line(line)

    recorder.close()
    print(f"[CONVERT] Processed {lines_read} lines from input file.")


def main():
    parser = argparse.ArgumentParser(description="TARANG Telemetry Dual-CSV Stream Recorder & Converter")
    parser.add_argument("--port", type=str, help="Serial VCOM port (e.g. COM11)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--test", type=str, default="Test1", help="Test identifier (e.g. Test1, Test2)")
    parser.add_argument("--output-dir", type=str, default=".", help="Output directory for CSV files")
    parser.add_argument("--input", type=str, help="Input raw telemetry CSV file to convert")

    args = parser.parse_args()

    if args.input:
        convert_input_file(args.input, test_name=args.test, output_dir=args.output_dir)
    else:
        port = args.port or find_serial_port()
        record_live(port=port, baud=args.baud, test_name=args.test, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
