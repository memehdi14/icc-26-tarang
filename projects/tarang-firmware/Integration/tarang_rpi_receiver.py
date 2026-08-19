#!/usr/bin/env python3
"""
TARANG BLE Telemetry Receiver (Mode A)
--------------------------------------
Invokes the Mode A Telemetry Receiver for Service A (Vitals), Service B (Analytics),
and Service C (Clinical Events with 4s ECG Reassembly).
"""

from rpi_tarang_ble_receiver import main
import asyncio
import sys

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)

