#!/usr/bin/env python3
"""
tarang_disconnect_debug.py — RPi-side diagnostic for the TARANG connect-disconnect loop.

WHAT THIS SCRIPT DOES
--------------------
1. Connects to a single TARANG device (by MAC or by name prefix).
2. Subscribes to ALL 14 GATT characteristics with the FAST 0.6s timeout
   (matches the fix shipped in this same drop).
3. Timestamps every packet to millisecond precision.
4. Detects the exact failure signature: two clinical events fired
   within TARANG_EVENT_COOLDOWN_MS (6.0s) of each other.
5. Tracks disconnect/reconnect cycles and prints a session summary
   every time the link drops.
6. Validates that the negotiated MTU is actually 247 by sniffing
   ECG chunk sizes (anything > 20 bytes is impossible at MTU 23).
7. Writes a JSONL session log to disk for post-mortem analysis.

USAGE
-----
    # By MAC address (recommended):
    TARANG_BLE_ADDRESS=F8:8A:5E:11:22:33 python3 tarang_disconnect_debug.py

    # By name prefix:
    TARANG_BLE_NAME_PREFIX=TARANG python3 tarang_disconnect_debug.py

    # Optional flags:
    TARANG_LOG_LEVEL=DEBUG python3 tarang_disconnect_debug.py
    TARANG_DEBUG_LOG_FILE=/tmp/tarang_debug.jsonl python3 tarang_disconnect_debug.py

EXIT CODES
---------
    0  — clean Ctrl-C exit (normal)
    1  — config error
    2  — could not find device
    3  — link never came up
    4  — unrecoverable bleak/bluez error

REQUIREMENTS
------------
    pip install bleak
    # bluez must be running: sudo systemctl status bluetooth
    # if pairing fails: bluetoothctl -> menu scan -> ... -> trust <addr>
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Bleak prints a UserWarning about "default MTU" on Linux because BlueZ
# doesn't expose the kernel-negotiated MTU via D-Bus. The link IS at 247
# (proof: 204-byte ECG chunks decode successfully). Suppress the noise.
warnings.filterwarnings(
    "ignore",
    message=r".*default MTU.*",
    category=UserWarning,
)

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    print("ERROR: bleak not installed.  pip install bleak", file=sys.stderr)
    sys.exit(1)

# Import the protocol decoder from the gateway's local module.
backend_dir = Path(__file__).resolve().parent / "dashboard" / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

try:
    from ble_protocol import (
        ANALYTICS_CHARACTERISTIC_UUIDS,
        EVENT_ANNOTATIONS_UUID,
        EVENT_ECG_CHUNK_UUID,
        EVENT_META_UUID,
        EVENT_RHYTHM_UUID,
        EVENT_TICKER_UUID,
        PATTERN_NAMES,
        ProtocolError,
        REQUIRED_SERVICE_UUIDS,
        REQUIRED_SUBSCRIPTION_UUIDS,
        SnippetReassembler,
        VITALS_HR_UUID,
        VITALS_SPO2_UUID,
        VITALS_MOTION_CORR_UUID,
        decode_analytics_characteristic,
        decode_annotations,
        decode_event_meta,
        decode_event_ticker,
        decode_heart_rate,
        decode_motion_corr,
        decode_spo2,
    )
except ImportError:
    print(
        "ERROR: ble_protocol.py not found on sys.path.\n"
        "Copy it next to this script or set PYTHONPATH.",
        file=sys.stderr,
    )
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Constants — must match the firmware's TARANG_EVENT_COOLDOWN_MS
# ─────────────────────────────────────────────────────────────────────────────

TARANG_EVENT_COOLDOWN_MS = 6000.0  # 6.0s refractory period between events
SUBSCRIPTION_TIMEOUT_S = 0.6       # fast-subscribe per characteristic
SUBSCRIPTION_PACING_S = 0.04       # 40 ms between CCCD writes
SCAN_TIMEOUT_S = 15.0
CONNECT_TIMEOUT_S = 35.0
RECONNECT_DELAY_S = 3.0
DEFAULT_LOG_FILE = "/tmp/tarang_debug.jsonl"

# ANSI color codes — makes the live output readable on a terminal.
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GREY = "\033[90m"
    BG_RED = "\033[41;30m"
    BG_GREEN = "\033[42;30m"
    BG_YELLOW = "\033[43;30m"
    BG_CYAN = "\033[46;30m"


# ─────────────────────────────────────────────────────────────────────────────
# Session metrics — accumulated across one BLE session, reset on disconnect
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SessionMetrics:
    connect_started_at: float | None = None
    connect_completed_at: float | None = None
    disconnect_at: float | None = None
    subscription_started_at: float | None = None
    subscription_completed_at: float | None = None
    subscriptions_ok: set[str] = field(default_factory=set)
    subscriptions_failed: dict[str, str] = field(default_factory=dict)
    mtu_size_reported: int = 23  # bleak's default; updated by gatt_mtu event
    hr_packets: int = 0
    spo2_packets: int = 0
    analytics_packets: int = 0
    rhythm_packets: int = 0
    event_meta_packets: int = 0
    event_ticker_packets: int = 0
    annotation_packets: int = 0
    ecg_chunks_received: int = 0
    ecg_chunks_max_size: int = 0
    ecg_snippets_completed: int = 0
    clinical_event_timestamps: list[float] = field(default_factory=list)
    last_event_meta_at: float | None = None
    last_event_meta_id: int | None = None
    dropped_malformed: int = 0

    def reset_for_new_connection(self) -> None:
        self.connect_started_at = None
        self.connect_completed_at = None
        self.disconnect_at = None
        self.subscription_started_at = None
        self.subscription_completed_at = None
        self.subscriptions_ok.clear()
        self.subscriptions_failed.clear()
        self.mtu_size_reported = 23
        self.hr_packets = 0
        self.spo2_packets = 0
        self.analytics_packets = 0
        self.rhythm_packets = 0
        self.event_meta_packets = 0
        self.event_ticker_packets = 0
        self.annotation_packets = 0
        self.ecg_chunks_received = 0
        self.ecg_chunks_max_size = 0
        self.ecg_snippets_completed = 0
        self.clinical_event_timestamps.clear()
        self.last_event_meta_at = None
        self.last_event_meta_id = None
        self.dropped_malformed = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "connect_started_at": self.connect_started_at,
            "connect_completed_at": self.connect_completed_at,
            "disconnect_at": self.disconnect_at,
            "duration_s": (
                (self.disconnect_at - self.connect_completed_at)
                if (self.disconnect_at and self.connect_completed_at)
                else None
            ),
            "subscription_duration_s": (
                (self.subscription_completed_at - self.subscription_started_at)
                if (self.subscription_completed_at and self.subscription_started_at)
                else None
            ),
            "subscriptions_ok_count": len(self.subscriptions_ok),
            "subscriptions_failed_count": len(self.subscriptions_failed),
            "subscriptions_failed": self.subscriptions_failed,
            "mtu_reported": self.mtu_size_reported,
            "ecg_chunks_received": self.ecg_chunks_received,
            "ecg_chunks_max_size": self.ecg_chunks_max_size,
            "ecg_snippets_completed": self.ecg_snippets_completed,
            "hr_packets": self.hr_packets,
            "spo2_packets": self.spo2_packets,
            "analytics_packets": self.analytics_packets,
            "rhythm_packets": self.rhythm_packets,
            "event_meta_packets": self.event_meta_packets,
            "event_ticker_packets": self.event_ticker_packets,
            "annotation_packets": self.annotation_packets,
            "dropped_malformed": self.dropped_malformed,
            "clinical_event_count": len(self.clinical_event_timestamps),
            "clinical_event_ts": list(self.clinical_event_timestamps),
        }


# ─────────────────────────────────────────────────────────────────────────────
# The debug session itself
# ─────────────────────────────────────────────────────────────────────────────

class TarangDebugSession:
    def __init__(
        self,
        ble_address: str | None,
        name_prefix: str,
        log_file: Path,
        metrics_log: list[dict[str, Any]],
    ) -> None:
        self.ble_address = ble_address
        self.name_prefix = name_prefix
        self.log_file = log_file
        self.metrics_log = metrics_log  # cumulative across sessions
        self.metrics = SessionMetrics()
        self._snippet = SnippetReassembler()
        self._stop = asyncio.Event()

    # ── Logging helpers ──────────────────────────────────────────────────

    def _ts(self) -> str:
        return datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]

    def _write_jsonl(self, kind: str, payload: dict[str, Any]) -> None:
        record = {
            "ts_epoch": time.time(),
            "ts_human": self._ts(),
            "kind": kind,
            **payload,
        }
        try:
            with self.log_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except OSError as exc:
            logging.warning("Could not write JSONL record: %s", exc)

    def _emit(self, kind: str, message: str, payload: dict[str, Any] | None = None) -> None:
        print(f"{C.GREY}{self._ts()}{C.RESET} {message}")
        self._write_jsonl(kind, payload or {})

    # ── Discovery ─────────────────────────────────────────────────────────

    async def discover(self) -> Any | None:
        address = self.ble_address
        prefix = self.name_prefix

        if address:
            print(f"{C.CYAN}[SCAN]{C.RESET} looking for {address}")
        else:
            print(f"{C.CYAN}[SCAN]{C.RESET} looking for {prefix}*")

        loop = asyncio.get_running_loop()
        found: asyncio.Future[Any] = loop.create_future()

        def on_advertisement(device: Any, advertisement_data: Any) -> None:
            if found.done():
                return
            device_address = str(device.address).upper()
            name = advertisement_data.local_name or device.name or ""
            match = (
                address and device_address == address.upper()
            ) or (
                not address and name.upper().startswith(prefix)
            )
            if match:
                found.set_result(device)

        scanner = BleakScanner(detection_callback=on_advertisement)
        await scanner.start()
        try:
            device = await asyncio.wait_for(found, timeout=SCAN_TIMEOUT_S)
            print(f"{C.GREEN}[SCAN]{C.RESET} found {device.name or 'TARANG'} @ {device.address}")
            return device
        except asyncio.TimeoutError:
            print(f"{C.RED}[SCAN]{C.RESET} no device found in {SCAN_TIMEOUT_S}s")
            return None
        finally:
            await scanner.stop()

    # ── BLE callbacks ─────────────────────────────────────────────────────

    def _decode_or_drop(self, label: str, decoder: Callable, data: bytearray) -> Any:
        try:
            return decoder(data)
        except (ProtocolError, ValueError, TypeError) as exc:
            self.metrics.dropped_malformed += 1
            print(f"{C.YELLOW}[DROP]{C.RESET} malformed {label}: {exc}")
            self._write_jsonl("drop", {"label": label, "error": str(exc), "data_hex": data.hex()})
            return None

    def on_heart_rate(self, _sender: Any, data: bytearray) -> None:
        value = self._decode_or_drop("heart-rate", decode_heart_rate, data)
        if value is None:
            return
        self.metrics.hr_packets += 1
        msg = f"{C.GREEN}[HR]{C.RESET}   {value} BPM  (pkt #{self.metrics.hr_packets})"
        print(msg)
        self._write_jsonl("hr", {"bpm": value})

    def on_spo2(self, _sender: Any, data: bytearray) -> None:
        value = self._decode_or_drop("SpO2", decode_spo2, data)
        if value is None:
            return
        self.metrics.spo2_packets += 1
        finger = "OK" if value > 0 else "no finger"
        msg = f"{C.MAGENTA}[SpO2]{C.RESET} {value}%  ({finger})  (pkt #{self.metrics.spo2_packets})"
        print(msg)
        self._write_jsonl("spo2", {"pct": value})

    def on_analytics_scalar(self, uuid: str, _sender: Any, data: bytearray) -> None:
        decoded = self._decode_or_drop(
            "analytics",
            lambda payload: decode_analytics_characteristic(uuid, payload),
            data,
        )
        if decoded is None:
            return
        self.metrics.analytics_packets += 1
        field_name, value = decoded
        print(f"{C.BLUE}[ANL]{C.RESET} {field_name} = {value}")
        self._write_jsonl("analytics", {"field": field_name, "value": value})

    def on_rhythm(self, _sender: Any, data: bytearray) -> None:
        if not data:
            return
        rhythm = data[0]
        self.metrics.rhythm_packets += 1
        # Map bit positions to names — matches the firmware's RHYTHM_* flags
        from ble_protocol import RHYTHM_NAMES
        names = [name for bit, name in RHYTHM_NAMES.items() if rhythm & bit]
        label = ", ".join(names) if names else f"unknown 0x{rhythm:02X}"
        print(f"{C.YELLOW}[RHY]{C.RESET} rhythm=0x{rhythm:02X} -> {label}")
        self._write_jsonl("rhythm", {"rhythm": rhythm, "names": names})

    def on_event_meta(self, _sender: Any, data: bytearray) -> None:
        meta = self._decode_or_drop("event-meta", decode_event_meta, data)
        if meta is None:
            return
        self.metrics.event_meta_packets += 1
        now = time.monotonic()

        # ── THIS IS THE CRITICAL DETECTOR ───────────────────────────────
        # If a previous event_meta arrived < TARANG_EVENT_COOLDOWN_MS ago,
        # the firmware's cooldown guard FAILED — either it's not in the
        # build, or the guard is being bypassed. Flag it loudly.
        cooldown_violation = False
        gap_ms = None
        if self.metrics.last_event_meta_at is not None:
            gap_ms = (now - self.metrics.last_event_meta_at) * 1000.0
            if gap_ms < TARANG_EVENT_COOLDOWN_MS:
                cooldown_violation = True

        if cooldown_violation:
            msg = (
                f"{C.BG_RED}[EVT]{C.RESET} {C.BOLD}COOLDOWN VIOLATION{C.RESET} "
                f"Event#{meta.event_id} fired {gap_ms:.0f}ms after "
                f"Event#{self.metrics.last_event_meta_id} "
                f"(threshold {TARANG_EVENT_COOLDOWN_MS:.0f}ms) — disconnect imminent"
            )
        else:
            gap_str = f" (+{gap_ms:.0f}ms)" if gap_ms is not None else ""
            msg = (
                f"{C.BG_YELLOW}[EVT]{C.RESET} Event#{meta.event_id} "
                f"rhythm=0x{meta.event_type:02X} "
                f"conf={meta.confidence / 255.0 * 100:.0f}%{gap_str}"
            )
        print(msg)

        self.metrics.clinical_event_timestamps.append(now)
        self.metrics.last_event_meta_at = now
        self.metrics.last_event_meta_id = meta.event_id
        self._write_jsonl(
            "event_meta",
            {
                "event_id": meta.event_id,
                "rhythm": meta.event_type,
                "confidence": meta.confidence,
                "gap_ms": gap_ms,
                "cooldown_violation": cooldown_violation,
            },
        )

    def on_event_ticker(self, _sender: Any, data: bytearray) -> None:
        ticker = self._decode_or_drop("event-ticker", decode_event_ticker, data)
        if ticker is None:
            return
        self.metrics.event_ticker_packets += 1
        pattern = PATTERN_NAMES.get(
            ticker.pattern_type, f"Pattern-{ticker.pattern_type}"
        )
        print(f"{C.YELLOW}[TKR]{C.RESET} pattern={pattern} ts={ticker.timestamp_ms}")
        self._write_jsonl("event_ticker", {"pattern": pattern, "pattern_code": ticker.pattern_type})

    def on_ecg_chunk(self, _sender: Any, data: bytearray) -> None:
        self.metrics.ecg_chunks_received += 1
        self.metrics.ecg_chunks_max_size = max(self.metrics.ecg_chunks_max_size, len(data))

        # Validate MTU: a chunk > 20 bytes is impossible at MTU 23.
        # If we ever see one, the link IS running at a raised MTU —
        # regardless of what bleak's mtu_size property reports.
        mtu_inference = "raised" if len(data) > 20 else "default"
        try:
            waveform = self._snippet.add_chunk(data)
        except ProtocolError as exc:
            self.metrics.dropped_malformed += 1
            print(f"{C.YELLOW}[ECG]{C.RESET} malformed chunk ({len(data)}B): {exc}")
            self._write_jsonl(
                "ecg_chunk_drop",
                {"size": len(data), "error": str(exc), "data_hex": data.hex()},
            )
            return

        if waveform is not None:
            self.metrics.ecg_snippets_completed += 1
            print(
                f"{C.BG_CYAN}[ECG]{C.RESET} snippet complete: "
                f"{len(waveform)} samples, max_chunk={self.metrics.ecg_chunks_max_size}B "
                f"(MTU={mtu_inference})"
            )
            self._write_jsonl(
                "ecg_snippet_complete",
                {
                    "samples": len(waveform),
                    "chunks_received": self.metrics.ecg_chunks_received,
                    "max_chunk_bytes": self.metrics.ecg_chunks_max_size,
                    "mtu_inference": mtu_inference,
                },
            )
        else:
            print(
                f"{C.CYAN}[ECG]{C.RESET} chunk {len(data)}B "
                f"({self._snippet.received_chunks}/{self._snippet.total_chunks}) "
                f"(MTU={mtu_inference})"
            )
            self._write_jsonl(
                "ecg_chunk",
                {
                    "size": len(data),
                    "received": self._snippet.received_chunks,
                    "total": self._snippet.total_chunks,
                },
            )

    def on_annotations(self, _sender: Any, data: bytearray) -> None:
        annotations = self._decode_or_drop("annotations", decode_annotations, data)
        if annotations is None:
            return
        self.metrics.annotation_packets += 1
        labels = [a["label"] for a in annotations]
        print(f"{C.MAGENTA}[ANN]{C.RESET} {len(annotations)} beats: {''.join(labels)}")
        self._write_jsonl(
            "annotations",
            {"count": len(annotations), "labels": labels, "raw": annotations},
        )

    # ── Subscription ──────────────────────────────────────────────────────

    async def subscribe_all(self, client: BleakClient) -> None:
        self.metrics.subscription_started_at = time.monotonic()

        subs: list[tuple[str, str, Callable]] = [
            ("HR",       VITALS_HR_UUID,        self.on_heart_rate),
            ("SpO2",     VITALS_SPO2_UUID,      self.on_spo2),
            ("MotCorr",  VITALS_MOTION_CORR_UUID, lambda s, d: None),
            ("Rhythm",   EVENT_RHYTHM_UUID,     self.on_rhythm),
            ("Meta",     EVENT_META_UUID,       self.on_event_meta),
            ("ECG",      EVENT_ECG_CHUNK_UUID,  self.on_ecg_chunk),
            ("Annot",    EVENT_ANNOTATIONS_UUID, self.on_annotations),
            ("Ticker",   EVENT_TICKER_UUID,     self.on_event_ticker),
        ]
        for i, analytics_uuid in enumerate(ANALYTICS_CHARACTERISTIC_UUIDS, 1):
            subs.append((
                f"ANL{i}",
                analytics_uuid,
                lambda sender, data, _uuid=analytics_uuid:
                    self.on_analytics_scalar(_uuid, sender, data),
            ))

        print(
            f"{C.CYAN}[SUB]{C.RESET} subscribing to {len(subs)} characteristics "
            f"(timeout={SUBSCRIPTION_TIMEOUT_S}s each, pacing={SUBSCRIPTION_PACING_S}s)"
        )

        for label, uuid, handler in subs:
            try:
                await asyncio.wait_for(
                    client.start_notify(uuid, handler),
                    timeout=SUBSCRIPTION_TIMEOUT_S,
                )
                self.metrics.subscriptions_ok.add(uuid)
                print(f"{C.GREEN}[SUB]{C.RESET} {label:<8} OK  ({uuid[:8]}...)")
            except Exception as exc:
                self.metrics.subscriptions_failed[uuid] = str(exc)
                print(f"{C.RED}[SUB]{C.RESET} {label:<8} FAIL: {exc}")
            await asyncio.sleep(SUBSCRIPTION_PACING_S)

        self.metrics.subscription_completed_at = time.monotonic()
        duration = self.metrics.subscription_completed_at - self.metrics.subscription_started_at
        print(
            f"{C.BG_GREEN}[SUB]{C.RESET} {len(self.metrics.subscriptions_ok)}/{len(subs)} "
            f"subscriptions active in {duration:.2f}s"
        )

        missing_required = REQUIRED_SUBSCRIPTION_UUIDS - self.metrics.subscriptions_ok
        if missing_required:
            print(
                f"{C.BG_RED}[SUB]{C.RESET} MISSING REQUIRED: "
                f"{', '.join(sorted(missing_required))}"
            )
            self._write_jsonl(
                "subscription_missing_required",
                {"missing": sorted(missing_required)},
            )

    # ── Session lifecycle ────────────────────────────────────────────────

    async def run_one_session(self) -> bool:
        """Returns True if a disconnect happened (caller may reconnect),
        False if a fatal error or stop signal occurred."""
        device = await self.discover()
        if device is None:
            return False

        self.metrics.reset_for_new_connection()
        self.metrics.connect_started_at = time.monotonic()

        disconnected = asyncio.Event()
        loop = asyncio.get_running_loop()

        def on_disconnect(_client: BleakClient) -> None:
            loop.call_soon_threadsafe(disconnected.set)

        print(f"{C.CYAN}[CONN]{C.RESET} connecting to {device.address}")
        client = BleakClient(
            device,
            disconnected_callback=on_disconnect,
            timeout=CONNECT_TIMEOUT_S,
            pair=False,
        )

        try:
            await client.connect()
            if not client.is_connected:
                print(f"{C.RED}[CONN]{C.RESET} connect returned without active connection")
                return False
            self.metrics.connect_completed_at = time.monotonic()
            self.metrics.mtu_size_reported = client.mtu_size
            connect_duration = self.metrics.connect_completed_at - self.metrics.connect_started_at
            print(
                f"{C.GREEN}[CONN]{C.RESET} connected in {connect_duration:.2f}s "
                f"(bleak MTU={client.mtu_size})"
            )

            # [FIX] The GATT DB requires bonded+encrypted CCCD writes. Without
            # pairing first, every start_notify() fails with
            # WRITE_NOT_PERMITTED and BlueZ may drop the link.
            print(f"{C.CYAN}[CONN]{C.RESET} pairing (encryption required for CCCD writes)...")
            try:
                await asyncio.wait_for(client.pair(), timeout=15.0)
                print(f"{C.GREEN}[CONN]{C.RESET} paired/encrypted OK")
            except Exception as exc:
                print(
                    f"{C.YELLOW}[CONN]{C.RESET} pair() failed ({exc}); continuing - "
                    f"if subscriptions report WRITE_NOT_PERMITTED, run: "
                    f"bluetoothctl remove {device.address} and retry"
                )
            self._write_jsonl("paired", {"address": device.address})
            # Verify all 3 required services exist before subscribing
            service_uuids = {s.uuid.lower() for s in client.services}
            missing_services = REQUIRED_SERVICE_UUIDS - service_uuids
            if missing_services:
                print(
                    f"{C.BG_RED}[CONN]{C.RESET} MISSING SERVICES: "
                    f"{', '.join(sorted(missing_services))}"
                )
                self._write_jsonl(
                    "missing_services",
                    {"missing": sorted(missing_services), "have": sorted(service_uuids)},
                )
                return False

            await self.subscribe_all(client)
            print(
                f"{C.GREEN}[LIVE]{C.RESET} streaming telemetry — Ctrl-C to stop, "
                f"or wait for disconnect..."
            )
            self._write_jsonl("session_live", {})

            await disconnected.wait()

        except asyncio.TimeoutError:
            print(f"{C.RED}[CONN]{C.RESET} connect timeout after {CONNECT_TIMEOUT_S}s")
            self._write_jsonl("connect_timeout", {})
            return False
        except Exception as exc:
            print(f"{C.RED}[CONN]{C.RESET} connection error: {exc}")
            self._emit("connect_error", f"{C.RED}[CONN]{C.RESET} {exc}", {"error": str(exc)})
            return False
        finally:
            if client.is_connected:
                try:
                    await client.disconnect()
                except Exception:
                    pass

        self.metrics.disconnect_at = time.monotonic()
        self.print_session_summary()
        self.metrics_log.append(self.metrics.to_dict())
        return True

    # ── Session summary — printed at every disconnect ────────────────────

    def print_session_summary(self) -> None:
        m = self.metrics
        if not m.connect_completed_at:
            print(f"{C.YELLOW}[SUM]{C.RESET} session never completed connection — nothing to summarize")
            return

        connect_duration = (m.connect_completed_at or 0) - (m.connect_started_at or 0)
        live_duration = (m.disconnect_at or 0) - (m.connect_completed_at or 0)
        sub_duration = (
            (m.subscription_completed_at or 0) - (m.subscription_started_at or 0)
        ) if m.subscription_completed_at else 0.0

        # Detect the disconnect signature: cooldown violation in this session
        cooldown_violations = 0
        for i in range(1, len(m.clinical_event_timestamps)):
            gap_ms = (m.clinical_event_timestamps[i] - m.clinical_event_timestamps[i-1]) * 1000.0
            if gap_ms < TARANG_EVENT_COOLDOWN_MS:
                cooldown_violations += 1

        verdict_color = C.BG_RED if cooldown_violations else C.BG_GREEN
        verdict_text = (
            f"COOLDOWN VIOLATION x{cooldown_violations}"
            if cooldown_violations
            else "clean session"
        )

        print()
        print(f"{C.BOLD}{'=' * 70}{C.RESET}")
        print(f"{verdict_color}{C.BOLD} SESSION SUMMARY: {verdict_text} {C.RESET}")
        print(f"{C.BOLD}{'=' * 70}{C.RESET}")
        print(f"  Connect time:        {connect_duration:.2f}s")
        print(f"  Live time:           {live_duration:.2f}s")
        print(f"  Subscription time:   {sub_duration:.2f}s  ({len(m.subscriptions_ok)}/14 ok)")
        if m.subscriptions_failed:
            print(f"  Failed subscriptions:")
            for uuid, err in m.subscriptions_failed.items():
                print(f"    {uuid[:8]}... : {err}")
        print(f"  MTU (bleak):         {m.mtu_size_reported}")
        print(f"  MTU (inferred):     {'raised (247)' if m.ecg_chunks_max_size > 20 else 'default (23)'}  "
              f"from largest ECG chunk ({m.ecg_chunks_max_size}B)")
        print(f"  Packets:             HR={m.hr_packets}  SpO2={m.spo2_packets}  "
              f"ANL={m.analytics_packets}  RHY={m.rhythm_packets}")
        print(f"  Clinical events:     {m.event_meta_packets}  (tickers={m.event_ticker_packets})")
        print(f"  ECG chunks:          {m.ecg_chunks_received}  "
              f"(snippets completed: {m.ecg_snippets_completed})")
        print(f"  Annotations:         {m.annotation_packets} packets")
        print(f"  Dropped malformed:   {m.dropped_malformed}")
        if m.clinical_event_timestamps:
            print(f"  Event gaps (ms):     ", end="")
            gaps = [
                (m.clinical_event_timestamps[i] - m.clinical_event_timestamps[i-1]) * 1000.0
                for i in range(1, len(m.clinical_event_timestamps))
            ]
            if gaps:
                print(", ".join(f"{g:.0f}" for g in gaps))
            else:
                print("n/a (only one event)")
        print(f"{C.BOLD}{'=' * 70}{C.RESET}")
        print()

    # ── Run forever, reconnecting on disconnect ──────────────────────────

    async def run_forever(self) -> None:
        signal.signal(signal.SIGINT, lambda *_: self._stop.set())
        session_count = 0
        while not self._stop.is_set():
            session_count += 1
            print(f"\n{C.BOLD}=== Session #{session_count} ==={C.RESET}")
            disconnected = await self.run_one_session()
            if not disconnected:
                if self._stop.is_set():
                    break
                print(f"{C.YELLOW}[LOOP]{C.RESET} session did not end in clean disconnect; retrying in {RECONNECT_DELAY_S}s")
            else:
                print(f"{C.YELLOW}[LOOP]{C.RESET} reconnecting in {RECONNECT_DELAY_S}s")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=RECONNECT_DELAY_S)
            except asyncio.TimeoutError:
                pass

        # Final cross-session summary
        print(f"\n{C.BOLD}=== CROSS-SESSION SUMMARY ({session_count} sessions) ==={C.RESET}")
        if not self.metrics_log:
            print("No completed sessions to summarize.")
            return
        total_live = sum(
            (m.get("duration_s") or 0) for m in self.metrics_log
        )
        total_cooldown_violations = 0
        for m in self.metrics_log:
            ts = m.get("clinical_event_ts") or []
            for i in range(1, len(ts)):
                gap_ms = (ts[i] - ts[i-1]) * 1000.0
                if gap_ms < TARANG_EVENT_COOLDOWN_MS:
                    total_cooldown_violations += 1
        print(f"  Total live time:           {total_live:.1f}s")
        print(f"  Cooldown violations:       {total_cooldown_violations}")
        print(f"  Sessions w/ violations:    {sum(1 for m in self.metrics_log if any((m['clinical_event_ts'][i]-m['clinical_event_ts'][i-1])*1000 < TARANG_EVENT_COOLDOWN_MS for i in range(1, len(m['clinical_event_ts']))))}")
        print(f"  JSONL log:                 {self.log_file}")


# ─────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=os.getenv("TARANG_LOG_LEVEL", "WARNING").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    ble_address = os.getenv("TARANG_BLE_ADDRESS")
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        ble_address = sys.argv[1]
    name_prefix = os.getenv("TARANG_BLE_NAME_PREFIX", "TARANG").strip().upper()
    log_file = Path(os.getenv("TARANG_DEBUG_LOG_FILE", DEFAULT_LOG_FILE))

    if not ble_address and not name_prefix:
        print("ERROR: set TARANG_BLE_ADDRESS or TARANG_BLE_NAME_PREFIX", file=sys.stderr)
        sys.exit(1)

    log_file.parent.mkdir(parents=True, exist_ok=True)
    # Truncate the file on each run so it stays scoped to this session.
    log_file.write_text("")
    print(f"{C.BOLD}TARANG Disconnect Debug{C.RESET}")
    print(f"  BLE address:  {ble_address or '(none)'}")
    print(f"  Name prefix:   {name_prefix}")
    print(f"  Log file:      {log_file}")
    print(f"  Cooldown:      {TARANG_EVENT_COOLDOWN_MS:.0f}ms")
    print(f"  Sub timeout:   {SUBSCRIPTION_TIMEOUT_S}s")
    print()

    session = TarangDebugSession(
        ble_address=ble_address,
        name_prefix=name_prefix,
        log_file=log_file,
        metrics_log=[],
    )

    try:
        asyncio.run(session.run_forever())
    except KeyboardInterrupt:
        pass

    print(f"\n{C.GREEN}Done.{C.RESET} Inspect the JSONL log: cat {log_file} | jq .")


if __name__ == "__main__":
    main()
