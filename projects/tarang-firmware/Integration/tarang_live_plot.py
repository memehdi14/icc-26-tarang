#!/usr/bin/env python3
"""
TARANG Telemetry Logger & Plotter
==================================
Reads sensor telemetry from the TARANG board over VCOM serial,
logs everything to a timestamped CSV, and plots data live.

Usage:
  Live capture + plot:   python tarang_live_plot.py
  Live capture + plot:   python tarang_live_plot.py --port COM11
  Plot existing CSV:     python tarang_live_plot.py --csv telemetry_log_xxx.csv

Firmware printf formats parsed:
  ECG stream:  "  [ECG] raw=<val>"
  ECG diag:    "  [ECG] halves=<n>  total_samples=<n>  overruns=<n>"
  PPG diag:    "  [PPG] samples=<n>  RED=<n>  IR=<n>  sensor=<OK|FAIL>"
  IMU accel:   "  [IMU] accel: ax=<n>  ay=<n>  az=<n>"
  IMU gyro:    "  [IMU] gyro:  gx=<n>  gy=<n>  gz=<n>"
"""

import argparse
import csv
import os
import re
import sys
import time
import threading
from datetime import datetime
from collections import deque

import numpy as np
import serial
import serial.tools.list_ports
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.gridspec import GridSpec

try:
    from scipy.signal import butter, sosfiltfilt
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

# ─── Configuration ────────────────────────────────────────────────────────────

DEFAULT_BAUD   = 115200
DEFAULT_PORT   = "COM11"
MAX_POINTS     = 2000        # rolling window for live plots
ECG_FS         = 62.0        # effective UART sample rate (248 Hz / 4 decimation)
ECG_WINDOW_SEC = 4.0         # show 4 seconds on screen like a real ECG monitor
CSV_DIR        = os.path.dirname(os.path.abspath(__file__))

# ─── ECG Filter Design ───────────────────────────────────────────────────────

def design_ecg_filter(fs, lowcut=0.5, highcut=25.0, order=3):
    """Design a Butterworth bandpass filter for ECG signal."""
    nyq = fs / 2.0
    low = max(lowcut / nyq, 0.01)
    high = min(highcut / nyq, 0.99)
    return butter(order, [low, high], btype='band', output='sos')

def apply_ecg_filter(data, sos):
    """Apply zero-phase bandpass filter to ECG data."""
    if len(data) < 30:  # need enough points for filter
        # Simple DC removal fallback
        arr = np.array(data, dtype=float)
        return arr - np.mean(arr)
    arr = np.array(data, dtype=float)
    try:
        return sosfiltfilt(sos, arr)
    except Exception:
        return arr - np.mean(arr)

def simple_dc_remove(data, window=15):
    """Simple baseline removal using moving average subtraction."""
    arr = np.array(data, dtype=float)
    if len(arr) < window:
        return arr - np.mean(arr)
    kernel = np.ones(window) / window
    baseline = np.convolve(arr, kernel, mode='same')
    return arr - baseline

# ─── Regex parsers for each firmware printf line ──────────────────────────────

RE_ECG_RAW   = re.compile(r"\[ECG\]\s+raw=(\d+)")
RE_ECG_DIAG  = re.compile(
    r"\[ECG\]\s+halves=(\d+)\s+total_samples=(\d+)\s+overruns=(\d+)"
)
RE_PPG       = re.compile(
    r"\[PPG\]\s+(?:samples|cnt)=(\d+)\s+.*RED=(\d+)\s+IR=(\d+)"
)
RE_IMU_ACCEL = re.compile(
    r"\[IMU\]\s+accel:\s+ax=(-?\d+)\s+ay=(-?\d+)\s+az=(-?\d+)"
)
RE_IMU_GYRO  = re.compile(
    r"\[IMU\]\s+gyro:\s+gx=(-?\d+)\s+gy=(-?\d+)\s+gz=(-?\d+)"
)
RE_IMU_COMBO = re.compile(
    r"\[IMU\]\s+cnt=\d+\s+ax=(-?\d+)\s+ay=(-?\d+)\s+az=(-?\d+)\s+gx=(-?\d+)\s+gy=(-?\d+)\s+gz=(-?\d+)"
)
RE_PIPELINE_BEATS = re.compile(
    r"\[PIPELINE\]\s+beats:\s+total=(\d+)\s+suspicious=(\d+)\s+gate_passed=(\d+)"
)
RE_PIPELINE_AI = re.compile(
    r"\[PIPELINE\]\s+AI:\s+triggers=(\d+)\s+time=(\d+)\s+us\s+BLE_pkts=(\d+)"
)
RE_PIPELINE_STATUS = re.compile(
    r"\[PIPELINE\]\s+HR=(\d+)\s+bpm\s+rhythm=(0x[0-9A-Fa-f]+)\s+PAC=(\d+)%\s+PVC=(\d+)%"
)

# ─── Auto-detect serial port ─────────────────────────────────────────────────

def find_serial_port():
    """Try to find a Silicon Labs VCOM port, fall back to DEFAULT_PORT."""
    ports = serial.tools.list_ports.comports()
    for p in ports:
        desc = (p.description or "").lower()
        mfg  = (p.manufacturer or "").lower()
        if any(kw in desc for kw in ["silicon labs", "jlink", "efr32", "vcom"]):
            print(f"[AUTO] Found board on {p.device}: {p.description}")
            return p.device
        if "silicon" in mfg:
            print(f"[AUTO] Found board on {p.device}: {p.description}")
            return p.device
    print(f"[AUTO] No board auto-detected, using {DEFAULT_PORT}")
    return DEFAULT_PORT

# ─── CSV Logger ───────────────────────────────────────────────────────────────

class TelemetryLogger:
    """Writes parsed telemetry rows to a timestamped CSV file."""

    HEADER = [
        "timestamp", "relative_sec", "sensor",
        "ch1_name", "ch1_val",
        "ch2_name", "ch2_val",
        "ch3_name", "ch3_val",
        "raw_line",
    ]

    def __init__(self, directory=CSV_DIR):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = os.path.join(directory, f"telemetry_log_{ts}.csv")
        self._file = open(self.path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(self.HEADER)
        self._t0 = time.time()
        print(f"[LOG] Logging to {self.path}")

    def write(self, sensor, channels, raw_line=""):
        """channels: list of (name, value) tuples, up to 3."""
        now = time.time()
        row = [now, f"{now - self._t0:.3f}", sensor]
        for i in range(3):
            if i < len(channels):
                row.extend([channels[i][0], channels[i][1]])
            else:
                row.extend(["", ""])
        row.append(raw_line.strip())
        self._writer.writerow(row)
        self._file.flush()

    def close(self):
        self._file.close()
        print(f"[LOG] Closed {self.path}")

# ─── Data Store (thread-safe ring buffers) ────────────────────────────────────

class TelemetryData:
    """Thread-safe rolling data store for all sensor channels."""

    def __init__(self, maxlen=MAX_POINTS):
        self.lock = threading.Lock()
        # ECG
        self.ecg_t   = deque(maxlen=maxlen)
        self.ecg_raw = deque(maxlen=maxlen)
        # PPG
        self.ppg_t   = deque(maxlen=maxlen)
        self.ppg_red = deque(maxlen=maxlen)
        self.ppg_ir  = deque(maxlen=maxlen)
        # IMU accel
        self.imu_accel_t  = deque(maxlen=maxlen)
        self.imu_ax       = deque(maxlen=maxlen)
        self.imu_ay       = deque(maxlen=maxlen)
        self.imu_az       = deque(maxlen=maxlen)
        # IMU gyro
        self.imu_gyro_t   = deque(maxlen=maxlen)
        self.imu_gx       = deque(maxlen=maxlen)
        self.imu_gy       = deque(maxlen=maxlen)
        self.imu_gz       = deque(maxlen=maxlen)
        # flags for which sensors are active
        self.has_ecg = False
        self.has_ppg = False
        self.has_imu = False
        # sample counter for status bar
        self.ecg_count = 0
        self.ppg_count = 0
        self.imu_count = 0

# ─── Serial reader thread ────────────────────────────────────────────────────

def serial_reader(port, baud, data: TelemetryData, logger: TelemetryLogger, stop_event: threading.Event):
    """Background thread: reads serial lines, parses, stores, and logs."""
    t0 = time.time()
    try:
        ser = serial.Serial(port, baud, timeout=1)
        print(f"[SERIAL] Connected to {port} @ {baud}")
    except serial.SerialException as e:
        print(f"[SERIAL] ERROR: {e}")
        stop_event.set()
        return

    while not stop_event.is_set():
        try:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            t = time.time() - t0
        except serial.SerialException as e:
            print(f"[SERIAL] Port error/lost ({e}). Retrying in 1s...")
            time.sleep(1)
            try:
                ser.close()
                ser = serial.Serial(port, baud, timeout=1)
                print(f"[SERIAL] Reconnected to {port}")
            except Exception:
                pass
            continue
        except Exception as e:
            print(f"[SERIAL] Read error: {e}")
            continue

        # ── Parse ECG raw stream ──
        m = RE_ECG_RAW.search(line)
        if m and not RE_ECG_DIAG.search(line):
            val = int(m.group(1))
            with data.lock:
                data.ecg_t.append(t)
                data.ecg_raw.append(val)
                data.has_ecg = True
                data.ecg_count += 1
            logger.write("ECG_RAW", [("raw", val)], line)
            continue

        # ── Parse ECG diagnostics ──
        m = RE_ECG_DIAG.search(line)
        if m:
            halves, samples, overruns = int(m.group(1)), int(m.group(2)), int(m.group(3))
            logger.write("ECG_DIAG", [
                ("halves", halves), ("total_samples", samples), ("overruns", overruns)
            ], line)
            if overruns > 0:
                print(f"[WARN] ECG overruns detected: {overruns}")
            continue

        # ── Parse PPG ──
        m = RE_PPG.search(line)
        if m:
            samples, red, ir = int(m.group(1)), int(m.group(2)), int(m.group(3))
            with data.lock:
                data.ppg_t.append(t)
                data.ppg_red.append(red)
                data.ppg_ir.append(ir)
                data.has_ppg = True
                data.ppg_count += 1
            logger.write("PPG", [("RED", red), ("IR", ir), ("samples", samples)], line)
            continue

        # ── Parse IMU combined (cnt=... ax=... ay=... az=... gx=... gy=... gz=...) ──
        m = RE_IMU_COMBO.search(line)
        if m:
            ax, ay, az = int(m.group(1)), int(m.group(2)), int(m.group(3))
            gx, gy, gz = int(m.group(4)), int(m.group(5)), int(m.group(6))
            with data.lock:
                data.imu_accel_t.append(t)
                data.imu_ax.append(ax)
                data.imu_ay.append(ay)
                data.imu_az.append(az)
                data.imu_gyro_t.append(t)
                data.imu_gx.append(gx)
                data.imu_gy.append(gy)
                data.imu_gz.append(gz)
                data.has_imu = True
                data.imu_count += 1
            logger.write("IMU_ACCEL", [("ax", ax), ("ay", ay), ("az", az)], line)
            logger.write("IMU_GYRO", [("gx", gx), ("gy", gy), ("gz", gz)], line)
            continue

        # ── Parse IMU accel ──
        m = RE_IMU_ACCEL.search(line)
        if m:
            ax, ay, az = int(m.group(1)), int(m.group(2)), int(m.group(3))
            with data.lock:
                data.imu_accel_t.append(t)
                data.imu_ax.append(ax)
                data.imu_ay.append(ay)
                data.imu_az.append(az)
                data.has_imu = True
                data.imu_count += 1
            logger.write("IMU_ACCEL", [("ax", ax), ("ay", ay), ("az", az)], line)
            continue

        # ── Parse IMU gyro ──
        m = RE_IMU_GYRO.search(line)
        if m:
            gx, gy, gz = int(m.group(1)), int(m.group(2)), int(m.group(3))
            with data.lock:
                data.imu_gyro_t.append(t)
                data.imu_gx.append(gx)
                data.imu_gy.append(gy)
                data.imu_gz.append(gz)
            logger.write("IMU_GYRO", [("gx", gx), ("gy", gy), ("gz", gz)], line)
            continue

        # ── Parse Pipeline beats ──
        m = RE_PIPELINE_BEATS.search(line)
        if m:
            logger.write("PIPELINE_BEATS", [
                ("total", int(m.group(1))),
                ("suspicious", int(m.group(2))),
                ("gate_passed", int(m.group(3)))
            ], line)
            continue

        # ── Parse Pipeline AI ──
        m = RE_PIPELINE_AI.search(line)
        if m:
            logger.write("PIPELINE_AI", [
                ("triggers", int(m.group(1))),
                ("time_us", int(m.group(2))),
                ("ble_pkts", int(m.group(3)))
            ], line)
            continue

        # ── Parse Pipeline Status ──
        m = RE_PIPELINE_STATUS.search(line)
        if m:
            logger.write("PIPELINE_STATUS", [
                ("hr_bpm", int(m.group(1))),
                ("rhythm", m.group(2)),
                ("pac_pct", int(m.group(3))),
                ("pvc_pct", int(m.group(4)))
            ], line)
            continue

        # ── Catch-all for all other firmware lines ──
        logger.write("OTHER", [], line)

    ser.close()
    print("[SERIAL] Closed.")

# ─── Plot Styling ─────────────────────────────────────────────────────────────

# Colors — ECG monitor theme
BG_COLOR       = "#0a0a0a"
PANEL_COLOR    = "#0d1117"
GRID_COLOR     = "#1a2332"
GRID_MAJOR     = "#1e3a20"      # dark green major grid (ECG paper style)
ECG_COLOR      = "#00ff41"      # phosphor green
ECG_COLOR_DIM  = "#00cc33"
PPG_RED_COLOR  = "#ff4444"
PPG_IR_COLOR   = "#44aaff"
IMU_AX_COLOR   = "#ff6b6b"
IMU_AY_COLOR   = "#4ecdc4"
IMU_AZ_COLOR   = "#ffd93d"
IMU_GX_COLOR   = "#ff9f43"
IMU_GY_COLOR   = "#a29bfe"
IMU_GZ_COLOR   = "#fd79a8"
LABEL_COLOR    = "#888888"
TITLE_COLOR    = "#00ff41"
AXIS_COLOR     = "#333333"

def style_ax(ax, title, ylabel, title_color=TITLE_COLOR):
    """Apply ECG-monitor dark theme to an axis."""
    ax.set_facecolor(PANEL_COLOR)
    ax.set_title(title, color=title_color, fontsize=11, fontweight="bold",
                 pad=8, loc="left", fontfamily="monospace")
    ax.set_xlabel("Time (s)", color=LABEL_COLOR, fontsize=8)
    ax.set_ylabel(ylabel, color=LABEL_COLOR, fontsize=9)
    ax.tick_params(colors=LABEL_COLOR, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(AXIS_COLOR)
    # ECG paper-style grid
    ax.grid(True, which='major', alpha=0.3, color=GRID_MAJOR, linewidth=0.5)
    ax.grid(True, which='minor', alpha=0.1, color=GRID_COLOR, linewidth=0.3)
    ax.minorticks_on()

# ─── Live Plot ────────────────────────────────────────────────────────────────

def run_live(port, baud, ecg_only=False):
    """Start serial reader thread and live matplotlib animation."""
    data   = TelemetryData()
    logger = TelemetryLogger()
    stop   = threading.Event()

    # Design ECG filter
    ecg_sos = None
    if HAS_SCIPY:
        try:
            ecg_sos = design_ecg_filter(ECG_FS, lowcut=0.5, highcut=25.0, order=3)
            print("[FILTER] Bandpass 0.5–25 Hz (scipy)")
        except Exception as e:
            print(f"[FILTER] Failed to design filter: {e}, using DC removal only")
    else:
        print("[FILTER] scipy not found, using simple DC removal")

    reader = threading.Thread(target=serial_reader, args=(port, baud, data, logger, stop), daemon=True)
    reader.start()

    # Build panel layout
    if ecg_only:
        panels = ["ecg"]
        print("[PLOT] ECG-only mode")
    else:
        panels = ["ecg", "ppg", "imu_accel", "imu_gyro"]
        print("[PLOT] All sensors mode (ECG + PPG + IMU)")

    print("[PLOT] Waiting for data...")

    n_plots = len(panels)
    fig = plt.figure(figsize=(16, 3.2 * n_plots), facecolor=BG_COLOR)
    fig.canvas.manager.set_window_title("TARANG — Live Telemetry Monitor")
    gs = GridSpec(n_plots, 1, figure=fig, hspace=0.45)

    axes = {}
    for i, panel in enumerate(panels):
        ax = fig.add_subplot(gs[i])
        axes[panel] = ax

    if "ecg" in axes:
        style_ax(axes["ecg"], "♥ ECG", "mV (filtered)")
    if "ppg" in axes:
        style_ax(axes["ppg"], "● PPG", "Counts", title_color=PPG_RED_COLOR)
    if "imu_accel" in axes:
        style_ax(axes["imu_accel"], "◆ ACCEL", "Raw (LSB)", title_color=IMU_AX_COLOR)
    if "imu_gyro" in axes:
        style_ax(axes["imu_gyro"], "◆ GYRO", "Raw (LSB)", title_color=IMU_GX_COLOR)

    # Create persistent Line2D artists once (never clear axes!)
    lines = {}
    if "ecg" in axes:
        l_ecg, = axes["ecg"].plot([], [], color=ECG_COLOR, linewidth=1.2, alpha=0.95)
        lines["ecg"] = l_ecg
    if "ppg" in axes:
        l_red, = axes["ppg"].plot([], [], color=PPG_RED_COLOR, linewidth=1.2, label="RED", alpha=0.9)
        l_ir,  = axes["ppg"].plot([], [], color=PPG_IR_COLOR, linewidth=1.2, label="IR", alpha=0.9)
        axes["ppg"].legend(loc="upper right", fontsize=7, facecolor=PANEL_COLOR,
                           edgecolor=AXIS_COLOR, labelcolor=LABEL_COLOR)
        lines["ppg_red"] = l_red
        lines["ppg_ir"]  = l_ir
    if "imu_accel" in axes:
        l_ax, = axes["imu_accel"].plot([], [], color=IMU_AX_COLOR, linewidth=1, label="aX", alpha=0.9)
        l_ay, = axes["imu_accel"].plot([], [], color=IMU_AY_COLOR, linewidth=1, label="aY", alpha=0.9)
        l_az, = axes["imu_accel"].plot([], [], color=IMU_AZ_COLOR, linewidth=1, label="aZ", alpha=0.9)
        axes["imu_accel"].legend(loc="upper right", fontsize=7, facecolor=PANEL_COLOR,
                                 edgecolor=AXIS_COLOR, labelcolor=LABEL_COLOR, ncol=3)
        lines["imu_ax"] = l_ax
        lines["imu_ay"] = l_ay
        lines["imu_az"] = l_az
    if "imu_gyro" in axes:
        l_gx, = axes["imu_gyro"].plot([], [], color=IMU_GX_COLOR, linewidth=1, label="gX", alpha=0.9)
        l_gy, = axes["imu_gyro"].plot([], [], color=IMU_GY_COLOR, linewidth=1, label="gY", alpha=0.9)
        l_gz, = axes["imu_gyro"].plot([], [], color=IMU_GZ_COLOR, linewidth=1, label="gZ", alpha=0.9)
        axes["imu_gyro"].legend(loc="upper right", fontsize=7, facecolor=PANEL_COLOR,
                                edgecolor=AXIS_COLOR, labelcolor=LABEL_COLOR, ncol=3)
        lines["imu_gx"] = l_gx
        lines["imu_gy"] = l_gy
        lines["imu_gz"] = l_gz

    # Status text at bottom
    status_text = fig.text(0.01, 0.005, "", color=LABEL_COLOR, fontsize=8,
                           fontfamily="monospace", va="bottom")

    # ── High-efficiency in-place animation update ──
    def update(frame):
        with data.lock:
            # ── ECG ──
            if "ecg" in axes and len(data.ecg_raw) > 5:
                t_arr = np.array(data.ecg_t)
                raw_arr = np.array(data.ecg_raw, dtype=float)

                t_max = t_arr[-1]
                t_min = t_max - ECG_WINDOW_SEC
                mask = t_arr >= t_min
                t_win = t_arr[mask]
                raw_win = raw_arr[mask]

                if len(raw_win) > 5:
                    filtered = simple_dc_remove(raw_win)
                    lines["ecg"].set_data(t_win, filtered)
                    axes["ecg"].set_xlim(t_min, t_max)
                    ymin, ymax = np.min(filtered), np.max(filtered)
                    ypad = max((ymax - ymin) * 0.15, 5)
                    axes["ecg"].set_ylim(ymin - ypad, ymax + ypad)
                    axes["ecg"].set_title(f"♥ ECG  [{data.ecg_count} samples]",
                                         color=TITLE_COLOR, fontsize=11, fontweight="bold", pad=8, loc="left")

            # ── PPG ──
            if "ppg" in axes and len(data.ppg_red) > 2:
                t_arr = np.array(data.ppg_t)
                t_max = t_arr[-1]
                t_min = max(t_max - 10.0, t_arr[0])
                mask = t_arr >= t_min

                lines["ppg_red"].set_data(t_arr[mask], np.array(data.ppg_red)[mask])
                lines["ppg_ir"].set_data(t_arr[mask], np.array(data.ppg_ir)[mask])
                axes["ppg"].set_xlim(t_min, t_max)
                r_win = np.array(data.ppg_red)[mask]
                i_win = np.array(data.ppg_ir)[mask]
                if len(r_win) > 0 and len(i_win) > 0:
                    ymin = min(np.min(r_win), np.min(i_win))
                    ymax = max(np.max(r_win), np.max(i_win))
                    ypad = max((ymax - ymin) * 0.1, 10)
                    axes["ppg"].set_ylim(ymin - ypad, ymax + ypad)
                axes["ppg"].set_title(f"● PPG  [{data.ppg_count} samples]",
                                      color=PPG_RED_COLOR, fontsize=11, fontweight="bold", pad=8, loc="left")

            # ── IMU Accel ──
            if "imu_accel" in axes and len(data.imu_ax) > 2:
                t_arr = np.array(data.imu_accel_t)
                t_max = t_arr[-1]
                t_min = max(t_max - 10.0, t_arr[0])
                mask = t_arr >= t_min

                ax_w = np.array(data.imu_ax)[mask]
                ay_w = np.array(data.imu_ay)[mask]
                az_w = np.array(data.imu_az)[mask]
                lines["imu_ax"].set_data(t_arr[mask], ax_w)
                lines["imu_ay"].set_data(t_arr[mask], ay_w)
                lines["imu_az"].set_data(t_arr[mask], az_w)
                axes["imu_accel"].set_xlim(t_min, t_max)
                if len(ax_w) > 0:
                    ymin = min(np.min(ax_w), np.min(ay_w), np.min(az_w))
                    ymax = max(np.max(ax_w), np.max(ay_w), np.max(az_w))
                    ypad = max((ymax - ymin) * 0.1, 100)
                    axes["imu_accel"].set_ylim(ymin - ypad, ymax + ypad)
                axes["imu_accel"].set_title(f"◆ ACCEL  [{data.imu_count} samples]",
                                            color=IMU_AX_COLOR, fontsize=11, fontweight="bold", pad=8, loc="left")

            # ── IMU Gyro ──
            if "imu_gyro" in axes and len(data.imu_gx) > 2:
                t_arr = np.array(data.imu_gyro_t)
                t_max = t_arr[-1]
                t_min = max(t_max - 10.0, t_arr[0])
                mask = t_arr >= t_min

                gx_w = np.array(data.imu_gx)[mask]
                gy_w = np.array(data.imu_gy)[mask]
                gz_w = np.array(data.imu_gz)[mask]
                lines["imu_gx"].set_data(t_arr[mask], gx_w)
                lines["imu_gy"].set_data(t_arr[mask], gy_w)
                lines["imu_gz"].set_data(t_arr[mask], gz_w)
                axes["imu_gyro"].set_xlim(t_min, t_max)
                if len(gx_w) > 0:
                    ymin = min(np.min(gx_w), np.min(gy_w), np.min(gz_w))
                    ymax = max(np.max(gx_w), np.max(gy_w), np.max(gz_w))
                    ypad = max((ymax - ymin) * 0.1, 100)
                    axes["imu_gyro"].set_ylim(ymin - ypad, ymax + ypad)

            # ── Status bar ──
            parts = []
            if data.has_ecg: parts.append(f"ECG: {data.ecg_count}")
            if data.has_ppg: parts.append(f"PPG: {data.ppg_count}")
            if data.has_imu: parts.append(f"IMU: {data.imu_count}")
            status_text.set_text("  |  ".join(parts))

        return []

    global _ani_ref
    _ani_ref = animation.FuncAnimation(fig, update, interval=200, blit=False, cache_frame_data=False)

    try:
        fig.subplots_adjust(hspace=0.45, top=0.95, bottom=0.05, left=0.08, right=0.96)
        plt.show()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        reader.join(timeout=2)
        logger.close()
        print(f"\n[DONE] CSV saved to: {logger.path}")

# ─── Offline CSV Plot ────────────────────────────────────────────────────────

def plot_csv(csv_path):
    """Load a previously saved CSV and plot all sensor channels with filtering."""
    print(f"[CSV] Loading {csv_path}")

    ecg_t, ecg_v = [], []
    ppg_t, ppg_red, ppg_ir = [], [], []
    imu_accel_t, imu_ax, imu_ay, imu_az = [], [], [], []
    imu_gyro_t, imu_gx, imu_gy, imu_gz = [], [], [], []

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                t = float(row["relative_sec"])
            except (ValueError, KeyError):
                continue
            sensor = row.get("sensor", "")

            if sensor == "ECG_RAW":
                try:
                    ecg_t.append(t)
                    ecg_v.append(float(row["ch1_val"]))
                except (ValueError, KeyError):
                    pass
            elif sensor == "PPG":
                try:
                    ppg_t.append(t)
                    ppg_red.append(float(row["ch1_val"]))
                    ppg_ir.append(float(row["ch2_val"]))
                except (ValueError, KeyError):
                    pass
            elif sensor == "IMU_ACCEL":
                try:
                    imu_accel_t.append(t)
                    imu_ax.append(float(row["ch1_val"]))
                    imu_ay.append(float(row["ch2_val"]))
                    imu_az.append(float(row["ch3_val"]))
                except (ValueError, KeyError):
                    pass
            elif sensor == "IMU_GYRO":
                try:
                    imu_gyro_t.append(t)
                    imu_gx.append(float(row["ch1_val"]))
                    imu_gy.append(float(row["ch2_val"]))
                    imu_gz.append(float(row["ch3_val"]))
                except (ValueError, KeyError):
                    pass

    has_ecg  = len(ecg_t) > 0
    has_ppg  = len(ppg_t) > 0
    has_imu_a = len(imu_accel_t) > 0
    has_imu_g = len(imu_gyro_t) > 0

    panels = []
    if has_ecg:   panels.append("ecg")
    if has_ppg:   panels.append("ppg")
    if has_imu_a: panels.append("imu_accel")
    if has_imu_g: panels.append("imu_gyro")

    n_plots = len(panels)
    if n_plots == 0:
        print("[CSV] No plottable data found!")
        return

    fig, axs = plt.subplots(n_plots, 1, figsize=(16, 3.2 * n_plots), facecolor=BG_COLOR)
    if n_plots == 1:
        axs = [axs]

    fig.canvas.manager.set_window_title(f"TARANG — {os.path.basename(csv_path)}")
    plot_idx = 0

    if has_ecg:
        ax = axs[plot_idx]
        style_ax(ax, f"♥ ECG  [{len(ecg_t)} samples]", "Filtered")

        ecg_arr = np.array(ecg_v, dtype=float)
        ecg_t_arr = np.array(ecg_t)

        # Apply bandpass filter
        if HAS_SCIPY and len(ecg_arr) >= 30:
            sos = design_ecg_filter(ECG_FS)
            filtered = apply_ecg_filter(ecg_arr, sos)
        else:
            filtered = simple_dc_remove(ecg_arr)

        ax.plot(ecg_t_arr, filtered, color=ECG_COLOR, linewidth=0.8, alpha=0.95)
        plot_idx += 1

    if has_ppg:
        ax = axs[plot_idx]
        style_ax(ax, f"● PPG  [{len(ppg_t)} samples]", "Counts", title_color=PPG_RED_COLOR)
        ax.plot(ppg_t, ppg_red, color=PPG_RED_COLOR, linewidth=1, label="RED", alpha=0.9)
        ax.plot(ppg_t, ppg_ir,  color=PPG_IR_COLOR, linewidth=1, label="IR", alpha=0.9)
        ax.legend(loc="upper right", fontsize=8, facecolor=PANEL_COLOR,
                  edgecolor=AXIS_COLOR, labelcolor=LABEL_COLOR)
        plot_idx += 1

    if has_imu_a:
        ax = axs[plot_idx]
        style_ax(ax, f"◆ ACCEL  [{len(imu_accel_t)} samples]", "Raw (LSB)",
                 title_color=IMU_AX_COLOR)
        ax.plot(imu_accel_t, imu_ax, color=IMU_AX_COLOR, linewidth=1, label="aX")
        ax.plot(imu_accel_t, imu_ay, color=IMU_AY_COLOR, linewidth=1, label="aY")
        ax.plot(imu_accel_t, imu_az, color=IMU_AZ_COLOR, linewidth=1, label="aZ")
        ax.legend(loc="upper right", fontsize=8, facecolor=PANEL_COLOR,
                  edgecolor=AXIS_COLOR, labelcolor=LABEL_COLOR, ncol=3)
        plot_idx += 1

    if has_imu_g:
        ax = axs[plot_idx]
        style_ax(ax, f"◆ GYRO  [{len(imu_gyro_t)} samples]", "Raw (LSB)",
                 title_color=IMU_GX_COLOR)
        ax.plot(imu_gyro_t, imu_gx, color=IMU_GX_COLOR, linewidth=1, label="gX")
        ax.plot(imu_gyro_t, imu_gy, color=IMU_GY_COLOR, linewidth=1, label="gY")
        ax.plot(imu_gyro_t, imu_gz, color=IMU_GZ_COLOR, linewidth=1, label="gZ")
        ax.legend(loc="upper right", fontsize=8, facecolor=PANEL_COLOR,
                  edgecolor=AXIS_COLOR, labelcolor=LABEL_COLOR, ncol=3)
        plot_idx += 1

    plt.tight_layout()
    print(f"[CSV] Plotted {n_plots} channel(s). Close the window to exit.")
    plt.show()

# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="TARANG Telemetry Logger & Plotter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tarang_live_plot.py                     # auto-detect port, live plot
  python tarang_live_plot.py --port COM11        # specify port
  python tarang_live_plot.py --csv log.csv       # plot existing CSV file
        """,
    )
    parser.add_argument("--port", default=None, help="Serial port (e.g. COM11)")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help=f"Baud rate (default: {DEFAULT_BAUD})")
    parser.add_argument("--csv", default=None, help="Path to an existing CSV to plot (offline mode)")
    parser.add_argument("--ecg-only", action="store_true", help="Show only ECG panel (no PPG/IMU)")
    args = parser.parse_args()

    if args.csv:
        plot_csv(args.csv)
    else:
        port = args.port or find_serial_port()
        print(f"[MAIN] Starting live capture on {port} @ {args.baud}")
        run_live(port, args.baud, ecg_only=args.ecg_only)


if __name__ == "__main__":
    main()
