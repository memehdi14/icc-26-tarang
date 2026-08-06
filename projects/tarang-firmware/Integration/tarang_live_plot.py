#!/usr/bin/env python3
"""
TARANG Serial Telemetry Logger & Plotter
──────────────────────────────────────────
Reads UART telemetry output from the EFR32 board, parses ECG / PPG / IMU sensor data,
and provides both live plotting and CSV recording/offline plotting modes.

Usage:
    # 1. Live Plotter + Auto CSV Recording (Default):
    python tarang_live_plot.py              # Auto-detect COM port
    python tarang_live_plot.py COM11        # Specify COM port manually

    # 2. Offline CSV Telemetry Plotter:
    python tarang_live_plot.py --plot-csv telemetry_log.csv

    # 3. Headless CSV Recorder (no GUI, log serial directly to file):
    python tarang_live_plot.py --record telemetry_log.csv
    python tarang_live_plot.py --record COM11 telemetry_log.csv

Requirements:
    pip install pyserial matplotlib
"""

import sys
import os
import re
import time
import csv
import argparse
import threading
from collections import deque
from datetime import datetime

import serial
import serial.tools.list_ports
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.animation as animation


# ─── CONFIG & DEFAULTS ──────────────────────────────────────────────────────
BAUD_RATE = 115200
MAX_POINTS = 300        # Data points to keep on live X axis
ANIM_INTERVAL_MS = 300  # Plot refresh rate (ms)

# ─── REGEX PARSERS ──────────────────────────────────────────────────────────
RE_ECG_STATS = re.compile(
    r"\[?ECG\]?:?\s+halves=(\d+)\s+total_samples=(\d+)\s+overruns=(\d+)", re.IGNORECASE
)
RE_ECG_RAW = re.compile(
    r"\[?ECG\]?:?\s+raw_half0\[0\]=(\d+)\s+raw_half1\[0\]=(\d+)", re.IGNORECASE
)
RE_PPG = re.compile(
    r"\[?PPG\]?:?\s+(?:samples|cnt)=(\d+)\s+(?:int=\d+\s+)?RED=(\d+)\s+IR=(\d+)(?:\s+sensor=(\w+))?", re.IGNORECASE
)
RE_IMU_STATS = re.compile(
    r"\[?IMU\]?:?\s+samples=(\d+)\s+interrupts=(\d+)\s+sensor=(\w+)", re.IGNORECASE
)
RE_IMU_ACCEL = re.compile(
    r"\[?IMU\]?:?\s+accel:\s+ax=(-?\d+)\s+ay=(-?\d+)\s+az=(-?\d+)", re.IGNORECASE
)
RE_IMU_GYRO = re.compile(
    r"\[?IMU\]?:?\s+gyro:\s+gx=(-?\d+)\s+gy=(-?\d+)\s+gz=(-?\d+)", re.IGNORECASE
)
RE_IMU_COMBINED = re.compile(
    r"\[?IMU\]?:?\s+(?:cnt|samples)=(\d+)\s+ax=(-?\d+)\s+ay=(-?\d+)\s+az=(-?\d+)\s+gx=(-?\d+)\s+gy=(-?\d+)\s+gz=(-?\d+)", re.IGNORECASE
)


# ─── DATA STORES FOR LIVE PLOT ─────────────────────────────────────────────
ecg_halves    = deque(maxlen=MAX_POINTS)
ecg_samples   = deque(maxlen=MAX_POINTS)
ecg_raw0      = deque(maxlen=MAX_POINTS)
ecg_raw1      = deque(maxlen=MAX_POINTS)
ecg_overruns  = deque(maxlen=MAX_POINTS)

ppg_red       = deque(maxlen=MAX_POINTS)
ppg_ir        = deque(maxlen=MAX_POINTS)
ppg_samples   = deque(maxlen=MAX_POINTS)

imu_ax        = deque(maxlen=MAX_POINTS)
imu_ay        = deque(maxlen=MAX_POINTS)
imu_az        = deque(maxlen=MAX_POINTS)
imu_gx        = deque(maxlen=MAX_POINTS)
imu_gy        = deque(maxlen=MAX_POINTS)
imu_gz        = deque(maxlen=MAX_POINTS)
imu_samples   = deque(maxlen=MAX_POINTS)

sensors_detected = {"ECG": False, "PPG": False, "IMU": False}
lock = threading.Lock()
serial_error_msg = None


# ─── AUTO-DETECT COM PORT ──────────────────────────────────────────────────
def find_serial_port():
    """Auto-detect a likely Silicon Labs / J-Link serial port."""
    ports = serial.tools.list_ports.comports()
    if not ports:
        return None

    keywords = ["silicon labs", "j-link", "jlink", "cp210", "efr32", "wstk", "usb", "acm", "usbser"]

    print("\n  Available serial ports:")
    for p in ports:
        print(f"    {p.device}  —  {p.description}")

    for p in ports:
        desc_lower = (p.description or "").lower()
        for kw in keywords:
            if kw in desc_lower:
                return p.device

    return ports[0].device if ports else None


# ─── CSV LOGGER ─────────────────────────────────────────────────────────────
class CSVLogger:
    def __init__(self, filename=None):
        if filename is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"telemetry_log_{ts}.csv"
        self.filename = filename
        self.file = open(self.filename, mode="w", newline="", encoding="utf-8")
        self.writer = csv.writer(self.file)
        self.writer.writerow([
            "timestamp", "relative_sec", "sensor",
            "ch1_name", "ch1_val",
            "ch2_name", "ch2_val",
            "ch3_name", "ch3_val",
            "raw_line"
        ])
        self.start_time = time.time()
        print(f"  [CSV] Logging telemetry to: {os.path.abspath(self.filename)}")

    def log(self, sensor, ch1_n, ch1_v, ch2_n="", ch2_v="", ch3_n="", ch3_v="", raw_line=""):
        now = time.time()
        rel = round(now - self.start_time, 3)
        self.writer.writerow([now, rel, sensor, ch1_n, ch1_v, ch2_n, ch2_v, ch3_n, ch3_v, raw_line])
        self.file.flush()

    def close(self):
        if self.file and not self.file.closed:
            self.file.close()
            print(f"  [CSV] Closed file: {self.filename}")


# ─── SERIAL READER THREAD ──────────────────────────────────────────────────
def serial_reader(port, logger=None, verbose=True):
    """Background thread: read lines from serial, log to CSV, & parse into data stores."""
    global serial_error_msg

    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=1)
        print(f"\n  [OK] Connected to {port} @ {BAUD_RATE} baud\n")
    except serial.SerialException as e:
        err = (f"\n  [FAIL] Failed to open serial port {port}:\n"
               f"    {e}\n\n"
               "  TROUBLESHOOTING:\n"
               "  1. Ensure no other app (Simplicity Studio, PuTTY, VS Code Serial Monitor) is using the port.\n"
               "  2. Run 'find_com_blocker.ps1' or check Device Manager.\n")
        print(err)
        serial_error_msg = str(e)
        return

    _imu_ax = _imu_ay = _imu_az = 0
    _imu_gx = _imu_gy = _imu_gz = 0
    _imu_cnt = 0

    while True:
        try:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            if verbose:
                print(f"  [SERIAL] {line}")

            # ── ECG ──────────────────────────────────────────────────
            m = RE_ECG_STATS.search(line)
            if m:
                with lock:
                    sensors_detected["ECG"] = True
                    ecg_halves.append(int(m.group(1)))
                    ecg_samples.append(int(m.group(2)))
                    ecg_overruns.append(int(m.group(3)))
                if logger:
                    logger.log("ECG_STATS", "halves", m.group(1), "samples", m.group(2), "overruns", m.group(3), line)
                continue

            m = RE_ECG_RAW.search(line)
            if m:
                with lock:
                    sensors_detected["ECG"] = True
                    ecg_raw0.append(int(m.group(1)))
                    ecg_raw1.append(int(m.group(2)))
                if logger:
                    logger.log("ECG_RAW", "raw_half0", m.group(1), "raw_half1", m.group(2), "", "", line)
                continue

            # ── PPG ──────────────────────────────────────────────────
            m = RE_PPG.search(line)
            if m:
                with lock:
                    sensors_detected["PPG"] = True
                    ppg_samples.append(int(m.group(1)))
                    ppg_red.append(int(m.group(2)))
                    ppg_ir.append(int(m.group(3)))
                if logger:
                    logger.log("PPG", "RED", m.group(2), "IR", m.group(3), "samples", m.group(1), line)
                continue

            # ── IMU ──────────────────────────────────────────────────
            m = RE_IMU_COMBINED.search(line)
            if m:
                with lock:
                    sensors_detected["IMU"] = True
                    imu_samples.append(int(m.group(1)))
                    imu_ax.append(int(m.group(2)))
                    imu_ay.append(int(m.group(3)))
                    imu_az.append(int(m.group(4)))
                    imu_gx.append(int(m.group(5)))
                    imu_gy.append(int(m.group(6)))
                    imu_gz.append(int(m.group(7)))
                if logger:
                    logger.log("IMU_ACCEL", "ax", m.group(2), "ay", m.group(3), "az", m.group(4), line)
                    logger.log("IMU_GYRO", "gx", m.group(5), "gy", m.group(6), "gz", m.group(7), line)
                continue

            m = RE_IMU_STATS.search(line)
            if m:
                with lock:
                    sensors_detected["IMU"] = True
                    _imu_cnt = int(m.group(1))
                continue

            m = RE_IMU_ACCEL.search(line)
            if m:
                _imu_ax = int(m.group(1))
                _imu_ay = int(m.group(2))
                _imu_az = int(m.group(3))
                if logger:
                    logger.log("IMU_ACCEL", "ax", _imu_ax, "ay", _imu_ay, "az", _imu_az, line)
                continue

            m = RE_IMU_GYRO.search(line)
            if m:
                _imu_gx = int(m.group(1))
                _imu_gy = int(m.group(2))
                _imu_gz = int(m.group(3))
                with lock:
                    sensors_detected["IMU"] = True
                    imu_samples.append(_imu_cnt)
                    imu_ax.append(_imu_ax)
                    imu_ay.append(_imu_ay)
                    imu_az.append(_imu_az)
                    imu_gx.append(_imu_gx)
                    imu_gy.append(_imu_gy)
                    imu_gz.append(_imu_gz)
                if logger:
                    logger.log("IMU_GYRO", "gx", _imu_gx, "gy", _imu_gy, "gz", _imu_gz, line)
                continue

        except serial.SerialException:
            print("  [FAIL] Serial port disconnected!")
            break
        except Exception as e:
            print(f"  [ERR] Parse error: {e}")
            continue


# ─── LIVE GUI PLOTTER ──────────────────────────────────────────────────────
def run_live_plot():
    """Build and animate the live matplotlib telemetry window."""
    plt.style.use("dark_background")

    fig = plt.figure(figsize=(14, 9))
    fig.patch.set_facecolor("#0d1117")
    fig.suptitle("TARANG Live Telemetry", fontsize=18, fontweight="bold", color="#58a6ff", y=0.98)

    axes = {}
    lines = {}
    layout_built = [False]

    status_text = fig.text(
        0.5, 0.5,
        "Waiting for telemetry data from board...\n\n"
        "(Ensure board is flashed, powered, and serial port is connected)",
        ha="center", va="center", fontsize=14, color="#8b949e", style="italic"
    )

    def build_layout():
        fig.clf()
        fig.patch.set_facecolor("#0d1117")
        fig.suptitle("TARANG Live Telemetry", fontsize=18, fontweight="bold", color="#58a6ff", y=0.98)

        active = [s for s, on in sensors_detected.items() if on]
        n = 0
        if "ECG" in active: n += 1
        if "PPG" in active: n += 1
        if "IMU" in active: n += 2  # Accel + Gyro

        if n == 0:
            n = 1

        row = 0

        # ── ECG Subplot ────────────────────────────────────────────
        if "ECG" in active:
            row += 1
            ax = fig.add_subplot(n, 1, row)
            ax.set_facecolor("#161b22")
            ax.set_title("ECG — Raw ADC", fontsize=12, color="#f0883e", pad=6)
            ax.set_ylabel("ADC Value", color="#8b949e")
            ax.tick_params(colors="#8b949e")
            ax.grid(True, color="#21262d", linestyle="--", alpha=0.5)
            for spine in ax.spines.values(): spine.set_color("#30363d")
            l0, = ax.plot([], [], color="#f97583", linewidth=1.5, marker="o", markersize=4, label="half0[0]")
            l1, = ax.plot([], [], color="#79c0ff", linewidth=1.5, marker="s", markersize=4, label="half1[0]")
            ax.legend(loc="upper right", fontsize=9, framealpha=0.3)
            axes["ecg"] = ax
            lines["ecg_raw0"] = l0
            lines["ecg_raw1"] = l1

        # ── PPG Subplot ────────────────────────────────────────────
        if "PPG" in active:
            row += 1
            ax = fig.add_subplot(n, 1, row)
            ax.set_facecolor("#161b22")
            ax.set_title("PPG — Optical Count (RED / IR)", fontsize=12, color="#f0883e", pad=6)
            ax.set_ylabel("Count", color="#8b949e")
            ax.tick_params(colors="#8b949e")
            ax.grid(True, color="#21262d", linestyle="--", alpha=0.5)
            for spine in ax.spines.values(): spine.set_color("#30363d")
            lr, = ax.plot([], [], color="#f85149", linewidth=1.5, marker="o", markersize=4, label="RED")
            li, = ax.plot([], [], color="#a5d6ff", linewidth=1.5, marker="^", markersize=4, label="IR")
            ax.legend(loc="upper right", fontsize=9, framealpha=0.3)
            axes["ppg"] = ax
            lines["ppg_red"] = lr
            lines["ppg_ir"] = li

        # ── IMU Accel Subplot ─────────────────────────────────────
        if "IMU" in active:
            row += 1
            ax = fig.add_subplot(n, 1, row)
            ax.set_facecolor("#161b22")
            ax.set_title("IMU — Accelerometer", fontsize=12, color="#f0883e", pad=6)
            ax.set_ylabel("Raw (int16)", color="#8b949e")
            ax.tick_params(colors="#8b949e")
            ax.grid(True, color="#21262d", linestyle="--", alpha=0.5)
            for spine in ax.spines.values(): spine.set_color("#30363d")
            lx, = ax.plot([], [], color="#f97583", linewidth=1.2, marker="o", markersize=3, label="aX")
            ly, = ax.plot([], [], color="#56d364", linewidth=1.2, marker="s", markersize=3, label="aY")
            lz, = ax.plot([], [], color="#79c0ff", linewidth=1.2, marker="^", markersize=3, label="aZ")
            ax.legend(loc="upper right", fontsize=9, framealpha=0.3)
            axes["imu_accel"] = ax
            lines["imu_ax"] = lx
            lines["imu_ay"] = ly
            lines["imu_az"] = lz

            # ── IMU Gyro Subplot ──────────────────────────────────
            row += 1
            ax = fig.add_subplot(n, 1, row)
            ax.set_facecolor("#161b22")
            ax.set_title("IMU — Gyroscope", fontsize=12, color="#f0883e", pad=6)
            ax.set_ylabel("Raw (int16)", color="#8b949e")
            ax.set_xlabel("Snapshot #", color="#8b949e")
            ax.tick_params(colors="#8b949e")
            ax.grid(True, color="#21262d", linestyle="--", alpha=0.5)
            for spine in ax.spines.values(): spine.set_color("#30363d")
            lgx, = ax.plot([], [], color="#d2a8ff", linewidth=1.2, marker="o", markersize=3, label="gX")
            lgy, = ax.plot([], [], color="#f0883e", linewidth=1.2, marker="s", markersize=3, label="gY")
            lgz, = ax.plot([], [], color="#3fb950", linewidth=1.2, marker="^", markersize=3, label="gZ")
            ax.legend(loc="upper right", fontsize=9, framealpha=0.3)
            axes["imu_gyro"] = ax
            lines["imu_gx"] = lgx
            lines["imu_gy"] = lgy
            lines["imu_gz"] = lgz

        fig.subplots_adjust(hspace=0.45, top=0.92, bottom=0.06, left=0.08, right=0.96)
        fig.canvas.draw_idle()
        layout_built[0] = True

    def update(_frame):
        with lock:
            if serial_error_msg and not layout_built[0]:
                status_text.set_text(f"SERIAL ERROR:\n{serial_error_msg}\n\nCheck terminal console output.")
                status_text.set_color("#f85149")
                return []

            any_data = any(sensors_detected.values())
            if any_data and not layout_built[0]:
                build_layout()

            if not layout_built[0]:
                return []

            # Update ECG
            if "ecg" in axes and len(ecg_raw0) > 0:
                x = list(range(len(ecg_raw0)))
                lines["ecg_raw0"].set_data(x, list(ecg_raw0))
                lines["ecg_raw1"].set_data(x, list(ecg_raw1))
                axes["ecg"].set_xlim(0, max(len(ecg_raw0), 1))
                vals = list(ecg_raw0) + list(ecg_raw1)
                if vals:
                    mn, mx = min(vals), max(vals)
                    pad = max((mx - mn) * 0.1, 10)
                    axes["ecg"].set_ylim(mn - pad, mx + pad)

            # Update PPG
            if "ppg" in axes and len(ppg_red) > 0:
                x = list(range(len(ppg_red)))
                lines["ppg_red"].set_data(x, list(ppg_red))
                lines["ppg_ir"].set_data(x, list(ppg_ir))
                axes["ppg"].set_xlim(0, max(len(ppg_red), 1))
                vals = list(ppg_red) + list(ppg_ir)
                if vals:
                    mn, mx = min(vals), max(vals)
                    pad = max((mx - mn) * 0.1, 100)
                    axes["ppg"].set_ylim(mn - pad, mx + pad)

            # Update IMU Accel
            if "imu_accel" in axes and len(imu_ax) > 0:
                x = list(range(len(imu_ax)))
                lines["imu_ax"].set_data(x, list(imu_ax))
                lines["imu_ay"].set_data(x, list(imu_ay))
                lines["imu_az"].set_data(x, list(imu_az))
                axes["imu_accel"].set_xlim(0, max(len(imu_ax), 1))
                vals = list(imu_ax) + list(imu_ay) + list(imu_az)
                if vals:
                    mn, mx = min(vals), max(vals)
                    pad = max((mx - mn) * 0.1, 100)
                    axes["imu_accel"].set_ylim(mn - pad, mx + pad)

            # Update IMU Gyro
            if "imu_gyro" in axes and len(imu_gx) > 0:
                x = list(range(len(imu_gx)))
                lines["imu_gx"].set_data(x, list(imu_gx))
                lines["imu_gy"].set_data(x, list(imu_gy))
                lines["imu_gz"].set_data(x, list(imu_gz))
                axes["imu_gyro"].set_xlim(0, max(len(imu_gx), 1))
                vals = list(imu_gx) + list(imu_gy) + list(imu_gz)
                if vals:
                    mn, mx = min(vals), max(vals)
                    pad = max((mx - mn) * 0.1, 100)
                    axes["imu_gyro"].set_ylim(mn - pad, mx + pad)

        return list(lines.values())

    _ani = animation.FuncAnimation(fig, update, interval=ANIM_INTERVAL_MS, blit=False, cache_frame_data=False)
    plt.show()


# ─── OFFLINE CSV PLOTTER ───────────────────────────────────────────────────
def plot_csv_file(csv_path):
    """Load and plot a saved telemetry CSV file."""
    if not os.path.exists(csv_path):
        print(f"\n  [FAIL] CSV file not found: {csv_path}")
        sys.exit(1)

    print(f"\n  Loading CSV telemetry log: {csv_path}...")

    ecg_t, ecg_r0, ecg_r1 = [], [], []
    ppg_t, ppg_r, ppg_i = [], [], []
    accel_t, ax_v, ay_v, az_v = [], [], [], []
    gyro_t, gx_v, gy_v, gz_v = [], [], [], []

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rel = float(row.get("relative_sec", 0))
            sensor = row.get("sensor", "")
            ch1_n, ch1_v = row.get("ch1_name", ""), row.get("ch1_val", "")
            ch2_n, ch2_v = row.get("ch2_name", ""), row.get("ch2_val", "")
            ch3_n, ch3_v = row.get("ch3_name", ""), row.get("ch3_val", "")

            if sensor == "ECG_RAW":
                if ch1_v and ch2_v:
                    ecg_t.append(rel)
                    ecg_r0.append(int(ch1_v))
                    ecg_r1.append(int(ch2_v))
            elif sensor == "PPG":
                if ch1_v and ch2_v:
                    ppg_t.append(rel)
                    ppg_r.append(int(ch1_v))
                    ppg_i.append(int(ch2_v))
            elif sensor == "IMU_ACCEL":
                if ch1_v and ch2_v and ch3_v:
                    accel_t.append(rel)
                    ax_v.append(int(ch1_v))
                    ay_v.append(int(ch2_v))
                    az_v.append(int(ch3_v))
            elif sensor == "IMU_GYRO":
                if ch1_v and ch2_v and ch3_v:
                    gyro_t.append(rel)
                    gx_v.append(int(ch1_v))
                    gy_v.append(int(ch2_v))
                    gz_v.append(int(ch3_v))

    active = []
    if ecg_t: active.append("ECG")
    if ppg_t: active.append("PPG")
    if accel_t: active.append("ACCEL")
    if gyro_t: active.append("GYRO")

    if not active:
        print("  [FAIL] No parseable telemetry data found in CSV file.")
        sys.exit(1)

    print(f"  Parsed sensors: {', '.join(active)}")
    print(f"  Opening viewer window...")

    plt.style.use("dark_background")
    fig = plt.figure(figsize=(14, 9))
    fig.patch.set_facecolor("#0d1117")
    fig.suptitle(f"TARANG Telemetry Viewer — {os.path.basename(csv_path)}",
                 fontsize=16, fontweight="bold", color="#58a6ff", y=0.98)

    n = len(active)
    row = 0

    if "ECG" in active:
        row += 1
        ax = fig.add_subplot(n, 1, row)
        ax.set_facecolor("#161b22")
        ax.set_title("ECG — Raw ADC", fontsize=11, color="#f0883e")
        ax.plot(ecg_t, ecg_r0, color="#f97583", linewidth=1.5, marker="o", markersize=3, label="raw_half0[0]")
        ax.plot(ecg_t, ecg_r1, color="#79c0ff", linewidth=1.5, marker="s", markersize=3, label="raw_half1[0]")
        ax.set_ylabel("ADC Value", color="#8b949e")
        ax.grid(True, color="#21262d", linestyle="--", alpha=0.5)
        ax.legend(loc="upper right", fontsize=9)

    if "PPG" in active:
        row += 1
        ax = fig.add_subplot(n, 1, row)
        ax.set_facecolor("#161b22")
        ax.set_title("PPG — Optical (RED / IR)", fontsize=11, color="#f0883e")
        ax.plot(ppg_t, ppg_r, color="#f85149", linewidth=1.5, marker="o", markersize=3, label="RED")
        ax.plot(ppg_t, ppg_i, color="#a5d6ff", linewidth=1.5, marker="^", markersize=3, label="IR")
        ax.set_ylabel("Count", color="#8b949e")
        ax.grid(True, color="#21262d", linestyle="--", alpha=0.5)
        ax.legend(loc="upper right", fontsize=9)

    if "ACCEL" in active:
        row += 1
        ax = fig.add_subplot(n, 1, row)
        ax.set_facecolor("#161b22")
        ax.set_title("IMU — Accelerometer", fontsize=11, color="#f0883e")
        ax.plot(accel_t, ax_v, color="#f97583", linewidth=1.2, marker="o", markersize=2, label="aX")
        ax.plot(accel_t, ay_v, color="#56d364", linewidth=1.2, marker="s", markersize=2, label="aY")
        ax.plot(accel_t, az_v, color="#79c0ff", linewidth=1.2, marker="^", markersize=2, label="aZ")
        ax.set_ylabel("Raw (int16)", color="#8b949e")
        ax.grid(True, color="#21262d", linestyle="--", alpha=0.5)
        ax.legend(loc="upper right", fontsize=9)

    if "GYRO" in active:
        row += 1
        ax = fig.add_subplot(n, 1, row)
        ax.set_facecolor("#161b22")
        ax.set_title("IMU — Gyroscope", fontsize=11, color="#f0883e")
        ax.plot(gyro_t, gx_v, color="#d2a8ff", linewidth=1.2, marker="o", markersize=2, label="gX")
        ax.plot(gyro_t, gy_v, color="#f0883e", linewidth=1.2, marker="s", markersize=2, label="gY")
        ax.plot(gyro_t, gz_v, color="#3fb950", linewidth=1.2, marker="^", markersize=2, label="gZ")
        ax.set_ylabel("Raw (int16)", color="#8b949e")
        ax.set_xlabel("Time (seconds)", color="#8b949e")
        ax.grid(True, color="#21262d", linestyle="--", alpha=0.5)
        ax.legend(loc="upper right", fontsize=9)

    fig.subplots_adjust(hspace=0.45, top=0.92, bottom=0.08, left=0.08, right=0.96)
    plt.show()


# ─── MAIN ENTRY ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="TARANG Serial Telemetry Logger & Plotter")
    parser.add_argument("port", nargs="?", help="Serial port (e.g. COM11 or /dev/ttyACM0). Auto-detected if omitted.")
    parser.add_argument("--plot-csv", dest="plot_csv", help="Plot saved CSV telemetry file offline.")
    parser.add_argument("--record", dest="record_csv", help="Record serial telemetry directly to specified CSV file (headless).")
    args = parser.parse_args()

    print("=" * 60)
    print("  TARANG Telemetry Plotter & Recorder")
    print("=" * 60)

    # 1. Offline CSV Plotter Mode
    if args.plot_csv:
        plot_csv_file(args.plot_csv)
        return

    # 2. Port resolution
    port = args.port
    if not port and not args.plot_csv:
        print("\n  Auto-detecting serial port...")
        port = find_serial_port()
        if not port:
            print("\n  [FAIL] No serial ports found! Connect your board and try again.")
            sys.exit(1)
        print(f"  >> Selected: {port}")

    # 3. Headless Record Mode
    if args.record_csv:
        logger = CSVLogger(args.record_csv)
        print("\n  [RECORD MODE] Capturing serial telemetry... Press Ctrl+C to stop.\n")
        try:
            serial_reader(port, logger, verbose=True)
        except KeyboardInterrupt:
            print("\n  Stopped by user.")
        finally:
            logger.close()
        return

    # 4. Default Mode: Live GUI + Auto CSV Logger
    logger = CSVLogger()
    reader_thread = threading.Thread(target=serial_reader, args=(port, logger, True), daemon=True)
    reader_thread.start()

    time.sleep(0.5)

    try:
        run_live_plot()
    finally:
        logger.close()

    print("\n  Plot window closed. CSV log saved. Goodbye!")


if __name__ == "__main__":
    main()
