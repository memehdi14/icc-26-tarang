#!/usr/bin/env python3
"""
TARANG RPi Hub — tarang_hub.py
-------------------------------
Connects to the TARANG EFR32 BLE peripheral without pairing or bonding,
subscribes to Clinical Telemetry and Device Health notifications,
and optionally forwards packets to a local FastAPI backend.

Usage on Raspberry Pi:
    pip install bleak requests
    python3 tarang_hub.py [--backend http://localhost:8000]
"""

import asyncio
import struct
import sys
import argparse
import time

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from bleak import BleakScanner, BleakClient
from bleak.exc import BleakError

# ── GATT UUIDs (must match gatt_configuration.btconf) ─────────────────────
TELEMETRY_CHAR_UUID  = "b4cf8877-ba1a-414c-a99d-de85a13fd66a"
HEALTH_CHAR_UUID     = "c5da9988-ca2b-425d-b00e-ef96b24ee77b"

# ── Clinical packet layout (16 bytes, little-endian) ──────────────────────
# <IBBHBBBBHH
#  uint32 timestamp_ms
#  uint8  beat_class
#  uint8  confidence
#  uint16 rr_interval_ms
#  uint8  rhythm_flags
#  uint8  pac_burden_pct
#  uint8  pvc_burden_pct
#  uint8  current_hr
#  uint16 sdnn_ms
#  uint16 rmssd_ms
TELEMETRY_FMT  = "<IBBHBBBBHH"
TELEMETRY_SIZE = struct.calcsize(TELEMETRY_FMT)   # 16

RHYTHM_FLAGS = {
    0x01: "AFib",
    0x02: "SinusTachy",
    0x04: "SinusBrady",
    0x08: "Bigeminy",
    0x10: "Trigeminy",
    0x20: "V-Run",
    0x40: "SVT-Run",
    0x80: "VT!",
}
BEAT_CLASSES = {0: "N", 1: "S(PAC)", 2: "V(PVC)", 3: "Q(Noise)"}

backend_url: str | None = None


def _check_backend() -> bool:
    if not HAS_REQUESTS or not backend_url:
        return False
    try:
        r = requests.get(f"{backend_url}/health", timeout=1.0)
        return r.status_code == 200
    except Exception:
        return False


def _post_to_backend(endpoint: str, payload: dict) -> None:
    if not HAS_REQUESTS or not backend_url:
        return
    try:
        requests.post(f"{backend_url}{endpoint}", json=payload, timeout=1.0)
    except Exception:
        pass


def _decode_telemetry(data: bytes) -> dict | None:
    if len(data) != TELEMETRY_SIZE:
        print(f"[WARN] Telemetry packet wrong size: {len(data)}B (expected {TELEMETRY_SIZE}B)")
        return None
    fields = struct.unpack(TELEMETRY_FMT, data)
    ts, beat_cls, conf, rr, rhythm, pac, pvc, hr, sdnn, rmssd = fields
    rhythm_str = " | ".join(name for mask, name in RHYTHM_FLAGS.items() if rhythm & mask) or "NSR"
    beat_str   = BEAT_CLASSES.get(beat_cls, f"?{beat_cls}")
    return {
        "timestamp_ms":   ts,
        "beat_class":     beat_str,
        "confidence":     conf,
        "rr_interval_ms": rr,
        "rhythm":         rhythm_str,
        "rhythm_flags":   rhythm,
        "pac_burden_pct": pac,
        "pvc_burden_pct": pvc,
        "heart_rate":     hr,
        "sdnn_ms":        sdnn,
        "rmssd_ms":       rmssd,
    }


def on_telemetry(sender: int, data: bytearray) -> None:
    pkt = _decode_telemetry(bytes(data))
    if pkt is None:
        return
    print(
        f"[TELE] HR={pkt['heart_rate']:3d}bpm  RR={pkt['rr_interval_ms']:4d}ms  "
        f"Beat={pkt['beat_class']}  Rhythm={pkt['rhythm']}  "
        f"PAC={pkt['pac_burden_pct']}%  PVC={pkt['pvc_burden_pct']}%  "
        f"SDNN={pkt['sdnn_ms']}ms  RMSSD={pkt['rmssd_ms']}ms"
    )
    _post_to_backend("/telemetry", pkt)


def on_health(sender: int, data: bytearray) -> None:
    print(f"[HEALTH] {len(data)}B: {data.hex()}")
    _post_to_backend("/health_packet", {"raw_hex": data.hex(), "length": len(data)})


async def find_tarang(timeout: float = 10.0) -> str | None:
    """Scan and return the address of the first TARANG device found."""
    print(f"[BLE] Scanning for TARANG device ({timeout:.0f}s)...")
    devices = await BleakScanner.discover(timeout=timeout)
    for d in devices:
        name = (d.name or "").upper()
        if "TARANG" in name:
            print(f"[BLE] Found: {d.name} @ {d.address}")
            return d.address
    print("[BLE] TARANG device not found. Available devices:")
    for d in devices:
        print(f"       {d.address}  {d.name or '(no name)'}")
    return None


async def run_once(address: str) -> None:
    """Connect, subscribe, and stream until disconnect."""
    print(f"[BLE] Connecting to {address} (no pairing)...")
    async with BleakClient(address, timeout=20.0) as client:
        if not client.is_connected:
            print("[BLE] Connection failed.")
            return
        print(f"[BLE] Connected!")

        # Subscribe to telemetry notifications
        try:
            await client.start_notify(TELEMETRY_CHAR_UUID, on_telemetry)
            print(f"[BLE] Subscribed: Clinical Telemetry")
        except BleakError as e:
            print(f"[BLE][WARN] Could not subscribe to telemetry: {e}")

        # Subscribe to device health notifications (best-effort)
        try:
            await client.start_notify(HEALTH_CHAR_UUID, on_health)
            print(f"[BLE] Subscribed: Device Health")
        except BleakError:
            pass

        print("[BLE] Streaming. Press Ctrl+C to stop.\n")
        try:
            while client.is_connected:
                await asyncio.sleep(1.0)
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass

        print("[BLE] Disconnected.")


async def main(args: argparse.Namespace) -> None:
    global backend_url
    backend_url = args.backend

    if backend_url:
        if _check_backend():
            print(f"[BLE] Backend OK: {backend_url}")
        else:
            print(f"[BLE] Warning: Backend at {backend_url} not responding — continuing without it.")

    retry_delay = 5.0
    while True:
        try:
            address = await find_tarang(timeout=10.0)
            if address is None:
                print(f"[BLE] Retrying in {retry_delay:.0f}s...\n")
                await asyncio.sleep(retry_delay)
                continue

            await run_once(address)
            retry_delay = 5.0   # reset backoff on clean disconnect
        except BleakError as e:
            print(f"[BLE] BLE error: {e}")
        except KeyboardInterrupt:
            print("\n[BLE] Stopped by user.")
            break
        except Exception as e:
            print(f"[BLE] Unexpected error: {e}")

        print(f"[BLE] Reconnecting in {retry_delay:.0f}s...")
        await asyncio.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, 60.0)   # exponential backoff, max 60s


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TARANG BLE Hub")
    parser.add_argument(
        "--backend",
        default=None,
        metavar="URL",
        help="FastAPI backend base URL (e.g. http://localhost:8000)"
    )
    args = parser.parse_args()
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        sys.exit(0)
