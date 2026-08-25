#!/usr/bin/env python3
"""
TARANG VCOM Stream Reader & Protocol Decoder
===========================================
Shared utility to stream live VCOM serial telemetry or replay CSV captures.
Supports:
  - Protocol v2 compact Base64 binary packets (@E2, @P2, @I2)
  - Protocol v1 ASCII schema (@E, @P, @I, @A, @M, @D, @V)
  - Legacy schema (@S, @B)
  - Human-readable debug prints ([ECG], [PPG], [IMU], [PIPELINE], etc.)
"""

from __future__ import annotations

import base64
import csv
import itertools
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Generator, Iterable, Optional

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False


# Data models for sensor frames
@dataclass
class ECGFrame:
    timestamp_ms: float
    sample_index: int
    raw_adc: int
    clean_adc: int
    bandpass: float
    z_score: float
    mwi: float
    threshold: float
    valid: bool
    source_type: str = "E"  # "E", "E2", "S", "DEBUG"


@dataclass
class PPGFrame:
    timestamp_ms: float
    sample_index: int
    red: int
    ir: int
    source_type: str = "P"  # "P", "P2", "DEBUG"


@dataclass
class IMUFrame:
    timestamp_ms: float
    sample_index: int
    ax: float
    ay: float
    az: float
    gx: float
    gy: float
    gz: float
    motion_energy: float
    source_type: str = "I"  # "I", "I2", "DEBUG"


@dataclass
class BeatEvent:
    timestamp_ms: float
    sample_index: int
    rr_ms: float
    hr_bpm: float
    sqi: float
    gate_trigger: bool
    gate_pass: bool
    cls_code: int
    cls_name: str
    confidence: float
    source_line: str = ""


@dataclass
class SystemMetrics:
    timestamp_ms: float
    sample_count: int
    drops: int
    cpu_load: float
    gate_rate: float
    raw_fields: list[float] = field(default_factory=list)


def auto_detect_serial_port() -> Optional[str]:
    """Find Silicon Labs / Segger J-Link VCOM port or fallback to first available."""
    if not SERIAL_AVAILABLE:
        return None
    ports = serial.tools.list_ports.comports()
    for p in ports:
        desc = (p.description or "").lower()
        mfg = (p.manufacturer or "").lower()
        if p.vid == 0x1366 or "segger" in desc or "j-link" in desc or "jlink" in desc:
            return p.device
        if any(kw in desc for kw in ["silicon labs", "efr32", "vcom", "usb serial"]):
            return p.device
        if "silicon" in mfg:
            return p.device
    if ports:
        return ports[0].device
    return "COM11"


class VCOMTelemetryStream:
    """Streams and parses TARANG telemetry from live serial or recorded CSV."""

    def __init__(self, port: Optional[str] = None, baud: int = 115200, replay_file: Optional[str] = None):
        self.port = port
        self.baud = baud
        self.replay_file = replay_file
        self.ser: Optional[serial.Serial] = None
        self.running = False
        self.records_received = 0
        self.parse_errors = 0
        self.protocol_detected = "unknown"

    def open(self):
        if self.replay_file:
            path = Path(self.replay_file)
            if not path.exists():
                raise FileNotFoundError(f"Replay file not found: {self.replay_file}")
            return
        if not SERIAL_AVAILABLE:
            raise RuntimeError("pyserial is required for live VCOM capture. Run: pip install pyserial")
        if not self.port:
            self.port = auto_detect_serial_port() or "COM11"
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.5)
            self.ser.dtr = True
            self.ser.rts = True
            self.ser.reset_input_buffer()
        except serial.SerialException as e:
            raise RuntimeError(f"Could not open serial port {self.port}: {e}")

    def close(self):
        self.running = False
        if self.ser and self.ser.is_open:
            self.ser.close()

    def stream_lines(self) -> Generator[str, None, None]:
        """Yield raw telemetry lines from live serial or replay file."""
        self.running = True
        if self.replay_file:
            path = Path(self.replay_file)
            with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
                for line in f:
                    if not self.running:
                        break
                    s = line.strip()
                    if not s or s.startswith("#"):
                        continue
                    if "raw_line" in s and "elapsed_sec" in s:
                        reader = csv.DictReader(itertools.chain([line], f))
                        for row in reader:
                            if not self.running:
                                break
                            raw = row.get("raw_line", "").strip()
                            if raw:
                                yield raw
                        break
                    yield s
        else:
            if not self.ser:
                self.open()
            while self.running:
                try:
                    line_bytes = self.ser.readline()
                    if not line_bytes:
                        continue
                    line = line_bytes.decode("utf-8", errors="replace").strip()
                    if line:
                        yield line
                except (serial.SerialException, UnicodeDecodeError):
                    continue

    def parse_line(self, line: str) -> tuple[
        Optional[list[ECGFrame]],
        Optional[list[PPGFrame]],
        Optional[list[IMUFrame]],
        Optional[BeatEvent],
        Optional[SystemMetrics],
        Optional[str]  # Raw debug text if non-structured
    ]:
        """Parses a line into strongly typed sensor frames."""
        self.records_received += 1
        line = line.strip()
        if not line:
            return None, None, None, None, None, None

        # 1. Base64 Compact Protocol (@E2, @P2, @I2)
        if line.startswith(("@E2,", "@P2,", "@I2,")):
            return self._parse_compact(line)

        # 2. Versioned / Legacy Schema (@E, @P, @I, @A, @B, @M, @D, @S, @V)
        if line.startswith("@"):
            return self._parse_schema(line)

        # 3. Human-readable debug text
        return self._parse_debug_text(line)

    def _parse_compact(self, line: str):
        tag, encoded = line.split(",", 1)
        try:
            payload = base64.b64decode(encoded, validate=True)
        except Exception:
            self.parse_errors += 1
            return None, None, None, None, None, None

        if len(payload) < 9:
            return None, None, None, None, None, None

        first_index = int.from_bytes(payload[0:4], "little")
        first_timestamp = int.from_bytes(payload[4:8], "little")
        count = payload[8]
        sample_size = {"@E2": 13, "@P2": 6, "@I2": 14}.get(tag, 0)
        if count == 0 or len(payload) != 9 + count * sample_size:
            return None, None, None, None, None, None

        period_ms = 4 if tag == "@E2" else 10
        self.protocol_detected = "validation-v2-compact"

        if tag == "@E2":
            frames = []
            for i in range(count):
                off = 9 + i * 13
                raw = int.from_bytes(payload[off:off+2], "little")
                clean = int.from_bytes(payload[off+2:off+4], "little")
                bp = int.from_bytes(payload[off+4:off+6], "little", signed=True) * 1000.0
                z = int.from_bytes(payload[off+6:off+8], "little", signed=True) / 100.0
                mwi = int.from_bytes(payload[off+8:off+10], "little")
                th = int.from_bytes(payload[off+10:off+12], "little")
                valid = bool(payload[off+12])
                frames.append(ECGFrame(
                    timestamp_ms=first_timestamp + i * period_ms,
                    sample_index=first_index + i,
                    raw_adc=raw,
                    clean_adc=clean,
                    bandpass=bp,
                    z_score=z,
                    mwi=float(mwi),
                    threshold=float(th),
                    valid=valid,
                    source_type="E2"
                ))
            return frames, None, None, None, None, None

        elif tag == "@P2":
            frames = []
            for i in range(count):
                off = 9 + i * 6
                red = int.from_bytes(payload[off:off+3], "little")
                ir = int.from_bytes(payload[off+3:off+6], "little")
                frames.append(PPGFrame(
                    timestamp_ms=first_timestamp + i * period_ms,
                    sample_index=first_index + i,
                    red=red,
                    ir=ir,
                    source_type="P2"
                ))
            return None, frames, None, None, None, None

        elif tag == "@I2":
            frames = []
            for i in range(count):
                off = 9 + i * 14
                ax = int.from_bytes(payload[off:off+2], "little", signed=True) / 16384.0
                ay = int.from_bytes(payload[off+2:off+4], "little", signed=True) / 16384.0
                az = int.from_bytes(payload[off+4:off+6], "little", signed=True) / 16384.0
                gx = int.from_bytes(payload[off+6:off+8], "little", signed=True) / 131.0
                gy = int.from_bytes(payload[off+8:off+10], "little", signed=True) / 131.0
                gz = int.from_bytes(payload[off+10:off+12], "little", signed=True) / 131.0
                energy = int.from_bytes(payload[off+12:off+14], "little")
                frames.append(IMUFrame(
                    timestamp_ms=first_timestamp + i * period_ms,
                    sample_index=first_index + i,
                    ax=ax, ay=ay, az=az,
                    gx=gx, gy=gy, gz=gz,
                    motion_energy=float(energy),
                    source_type="I2"
                ))
            return None, None, frames, None, None, None

        return None, None, None, None, None, None

    def _parse_schema(self, line: str):
        parts = line.split(",")
        tag = parts[0]
        vals = parts[1:]

        try:
            if tag == "@E" and len(vals) >= 9:
                self.protocol_detected = "validation-v1"
                idx = int(vals[0])
                ts = float(vals[1])
                raw = int(float(vals[2]))
                clean = int(float(vals[3]))
                bp = float(vals[4])
                z = float(vals[5])
                mwi = float(vals[6])
                th = float(vals[7])
                valid = bool(int(float(vals[8])))
                frame = ECGFrame(ts, idx, raw, clean, bp, z, mwi, th, valid, source_type="E")
                return [frame], None, None, None, None, None

            elif tag == "@P" and len(vals) >= 4:
                self.protocol_detected = "validation-v1"
                idx = int(vals[0])
                ts = float(vals[1])
                red = int(float(vals[2]))
                ir = int(float(vals[3]))
                frame = PPGFrame(ts, idx, red, ir, source_type="P")
                return None, [frame], None, None, None, None

            elif tag == "@I" and len(vals) >= 9:
                self.protocol_detected = "validation-v1"
                idx = int(vals[0])
                ts = float(vals[1])
                ax = float(vals[2]) / 16384.0 if abs(float(vals[2])) > 10 else float(vals[2])
                ay = float(vals[3]) / 16384.0 if abs(float(vals[3])) > 10 else float(vals[3])
                az = float(vals[4]) / 16384.0 if abs(float(vals[4])) > 10 else float(vals[4])
                gx = float(vals[5]) / 131.0 if abs(float(vals[5])) > 10 else float(vals[5])
                gy = float(vals[6]) / 131.0 if abs(float(vals[6])) > 10 else float(vals[6])
                gz = float(vals[7]) / 131.0 if abs(float(vals[7])) > 10 else float(vals[7])
                energy = float(vals[8])
                frame = IMUFrame(ts, idx, ax, ay, az, gx, gy, gz, energy, source_type="I")
                return None, None, [frame], None, None, None

            elif tag == "@S" and len(vals) >= 9:
                self.protocol_detected = "legacy"
                ts = float(vals[0])
                idx = int(float(vals[1]))
                raw = int(float(vals[2]))
                bp = float(vals[3])
                z = float(vals[4])
                mwi = float(vals[5])
                th = float(vals[6])
                valid = bool(int(float(vals[8])))
                frame = ECGFrame(ts, idx, raw, raw, bp, z, mwi, th, valid, source_type="S")
                return [frame], None, None, None, None, None

            elif tag in ("@A", "@B") and len(vals) >= 10:
                ts = float(vals[0])
                idx = int(float(vals[1]))
                rr = float(vals[2])
                
                # Correct field indices for @A:
                # vals[0]: ts, vals[1]: idx, vals[2]: rr_ms, vals[3]: local_hr_x10, vals[4]: sqi
                # vals[8]: class, vals[9]: conf, vals[11]: current_hr
                if len(vals) >= 12 and float(vals[3]) > 0:
                    hr = float(vals[3]) / 10.0
                elif 300.0 <= rr <= 2000.0:
                    hr = 60000.0 / rr
                else:
                    hr = 0.0

                sqi = float(vals[4]) / 255.0 if len(vals) > 4 else 1.0
                cls_code = int(float(vals[8])) if len(vals) > 8 else 0
                cls_names = {0: "Normal(N)", 1: "S-Ectopic(S)", 2: "V-Ectopic(V)", 3: "Unknown(Q)"}
                conf = (float(vals[9]) / 255.0) if len(vals) > 9 else 1.0
                gate_trig = (float(vals[5]) >= 0) if len(vals) > 5 else False
                gate_pass = bool(cls_code != 0)
                
                beat = BeatEvent(ts, idx, rr, hr, sqi, gate_trig, gate_pass, cls_code, cls_names.get(cls_code, "N"), conf, line)
                return None, None, None, beat, None, None

            elif tag == "@M" and len(vals) >= 4:
                ts = float(vals[0])
                samples = int(float(vals[1]))
                drops = int(float(vals[2]))
                cpu = float(vals[3])
                gate_r = float(vals[4]) if len(vals) > 4 else 0.0
                num_fields = [float(v) for v in vals]
                metrics = SystemMetrics(ts, samples, drops, cpu, gate_r, num_fields)
                return None, None, None, None, metrics, None

        except (ValueError, IndexError):
            self.parse_errors += 1
            return None, None, None, None, None, line

        return None, None, None, None, None, line

    def _parse_debug_text(self, line: str):
        now_ms = time.time() * 1000.0

        # Pattern 1: [ECG] latest_half0=2624  latest_half1=3562
        ecg_halves_match = re.search(r"\[ECG\]\s+latest_half0=(\d+)\s+latest_half1=(\d+)", line)
        if ecg_halves_match:
            raw0 = int(ecg_halves_match.group(1))
            raw1 = int(ecg_halves_match.group(2))
            f0 = ECGFrame(now_ms, self.records_received, raw0, raw0, 0.0, 0.0, 0.0, 0.0, True, source_type="DEBUG")
            f1 = ECGFrame(now_ms, self.records_received + 1, raw1, raw1, 0.0, 0.0, 0.0, 0.0, True, source_type="DEBUG")
            return [f0, f1], None, None, None, None, line

        # Pattern 2: [ECG] halves=179  total_samples=11456  overruns=0
        ecg_tot_match = re.search(r"\[ECG\]\s+halves=(\d+)\s+total_samples=(\d+)", line)
        if ecg_tot_match:
            tot = int(ecg_tot_match.group(2))
            frame = ECGFrame(now_ms, tot, 2048, 2048, 0.0, 0.0, 0.0, 0.0, True, source_type="DEBUG")
            return [frame], None, None, None, None, line

        # Pattern 3: [ECG] raw=2048 clean=2050
        ecg_match = re.search(r"\[ECG\]\s+raw=(\d+)", line)
        if ecg_match:
            raw = int(ecg_match.group(1))
            frame = ECGFrame(now_ms, self.records_received, raw, raw, 0.0, 0.0, 0.0, 0.0, True, source_type="DEBUG")
            return [frame], None, None, None, None, line

        # Pattern 4: [PPG] samples=4551  RED=262143  IR=262143  sensor=OK
        ppg_diag_match = re.search(r"\[PPG\]\s+samples=(\d+)\s+RED=(\d+)\s+IR=(\d+)", line)
        if ppg_diag_match:
            s_idx = int(ppg_diag_match.group(1))
            red = int(ppg_diag_match.group(2))
            ir = int(ppg_diag_match.group(3))
            frame = PPGFrame(now_ms, s_idx, red, ir, source_type="DEBUG")
            return None, [frame], None, None, None, line

        # Pattern 5: [PPG] red=1234 ir=5678
        ppg_match = re.search(r"\[PPG\]\s+red=(\d+)\s+ir=(\d+)", line, re.IGNORECASE)
        if ppg_match:
            red = int(ppg_match.group(1))
            ir = int(ppg_match.group(2))
            frame = PPGFrame(now_ms, self.records_received, red, ir, source_type="DEBUG")
            return None, [frame], None, None, None, line

        # Pattern 6: [IMU] accel: ax=0  ay=0  az=0
        imu_accel_match = re.search(r"\[IMU\]\s+accel:\s+ax=([\d.-]+)\s+ay=([\d.-]+)\s+az=([\d.-]+)", line)
        if imu_accel_match:
            ax = float(imu_accel_match.group(1))
            ay = float(imu_accel_match.group(2))
            az = float(imu_accel_match.group(3))
            frame = IMUFrame(now_ms, self.records_received, ax, ay, az, 0.0, 0.0, 0.0, 0.0, source_type="DEBUG")
            return None, None, [frame], None, None, line

        # Pattern 7: [IMU] ax=... ay=... az=...
        imu_match = re.search(r"\[IMU\]\s+ax=([\d.-]+)\s+ay=([\d.-]+)\s+az=([\d.-]+)", line)
        if imu_match:
            ax = float(imu_match.group(1))
            ay = float(imu_match.group(2))
            az = float(imu_match.group(3))
            frame = IMUFrame(now_ms, self.records_received, ax, ay, az, 0.0, 0.0, 0.0, 0.0, source_type="DEBUG")
            return None, None, [frame], None, None, line

        # Pattern 8: [AI] tier0_evals=47  tier1_fires=17  tier2_fires=0
        ai_match = re.search(r"\[AI\]\s+tier0_evals=(\d+)\s+tier1_fires=(\d+)", line)
        if ai_match:
            evals = int(ai_match.group(1))
            fires = int(ai_match.group(2))
            beat = BeatEvent(now_ms, evals, 800.0, 75.0, 1.0, fires > 0, False, 0, "Normal(N)", 1.0, line)
            return None, None, None, beat, None, line

        return None, None, None, None, None, line
