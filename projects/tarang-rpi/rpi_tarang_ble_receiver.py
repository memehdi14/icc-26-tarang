#!/usr/bin/env python3
"""
===============================================================================
 TARANG Patient Pod — Raspberry Pi Mode A BLE Telemetry Receiver & Live Monitor
===============================================================================
Target : Raspberry Pi 4 / 5 / Zero 2W (Linux BlueZ + Bleak)
Usage  : python3 rpi_tarang_ble_receiver.py [OPTIONAL_POD_MAC_OR_NAME]

Features:
  ✔ Automatic discovery of "TARANG-*" BLE pods
  ✔ Bond-preserving BlueZ connection and service discovery
  ✔ Service A (Vitals) live parsing: Heart Rate (BPM), SpO2 (%), Timestamp
  ✔ Service B (Analytics) live parsing: PVC/PAC burden %, SDNN/RMSSD (ms), EM2 Sleep %
  ✔ Service C (Clinical Events): Rhythm flags, Meta, Glitch Ticker, Beat Annotations
  ✔ Multi-chunk indication reassembly of 4-second (1000 sample @ 250Hz) ECG snippets
  ✔ ASCII live waveform & telemetry console visualization
===============================================================================
"""

import sys
import time
import struct
import asyncio
from typing import Dict, List, Optional
from bleak import BleakScanner, BleakClient

# ============================================================================
# TARANG GATT 128-bit UUID Constants (Mode A Profile)
# ============================================================================
UUID_SERVICE_VITALS       = "544e937a-82f3-4395-b62b-b72bdea94c75"
UUID_CHAR_VITALS_HR       = "b4cf8877-ba1a-414c-a99d-de85a13fd66a"
UUID_CHAR_VITALS_SPO2     = "b4cf8877-ba1a-414c-a99d-de85a13fd66b"
UUID_CHAR_VITALS_TS       = "b4cf8877-ba1a-414c-a99d-de85a13fd66c"

UUID_SERVICE_ANALYTICS    = "655f937a-82f3-4395-b62b-b72bdea94c75"
UUID_CHAR_ANALYTICS_PVC   = "c5da9988-ca2b-425d-b00e-ef96b24ee77b"
UUID_CHAR_ANALYTICS_PAC   = "c5da9988-ca2b-425d-b00e-ef96b24ee77c"
UUID_CHAR_ANALYTICS_SDNN  = "c5da9988-ca2b-425d-b00e-ef96b24ee77d"
UUID_CHAR_ANALYTICS_RMSSD = "c5da9988-ca2b-425d-b00e-ef96b24ee77e"
UUID_CHAR_ANALYTICS_PRR50 = "c5da9988-ca2b-425d-b00e-ef96b24ee77f"
UUID_CHAR_ANALYTICS_AIDUTY= "c5da9988-ca2b-425d-b00e-ef96b24ee780"
UUID_CHAR_ANALYTICS_EM2   = "c5da9988-ca2b-425d-b00e-ef96b24ee781"

UUID_SERVICE_CLINICAL     = "7660937a-82f3-4395-b62b-b72bdea94c75"
UUID_CHAR_EVENT_RHYTHM    = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88a"
UUID_CHAR_EVENT_META      = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88b"
UUID_CHAR_EVENT_CHUNK     = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88c"
UUID_CHAR_EVENT_CTRL      = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88d"
UUID_CHAR_EVENT_ANNOT     = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88e"
UUID_CHAR_EVENT_TICKER    = "d6ebaa99-da3c-536e-c11f-f0a7c35ff88f"

RHYTHM_NAMES = {
    0: "Normal Sinus Rhythm (NSR)",
    1: "Atrial Fibrillation (AFib)",
    2: "Ventricular Tachycardia (VT)",
    3: "Bradycardia",
    4: "Tachycardia"
}

PATTERN_NAMES = {
    0: "None",
    1: "PVC Couplet",
    2: "PVC Triplet",
    3: "Bigeminy",
    4: "Trigeminy",
    5: "Ventricular Run (V-Run)",
    6: "Supraventricular Run (SVT)"
}

# ============================================================================
# Telemetry State & Reassembly Buffer
# ============================================================================
class TarangSnippetReassembler:
    def __init__(self):
        self.active_chunks: Dict[int, List[int]] = {}
        self.expected_chunks: int = 0
        self.total_samples: int = 0

    def reset(self):
        self.active_chunks.clear()
        self.expected_chunks = 0
        self.total_samples = 0

    def ingest_chunk(self, data: bytes) -> Optional[List[int]]:
        """Ingests a snippet chunk: sequence_id(uint16), total_chunks(uint16), samples[](int16)"""
        if len(data) < 4:
            return None
        seq_id, total_chunks = struct.unpack_from("<HH", data, 0)
        self.expected_chunks = total_chunks
        
        sample_count = (len(data) - 4) // 2
        samples = struct.unpack_from(f"<{sample_count}h", data, 4)
        self.active_chunks[seq_id] = list(samples)

        # Check if all chunks received
        if len(self.active_chunks) == total_chunks:
            full_waveform = []
            for i in range(total_chunks):
                full_waveform.extend(self.active_chunks.get(i, []))
            self.reset()
            return full_waveform
        return None


async def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None

    print("\n" + "=" * 70)
    print("  TARANG POD — RASPBERRY PI MODE A BLE TELEMETRY RECEIVER")
    print("=" * 70)
    print(" [1/3] Scanning for TARANG Pods...")

    device = None
    devices = await BleakScanner.discover(timeout=6.0)
    for d in devices:
        name = (d.name or "").upper()
        addr = (d.address or "").upper()
        if target:
            if target.upper() in addr or target.upper() in name:
                device = d
                break
        else:
            if "TARANG" in name or "EFR32" in name or "SILABS" in name:
                device = d
                break

    if not device:
        print("\n [!] No TARANG device found. Nearby BLE devices:")
        for d in devices:
            print(f"     • {d.address} | {d.name or '<Unknown>'}")
        print("\n Hint: Power on your EFR32MG26 board or specify MAC: python3 rpi_tarang_ble_receiver.py XX:XX:XX:XX:XX:XX")
        return

    print(f" [✓] Target Found: {device.name or 'TARANG'} [{device.address}]")
    print(" [2/3] Pairing and connecting to GATT Server (35s timeout)...")
    reassembler = TarangSnippetReassembler()

    async with BleakClient(device, timeout=35.0, pair=True) as client:
        print(f" [✓] Connected! (MTU / Connection established)")
        print(" [3/3] Subscribing to Mode A Telemetry Streams...")

        # --------------------------------------------------------------------
        # Notification Handlers
        # --------------------------------------------------------------------
        def on_vitals_hr(sender, data: bytearray):
            if len(data) >= 2:
                hr = struct.unpack("<H", data[:2])[0]
                t_str = time.strftime("%H:%M:%S")
                print(f"[{t_str}] [VITALS] ❤️  Heart Rate: {hr:3d} BPM  | {'█' * (hr // 10)}")

        def on_vitals_spo2(sender, data: bytearray):
            if len(data) >= 1:
                spo2 = data[0]
                t_str = time.strftime("%H:%M:%S")
                print(f"[{t_str}] [VITALS] 🫁  SpO2:       {spo2:3d} %")

        def on_analytics_rollup(sender, data: bytearray):
            # Packet: { pvc(1B), pac(1B), sdnn(2B), rmssd(2B), prr50(1B), ai_duty(1B), sleep(1B) }
            if len(data) >= 9:
                pvc, pac, sdnn, rmssd, prr50, ai_duty10, sleep = struct.unpack("<BBHHBBB", data[:9])
                t_str = time.strftime("%H:%M:%S")
                print("\n" + "-" * 60)
                print(f"[{t_str}] 📊 [5-MIN ANALYTICS ROLLUP RECEIVED]")
                print(f"     • PVC Burden : {pvc}%    | PAC Burden : {pac}%")
                print(f"     • SDNN       : {sdnn} ms | RMSSD      : {rmssd} ms")
                print(f"     • pRR50      : {prr50}%")
                print(f"     • AI Duty    : {ai_duty10 / 10.0:.1f}% | EM2 Sleep  : {sleep}%")
                print("-" * 60 + "\n")

        def on_event_rhythm(sender, data: bytearray):
            if len(data) >= 1:
                rhythm = data[0]
                r_name = RHYTHM_NAMES.get(rhythm, f"Unknown ({rhythm})")
                t_str = time.strftime("%H:%M:%S")
                print(f"\n🚨 [{t_str}] [CLINICAL EVENT] Rhythm Status Alert: >>> {r_name} <<<")

        def on_event_meta(sender, data: bytearray):
            # Layout: { event_id(uint16), event_type(uint8), confidence(uint8), ts(uint32) }
            if len(data) >= 8:
                ev_id, ev_type, conf, ts = struct.unpack("<HBB I", data[:8])
                t_str = time.strftime("%H:%M:%S")
                print(f"[{t_str}] [EVENT META] Event #{ev_id} | Type: {ev_type} | Conf: {conf}/255 ({conf/255*100:.1f}%) | Onset: {ts}ms")

        def on_glitch_ticker(sender, data: bytearray):
            # Layout: { pattern(uint16), ts(uint32) }
            if len(data) >= 6:
                pattern, ts = struct.unpack("<HI", data[:6])
                p_name = PATTERN_NAMES.get(pattern, f"Pattern-{pattern}")
                t_str = time.strftime("%H:%M:%S")
                print(f"[{t_str}] ⚡ [GLITCH TICKER] Detected Arrhythmia Pattern: {p_name} @ {ts}ms")

        def on_ecg_chunk(sender, data: bytearray):
            waveform = reassembler.ingest_chunk(bytes(data))
            if waveform:
                t_str = time.strftime("%H:%M:%S")
                print(f"\n[{t_str}] 📈 [ECG SNIPPET REASSEMBLED] 4.0s @ 250 Hz ({len(waveform)} samples)")
                # Print ASCII mini sparkline of middle 40 samples
                mid = len(waveform) // 2
                subset = waveform[mid:mid+40]
                mn, mx = min(subset), max(subset)
                rng = max(1, mx - mn)
                bars = "  ▂▃▄▅▆▇█"
                spark = "".join(bars[min(len(bars)-1, int((s - mn) / rng * (len(bars)-1)))] for s in subset)
                print(f"     Waveform Preview: [{spark}] (Min: {mn}, Max: {mx})")

        def on_beat_annotations(sender, data: bytearray):
            # Array of { offset_ms(uint16), label(uint8), conf(uint8) } = 4 bytes per annotation
            count = len(data) // 4
            t_str = time.strftime("%H:%M:%S")
            print(f"[{t_str}] 🏷️  [AI BEAT ANNOTATIONS] {count} beats classified:")
            for i in range(count):
                offset, label_code, conf = struct.unpack_from("<HBB", data, i * 4)
                label_char = chr(label_code) if label_code >= 32 else str(label_code)
                print(f"     Beat {i+1}: Offset={offset:4d}ms | Label='{label_char}' | Confidence={conf}/255")

        # --------------------------------------------------------------------
        # Subscribe to all Characteristics
        # --------------------------------------------------------------------
        try:
            await client.start_notify(UUID_CHAR_VITALS_HR, on_vitals_hr)
            print(f"  ✓ Subscribed to Vitals Heart Rate ({UUID_CHAR_VITALS_HR[:8]}...)")
        except Exception as e:
            print(f"  ✗ Vitals HR sub note: {e}")

        try:
            await client.start_notify(UUID_CHAR_VITALS_SPO2, on_vitals_spo2)
            print(f"  ✓ Subscribed to Vitals SpO2 ({UUID_CHAR_VITALS_SPO2[:8]}...)")
        except Exception as e:
            print(f"  ✗ Vitals SpO2 sub note: {e}")

        try:
            await client.start_notify(UUID_CHAR_ANALYTICS_PVC, on_analytics_rollup)
            print(f"  ✓ Subscribed to 5-Min Analytics ({UUID_CHAR_ANALYTICS_PVC[:8]}...)")
        except Exception as e:
            print(f"  ✗ Analytics sub note: {e}")

        try:
            await client.start_notify(UUID_CHAR_EVENT_RHYTHM, on_event_rhythm)
            print(f"  ✓ Subscribed to Clinical Rhythm Status ({UUID_CHAR_EVENT_RHYTHM[:8]}...)")
        except Exception as e:
            print(f"  ✗ Rhythm sub note: {e}")

        try:
            await client.start_notify(UUID_CHAR_EVENT_META, on_event_meta)
            print(f"  ✓ Subscribed to Event Meta ({UUID_CHAR_EVENT_META[:8]}...)")
        except Exception as e:
            print(f"  ✗ Event Meta sub note: {e}")

        try:
            await client.start_notify(UUID_CHAR_EVENT_CHUNK, on_ecg_chunk)
            print(f"  ✓ Subscribed to 4s ECG Snippet Chunks ({UUID_CHAR_EVENT_CHUNK[:8]}...)")
        except Exception as e:
            print(f"  ✗ ECG Chunk sub note: {e}")

        try:
            await client.start_notify(UUID_CHAR_EVENT_ANNOT, on_beat_annotations)
            print(f"  ✓ Subscribed to AI Beat Annotations ({UUID_CHAR_EVENT_ANNOT[:8]}...)")
        except Exception as e:
            print(f"  ✗ Beat Annotations sub note: {e}")

        try:
            await client.start_notify(UUID_CHAR_EVENT_TICKER, on_glitch_ticker)
            print(f"  ✓ Subscribed to Glitch Ticker ({UUID_CHAR_EVENT_TICKER[:8]}...)")
        except Exception as e:
            print(f"  ✗ Glitch Ticker sub note: {e}")

        print("\n" + "=" * 70)
        print("  STREAMING LIVE TARANG POD TELEMETRY (Press Ctrl+C to stop)")
        print("=" * 70 + "\n")

        try:
            while client.is_connected:
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass

    print("\n [✓] Disconnected cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n [!] Monitoring stopped by user.")
