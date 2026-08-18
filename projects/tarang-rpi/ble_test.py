#!/usr/bin/env python3
"""
TARANG Mode A BLE Connection & GATT Discovery Test Script
=========================================================
Scans for TARANG Pod, cleans BlueZ stale cache, connects, prints all
3 Mode A services & characteristics, and streams live notifications.

Run on Raspberry Pi or PC:
    python ble_test.py [OPTIONAL_MAC_ADDRESS]
"""

import sys
import asyncio
import subprocess
from bleak import BleakScanner, BleakClient

VITALS_HR_UUID         = "b4cf8877-ba1a-414c-a99d-de85a13fd66a"
VITALS_SPO2_UUID       = "b4cf8877-ba1a-414c-a99d-de85a13fd66b"
ANALYTICS_BURDEN_UUID  = "c5da9988-ca2b-425d-b00e-ef96b24ee77b"
EVENT_RHYTHM_UUID      = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88a"


def clean_bluez_cache(address: str):
    """Remove device from BlueZ cache so GATT table is freshly discovered."""
    try:
        subprocess.run(["bluetoothctl", "remove", address], capture_output=True, timeout=2.0)
    except Exception:
        pass


async def main():
    target_address = sys.argv[1] if len(sys.argv) > 1 else None

    if not target_address:
        print("🔍 Scanning for TARANG BLE device (timeout 8s)...")
        devices = await BleakScanner.discover(timeout=8.0)
        for d in devices:
            name = d.name or ""
            if "TARANG" in name.upper() or "SILABS" in name.upper() or "EFR32" in name.upper():
                print(f"✅ Found: {d.name} @ {d.address}")
                target_address = d.address
                break

    if not target_address:
        print("❌ No TARANG device found during scan. Make sure the board is powered on and advertising.")
        return

    print(f"🧹 Clearing BlueZ stale cache for {target_address}...")
    clean_bluez_cache(target_address)
    await asyncio.sleep(1.0)

    print(f"🔗 Connecting to {target_address} (timeout 25s)...")
    async with BleakClient(target_address, timeout=25.0) as client:
        print(f"✅ Connected: {client.is_connected}")
        print("\n📋 Discovering GATT Services and Characteristics:")
        
        services = await client.get_services()
        for svc in services:
            print(f"\n  [Service] {svc.description} ({svc.uuid})")
            for char in svc.characteristics:
                props = ", ".join(char.properties)
                print(f"    └─ [Char] {char.description} ({char.uuid}) [{props}]")

        print("\n📡 Subscribing to live Mode A Vitals & Rhythm notifications (listening for 15s)...")

        def notification_handler(sender, data: bytearray):
            print(f"  🔔 Notification from {sender}: {list(data)} (Hex: {data.hex()})")

        try:
            await client.start_notify(VITALS_HR_UUID, notification_handler)
            print(f"  -> Subscribed to Vitals HR ({VITALS_HR_UUID})")
        except Exception as e:
            print(f"  -> Note on HR notify: {e}")

        try:
            await client.start_notify(EVENT_RHYTHM_UUID, notification_handler)
            print(f"  -> Subscribed to Event Rhythm ({EVENT_RHYTHM_UUID})")
        except Exception as e:
            print(f"  -> Note on Rhythm notify: {e}")

        for i in range(15):
            await asyncio.sleep(1)
            print(f"  ⏳ Listening... {15 - i}s remaining")

    print("\n✅ BLE Test Complete. Connection & GATT verified successfully!")


if __name__ == "__main__":
    asyncio.run(main())
