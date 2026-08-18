#!/usr/bin/env python3
"""
TARANG BLE Telemetry Receiver for Raspberry Pi / Linux — mmd_tarang.py
---------------------------------------------------------------------
Connects to the TARANG EFR32 BLE device, subscribes to GATT telemetry notifications,
unpacking the 16-byte clinical event packet, and displays real-time telemetry with
exact raw 128 binary bits, raw hex bytes, and offset breakdown.
"""

import asyncio
import struct
import sys
from bleak import BleakScanner, BleakClient

# UUID of the telemetry characteristic defined in Simplicity Studio GATT Configurator.
TELEMETRY_CHAR_UUID = "b4cf8877-ba1a-414c-a99d-de85a13fd66a"

# Rhythm Flag Bitfield Bitmask Definitions
RHYTHM_FLAGS = {
    0x01: "AFib Detected",
    0x02: "Sinus Tachycardia",
    0x04: "Sinus Bradycardia",
    0x08: "Bigeminy",
    0x10: "Trigeminy",
    0x20: "V-Run",
    0x40: "SVT-Run",
    0x80: "CRITICAL: VT Suspected!",
}

BEAT_CLASSES = {0: "N (Normal)", 1: "S (PAC)", 2: "V (PVC)", 3: "Q (Noise)"}


def decode_rhythm_flags(flags: int) -> str:
    if flags == 0:
        return "Normal Sinus Rhythm"
    detected = [name for mask, name in RHYTHM_FLAGS.items() if flags & mask]
    return " | ".join(detected)


def notification_handler(sender: int, data: bytearray):
    if len(data) != 16:
        print(f"[WARN] Received packet of invalid size: {len(data)} bytes (expected 16)")
        hex_dump = " ".join(f"{b:02X}" for b in data)
        print(f"       Raw bytes ({len(data)}B): {hex_dump}")
        return

    # Unpack 16-byte packed C struct: <IBBHBBBBHH
    (
        timestamp_ms,
        beat_class_val,
        confidence,
        rr_ms,
        rhythm_flags,
        pac_burden,
        pvc_burden,
        current_hr,
        sdnn_ms,
        rmssd_ms,
    ) = struct.unpack("<IBBHBBBBHH", data)

    beat_class_str = BEAT_CLASSES.get(beat_class_val, f"Unknown({beat_class_val})")
    rhythm_str = decode_rhythm_flags(rhythm_flags)

    # Format raw hex and raw binary bits
    hex_str = " ".join(f"{b:02X}" for b in data)
    bin_str = " ".join(f"{b:08b}" for b in data)

    print("\n" + "=" * 65)
    print(f"  [TARANG CLINICAL TELEMETRY PACKET] (16 Bytes Received)")
    print("=" * 65)
    print(f"  RAW HEX  : {hex_str}")
    print(f"  RAW BITS : {bin_str}")
    print("-" * 65)
    print(f"  [00..03] Timestamp      : {timestamp_ms} ms ({timestamp_ms / 1000.0:.3f} s)")
    print(f"  [04]     Beat Class     : {beat_class_val} -> {beat_class_str}")
    print(f"  [05]     Confidence     : {confidence} / 255")
    print(f"  [06..07] RR Interval    : {rr_ms} ms")
    print(f"  [08]     Rhythm Flags   : 0x{rhythm_flags:02X} -> {rhythm_str}")
    print(f"  [09]     PAC Burden     : {pac_burden}%")
    print(f"  [10]     PVC Burden     : {pvc_burden}%")
    print(f"  [11]     Heart Rate     : {current_hr} BPM")
    print(f"  [12..13] SDNN           : {sdnn_ms} ms")
    print(f"  [14..15] RMSSD          : {rmssd_ms} ms")
    print("=" * 65)


async def main():
    print("Scanning for TARANG BLE device (10s)...")
    devices = await BleakScanner.discover(timeout=10.0)
    target_device = None

    for d in devices:
        name = d.name or ""
        if "TARANG" in name.upper() or "EFR32" in name.upper() or "SILABS" in name.upper():
            target_device = d
            break

    if not target_device:
        print("TARANG device not found by name. Available devices:")
        for idx, d in enumerate(devices):
            print(f"  [{idx}] {d.address} — {d.name}")
        choice = input("\nEnter device index or address to connect (or press Enter to exit): ").strip()
        if not choice:
            return
        if choice.isdigit() and int(choice) < len(devices):
            target_device = devices[int(choice)]
        else:
            target_device = choice

    address = getattr(target_device, "address", target_device)
    print(f"\nConnecting to TARANG at {address}...")

    async with BleakClient(address, timeout=20.0) as client:
        if not client.is_connected:
            print("Failed to connect.")
            return

        print(f"Connected to TARANG device!")

        telemetry_uuid = TELEMETRY_CHAR_UUID
        services = await client.get_services()
        found_char = False

        for service in services:
            for char in service.characteristics:
                if char.uuid.lower() == TELEMETRY_CHAR_UUID.lower():
                    telemetry_uuid = char.uuid
                    found_char = True
                    print(f"Found telemetry characteristic: {char.uuid} ({char.description})")
                    break
            if found_char:
                break

        if not found_char:
            print("[WARN] Telemetry characteristic not found by exact UUID.")
            for service in services:
                for char in service.characteristics:
                    if "notify" in char.properties:
                        print(f"  Candidate notify characteristic: {char.uuid} ({char.description})")
            print("[WARN] Falling back to configured UUID:", TELEMETRY_CHAR_UUID)

        print(f"Subscribing to telemetry notifications on {telemetry_uuid}...")
        await client.start_notify(telemetry_uuid, notification_handler)

        print("\nStreaming live clinical telemetry. Press Ctrl+C to stop.\n")
        try:
            while True:
                await asyncio.sleep(1.0)
        except KeyboardInterrupt:
            print("\nStopping telemetry stream...")
            await client.stop_notify(telemetry_uuid)
            print("Disconnected.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
