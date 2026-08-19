"""Behavior tests for one BLE gateway connection session."""

import asyncio
import struct
import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from ble_gateway import (  # noqa: E402
    GatewayConfig,
    GatewayMetrics,
    GatewaySession,
)
from ble_protocol import ANALYTICS_PVC_UUID, ANALYTICS_SDNN_UUID  # noqa: E402


class FakePublisher:
    def __init__(self):
        self.metrics = GatewayMetrics()
        self.items = []

    def enqueue(self, path, payload, packet_type):
        self.items.append((path, payload, packet_type))


class FakeDevice:
    address = "64:02:8F:64:26:14"
    name = "TARANG-2614"


def make_config() -> GatewayConfig:
    return GatewayConfig(
        backend_url="http://localhost:8000",
        ble_address=FakeDevice.address,
        name_prefix="TARANG",
        device_id="tarang-test",
        session_id="session-test",
        pair=True,
        scan_timeout_s=10.0,
        connect_timeout_s=35.0,
        reconnect_delay_s=5.0,
        diagnostics_interval_s=10.0,
    )


class GatewaySessionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.publisher = FakePublisher()
        self.session = GatewaySession(
            make_config(), self.publisher, FakeDevice(), "session-test"
        )

    async def asyncTearDown(self):
        await self.session.close()

    async def test_coalesces_heart_rate_and_spo2(self):
        self.session.on_heart_rate(None, bytearray(struct.pack("<H", 81)))
        self.session.on_spo2(None, bytearray([97]))
        await asyncio.sleep(0.2)

        self.assertEqual(len(self.publisher.items), 1)
        path, payload, packet_type = self.publisher.items[0]
        self.assertEqual(path, "/api/vitals")
        self.assertEqual(packet_type, "vitals")
        self.assertEqual(payload["heart_rate_bpm"], 81)
        self.assertEqual(payload["spo2_pct"], 97)
        self.assertEqual(payload["device_id"], "tarang-test")

    async def test_assembles_complete_clinical_event(self):
        self.session.on_rhythm(None, bytearray([2]))
        self.session.on_event_meta(
            None, bytearray(struct.pack("<HBBI", 7, 2, 240, 123456))
        )
        self.session.on_event_ticker(
            None, bytearray(struct.pack("<HI", 5, 123456))
        )
        self.session.on_event_control(None, bytearray([1]))
        self.session.on_ecg_chunk(
            None, bytearray(struct.pack("<HH2h", 0, 2, 10, 20))
        )
        self.session.on_ecg_chunk(
            None, bytearray(struct.pack("<HH2h", 1, 2, 30, 40))
        )
        self.session.on_event_control(None, bytearray([3]))
        self.session.on_annotations(
            None, bytearray(struct.pack("<HBB", 800, ord("V"), 245))
        )
        self.session._flush_event()

        event_items = [item for item in self.publisher.items if item[0] == "/api/events"]
        self.assertEqual(len(event_items), 1)
        payload = event_items[0][1]
        self.assertEqual(payload["rhythm_status"], 2)
        self.assertEqual(payload["pattern_type"], "V-Run")
        self.assertAlmostEqual(payload["confidence"], 240 / 255.0)
        self.assertEqual(payload["waveform"], [0.01, 0.02, 0.03, 0.04])
        self.assertEqual(payload["annotations"][0]["label"], "V")

    async def test_coalesces_scalar_analytics(self):
        self.session.on_analytics_scalar(
            ANALYTICS_PVC_UUID, None, bytearray([3])
        )
        self.session.on_analytics_scalar(
            ANALYTICS_SDNN_UUID, None, bytearray(struct.pack("<H", 46))
        )
        await asyncio.sleep(0.3)

        analytics = [
            item for item in self.publisher.items if item[0] == "/api/analytics"
        ]
        self.assertEqual(len(analytics), 1)
        self.assertEqual(analytics[0][1]["pvc_burden_pct"], 3.0)
        self.assertEqual(analytics[0][1]["sdnn"], 46.0)

    async def test_appends_fragmented_annotations(self):
        self.session.on_event_meta(
            None, bytearray(struct.pack("<HBBI", 8, 2, 240, 123456))
        )
        self.session.on_annotations(
            None, bytearray(struct.pack("<HBB", 400, 0, 250))
        )
        self.session.on_annotations(
            None, bytearray(struct.pack("<HBB", 800, 2, 245))
        )
        self.assertEqual(len(self.session._event.annotations), 2)

    async def test_malformed_packet_is_counted_and_not_forwarded(self):
        self.session.on_spo2(None, bytearray([255]))
        await asyncio.sleep(0)
        self.assertEqual(self.publisher.metrics.packets_dropped, 1)
        self.assertEqual(self.publisher.items, [])


if __name__ == "__main__":
    unittest.main()
