#!/usr/bin/env python3
"""
TARANG Mode A BLE Connection & GATT Discovery Test Script
=========================================================
Robust scanner & direct BLEDevice connector for Raspberry Pi (BlueZ).

Run on Raspberry Pi:
    python3 ble_test.py [OPTIONAL_MAC_ADDRESS]
"""

import sys
import asyncio
from bleak import BleakScanner, BleakClient

VITALS_HR_UUID         = "b4cf8877-ba1a-414c-a99d-de85a13fd66a"
VITALS_SPO2_UUID       = "b4cf8877-ba1a-414c-a99d-de85a13fd66b"
ANALYTICS_BURDEN_UUID  = "c5da9988-ca2b-425d-b00e-ef96b24ee77b"
EVENT_RHYTHM_UUID      = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88a"


async def main():
    target_mac = sys.argv[1].upper() if len(sys.argv) > 1 else None

    print("🔍 Scanning for TARANG BLE device...")
    device = None
    
    # 1. Discover device to get fresh BlueZ DBus device object
    devices = await BleakScanner.discover(timeout=7.0)
    for d in devices:
        name = (d.name or "").upper()
        addr = (d.address or "").upper()
        if target_mac and target_mac in addr:
            device = d
            break
        if not target_mac and ("TARANG" in name or "SILABS" in name or "EFR32" in name):
            device = d
            break

    if not device:
        print("❌ No TARANG device found. Nearby devices:")
        for d in devices:
            print(f"   • {d.address} | {d.name}")
        return

    print(f"✅ Found target: {device.name} @ {device.address}")
    print("🔗 Connecting directly via Bleak (timeout 20s)...")

    # 2. Connect passing the BLEDevice instance directly
    async with BleakClient(device, timeout=20.0) as client:
        print(f"🎉 Connected! (is_connected = {client.is_connected})")
        print("\n📋 Discovering GATT Services and Characteristics:")
        
        services = await client.get_services()
        for svc in services:
            print(f"\n  [Service] {svc.description} ({svc.uuid})")
            for char in svc.characteristics:
                props = ", ".join(char.properties)
                print(f"    └─ [Char] {char.description} ({char.uuid}) [{props}]")

        print("\n📡 Subscribing to Mode A Vitals & Rhythm notifications (listening for 15s)...")

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
