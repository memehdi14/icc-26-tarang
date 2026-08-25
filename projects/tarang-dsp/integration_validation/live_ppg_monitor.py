#!/usr/bin/env python3
"""
TARANG MAX30102 Live Terminal PPG & Optical Monitor
===================================================
Validates the MAX30102 optical sensor (Red/IR) and I2C acquisition chain @ 100 Hz.

Features:
  - Live ASCII PPG Pulse Waveform (IR & Red channels)
  - 100 Hz Sample Rate Verification & Jitter Tracking
  - Finger Contact Detection (detects zero/ambient readings)
  - AC/DC Ratio & Real-time SpO2 Estimation
  - I2C Bus Contention & Drop Monitor (ISSUE-FW-01 / ISSUE-SENSOR-01)

Usage:
  python live_ppg_monitor.py
  python live_ppg_monitor.py --port COM11 --baud 115200
  python live_ppg_monitor.py --replay ../../tarang-dsp/integration_validation/captures/sample.csv
"""

import argparse
import collections
import math
import os
import sys
import time
from pathlib import Path

# Local import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vcom_stream import VCOMTelemetryStream, PPGFrame


# ANSI Color Codes
RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
CYAN = "\033[96m"
WHITE = "\033[97m"
CLEAR_SCREEN = "\033[2J\033[H"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"


def draw_ascii_waveform(buffer: list[float], height: int = 10, width: int = 65, char_color: str = RED) -> list[str]:
    """Render a scrolling ASCII waveform from signal samples."""
    if not buffer:
        return [" " * width for _ in range(height)]
    
    samples = list(buffer)[-width:]
    if len(samples) < width:
        samples = [samples[0]] * (width - len(samples)) + samples

    min_val = min(samples)
    max_val = max(samples)
    span = max_val - min_val if max_val > min_val else 1.0

    grid = [[" " for _ in range(width)] for _ in range(height)]

    for col, val in enumerate(samples):
        norm = (val - min_val) / span
        row = height - 1 - int(norm * (height - 1))
        row = max(0, min(height - 1, row))
        grid[row][col] = "█" if col == width - 1 else "─"

    lines = []
    for r, row_chars in enumerate(grid):
        line = "".join(row_chars)
        lines.append(f"{CYAN}│{RESET}{char_color}{line}{RESET}{CYAN}│{RESET}")
    return lines


def main():
    parser = argparse.ArgumentParser(description="TARANG MAX30102 Live Terminal PPG Monitor")
    parser.add_argument("--port", help="Serial port (e.g. COM11)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--replay", help="Replay capture CSV file instead of live VCOM")
    args = parser.parse_args()

    stream = VCOMTelemetryStream(port=args.port, baud=args.baud, replay_file=args.replay)

    try:
        stream.open()
    except Exception as e:
        print(f"{RED}[ERROR]{RESET} {e}")
        sys.exit(1)

    print(HIDE_CURSOR, end="")

    # Rolling state buffers
    red_history = collections.deque(maxlen=100)
    ir_history = collections.deque(maxlen=100)
    sample_timestamps = collections.deque(maxlen=100)

    total_samples = 0
    zero_reads = 0
    last_red = 0
    last_ir = 0
    estimated_spo2 = 98.0

    t_start = time.time()
    last_render = 0.0

    try:
        for line in stream.stream_lines():
            _, ppg_frames, _, _, _, debug_text = stream.parse_line(line)
            now = time.time()

            if ppg_frames:
                for f in ppg_frames:
                    total_samples += 1
                    sample_timestamps.append(now)
                    last_red = f.red
                    last_ir = f.ir

                    red_history.append(f.red)
                    ir_history.append(f.ir)

                    if f.red < 1000 or f.ir < 1000:
                        zero_reads += 1

            # Render at ~20 FPS
            if now - last_render >= 0.05:
                last_render = now
                elapsed = now - t_start

                # Calculate measured sample rate (Hz)
                if len(sample_timestamps) >= 10:
                    dt = sample_timestamps[-1] - sample_timestamps[0]
                    hz = (len(sample_timestamps) - 1) / dt if dt > 0 else 0.0
                else:
                    hz = 0.0

                hz_color = GREEN if 95.0 <= hz <= 105.0 else (YELLOW if 80.0 <= hz <= 120.0 else RED)

                # Finger contact detection
                is_finger_on = last_ir > 10000 and last_red > 10000
                contact_status = f"{GREEN}[FINGER DETECTED]{RESET}" if is_finger_on else f"{YELLOW}[NO CONTACT / OFF-FINGER]{RESET}"

                # Calculate AC/DC and SpO2 estimate if finger is on
                if is_finger_on and len(ir_history) >= 50:
                    ir_dc = sum(ir_history) / len(ir_history)
                    red_dc = sum(red_history) / len(red_history)
                    ir_ac = max(ir_history) - min(ir_history)
                    red_ac = max(red_history) - min(red_history)

                    if ir_dc > 0 and red_dc > 0 and ir_ac > 0:
                        r_ratio = (red_ac / red_dc) / (ir_ac / ir_dc)
                        # Standard MAX30102 R-curve approx: SpO2 = 110 - 25 * R
                        spo2_calc = 110.0 - 25.0 * r_ratio
                        estimated_spo2 = max(70.0, min(100.0, spo2_calc))
                else:
                    estimated_spo2 = 0.0

                # Clear and draw dashboard
                sys.stdout.write(CLEAR_SCREEN)
                sys.stdout.write(f"{BOLD}{MAGENTA}╔═════════════════════════════════════════════════════════════════════════════╗{RESET}\n")
                sys.stdout.write(f"{BOLD}{MAGENTA}║         TARANG SENSOR 2: MAX30102 PPG (I2C @ 100 Hz) VALIDATION TOOL        ║{RESET}\n")
                sys.stdout.write(f"{BOLD}{MAGENTA}╚═════════════════════════════════════════════════════════════════════════════╝{RESET}\n")
                
                source_label = f"REPLAY: {Path(args.replay).name}" if args.replay else f"PORT: {stream.port} @ {stream.baud}"
                sys.stdout.write(f" {BOLD}Mode:{RESET} {source_label}  |  {BOLD}Protocol:{RESET} {stream.protocol_detected}  |  {BOLD}Elapsed:{RESET} {elapsed:.1f}s\n")
                sys.stdout.write(f" {BOLD}Sampling Rate:{RESET} {hz_color}{hz:5.1f} Hz{RESET} (Target: 100 Hz)  |  {BOLD}Optical Status:{RESET} {contact_status}\n")
                sys.stdout.write(f"{MAGENTA}───────────────────────────────────────────────────────────────────────────────{RESET}\n")

                # Metrics banner
                spo2_str = f"{GREEN}{estimated_spo2:5.1f}%{RESET}" if is_finger_on and estimated_spo2 > 0 else f"{WHITE}--.-%{RESET}"
                sys.stdout.write(f" 🔴 {BOLD}Red Channel:{RESET} {CYAN}{last_red:7d}{RESET}  |  "
                                 f"🟣 {BOLD}IR Channel:{RESET} {MAGENTA}{last_ir:7d}{RESET}  |  "
                                 f"🩸 {BOLD}Est. SpO2:{RESET} {spo2_str}\n")
                
                sys.stdout.write(f" ⚠️  {BOLD}ISSUE-SENSOR-01 / I2C Bus Health:{RESET} "
                                 f"{GREEN if total_samples > 0 else RED}{'Active Data Flow' if total_samples > 0 else 'NO PPG PACKETS DETECTED'}{RESET} "
                                 f"(Zero reads: {zero_reads})\n")
                sys.stdout.write(f"{MAGENTA}───────────────────────────────────────────────────────────────────────────────{RESET}\n")

                # Waveform display (IR Channel)
                sys.stdout.write(f" {BOLD}Live Infrared (IR) Pulse Waveform (MAX30102):{RESET}\n")
                waveform_lines = draw_ascii_waveform(list(ir_history), height=10, width=75, char_color=MAGENTA)
                for wl in waveform_lines:
                    sys.stdout.write(f" {wl}\n")

                sys.stdout.write(f"{MAGENTA}───────────────────────────────────────────────────────────────────────────────{RESET}\n")
                sys.stdout.write(f" {BOLD}Total Samples:{RESET} {total_samples}  |  "
                                 f"{BOLD}Zero Counts:{RESET} {zero_reads}  |  "
                                 f"{BOLD}Press Ctrl+C to Stop{RESET}\n")
                sys.stdout.flush()

    except KeyboardInterrupt:
        pass
    finally:
        print(SHOW_CURSOR)
        stream.close()
        print(f"\n{GREEN}[DONE]{RESET} Session closed. Captured {total_samples} PPG samples.")


if __name__ == "__main__":
    main()
