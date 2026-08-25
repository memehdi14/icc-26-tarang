#!/usr/bin/env python3
"""
TARANG AD8232 (IADC0) Live Terminal ECG Monitor & Diagnostic Tool
================================================================
Validates the AD8232 analog front-end and IADC0 250 Hz acquisition chain.

Features:
  - Live ASCII Oscilloscope (scrolling real-time ECG waveform)
  - 250 Hz Sample Rate Verification & Jitter Tracking
  - 12-bit ADC Saturation & Lead-Off Detection (0 or 4095 rails)
  - Streaming Pan-Tompkins DSP (MWI, Adaptive Thresholds TH1/TH2)
  - Real-Time HR (bpm), RR intervals (ms), SQI (Signal Quality)
  - ISSUE-DSP-04 Detector (T-wave double-trigger & CoV anomaly alert)

Usage:
  python live_ecg_monitor.py
  python live_ecg_monitor.py --port COM11 --baud 115200
  python live_ecg_monitor.py --replay ../../tarang-dsp/integration_validation/captures/sample.csv
"""

import argparse
import collections
import os
import sys
import time
from pathlib import Path

# Local import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vcom_stream import VCOMTelemetryStream, ECGFrame, BeatEvent


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
BG_DARK = "\033[40m"
CLEAR_SCREEN = "\033[2J\033[H"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"


def draw_ascii_waveform(buffer: list[float], height: int = 10, width: int = 65) -> list[str]:
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
        lines.append(f"{CYAN}│{RESET}{line}{CYAN}│{RESET}")
    return lines


def main():
    parser = argparse.ArgumentParser(description="TARANG AD8232 (IADC0) Live Terminal ECG Monitor")
    parser.add_argument("--port", help="Serial port (e.g. COM11)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--replay", help="Replay capture CSV file instead of live VCOM")
    parser.add_argument("--raw-only", action="store_true", help="Display raw ADC values instead of filtered")
    args = parser.parse_args()

    stream = VCOMTelemetryStream(port=args.port, baud=args.baud, replay_file=args.replay)

    try:
        stream.open()
    except Exception as e:
        print(f"{RED}[ERROR]{RESET} {e}")
        sys.exit(1)

    print(HIDE_CURSOR, end="")

    # Rolling state buffers
    raw_history = collections.deque(maxlen=120)
    clean_history = collections.deque(maxlen=120)
    mwi_history = collections.deque(maxlen=120)
    rr_history = collections.deque(maxlen=30)
    sample_timestamps = collections.deque(maxlen=250)

    total_samples = 0
    total_beats = 0
    suspicious_beats = 0
    sat_high_count = 0
    sat_low_count = 0
    last_hr = 0.0
    last_rr = 0.0
    last_sqi = 1.0
    last_beat_time = 0.0
    last_raw = 2048
    last_clean = 2048
    last_mwi = 0.0
    last_th = 0.0

    t_start = time.time()
    last_render = 0.0

    try:
        for line in stream.stream_lines():
            ecg_frames, _, _, beat, _, debug_text = stream.parse_line(line)
            now = time.time()

            if ecg_frames:
                for f in ecg_frames:
                    total_samples += 1
                    sample_timestamps.append(now)
                    last_raw = f.raw_adc
                    last_clean = f.clean_adc
                    last_mwi = f.mwi
                    last_th = f.threshold

                    raw_history.append(f.raw_adc)
                    clean_history.append(f.clean_adc if not args.raw_only else f.raw_adc)
                    mwi_history.append(f.mwi)

                    # 12-bit ADC rail check (IADC0 0..4095)
                    if f.raw_adc >= 4080:
                        sat_high_count += 1
                    elif f.raw_adc <= 15:
                        sat_low_count += 1

            if beat:
                total_beats += 1
                last_hr = beat.hr_bpm
                last_rr = beat.rr_ms
                last_sqi = beat.sqi
                last_beat_time = now
                rr_history.append(beat.rr_ms)

                # ISSUE-DSP-04 diagnostic check (physiologically implausible RR or double-trigger)
                if beat.rr_ms < 350.0:
                    suspicious_beats += 1

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

                # Sample rate color indicator
                hz_color = GREEN if 240.0 <= hz <= 260.0 else (YELLOW if 200.0 <= hz <= 300.0 else RED)

                # Lead-off / Saturation indicator
                lead_status = f"{GREEN}[CONNECTED]{RESET}"
                if sat_high_count > 10 or sat_low_count > 10:
                    lead_status = f"{RED}[RAILED/LEAD-OFF]{RESET}"

                # Suspicious beat rate
                susp_pct = (suspicious_beats / max(1, total_beats)) * 100.0
                susp_color = GREEN if susp_pct < 2.0 else (YELLOW if susp_pct < 10.0 else RED)

                # Beat pulse animation
                time_since_beat = now - last_beat_time
                pulse_icon = f"{RED}♥{RESET}" if time_since_beat < 0.25 else f"{WHITE}♡{RESET}"

                # Clear and draw dashboard
                sys.stdout.write(CLEAR_SCREEN)
                sys.stdout.write(f"{BOLD}{CYAN}╔═════════════════════════════════════════════════════════════════════════════╗{RESET}\n")
                sys.stdout.write(f"{BOLD}{CYAN}║         TARANG SENSOR 1: AD8232 ECG (IADC0 @ 250 Hz) VALIDATION TOOL        ║{RESET}\n")
                sys.stdout.write(f"{BOLD}{CYAN}╚═════════════════════════════════════════════════════════════════════════════╝{RESET}\n")
                
                source_label = f"REPLAY: {Path(args.replay).name}" if args.replay else f"PORT: {stream.port} @ {stream.baud}"
                sys.stdout.write(f" {BOLD}Mode:{RESET} {source_label}  |  {BOLD}Protocol:{RESET} {stream.protocol_detected}  |  {BOLD}Elapsed:{RESET} {elapsed:.1f}s\n")
                sys.stdout.write(f" {BOLD}Sampling Rate:{RESET} {hz_color}{hz:5.1f} Hz{RESET} (Target: 250 Hz)  |  {BOLD}Lead State:{RESET} {lead_status}\n")
                sys.stdout.write(f"{CYAN}───────────────────────────────────────────────────────────────────────────────{RESET}\n")

                # Metrics banner
                sys.stdout.write(f" {pulse_icon} {BOLD}Heart Rate:{RESET} {GREEN}{last_hr:5.1f} bpm{RESET}  |  "
                                 f"{BOLD}RR:{RESET} {CYAN}{last_rr:5.0f} ms{RESET}  |  "
                                 f"{BOLD}SQI:{RESET} {GREEN if last_sqi > 0.7 else YELLOW}{last_sqi:.2f}{RESET}  |  "
                                 f"{BOLD}Beats:{RESET} {total_beats}\n")
                
                sys.stdout.write(f" 📊 {BOLD}ADC Raw:{RESET} {last_raw:4d} (0..4095)  |  "
                                 f"{BOLD}Clean:{RESET} {last_clean:4d}  |  "
                                 f"{BOLD}MWI:{RESET} {last_mwi:4.0f}  |  "
                                 f"{BOLD}TH1:{RESET} {last_th:4.0f}\n")
                
                sys.stdout.write(f" ⚠️  {BOLD}ISSUE-DSP-04 (T-Wave Over-Trigger):{RESET} {susp_color}{suspicious_beats}/{total_beats} ({susp_pct:.1f}%){RESET} "
                                 f"[Target: <0.1%]\n")
                sys.stdout.write(f"{CYAN}───────────────────────────────────────────────────────────────────────────────{RESET}\n")

                # Waveform display
                sys.stdout.write(f" {BOLD}Live ECG Signal Stream (AD8232 / IADC0):{RESET}\n")
                waveform_lines = draw_ascii_waveform(list(clean_history), height=10, width=75)
                for wl in waveform_lines:
                    sys.stdout.write(f" {wl}\n")

                sys.stdout.write(f"{CYAN}───────────────────────────────────────────────────────────────────────────────{RESET}\n")
                sys.stdout.write(f" {BOLD}Total Samples:{RESET} {total_samples}  |  "
                                 f"{BOLD}Rail High:{RESET} {sat_high_count}  |  "
                                 f"{BOLD}Rail Low:{RESET} {sat_low_count}  |  "
                                 f"{BOLD}Press Ctrl+C to Stop{RESET}\n")
                sys.stdout.flush()

    except KeyboardInterrupt:
        pass
    finally:
        print(SHOW_CURSOR)
        stream.close()
        print(f"\n{GREEN}[DONE]{RESET} Session closed. Captured {total_samples} ECG samples, {total_beats} beats detected.")


if __name__ == "__main__":
    main()
