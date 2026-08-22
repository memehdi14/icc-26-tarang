"""Unit tests for the Tarang Mode A BLE wire protocol."""

import struct
import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from ble_protocol import (  # noqa: E402
    ANALYTICS_DUTY_UUID,
    ANALYTICS_SDNN_UUID,
    ProtocolError,
    SnippetReassembler,
    decode_analytics,
    decode_analytics_characteristic,
    decode_annotations,
    decode_event_meta,
    decode_event_ticker,
    decode_heart_rate,
    decode_spo2,
)


class BleProtocolTest(unittest.TestCase):
    def test_decodes_vitals(self):
        self.assertEqual(decode_heart_rate(struct.pack("<H", 78)), 78)
        self.assertEqual(decode_spo2(bytes([99])), 99)
        with self.assertRaises(ProtocolError):
            decode_spo2(bytes([101]))

    def test_decodes_analytics_packet(self):
        packet = struct.pack("<BBHHBBB", 3, 2, 44, 38, 9, 15, 92)
        decoded = decode_analytics(packet)
        self.assertEqual(decoded["pvc_burden_pct"], 3.0)
        self.assertEqual(decoded["sdnn"], 44.0)
        self.assertEqual(decoded["ai_duty_cycle_pct"], 1.5)
        self.assertEqual(decoded["em2_sleep_pct"], 92.0)

    def test_decodes_generated_analytics_characteristics(self):
        self.assertEqual(
            decode_analytics_characteristic(
                ANALYTICS_SDNN_UUID, struct.pack("<H", 47)
            ),
            ("sdnn", 47.0),
        )
        field, value = decode_analytics_characteristic(
            ANALYTICS_DUTY_UUID, bytes([15])
        )
        self.assertEqual(field, "ai_duty_cycle_pct")
        self.assertAlmostEqual(value, 1.5)

    def test_decodes_event_packets(self):
        meta = decode_event_meta(struct.pack("<HBBI", 42, 2, 245, 123456))
        self.assertEqual(meta.event_id, 42)
        self.assertEqual(meta.event_type, 2)
        self.assertEqual(meta.confidence, 245)

        routine_meta = decode_event_meta(struct.pack("<HBBI", 43, 254, 250, 123456))
        self.assertEqual(routine_meta.event_id, 43)
        self.assertEqual(routine_meta.event_type, 254)

        ticker = decode_event_ticker(struct.pack("<HI", 5, 123456))
        self.assertEqual(ticker.pattern_type, 5)

    def test_decodes_numeric_and_ascii_annotation_labels(self):
        packet = b"".join(
            [
                struct.pack("<HBB", 800, 0, 255),
                struct.pack("<HBB", 1600, ord("V"), 240),
            ]
        )
        annotations = decode_annotations(packet)
        self.assertEqual(annotations[0]["label"], "N")
        self.assertEqual(annotations[1]["label"], "V")
        self.assertAlmostEqual(annotations[1]["confidence"], 240 / 255.0)

    def test_reassembles_out_of_order_snippet(self):
        reassembler = SnippetReassembler()
        chunk_1 = struct.pack("<HH2h", 1, 2, 30, 40)
        chunk_0 = struct.pack("<HH2h", 0, 2, 10, 20)

        self.assertIsNone(reassembler.add_chunk(chunk_1))
        waveform = reassembler.add_chunk(chunk_0)
        self.assertEqual(waveform, [0.01, 0.02, 0.03, 0.04])
        self.assertEqual(reassembler.received_chunks, 0)

    def test_rejects_invalid_chunk_header(self):
        reassembler = SnippetReassembler()
        with self.assertRaises(ProtocolError):
            reassembler.add_chunk(struct.pack("<HHh", 2, 2, 10))
        with self.assertRaises(ProtocolError):
            reassembler.add_chunk(struct.pack("<HHh", 0, 0, 10))

    def test_accepts_default_mtu_chunk_count_for_four_seconds(self):
        reassembler = SnippetReassembler()
        for sequence in range(124):
            self.assertIsNone(
                reassembler.add_chunk(
                    struct.pack("<HH8h", sequence, 125, *([sequence] * 8))
                )
            )
        waveform = reassembler.add_chunk(
            struct.pack("<HH8h", 124, 125, *([124] * 8))
        )
        self.assertEqual(len(waveform), 1000)


if __name__ == "__main__":
    unittest.main()
