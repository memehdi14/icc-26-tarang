#!/usr/bin/env python3
"""
TARANG BLE Telemetry Receiver for Raspberry Pi / Linux
------------------------------------------------------
Connects to the TARANG EFR32 BLE device, subscribes to GATT telemetry notifications,
unpacks the 16-byte clinical event packet, and displays real-time telemetry:
- Heart Rate & Rhythm Status (Normal, AFib, Sinus Tachy/Brady, Bigeminy, Trigeminy, V-Run, VT)
- Beat Classification (N, S/PAC, V/PVC, Q)
- PAC/PVC Burden %
- HRV Metrics (SDNN, RMSSD)
"""

import asyncio
import struct
import sys
from bleak import BleakScanner, BleakClient

# UUID of the telemetry characteristic defined in Simplicity Studio GATT Configurator.
# Replace this with your exact GATT characteristic UUID if different.
TELEMETRY_CHAR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"  # Standard / Custom UUID

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
        print(f"[WARN] Received packet of invalid size: {len(data)} bytes")
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

    print("\n" + "=" * 55)
    print(f"  [TARANG CLINICAL TELEMETRY] Time: {timestamp_ms / 1000.0:.3f} s")
    print("=" * 55)
    print(f"  Heart Rate     : {current_hr} BPM")
    print(f"  RR Interval    : {rr_ms} ms")
    print(f"  Beat Class     : {beat_class_str} (Conf: {confidence}/255)")
    print(f"  Rhythm Status  : {rhythm_str}")
    print(f"  Ectopic Burden : PAC={pac_burden}%  PVC={pvc_burden}%")
    print(f"  HRV Metrics    : SDNN={sdnn_ms} ms  RMSSD={rmssd_ms} ms")
    print("=" * 55)


async def main():
    print("Scanning for TARANG BLE device...")
    devices = await BleakScanner.discover()
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

    async with BleakClient(address) as client:
        if not client.is_connected:
            print("Failed to connect.")
            return

        print(f"Connected to TARANG device!")

        # Find telemetry characteristic if UUID is default
        telemetry_uuid = TELEMETRY_CHAR_UUID
        services = client.services
        found_char = False

        for service in services:
            for char in service.characteristics:
                if "notify" in char.properties:
                    telemetry_uuid = char.uuid
                    found_char = True
                    print(f"Found notification characteristic: {char.uuid} ({char.description})")
                    break

        if not found_char:
            print("[WARN] Using fallback characteristic UUID:", TELEMETRY_CHAR_UUID)

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
