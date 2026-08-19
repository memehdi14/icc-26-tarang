#!/usr/bin/env python3
"""
TARANG BLE Mode A Telemetry Receiver for Linux / Raspberry Pi
-------------------------------------------------------------
Subscribes to all Mode A GATT Services & Characteristics on TARANG (EFR32MG26):
  - Service A (Vitals, periodic ~2.5s): HR (uint16), SpO2 (uint8), Timestamp (uint32)
  - Service B (5-Min Analytics Rollup): PVC/PAC burden, SDNN, RMSSD, pRR50, AI duty cycle, EM2 sleep %
  - Service C (Clinical Event Anomaly): Rhythm Status, Event Meta, Glitch Ticker, Beat Annotations,
                                        and 4-second chunked ECG snippet indications with reassembly.

Target Hardware: EFR32MG26B510F3200IM48 (Silicon Labs Series 2)
Requirement: Python 3.9+, bleak (`pip install bleak`)
"""

import asyncio
import struct
import sys
import time
from typing import Dict, List, Optional
from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic

# ── UUID Constants (matching gatt_configuration.btconf) ──────────────────────────
# Service A: Vitals
UUID_CHAR_VITALS_HR        = "b4cf8877-ba1a-414c-a99d-de85a13fd66a"
UUID_CHAR_VITALS_SPO2      = "b4cf8877-ba1a-414c-a99d-de85a13fd66b"
UUID_CHAR_VITALS_TIMESTAMP = "b4cf8877-ba1a-414c-a99d-de85a13fd66c"

# Service B: 5-Min Analytics Rollup
UUID_CHAR_ANALYTICS_BURDEN = "c5da9988-ca2b-425d-b00e-ef96b24ee77b"

# Service C: Clinical Event
UUID_CHAR_EVENT_RHYTHM     = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88a"
UUID_CHAR_EVENT_META       = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88b"
UUID_CHAR_EVENT_ECG_CHUNK  = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88c"
UUID_CHAR_EVENT_ECG_CTRL   = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88d"
UUID_CHAR_EVENT_ANNOTATION = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88e"
UUID_CHAR_EVENT_TICKER     = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88f"

# Rhythm Flags Bitfield Definition
RHYTHM_FLAGS = {
    0x01: "AFib Detected",
    0x02: "Sinus Tachycardia",
    0x04: "Sinus Bradycardia",
    0x08: "Ventricular Bigeminy",
    0x10: "Ventricular Trigeminy",
    0x20: "Ventricular Run (V-Run)",
    0x40: "SVT Run",
    0x80: "CRITICAL: VT Suspected!",
}

GLITCH_PATTERNS = {
    1: "Couplet",
    2: "Triplet",
    3: "Bigeminy",
    4: "Trigeminy",
    5: "V-Run",
    6: "SVT-Run",
}

BEAT_CLASSES = {
    ord("N"): "N (Normal)",
    ord("S"): "S (PAC)",
    ord("V"): "V (PVC)",
    ord("Q"): "Q (Noise/Unknown)",
    0: "N (Normal)",
    1: "S (PAC)",
    2: "V (PVC)",
    3: "Q (Noise)",
}


def decode_rhythm(flags: int) -> str:
    if flags == 0:
        return "Normal Sinus Rhythm"
    detected = [desc for mask, desc in RHYTHM_FLAGS.items() if flags & mask]
    return " | ".join(detected) if detected else f"0x{flags:02X}"


# ── Global ECG Snippet Chunk Assembly State ─────────────────────────────────────
class EcgChunkAssembler:
    def __init__(self):
        self.active_transfer = False
        self.chunks_received: Dict[int, List[int]] = {}
        self.total_expected_chunks = 0
        self.start_time = 0.0

    def start(self):
        self.active_transfer = True
        self.chunks_received.clear()
        self.total_expected_chunks = 0
        self.start_time = time.time()
        print("\n[ECG 4s] >>> Starting new waveform chunk transfer...")

    def add_chunk(self, data: bytearray):
        if len(data) < 4:
            return
        seq_id, total_chunks = struct.unpack("<HH", data[0:4])
        self.total_expected_chunks = total_chunks
        num_samples = (len(data) - 4) // 2
        samples = list(struct.unpack(f"<{num_samples}h", data[4 : 4 + num_samples * 2]))
        self.chunks_received[seq_id] = samples
        print(f"[ECG 4s] Received Chunk #{seq_id + 1}/{total_chunks} ({num_samples} samples, {len(data)}B)")

    def end(self):
        elapsed = time.time() - self.start_time
        total_samples = sum(len(s) for s in self.chunks_received.values())
        print(f"[ECG 4s] <<< Waveform Transfer Complete! {len(self.chunks_received)}/{self.total_expected_chunks} chunks, {total_samples} samples in {elapsed*1000:.1f}ms")
        self.active_transfer = False


assembler = EcgChunkAssembler()


# ── Notification Handlers ───────────────────────────────────────────────────────
def handle_vitals_hr(sender: BleakGATTCharacteristic, data: bytearray):
    if len(data) >= 2:
        hr = struct.unpack("<H", data[:2])[0]
        print(f"[VITALS] \033[92mHeart Rate: {hr} BPM\033[0m")


def handle_vitals_spo2(sender: BleakGATTCharacteristic, data: bytearray):
    if len(data) >= 1:
        spo2 = data[0]
        print(f"[VITALS] \033[96mSpO2: {spo2}%\033[0m")


def handle_analytics(sender: BleakGATTCharacteristic, data: bytearray):
    if len(data) >= 9:
        pvc_b, pac_b, sdnn, rmssd, prr50, duty10, em2_sleep = struct.unpack("<BBHHBBB", data[:9])
        print("\n" + "=" * 60)
        print("  [SERVICE B: 5-MIN ANALYTICS ROLLUP]")
        print("=" * 60)
        print(f"  PVC Burden       : {pvc_b}%")
        print(f"  PAC Burden       : {pac_b}%")
        print(f"  HRV SDNN / RMSSD : {sdnn} ms / {rmssd} ms")
        print(f"  HRV pRR50        : {prr50}%")
        print(f"  AI Duty Cycle    : {duty10 / 10.0:.1f}%")
        print(f"  EM2 Sleep Time   : {em2_sleep}%")
        print("=" * 60 + "\n")


def handle_event_rhythm(sender: BleakGATTCharacteristic, data: bytearray):
    if len(data) >= 1:
        rhythm = data[0]
        print(f"\n\033[93m[CLINICAL EVENT] Rhythm Status Changed: 0x{rhythm:02X} -> {decode_rhythm(rhythm)}\033[0m")


def handle_event_meta(sender: BleakGATTCharacteristic, data: bytearray):
    if len(data) >= 8:
        event_id, event_type, confidence, ts_ms = struct.unpack("<HBB I", data[:8])
        print(f"\033[91m[CLINICAL EVENT META] Event #{event_id} Type=0x{event_type:02X} ({decode_rhythm(event_type)}) Conf={confidence}/255 @ {ts_ms}ms\033[0m")


def handle_event_ecg_ctrl(sender: BleakGATTCharacteristic, data: bytearray):
    if len(data) >= 1:
        ctrl = data[0]
        if ctrl == 1:
            assembler.start()
        elif ctrl == 3:
            assembler.end()


def handle_event_ecg_chunk(sender: BleakGATTCharacteristic, data: bytearray):
    assembler.add_chunk(data)


def handle_event_annotations(sender: BleakGATTCharacteristic, data: bytearray):
    count = len(data) // 4
    annots = []
    for i in range(count):
        offset_ms, label, conf = struct.unpack("<HBB", data[i * 4 : (i + 1) * 4])
        cls_name = BEAT_CLASSES.get(label, f"'{chr(label)}'")
        annots.append(f"[+{offset_ms}ms: {cls_name} conf={conf}]")
    print(f"[CLINICAL ANNOTATIONS] ({count} beats): " + ", ".join(annots))


def handle_event_ticker(sender: BleakGATTCharacteristic, data: bytearray):
    if len(data) >= 6:
        pattern, ts_ms = struct.unpack("<HI", data[:6])
        name = GLITCH_PATTERNS.get(pattern, f"Pattern#{pattern}")
        print(f"\033[95m[GLITCH TICKER] Anomaly Pattern: {name} at {ts_ms} ms\033[0m")


# ── Main BLE Connection & Subscription Loop ─────────────────────────────────────
async def main():
    print("==========================================================")
    print("  TARANG Mode A Telemetry Receiver (Linux / Raspberry Pi)")
    print("==========================================================")
    print("[SCAN] Searching for TARANG BLE device (10s)...")

    devices = await BleakScanner.discover(timeout=10.0)
    target_device = None

    for d in devices:
        name = d.name or ""
        if "TARANG" in name.upper():
            target_device = d
            print(f"[FOUND] {d.name} ({d.address})")
            break

    if not target_device:
        print("[SCAN] TARANG not found by name prefix. Available BLE devices:")
        for idx, d in enumerate(devices):
            print(f"  [{idx}] {d.address} — {d.name or '(unknown)'}")
        choice = input("\nEnter device index or MAC address to connect: ").strip()
        if not choice:
            return
        if choice.isdigit() and int(choice) < len(devices):
            target_device = devices[int(choice)]
        else:
            target_device = choice

    address = getattr(target_device, "address", target_device)
    print(f"\n[CONNECT] Connecting to {address}...")

    async with BleakClient(address, timeout=20.0) as client:
        print(f"[CONNECT] Connected: {client.is_connected}")

        services = await client.get_services()
        print(f"[GATT] Discovered {len(services.services)} services.")

        # Mapping of characteristic UUID to notification callback
        subscriptions = {
            UUID_CHAR_VITALS_HR: ("Service A: Heart Rate", handle_vitals_hr),
            UUID_CHAR_VITALS_SPO2: ("Service A: SpO2", handle_vitals_spo2),
            UUID_CHAR_ANALYTICS_BURDEN: ("Service B: Analytics Rollup", handle_analytics),
            UUID_CHAR_EVENT_RHYTHM: ("Service C: Rhythm Status", handle_event_rhythm),
            UUID_CHAR_EVENT_META: ("Service C: Event Meta", handle_event_meta),
            UUID_CHAR_EVENT_ECG_CTRL: ("Service C: ECG Snippet Control", handle_event_ecg_ctrl),
            UUID_CHAR_EVENT_ECG_CHUNK: ("Service C: ECG Chunk", handle_event_ecg_chunk),
            UUID_CHAR_EVENT_ANNOTATION: ("Service C: Beat Annotations", handle_event_annotations),
            UUID_CHAR_EVENT_TICKER: ("Service C: Glitch Ticker", handle_event_ticker),
        }

        subscribed_count = 0
        for char_uuid, (desc, handler) in subscriptions.items():
            try:
                char = services.get_characteristic(char_uuid)
                if char:
                    await client.start_notify(char, handler)
                    print(f"  [SUB] Subscribed to {desc} ({char_uuid})")
                    subscribed_count += 1
            except Exception as e:
                print(f"  [WARN] Could not subscribe to {desc}: {e}")

        print(f"\n[READY] Subscribed to {subscribed_count} telemetry streams.")
        print("[STREAM] Streaming live Mode A clinical telemetry. Press Ctrl+C to exit.\n")

        try:
            while True:
                await asyncio.sleep(1.0)
        except KeyboardInterrupt:
            print("\n[DISCONNECT] Stopping subscriptions and disconnecting...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
