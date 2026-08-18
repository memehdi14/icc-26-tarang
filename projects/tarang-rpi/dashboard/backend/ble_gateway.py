#!/usr/bin/env python3
"""
Tarang Clinical — Real BLE Gateway (Mode A Event-Driven + Legacy)
=================================================================
Connects to the TARANG EFR32MG26 via BLE, subscribes to Mode A GATT services:
  - Service A: Vitals (HR, SpO2, Timestamp) -> POST /api/vitals
  - Service B: Analytics (5-Min rollups) -> POST /api/analytics
  - Service C: ClinicalEvent (Rhythm, Snippet Chunks, Annotations, Ticker) -> POST /api/events
"""

import sys
import asyncio
import os
import struct
import time
import httpx
from bleak import BleakScanner, BleakClient

# ── Mode A UUIDs ──────────────────────────────────────────────────────────────
VITALS_HR_UUID         = "b4cf8877-ba1a-414c-a99d-de85a13fd66a"
VITALS_SPO2_UUID       = "b4cf8877-ba1a-414c-a99d-de85a13fd66b"
ANALYTICS_BURDEN_UUID  = "c5da9988-ca2b-425d-b00e-ef96b24ee77b"
EVENT_RHYTHM_UUID      = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88a"
EVENT_META_UUID        = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88b"
EVENT_ECG_CHUNK_UUID   = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88c"
EVENT_ECG_CONTROL_UUID = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88d"
EVENT_ANNOTATIONS_UUID = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88e"
EVENT_TICKER_UUID      = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88f"

BACKEND_URL = os.getenv("TARANG_BACKEND_URL", "http://localhost:8000").rstrip("/")
BLE_ADDRESS = os.getenv("TARANG_BLE_ADDRESS")
CONFIGURED_SESSION_ID = os.getenv("TARANG_SESSION_ID")

VITALS_URL = f"{BACKEND_URL}/api/vitals"
ANALYTICS_URL = f"{BACKEND_URL}/api/analytics"
EVENTS_URL = f"{BACKEND_URL}/api/events"
LEGACY_INGEST_URL = f"{BACKEND_URL}/api/telemetry/ingest"
DIAGNOSTICS_URL = f"{BACKEND_URL}/api/diagnostics/update"
HEALTH_URL = f"{BACKEND_URL}/api/health/device"
RECONNECT_DELAY_S = 5

PATTERN_NAMES = {
    1: "Couplet",
    2: "Triplet",
    3: "Bigeminy",
    4: "Trigeminy",
    5: "V-Run",
    6: "SVT-Run",
}


# ── Packet Decoders ───────────────────────────────────────────────────────────

def decode_analytics_packet(data: bytearray) -> dict | None:
    """Unpack Service B Analytics 5-min struct: <BBHHBBB"""
    if len(data) < 9:
        return None
    (pvc, pac, sdnn, rmssd, prr50, duty_cycle_x10, sleep_pct) = struct.unpack("<BBHHBBB", data[:9])
    return {
        "pvc_burden_pct": float(pvc),
        "pac_burden_pct": float(pac),
        "sdnn": float(sdnn),
        "rmssd": float(rmssd),
        "prr50": float(prr50),
        "ai_duty_cycle_pct": duty_cycle_x10 / 10.0,
        "em2_sleep_pct": float(sleep_pct),
    }


# ── Chunked Snippet Reassembler ───────────────────────────────────────────────

class SnippetReassembler:
    def __init__(self):
        self.active_event_id = None
        self.chunks: dict[int, list[float]] = {}
        self.total_chunks = 0
        self.meta: dict = {}
        self.annotations: list[dict] = []

    def reset(self):
        self.chunks.clear()
        self.total_chunks = 0
        self.meta.clear()
        self.annotations.clear()

    def add_chunk(self, data: bytearray):
        if len(data) < 4:
            return
        seq_id, total = struct.unpack("<HH", data[:4])
        self.total_chunks = total
        # Samples are int16
        sample_bytes = data[4:]
        sample_count = len(sample_bytes) // 2
        samples = struct.unpack(f"<{sample_count}h", sample_bytes)
        # Normalize to float mV
        self.chunks[seq_id] = [s / 1000.0 for s in samples]

    def is_complete(self) -> bool:
        return self.total_chunks > 0 and len(self.chunks) >= self.total_chunks

    def get_full_waveform(self) -> list[float]:
        full = []
        for i in range(self.total_chunks):
            full.extend(self.chunks.get(i, []))
        return full


reassembler = SnippetReassembler()
packets_received = 0
packets_dropped = 0
last_ingest_latency_ms = 0.0


async def post_to_backend(http: httpx.AsyncClient, url: str, payload: dict):
    global packets_received, packets_dropped, last_ingest_latency_ms
    try:
        t0 = time.monotonic()
        r = await http.post(url, json=payload, timeout=2.5)
        last_ingest_latency_ms = round((time.monotonic() - t0) * 1000, 1)
        if r.status_code in (200, 201):
            packets_received += 1
        else:
            packets_dropped += 1
    except Exception as e:
        packets_dropped += 1
        print(f"[BLE][POST ERROR] {url}: {e}")


async def find_device():
    if BLE_ADDRESS:
        return BLE_ADDRESS
    print("[BLE] Scanning for TARANG device...")
    devices = await BleakScanner.discover(timeout=8.0)
    for d in devices:
        name = d.name or ""
        if any(kw in name.upper() for kw in ("TARANG", "EFR32", "SILABS")):
            print(f"[BLE] Found: {d.name} @ {d.address}")
            return d
    return None


async def run_ble_gateway():
    async with httpx.AsyncClient() as http:
        while True:
            device = await find_device()
            if not device:
                print(f"[BLE] Device not found. Retrying in {RECONNECT_DELAY_S}s...")
                await asyncio.sleep(RECONNECT_DELAY_S)
                continue

            address = device.address if hasattr(device, 'address') else str(device)
            print(f"[BLE] Connecting to {address}...")

            try:
                async with BleakClient(address, timeout=20.0) as client:
                    if not client.is_connected:
                        continue

                    session_id = CONFIGURED_SESSION_ID or f"sess_{int(time.time())}_{address.replace(':', '')[-6:]}"
                    print(f"[BLE] Connected! Session: {session_id}")

                    # ── Handlers ──────────────────────────────────────────────
                    last_hr = [75]
                    last_spo2 = [98]

                    def hr_handler(sender, data: bytearray):
                        if len(data) >= 2:
                            hr = struct.unpack("<H", data[:2])[0]
                            last_hr[0] = hr
                            asyncio.create_task(post_to_backend(http, VITALS_URL, {
                                "device_id": address,
                                "session_id": session_id,
                                "heart_rate_bpm": hr,
                                "spo2_pct": last_spo2[0],
                            }))

                    def spo2_handler(sender, data: bytearray):
                        if len(data) >= 1:
                            spo2 = data[0]
                            last_spo2[0] = spo2

                    def analytics_handler(sender, data: bytearray):
                        apkt = decode_analytics_packet(data)
                        if apkt:
                            apkt["device_id"] = address
                            apkt["session_id"] = session_id
                            asyncio.create_task(post_to_backend(http, ANALYTICS_URL, apkt))
                            print(f"[BLE][ANALYTICS] Rollup: PVC={apkt['pvc_burden_pct']}% Sleep={apkt['em2_sleep_pct']}%")

                    def rhythm_handler(sender, data: bytearray):
                        if len(data) >= 1:
                            rhythm = data[0]
                            print(f"[BLE][EVENT] Rhythm Status changed: 0x{rhythm:02X}")

                    def chunk_handler(sender, data: bytearray):
                        reassembler.add_chunk(data)
                        if reassembler.is_complete():
                            waveform = reassembler.get_full_waveform()
                            print(f"[BLE][EVENT] 4s ECG Snippet reassembled ({len(waveform)} samples). Posting...")
                            asyncio.create_task(post_to_backend(http, EVENTS_URL, {
                                "device_id": address,
                                "session_id": session_id,
                                "rhythm_status": reassembler.meta.get("rhythm_status", 0),
                                "pattern_type": reassembler.meta.get("pattern_type"),
                                "confidence": reassembler.meta.get("confidence", 0.95),
                                "sample_rate_hz": 250,
                                "waveform": waveform,
                                "annotations": reassembler.annotations,
                            }))
                            reassembler.reset()

                    def control_handler(sender, data: bytearray):
                        if len(data) >= 1 and data[0] == 1:
                            reassembler.reset()

                    # Subscribe to characteristics
                    for uuid, handler in [
                        (VITALS_HR_UUID, hr_handler),
                        (VITALS_SPO2_UUID, spo2_handler),
                        (ANALYTICS_BURDEN_UUID, analytics_handler),
                        (EVENT_RHYTHM_UUID, rhythm_handler),
                        (EVENT_ECG_CHUNK_UUID, chunk_handler),
                        (EVENT_ECG_CONTROL_UUID, control_handler),
                    ]:
                        try:
                            await client.start_notify(uuid, handler)
                        except Exception:
                            pass

                    print("[BLE] Subscribed to Mode A characteristics. Forwarding events...")
                    while client.is_connected:
                        await asyncio.sleep(1.0)

            except Exception as e:
                print(f"[BLE] Error: {e}")

            await asyncio.sleep(RECONNECT_DELAY_S)


if __name__ == "__main__":
    try:
        asyncio.run(run_ble_gateway())
    except KeyboardInterrupt:
        print("\n[BLE] Gateway stopped.")
