#!/usr/bin/env python3
"""Parse a TARANG VCOM capture and generate a complete validation report."""

from __future__ import annotations

import argparse
import base64
import csv
import html
import itertools
import json
import re
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


BEAT_NAMES = {0: "N", 1: "S", 2: "V", 3: "Q"}
BEAT_COLORS = {0: "#1f7a4d", 1: "#d97706", 2: "#c62828", 3: "#4b5563"}


@dataclass
class Session:
    protocol: str = "unknown"
    stream_version: int = 0
    rates_hz: dict[str, int] = field(default_factory=dict)
    ecg: list[list[float]] = field(default_factory=list)
    ppg: list[list[float]] = field(default_factory=list)
    imu: list[list[float]] = field(default_factory=list)
    beat: list[list[float]] = field(default_factory=list)
    metrics: list[list[float]] = field(default_factory=list)
    diagnostics: list[list[float]] = field(default_factory=list)
    telemetry_records: int = 0
    parse_errors: int = 0

    def arrays(self) -> dict[str, np.ndarray]:
        widths = {
            "ecg": 9,
            "ppg": 4,
            "imu": 9,
            "beat": 16,
            "metrics": 9,
            "diagnostics": 17,
        }
        return {
            name: np.asarray(getattr(self, name), dtype=float).reshape(-1, width)
            for name, width in widths.items()
        }


def _numbers(fields: list[str], expected: int) -> list[float] | None:
    if len(fields) != expected:
        return None
    try:
        return [float(value) for value in fields]
    except ValueError:
        return None


def _compact_u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 2], "little", signed=False)


def _compact_i16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 2], "little", signed=True)


def _parse_compact_packet(line: str, session: Session) -> bool:
    if not line.startswith(("@E2,", "@P2,", "@I2,")):
        return False

    record_type, encoded = line.split(",", 1)
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error):
        return False
    if len(payload) < 9:
        return False

    first_index = int.from_bytes(payload[0:4], "little")
    first_timestamp = int.from_bytes(payload[4:8], "little")
    count = payload[8]
    sample_size = {"@E2": 13, "@P2": 6, "@I2": 14}[record_type]
    if count == 0 or len(payload) != 9 + count * sample_size:
        return False

    period_ms = 4 if record_type == "@E2" else 10
    for sample_number in range(count):
        offset = 9 + sample_number * sample_size
        sample_index = first_index + sample_number
        timestamp_ms = first_timestamp + sample_number * period_ms

        if record_type == "@E2":
            session.ecg.append([
                timestamp_ms,
                sample_index,
                _compact_u16(payload, offset),
                _compact_u16(payload, offset + 2),
                _compact_i16(payload, offset + 4) * 1000,
                _compact_i16(payload, offset + 6),
                _compact_u16(payload, offset + 8),
                _compact_u16(payload, offset + 10),
                payload[offset + 12],
            ])
        elif record_type == "@P2":
            session.ppg.append([
                timestamp_ms,
                sample_index,
                int.from_bytes(payload[offset:offset + 3], "little"),
                int.from_bytes(payload[offset + 3:offset + 6], "little"),
            ])
        else:
            session.imu.append([
                timestamp_ms,
                sample_index,
                _compact_i16(payload, offset),
                _compact_i16(payload, offset + 2),
                _compact_i16(payload, offset + 4),
                _compact_i16(payload, offset + 6),
                _compact_i16(payload, offset + 8),
                _compact_i16(payload, offset + 10),
                _compact_u16(payload, offset + 12),
            ])

    session.protocol = "validation-v2"
    return True


def parse_telemetry_line(line: str, session: Session) -> bool:
    """Parse current validation records and the older @S/@B capture format."""
    line = line.strip()
    if not line.startswith("@") or line.startswith("@SCHEMA"):
        return False

    if _parse_compact_packet(line, session):
        return True

    fields = line.split(",")
    record_type = fields[0]
    values = fields[1:]

    if record_type == "@V":
        parsed = _numbers(values, 4)
        if parsed is None:
            return False
        session.protocol = "validation-v2" if int(parsed[0]) >= 2 else "validation-v1"
        session.stream_version = int(parsed[0])
        session.rates_hz = {
            "ecg": int(parsed[1]),
            "ppg": int(parsed[2]),
            "imu": int(parsed[3]),
        }
    elif record_type == "@E":
        parsed = _numbers(values, 9)
        if parsed is None:
            return False
        session.protocol = session.protocol if session.protocol != "unknown" else "validation-v1"
        # Device time, sample index, raw, clean, bandpass, z, MWI, threshold, valid.
        session.ecg.append([
            parsed[1], parsed[0], parsed[2], parsed[3], parsed[4],
            parsed[5], parsed[6], parsed[7], parsed[8],
        ])
    elif record_type == "@P":
        if len(values) == 4:
            parsed = _numbers(values, 4)
            if parsed is None:
                return False
            session.ppg.append([parsed[1], parsed[0], parsed[2], parsed[3]])
        elif len(values) == 5:
            parsed = _numbers(values, 5)
            if parsed is None:
                return False
            session.protocol = session.protocol if session.protocol != "unknown" else "legacy"
            session.ppg.append([parsed[0], parsed[1], parsed[3], parsed[4]])
        else:
            return False
    elif record_type == "@I":
        parsed = _numbers(values, 9)
        if parsed is None:
            return False
        # Device time (ms), sample index, ax, ay, az, gx, gy, gz, motion_mg
        session.imu.append([
            parsed[1], parsed[0], parsed[2], parsed[3], parsed[4],
            parsed[5], parsed[6], parsed[7], parsed[8],
        ])
    elif record_type == "@A":
        parsed = _numbers(values, 16) or _numbers(values, 15)
        if parsed is None:
            return False
        session.protocol = "validation-v1"
        session.beat.append(parsed)
    elif record_type == "@M":
        parsed = _numbers(values, 9)
        if parsed is None:
            return False
        session.metrics.append(parsed)
    elif record_type == "@D":
        parsed = _numbers(values, 17)
        if parsed is None:
            return False
        session.diagnostics.append(parsed)
    elif record_type == "@S":
        parsed = _numbers(values, 9)
        if parsed is None:
            return False
        session.protocol = "legacy"
        # Legacy had no separate clean ADC channel.
        session.ecg.append([
            parsed[0], parsed[1], parsed[2], parsed[2], parsed[3],
            parsed[4], parsed[5], parsed[6], parsed[8],
        ])
    elif record_type == "@B":
        parsed = _numbers(values, 15)
        if parsed is None:
            return False
        session.protocol = session.protocol if session.protocol != "unknown" else "legacy"
        session.beat.append(parsed)
    else:
        return False

    session.telemetry_records += 1
    return True


def iter_log_lines(path: Path) -> Iterable[tuple[str, float]]:
    """Yield raw VCOM lines from logger CSVs or plain serial text files."""
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        for first_data_line in handle:
            stripped = first_data_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "raw_line" in stripped and "elapsed_sec" in stripped:
                reader = csv.DictReader(itertools.chain([first_data_line], handle))
                for row in reader:
                    raw_line = row.get("raw_line", "")
                    try:
                        elapsed_ms = float(row.get("elapsed_sec", "0") or 0) * 1000.0
                    except ValueError:
                        elapsed_ms = 0.0
                    yield raw_line, elapsed_ms
                return

            yield first_data_line.rstrip("\r\n"), 0.0
            for line in handle:
                yield line.rstrip("\r\n"), 0.0
            return


def load_session(path: Path) -> Session:
    session = Session()
    fallback_index = 0
    for line, elapsed_ms in iter_log_lines(path):
        stripped = line.strip()
        if stripped.startswith("@"):
            if not parse_telemetry_line(stripped, session) and not stripped.startswith("@SCHEMA"):
                session.parse_errors += 1
            continue

        # Very old diagnostic logs can still provide a raw ECG trace.
        match = re.search(r"\[ECG\].*?raw(?:_adc)?[=:]\s*(\d+)", stripped, re.IGNORECASE)
        if match:
            raw = float(match.group(1))
            session.ecg.append([elapsed_ms, fallback_index, raw, raw, 0, 0, 0, 0, 1])
            fallback_index += 1

    if not session.ecg:
        raise ValueError(
            "No ECG samples were found. Flash a validation-stream build, reset the board "
            "after log_vcom opens VCOM, and confirm @E lines are arriving."
        )
    if session.protocol == "unknown":
        session.protocol = "diagnostic-fallback"
    return session


def _origin_ms(data: dict[str, np.ndarray]) -> float:
    starts = [rows[0, 0] for rows in data.values() if rows.size]
    return float(min(starts)) if starts else 0.0


def _time_s(rows: np.ndarray, origin_ms: float) -> np.ndarray:
    return (rows[:, 0] - origin_ms) / 1000.0 if rows.size else np.empty(0)


def _gap_count(rows: np.ndarray, sample_index_column: int = 1) -> int:
    if len(rows) < 2:
        return 0
    increments = np.diff(rows[:, sample_index_column])
    return int(np.count_nonzero(increments != 1))


def _measured_rate(rows: np.ndarray) -> float | None:
    if len(rows) < 2:
        return None
    duration_s = (rows[-1, 0] - rows[0, 0]) / 1000.0
    sample_span = rows[-1, 1] - rows[0, 1]
    return float(sample_span / duration_s) if duration_s > 0 else None


def build_summary(session: Session, source: Path) -> dict:
    data = session.arrays()
    ecg = data["ecg"]
    duration_s = float(max(0.0, (ecg[-1, 0] - ecg[0, 0]) / 1000.0))
    beat_classes = {name: 0 for name in BEAT_NAMES.values()}
    for value in data["beat"][:, 8].astype(int) if data["beat"].size else []:
        name = BEAT_NAMES.get(int(value), "Q")
        beat_classes[name] = beat_classes.get(name, 0) + 1

    diagnostics = data["diagnostics"]
    metrics = data["metrics"]
    return {
        "source": str(source.resolve()),
        "protocol": session.protocol,
        "stream_version": session.stream_version,
        "declared_rates_hz": session.rates_hz,
        "duration_seconds": round(duration_s, 3),
        "records": {
            "telemetry": session.telemetry_records,
            "parse_errors": session.parse_errors,
            "ecg": len(ecg),
            "ppg": len(data["ppg"]),
            "imu": len(data["imu"]),
            "beats": len(data["beat"]),
            "ppg_metric_windows": len(metrics),
            "diagnostic_snapshots": len(diagnostics),
        },
        "measured_rates_hz": {
            name: None if (rate := _measured_rate(data[name])) is None else round(rate, 3)
            for name in ("ecg", "ppg", "imu")
        },
        "sample_index_gaps": {
            name: _gap_count(data[name]) for name in ("ecg", "ppg", "imu")
        },
        "beat_classes": beat_classes,
        "ppg_valid_windows": int(np.count_nonzero(metrics[:, 8])) if metrics.size else 0,
        "maximums": {
            "ecg_overruns": int(np.max(diagnostics[:, 2])) if diagnostics.size else 0,
            "dropped_frames": int(np.max(diagnostics[:, 15])) if diagnostics.size else 0,
            "dsp_pending_overflows": int(np.max(diagnostics[:, 16])) if diagnostics.size else 0,
            "nlms_safety_resets": int(np.max(diagnostics[:, 14])) if diagnostics.size else 0,
        },
    }


def _empty_axis(axis: plt.Axes, message: str) -> None:
    axis.text(0.5, 0.5, message, ha="center", va="center", color="#6b7280", transform=axis.transAxes)
    axis.set_xticks([])
    axis.set_yticks([])


def build_figure(session: Session, title: str) -> plt.Figure:
    data = session.arrays()
    origin = _origin_ms(data)
    ecg, ppg, imu = data["ecg"], data["ppg"], data["imu"]
    beat, metrics, diagnostics = data["beat"], data["metrics"], data["diagnostics"]

    figure, axes = plt.subplots(7, 1, figsize=(16, 18), sharex=True)
    figure.patch.set_facecolor("#f5f7f8")
    figure.suptitle(title, x=0.055, ha="left", fontsize=16, fontweight="bold", color="#172126")

    te = _time_s(ecg, origin)
    axes[0].plot(te, ecg[:, 2], color="#223038", linewidth=0.7, label="Raw ADC")
    axes[0].plot(te, ecg[:, 3], color="#c04b36", linewidth=0.75, alpha=0.85, label="NLMS clean ADC")
    axes[0].set_ylabel("ADC counts")
    axes[0].set_title("ECG acquisition and NLMS output", loc="left")
    axes[0].legend(loc="upper right", ncols=2)

    axes[1].plot(te, ecg[:, 4] / 1000.0, color="#156f78", linewidth=0.8, label="Bandpass")
    axes[1].plot(te, ecg[:, 5] / 1000.0, color="#7651a8", linewidth=0.7, alpha=0.8, label="Z-score")
    dsp_axis = axes[1].twinx()
    dsp_axis.plot(te, ecg[:, 6] / 1000.0, color="#dc8b21", linewidth=0.75, label="MWI")
    dsp_axis.plot(te, ecg[:, 7] / 1000.0, color="#bf3030", linewidth=0.7, linestyle="--", label="Threshold")
    axes[1].set_ylabel("DSP amplitude")
    dsp_axis.set_ylabel("MWI")
    axes[1].set_title("ECG DSP and adaptive threshold", loc="left")
    lines = axes[1].get_lines() + dsp_axis.get_lines()
    axes[1].legend(lines, [line.get_label() for line in lines], loc="upper right", ncols=4)

    if ppg.size:
        tp = _time_s(ppg, origin)
        axes[2].plot(tp, ppg[:, 2] - np.median(ppg[:, 2]), color="#b32f4a", linewidth=0.75, label="RED AC")
        axes[2].plot(tp, ppg[:, 3] - np.median(ppg[:, 3]), color="#173e67", linewidth=0.75, label="IR AC")
        axes[2].set_ylabel("ADC - median")
        axes[2].legend(loc="upper right", ncols=2)
    else:
        _empty_axis(axes[2], "No @P samples captured")
    axes[2].set_title("PPG RED and IR waveforms", loc="left")

    if imu.size:
        ti = _time_s(imu, origin)
        for column, label, color in ((2, "Ax", "#176b87"), (3, "Ay", "#c96c2b"), (4, "Az", "#2b7a4b")):
            axes[3].plot(ti, imu[:, column] / 16384.0, linewidth=0.8, label=label, color=color)
        motion_axis = axes[3].twinx()
        motion_axis.plot(ti, imu[:, 8], color="#873b8f", linewidth=0.7, alpha=0.55, label="Motion")
        axes[3].set_ylabel("Acceleration (g)")
        motion_axis.set_ylabel("Motion (mg)")
        lines = axes[3].get_lines() + motion_axis.get_lines()
        axes[3].legend(lines, [line.get_label() for line in lines], loc="upper right", ncols=4)
    else:
        _empty_axis(axes[3], "No @I samples captured")
    axes[3].set_title("IMU motion reference used by NLMS", loc="left")

    if beat.size:
        tb = _time_s(beat, origin)
        axes[4].plot(tb, beat[:, 5] / 1000.0, "o-", color="#6c4aa1", markersize=3, linewidth=0.8, label="Gate")
        axes[4].plot(tb, beat[:, 6] / 1000.0, "o-", color="#c73535", markersize=3, linewidth=0.8, label="P(V)")
        axes[4].plot(tb, beat[:, 7] / 1000.0, "o-", color="#d8831f", markersize=3, linewidth=0.8, label="P(S)")
        for row, beat_time in zip(beat, tb):
            class_id = int(row[8])
            axes[4].scatter(beat_time, 1.04, color=BEAT_COLORS.get(class_id, "#4b5563"), s=18, zorder=4)
        axes[4].axhline(0.25, color="#6c4aa1", linestyle=":", linewidth=0.8)
        axes[4].set_ylim(-0.05, 1.1)
        axes[4].set_ylabel("Probability")
        axes[4].legend(loc="upper right", ncols=3)
    else:
        _empty_axis(axes[4], "No @A beat inference records captured")
    axes[4].set_title("AI gate, S/V classifier, and beat labels", loc="left")

    has_clinical = False
    if beat.size:
        tb = _time_s(beat, origin)
        axes[5].plot(tb, beat[:, 11], color="#20262d", linewidth=1.0, marker=".", label="ECG HR")
        has_clinical = True
    if metrics.size:
        tm = _time_s(metrics, origin)
        axes[5].plot(tm, metrics[:, 3], color="#14785d", linewidth=1.0, marker=".", label="PPG pulse")
        oxygen_axis = axes[5].twinx()
        oxygen_axis.plot(tm, metrics[:, 2], color="#1f62a2", linewidth=1.0, marker=".", label="SpO2")
        oxygen_axis.set_ylabel("SpO2 (%)")
        has_clinical = True
        lines = axes[5].get_lines() + oxygen_axis.get_lines()
        axes[5].legend(lines, [line.get_label() for line in lines], loc="upper right", ncols=3)
    elif beat.size:
        axes[5].legend(loc="upper right")
    if not has_clinical:
        _empty_axis(axes[5], "No beat or PPG metric records captured")
    axes[5].set_ylabel("Rate (BPM)")
    axes[5].set_title("Clinical metrics", loc="left")

    if diagnostics.size:
        td = _time_s(diagnostics, origin)
        axes[6].step(td, diagnostics[:, 2], where="post", color="#bd3030", label="ECG overruns")
        axes[6].step(td, diagnostics[:, 15], where="post", color="#d27616", label="Dropped frames")
        axes[6].step(td, diagnostics[:, 16], where="post", color="#6e4d94", label="DSP queue overflow")
        nlms_axis = axes[6].twinx()
        nlms_axis.plot(td, diagnostics[:, 13] / 10.0, color="#137366", marker=".", label="NLMS suppression")
        nlms_axis.set_ylabel("Suppression (%)")
        axes[6].set_ylabel("Cumulative count")
        lines = axes[6].get_lines() + nlms_axis.get_lines()
        axes[6].legend(lines, [line.get_label() for line in lines], loc="upper right", ncols=4)
    else:
        _empty_axis(axes[6], "No @D diagnostics captured")
    axes[6].set_title("Pipeline integrity and NLMS diagnostics", loc="left")
    axes[6].set_xlabel("Device time from capture start (seconds)")

    for axis in axes:
        axis.set_facecolor("#ffffff")
        axis.grid(True, color="#d8dde0", linewidth=0.45, alpha=0.75)
        axis.margins(x=0)
        axis.tick_params(labelsize=8)
        axis.title.set_fontsize(10)
        axis.title.set_fontweight("bold")

    figure.tight_layout(rect=(0.03, 0.02, 0.98, 0.975))
    return figure


def build_dsp_figure(session: Session, title: str) -> plt.Figure:
    """Generate high-resolution plot of all processed DSP pipeline stages."""
    data = session.arrays()
    origin = _origin_ms(data)
    ecg = data["ecg"]
    beat = data["beat"]

    figure, axes = plt.subplots(4, 1, figsize=(16, 12), sharex=True)
    figure.patch.set_facecolor("#f5f7f8")
    figure.suptitle(f"{title} - Processed DSP Waveforms", x=0.055, ha="left", fontsize=15, fontweight="bold", color="#172126")

    te = _time_s(ecg, origin)

    # Panel 1: Raw vs Clean
    axes[0].plot(te, ecg[:, 2], color="#2d3748", linewidth=0.7, label="Raw AD8232 ADC")
    axes[0].plot(te, ecg[:, 3], color="#e53e3e", linewidth=0.8, alpha=0.85, label="NLMS Motion-Cleaned ADC")
    if beat.size:
        tb = _time_s(beat, origin)
        for row, beat_time in zip(beat, tb):
            cid = int(row[8])
            axes[0].axvline(beat_time, color=BEAT_COLORS.get(cid, "#718096"), linestyle=":", alpha=0.6, linewidth=0.8)
    axes[0].set_ylabel("ADC Counts")
    axes[0].set_title("1. Raw Acquisition vs. NLMS Motion-Filtered ECG", loc="left")
    axes[0].legend(loc="upper right", ncols=2)

    # Panel 2: Bandpass (0.5 - 40 Hz)
    axes[1].plot(te, ecg[:, 4] / 1000.0, color="#0d9488", linewidth=0.8, label="Morphology Bandpass (0.5–40 Hz)")
    axes[1].axhline(0, color="#94a3b8", linestyle="--", linewidth=0.6)
    axes[1].set_ylabel("Amplitude")
    axes[1].set_title("2. Baseline-Removed 4th-Order Butterworth Bandpass", loc="left")
    axes[1].legend(loc="upper right")

    # Panel 3: Z-Score Normalized
    axes[2].plot(te, ecg[:, 5] / 1000.0, color="#7c3aed", linewidth=0.8, label="Rolling 30s Z-Score Normalized (μ=0, σ=1)")
    axes[2].axhline(0, color="#94a3b8", linestyle="--", linewidth=0.6)
    axes[2].set_ylabel("Z-Score (σ)")
    axes[2].set_title("3. Rolling Standardized Amplitude for ML Inference", loc="left")
    axes[2].legend(loc="upper right")

    # Panel 4: Pan-Tompkins MWI and Adaptive Threshold
    axes[3].plot(te, ecg[:, 6] / 1000.0, color="#d97706", linewidth=0.85, label="Moving Window Integrator (MWI)")
    axes[3].plot(te, ecg[:, 7] / 1000.0, color="#dc2626", linewidth=0.8, linestyle="--", label="Adaptive Threshold (TH1)")
    if beat.size:
        tb = _time_s(beat, origin)
        for row, beat_time in zip(beat, tb):
            cid = int(row[8])
            axes[3].scatter(beat_time, 1.0, color=BEAT_COLORS.get(cid, "#dc2626"), s=24, zorder=5)
    axes[3].set_ylabel("MWI Energy")
    axes[3].set_title("4. Pan-Tompkins QRS Energy & Dynamic Detection Threshold", loc="left")
    axes[3].set_xlabel("Device time from capture start (seconds)")
    axes[3].legend(loc="upper right", ncols=2)

    for ax in axes:
        ax.set_facecolor("#ffffff")
        ax.grid(True, color="#e2e8f0", linewidth=0.5, alpha=0.8)
        ax.margins(x=0)
        ax.tick_params(labelsize=8)
        ax.title.set_fontsize(10)
        ax.title.set_fontweight("bold")

    figure.tight_layout(rect=(0.03, 0.02, 0.98, 0.975))
    return figure


def build_imu_correlation_figure(session: Session, title: str) -> tuple[plt.Figure | None, dict]:
    """Generate IMU-to-ECG motion correlation, artifact cancellation, and scatter plots."""
    data = session.arrays()
    ecg = data["ecg"]
    imu = data["imu"]

    if ecg.size == 0 or imu.size == 0:
        return None, {"available": False}

    origin = _origin_ms(data)
    te = _time_s(ecg, origin)
    ti = _time_s(imu, origin)

    # Calculate ECG motion cancellation artifact = |Raw - Clean|
    raw_ecg = ecg[:, 2]
    clean_ecg = ecg[:, 3]
    ecg_artifact = np.abs(raw_ecg - clean_ecg)

    # Calculate 3D acceleration magnitude (in g)
    ax = imu[:, 2] / 16384.0
    ay = imu[:, 3] / 16384.0
    az = imu[:, 4] / 16384.0
    accel_mag = np.sqrt(ax**2 + ay**2 + az**2)
    motion_mg = imu[:, 8]

    # Interpolate IMU motion onto ECG sample timestamps for accurate correlation
    motion_interp = np.interp(ecg[:, 0], imu[:, 0], motion_mg, left=0, right=0)
    accel_mag_interp = np.interp(ecg[:, 0], imu[:, 0], accel_mag, left=1.0, right=1.0)

    # Compute Pearson Correlation
    if np.std(motion_interp) > 1e-6 and np.std(ecg_artifact) > 1e-6:
        corr_matrix = np.corrcoef(motion_interp, ecg_artifact)
        r_motion_artifact = float(corr_matrix[0, 1])
    else:
        r_motion_artifact = 0.0

    # NLMS Suppression stats
    active_motion_mask = motion_interp > 50.0  # > 50 mg motion threshold
    mean_artifact_motion = float(np.mean(ecg_artifact[active_motion_mask])) if np.any(active_motion_mask) else 0.0
    mean_artifact_rest = float(np.mean(ecg_artifact[~active_motion_mask])) if np.any(~active_motion_mask) else 0.0
    max_artifact = float(np.max(ecg_artifact)) if ecg_artifact.size else 0.0

    metrics = {
        "available": True,
        "pearson_r_motion_artifact": round(r_motion_artifact, 4),
        "mean_artifact_during_motion": round(mean_artifact_motion, 2),
        "mean_artifact_at_rest": round(mean_artifact_rest, 2),
        "max_nlms_correction_adc": round(max_artifact, 2),
        "motion_samples_pct": round(float(np.mean(active_motion_mask)) * 100.0, 1),
    }

    figure, axes = plt.subplots(3, 1, figsize=(16, 11))
    figure.patch.set_facecolor("#f5f7f8")
    figure.suptitle(f"{title} - IMU Motion vs. ECG Artifact Correlation", x=0.055, ha="left", fontsize=15, fontweight="bold", color="#172126")

    # Panel 1: Time-domain comparison of NLMS Correction vs IMU Motion
    axes[0].plot(te, ecg_artifact, color="#c53030", linewidth=0.8, label="ECG Artifact (|Raw - Clean ADC|)")
    ax0_twin = axes[0].twinx()
    ax0_twin.plot(ti, motion_mg, color="#3182ce", linewidth=0.75, alpha=0.7, label="IMU Motion Index (mg)")
    ax0_twin.set_ylabel("Motion (mg)", color="#3182ce")
    axes[0].set_ylabel("ADC Correction")
    axes[0].set_title("1. Dynamic NLMS Motion Artifact Cancellation vs. IMU Motion Intensity", loc="left")
    lines0 = axes[0].get_lines() + ax0_twin.get_lines()
    axes[0].legend(lines0, [l.get_label() for l in lines0], loc="upper right", ncols=2)

    # Panel 2: Scatter correlation plot (ECG Artifact vs. Motion Intensity)
    sample_step = max(1, len(ecg) // 2000)  # Downsample scatter points for clean rendering
    axes[1].scatter(motion_interp[::sample_step], ecg_artifact[::sample_step], color="#2b6cb0", alpha=0.35, s=12, edgecolors="none")
    if len(motion_interp) > 10 and np.std(motion_interp) > 1e-4:
        poly_fit = np.polyfit(motion_interp, ecg_artifact, deg=1)
        fit_x = np.linspace(float(np.min(motion_interp)), float(np.max(motion_interp)), 100)
        fit_y = np.polyval(poly_fit, fit_x)
        axes[1].plot(fit_x, fit_y, color="#e53e3e", linewidth=2.0, label=f"Linear Fit (r = {r_motion_artifact:+.3f})")
    axes[1].set_xlabel("IMU Motion Magnitude (mg)")
    axes[1].set_ylabel("ECG Artifact Magnitude (ADC Counts)")
    axes[1].set_title(f"2. IMU-to-ECG Motion Coupling (Pearson Correlation r = {r_motion_artifact:+.3f})", loc="left")
    axes[1].legend(loc="upper left")

    # Panel 3: 3-Axis Accelerometer Profile
    axes[2].plot(ti, ax, color="#319795", linewidth=0.8, label="Ax (g)")
    axes[2].plot(ti, ay, color="#dd6b20", linewidth=0.8, label="Ay (g)")
    axes[2].plot(ti, az, color="#38a169", linewidth=0.8, label="Az (g)")
    axes[2].set_ylabel("Acceleration (g)")
    axes[2].set_xlabel("Device time from capture start (seconds)")
    axes[2].set_title("3. 3-Axis IMU Acceleration Profile", loc="left")
    axes[2].legend(loc="upper right", ncols=3)

    for ax_i in axes:
        ax_i.set_facecolor("#ffffff")
        ax_i.grid(True, color="#e2e8f0", linewidth=0.5, alpha=0.8)
        ax_i.tick_params(labelsize=8)
        ax_i.title.set_fontsize(10)
        ax_i.title.set_fontweight("bold")

    figure.tight_layout(rect=(0.03, 0.02, 0.98, 0.975))
    return figure, metrics


def write_html_report(path: Path, png_overview: Path, png_dsp: Path, png_imu: Path | None, summary: dict, imu_metrics: dict) -> None:
    encoded_overview = base64.b64encode(png_overview.read_bytes()).decode("ascii")
    encoded_dsp = base64.b64encode(png_dsp.read_bytes()).decode("ascii") if png_dsp.exists() else ""
    encoded_imu = base64.b64encode(png_imu.read_bytes()).decode("ascii") if png_imu and png_imu.exists() else ""

    summary_rows = "".join(
        f"<tr><th>{html.escape(str(key))}</th><td><code>{html.escape(json.dumps(value))}</code></td></tr>"
        for key, value in summary.items()
    )

    imu_section = ""
    if imu_metrics.get("available"):
        imu_section = f"""
        <h2>IMU-to-ECG Motion Correlation</h2>
        <p><strong>Pearson Correlation (r):</strong> {imu_metrics['pearson_r_motion_artifact']} | 
           <strong>Mean Artifact during Motion:</strong> {imu_metrics['mean_artifact_during_motion']} ADC | 
           <strong>Active Motion:</strong> {imu_metrics['motion_samples_pct']}% of session</p>
        """

    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TARANG Validation Report</title><style>
body{{margin:0;background:#eef1f2;color:#172126;font:14px system-ui,sans-serif}}
main{{max-width:1500px;margin:auto;padding:24px}}
h1{{font-size:22px;margin:0 0 16px}}
h2{{font-size:18px;margin:24px 0 8px;color:#1a202c}}
img{{display:block;width:100%;background:white;border:1px solid #cfd6d9;margin-bottom:20px;border-radius:6px}}
table{{width:100%;margin-top:18px;border-collapse:collapse;background:white;border-radius:6px;overflow:hidden}}
th,td{{padding:9px 12px;border:1px solid #d8dde0;text-align:left;vertical-align:top}}
th{{width:220px;background:#f6f8f8}}code{{white-space:pre-wrap;word-break:break-word}}
</style></head><body><main>
<h1>TARANG Clinical & Sensor Validation Report</h1>

<h2>1. Complete 7-Panel Overview</h2>
<img src="data:image/png;base64,{encoded_overview}" alt="TARANG sensor validation overview">

<h2>2. Processed DSP Waveforms (NLMS, Bandpass, Z-Score, MWI)</h2>
<img src="data:image/png;base64,{encoded_dsp}" alt="TARANG DSP pipeline waveforms">

{f'<h2>3. IMU Motion vs ECG Artifact Correlation</h2><img src="data:image/png;base64,{encoded_imu}" alt="IMU correlation">' if encoded_imu else ''}

{imu_section}

<h2>Capture Summary & Health Diagnostics</h2>
<table>{summary_rows}</table>
</main></body></html>"""
    path.write_text(document, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="log_vcom CSV or raw VCOM text file")
    parser.add_argument("--output-dir", type=Path, help="directory for PNG, HTML, and JSON outputs")
    parser.add_argument("--save", type=Path, help="override output PNG path")
    parser.add_argument("--html", type=Path, help="override output HTML path")
    parser.add_argument("--no-open", action="store_true", help="do not open the HTML report")
    parser.add_argument("--no-show", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    try:
        session = load_session(args.csv)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    output_dir = args.output_dir or args.csv.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    png_path = args.save or output_dir / f"{args.csv.stem}_overview.png"
    dsp_png_path = output_dir / f"{args.csv.stem}_dsp_waveforms.png"
    imu_png_path = output_dir / f"{args.csv.stem}_imu_correlation.png"
    html_path = args.html or output_dir / f"{args.csv.stem}_report.html"
    json_path = output_dir / f"{args.csv.stem}_summary.json"

    summary = build_summary(session, args.csv)
    title = f"TARANG validation: {args.csv.stem}"

    # 1. Overview Figure
    fig_overview = build_figure(session, title)
    fig_overview.savefig(png_path, dpi=150, facecolor=fig_overview.get_facecolor())
    plt.close(fig_overview)

    # 2. Processed DSP Waveforms Figure
    fig_dsp = build_dsp_figure(session, title)
    fig_dsp.savefig(dsp_png_path, dpi=150, facecolor=fig_dsp.get_facecolor())
    plt.close(fig_dsp)

    # 3. IMU-ECG Motion Correlation Figure
    fig_imu, imu_metrics = build_imu_correlation_figure(session, title)
    if fig_imu is not None:
        fig_imu.savefig(imu_png_path, dpi=150, facecolor=fig_imu.get_facecolor())
        plt.close(fig_imu)
        summary["imu_correlation"] = imu_metrics
    else:
        imu_png_path = None

    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_html_report(html_path, png_path, dsp_png_path, imu_png_path, summary, imu_metrics)

    records = summary["records"]
    rates = summary["measured_rates_hz"]
    print("=" * 65)
    print(f"  TARANG DSP VALIDATION & IMU CORRELATION: {args.csv.name}")
    print("=" * 65)
    print(
        f"[SESSION] Duration={summary['duration_seconds']:.2f}s | ECG={records['ecg']} "
        f"PPG={records['ppg']} IMU={records['imu']} Beats={records['beats']}"
    )
    print(f"[RATES]   ECG={rates['ecg']} Hz | PPG={rates['ppg']} Hz | IMU={rates['imu']} Hz")
    if imu_metrics.get("available"):
        print(f"[IMU-DSP] Pearson Correlation r(Motion, ECG Artifact) = {imu_metrics['pearson_r_motion_artifact']:+.4f}")
        print(f"[IMU-DSP] Mean Artifact during Motion = {imu_metrics['mean_artifact_during_motion']} ADC | Rest = {imu_metrics['mean_artifact_at_rest']} ADC")
    print("-" * 65)
    print(f"[SAVED] Overview Plot  : {png_path}")
    print(f"[SAVED] DSP Waveforms  : {dsp_png_path}")
    if imu_png_path:
        print(f"[SAVED] IMU Correlation: {imu_png_path}")
    print(f"[SAVED] HTML Report    : {html_path}")
    print(f"[SAVED] JSON Summary   : {json_path}")
    print("=" * 65)

    if not (args.no_open or args.no_show):
        webbrowser.open(html_path.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
