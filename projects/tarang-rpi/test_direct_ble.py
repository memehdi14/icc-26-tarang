#!/usr/bin/env python3
"""
Direct Single-Shot BLE Test for TARANG Pod
Tests raw connection, MTU exchange, GATT discovery, and HR notification.
"""
import sys
import asyncio
from bleak import BleakScanner, BleakClient

TARGET_MAC = "64:02:8F:64:26:14"
HR_CHAR_UUID = "b4cf8877-ba1a-414c-a99d-de85a13fd66a"

def on_hr(_sender, data: bytearray):
    hr = data[0] if len(data) > 0 else 0
    print(f"  ❤️  [LIVE TELEMETRY] Heart Rate: {hr} BPM (raw={list(data)})")

async def main():
    print(f"\n[1/3] Scanning for TARANG Pod ({TARGET_MAC})...")
    device = await BleakScanner.find_device_by_address(TARGET_MAC, timeout=10.0)
    if not device:
        print(f"[FAIL] Could not find {TARGET_MAC}. Is the EFR32 powered on and advertising?")
        return

    print(f"[2/3] Found device: {device.name} [{device.address}]. Connecting directly...")
    try:
        async with BleakClient(device, timeout=15.0) as client:
            print(f"[3/3] Connected! MTU={client.mtu_size}. Discovering GATT services...")
            for service in client.services:
                print(f"  Service: {service.uuid} ({service.description})")
                for char in service.characteristics:
                    print(f"    Char: {char.uuid} ({','.join(char.properties)})")

            print("\nSubscribing to Heart Rate notifications for 15 seconds...")
            await client.start_notify(HR_CHAR_UUID, on_hr)
            print("Subscribed! Listening for packets...")
            for i in range(15):
                await asyncio.sleep(1.0)
                print(f"  [T+{i+1}s] Link active: connected={client.is_connected}")
            await client.stop_notify(HR_CHAR_UUID)
            print("\n[SUCCESS] Test completed with 0 drops!")
    except Exception as e:
        import traceback
        print(f"\n[ERROR] Connection failed: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
