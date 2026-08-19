#!/usr/bin/env python3
"""Connect, pair, inspect, and subscribe to a Tarang wearable over BLE."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
from typing import Any

from bleak import BleakClient, BleakScanner


BACKEND_DIR = Path(__file__).resolve().parent / "dashboard" / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from ble_protocol import (  # noqa: E402
    EVENT_META_UUID,
    REQUIRED_SERVICE_UUIDS,
    VITALS_HR_UUID,
    VITALS_SPO2_UUID,
    decode_event_meta,
    decode_heart_rate,
    decode_spo2,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "address",
        nargs="?",
        help="Optional BLE identity address, for example 64:02:8F:64:26:14",
    )
    parser.add_argument(
        "--no-pair",
        action="store_true",
        help="Connect without requesting pairing (only for unsecured GATT testing)",
    )
    parser.add_argument(
        "--listen-seconds",
        type=float,
        default=15.0,
        help="Notification listening duration (default: 15 seconds)",
    )
    return parser.parse_args()


async def find_device(address: str | None):
    if address:
        print(f"Scanning for configured address {address.upper()}...")
        return await BleakScanner.find_device_by_address(address.upper(), timeout=10.0)

    print("Scanning for TARANG-*...")

    def match(device, advertisement_data) -> bool:
        name = advertisement_data.local_name or device.name or ""
        return name.upper().startswith("TARANG")

    return await BleakScanner.find_device_by_filter(match, timeout=10.0)


async def main() -> int:
    args = parse_args()
    if args.listen_seconds < 0:
        raise ValueError("--listen-seconds must not be negative")

    device = await find_device(args.address)
    if device is None:
        print("No Tarang device found. Confirm that the board is advertising.")
        return 2

    print(f"Found {device.name or 'TARANG'} at {device.address}")
    print(f"Connecting with pairing={not args.no_pair}...")

    async with BleakClient(
        device,
        timeout=35.0,
        pair=not args.no_pair,
    ) as client:
        if not client.is_connected:
            print("Connection did not become active.")
            return 3

        service_uuids = {service.uuid.lower() for service in client.services}
        missing = REQUIRED_SERVICE_UUIDS - service_uuids
        if missing:
            print("Missing required Tarang services:")
            for uuid in sorted(missing):
                print(f"  {uuid}")
            return 4

        print(f"Connected. MTU={client.mtu_size}")
        print("Discovered GATT database:")
        for service in client.services:
            print(f"  Service {service.uuid} ({service.description})")
            for characteristic in service.characteristics:
                properties = ",".join(characteristic.properties)
                print(f"    {characteristic.uuid} [{properties}]")

        def on_hr(_sender: Any, data: bytearray) -> None:
            print(f"HR={decode_heart_rate(data)} BPM")

        def on_spo2(_sender: Any, data: bytearray) -> None:
            print(f"SpO2={decode_spo2(data)}%")

        def on_event_meta(_sender: Any, data: bytearray) -> None:
            meta = decode_event_meta(data)
            print(
                f"Event={meta.event_id} rhythm={meta.event_type} "
                f"confidence={meta.confidence}/255 timestamp={meta.timestamp_ms}ms"
            )

        subscriptions = (
            (VITALS_HR_UUID, on_hr),
            (VITALS_SPO2_UUID, on_spo2),
            (EVENT_META_UUID, on_event_meta),
        )
        for uuid, handler in subscriptions:
            await client.start_notify(uuid, handler)
            print(f"Subscribed to {uuid}")

        if args.listen_seconds:
            print(f"Listening for {args.listen_seconds:g} seconds...")
            await asyncio.sleep(args.listen_seconds)

    print("BLE test completed successfully.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("BLE test stopped.")
