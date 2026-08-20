#!/usr/bin/env python3
"""
===============================================================================
 TARANG Patient Pod — Raspberry Pi Mode A BLE Telemetry Receiver & Live Monitor
===============================================================================
Target : Raspberry Pi 4 / 5 / Zero 2W (Linux BlueZ + Bleak)
Usage  : python3 rpi_tarang_ble_receiver.py [OPTIONAL_POD_MAC_OR_NAME]

Features:
  ✔ Automatic discovery of "TARANG-*" BLE pods
  ✔ Robust BlueZ connection, pairing, and bond reuse
  ✔ Service A (Vitals): Heart Rate (BPM), SpO2 (%)
  ✔ Service B (Analytics): PVC/PAC burden %, SDNN/RMSSD (ms), pRR50, AI Duty %, EM2 Sleep %
  ✔ Service C (Clinical Events): Rhythm flags, Meta, Glitch Ticker, Beat Annotations
  ✔ Multi-chunk indication reassembly of 4-second (1000 sample @ 250Hz) ECG snippets
  ✔ ASCII live waveform & telemetry console visualization
  ✔ Clean reconnect resilience without crashing or infinite tight loops
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
    2: "Sinus Tachycardia",
    4: "Sinus Bradycardia",
    8: "Bigeminy",
    16: "Trigeminy",
    32: "Ventricular Run (V-Run)",
    64: "SVT Run",
    128: "Ventricular Tachycardia (VT Suspected!)"
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

BEAT_CLASSES = {0: "N (Normal)", 1: "S (PAC)", 2: "V (PVC)", 3: "Q (Noise/Unclass)"}

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

        if len(self.active_chunks) == total_chunks:
            full_waveform = []
            for i in range(total_chunks):
                full_waveform.extend(self.active_chunks.get(i, []))
            self.reset()
            return full_waveform
        return None


async def find_tarang_device(target: Optional[str] = None):
    """Active BLE scanner finding TARANG device with local name and MAC resolution."""
    loop = asyncio.get_running_loop()
    found: asyncio.Future = loop.create_future()
    target_clean = target.upper() if target else None

    def on_adv(device, adv_data):
        if found.done():
            return
        d_name = (adv_data.local_name or device.name or "").upper()
        d_addr = str(device.address).upper()
        if target_clean:
            if target_clean in d_addr or target_clean in d_name:
                found.set_result((device, adv_data))
        else:
            if d_name.startswith("TARANG") or "EFR32" in d_name or "SILABS" in d_name:
                found.set_result((device, adv_data))

    scanner = BleakScanner(detection_callback=on_adv)
    await scanner.start()
    try:
        device, adv = await asyncio.wait_for(found, timeout=8.0)
        return scanner, device
    except asyncio.TimeoutError:
        await scanner.stop()
        return None, None
    except Exception:
        await scanner.stop()
        raise


async def run_session(device, target_name: str) -> None:
    print(f"\n [✓] Target Found: {target_name} [{device.address}]")
    print(" [2/3] Establishing BLE Connection...")
    reassembler = TarangSnippetReassembler()
    analytics_state = {
        "pvc": 0, "pac": 0, "sdnn": 0, "rmssd": 0, "prr50": 0, "ai_duty": 0.0, "sleep": 0
    }

    disconnected = asyncio.Event()

    def on_disconnect(_client):
        print("\n [!] BLE Connection lost. Reconnecting...")
        disconnected.set()

    client = BleakClient(device, disconnected_callback=on_disconnect, timeout=30.0, pair=False)
    await client.connect()

    if not client.is_connected:
        print(" [!] Failed to establish active link.")
        return

    print(" [✓] Link Connected! Checking security / pairing...")
    try:
        await client.pair()
        print(" [✓] BLE Security / Pairing Confirmed.")
        await asyncio.sleep(0.5)
    except Exception as e:
        err_msg = str(e)
        if "AlreadyExists" in err_msg or "already" in err_msg.lower():
            print(" [✓] Bonded using cached BlueZ security keys.")
        else:
            print(f" [i] Pairing status note: {err_msg}")

    print(f" [✓] MTU size: {client.mtu_size}")
    print(" [3/3] Subscribing to Mode A Telemetry Streams...\n")

    # --------------------------------------------------------------------
    # Handlers
    # --------------------------------------------------------------------
    def on_vitals_hr(_sender, data: bytearray):
        if len(data) >= 2:
            hr = struct.unpack("<H", data[:2])[0]
            t_str = time.strftime("%H:%M:%S")
            bar = '█' * min(15, hr // 10)
            print(f"[{t_str}] [VITALS] ❤️  Heart Rate: {hr:3d} BPM  | {bar}")

    def on_vitals_spo2(_sender, data: bytearray):
        if len(data) >= 1:
            spo2 = data[0]
            t_str = time.strftime("%H:%M:%S")
            print(f"[{t_str}] [VITALS] 🫁  SpO2:       {spo2:3d} %")

    def print_analytics():
        t_str = time.strftime("%H:%M:%S")
        print("\n" + "-" * 65)
        print(f"[{t_str}] 📊 [5-MIN CLINICAL ANALYTICS UPDATE]")
        print(f"     • PVC Burden : {analytics_state['pvc']}%    | PAC Burden : {analytics_state['pac']}%")
        print(f"     • SDNN       : {analytics_state['sdnn']} ms | RMSSD      : {analytics_state['rmssd']} ms")
        print(f"     • pRR50      : {analytics_state['prr50']}%    | AI Duty    : {analytics_state['ai_duty']:.1f}%")
        print(f"     • EM2 Sleep  : {analytics_state['sleep']}%")
        print("-" * 65 + "\n")

    def on_pvc(_sender, data: bytearray):
        if data: analytics_state["pvc"] = data[0]; print_analytics()
    def on_pac(_sender, data: bytearray):
        if data: analytics_state["pac"] = data[0]
    def on_sdnn(_sender, data: bytearray):
        if len(data) >= 2: analytics_state["sdnn"] = struct.unpack("<H", data[:2])[0]
    def on_rmssd(_sender, data: bytearray):
        if len(data) >= 2: analytics_state["rmssd"] = struct.unpack("<H", data[:2])[0]
    def on_prr50(_sender, data: bytearray):
        if data: analytics_state["prr50"] = data[0]
    def on_aiduty(_sender, data: bytearray):
        if data: analytics_state["ai_duty"] = data[0] / 10.0
    def on_em2(_sender, data: bytearray):
        if data: analytics_state["sleep"] = data[0]

    def on_event_rhythm(_sender, data: bytearray):
        if data:
            rhythm = data[0]
            r_name = RHYTHM_NAMES.get(rhythm, f"Unknown (0x{rhythm:02X})")
            t_str = time.strftime("%H:%M:%S")
            print(f"\n🚨 [{t_str}] >>> CLINICAL ALERT: {r_name} <<<")

    def on_event_meta(_sender, data: bytearray):
        if len(data) >= 8:
            ev_id, ev_type, conf, ts = struct.unpack("<HBBI", data[:8])
            t_str = time.strftime("%H:%M:%S")
            print(f"[{t_str}] [EVENT META] Event #{ev_id} | Type: {ev_type} | Conf: {conf}/255 ({conf/255*100:.1f}%) | Timestamp: {ts}ms")

    def on_glitch_ticker(_sender, data: bytearray):
        if len(data) >= 6:
            pattern, ts = struct.unpack("<HI", data[:6])
            p_name = PATTERN_NAMES.get(pattern, f"Pattern-{pattern}")
            t_str = time.strftime("%H:%M:%S")
            print(f"[{t_str}] ⚡ [ARRHYTHMIA TICKER] Pattern Detected: {p_name} @ {ts}ms")

    def on_ecg_chunk(_sender, data: bytearray):
        waveform = reassembler.ingest_chunk(bytes(data))
        if waveform:
            t_str = time.strftime("%H:%M:%S")
            print(f"\n[{t_str}] 📈 [ECG SNIPPET REASSEMBLED] 4.0s @ 250 Hz ({len(waveform)} samples)")
            mid = len(waveform) // 2
            subset = waveform[mid:mid+45]
            mn, mx = min(subset), max(subset)
            rng = max(1, mx - mn)
            bars = "  ▂▃▄▅▆▇█"
            spark = "".join(bars[min(len(bars)-1, int((s - mn) / rng * (len(bars)-1)))] for s in subset)
            print(f"     Waveform Preview: [{spark}] (min={mn/1000.0:.2f}, max={mx/1000.0:.2f} mV)")

    def on_beat_annotations(_sender, data: bytearray):
        count = len(data) // 4
        t_str = time.strftime("%H:%M:%S")
        print(f"[{t_str}] 🏷️  [AI BEAT CLASSIFICATIONS] {count} beat(s) classified:")
        for i in range(count):
            offset, label_code, conf = struct.unpack_from("<HBB", data, i * 4)
            c_name = BEAT_CLASSES.get(label_code, f"Class {label_code}")
            print(f"     Beat {i+1}: Offset={offset:4d}ms | Class='{c_name}' | Confidence={conf}/255 ({conf/255*100:.1f}%)")

    # Subscriptions list
    subs = [
        (UUID_CHAR_VITALS_HR, on_vitals_hr, "Vitals HR"),
        (UUID_CHAR_VITALS_SPO2, on_vitals_spo2, "Vitals SpO2"),
        (UUID_CHAR_ANALYTICS_PVC, on_pvc, "Analytics PVC"),
        (UUID_CHAR_ANALYTICS_PAC, on_pac, "Analytics PAC"),
        (UUID_CHAR_ANALYTICS_SDNN, on_sdnn, "Analytics SDNN"),
        (UUID_CHAR_ANALYTICS_RMSSD, on_rmssd, "Analytics RMSSD"),
        (UUID_CHAR_ANALYTICS_PRR50, on_prr50, "Analytics pRR50"),
        (UUID_CHAR_ANALYTICS_AIDUTY, on_aiduty, "Analytics AI Duty"),
        (UUID_CHAR_ANALYTICS_EM2, on_em2, "Analytics EM2 Sleep"),
        (UUID_CHAR_EVENT_RHYTHM, on_event_rhythm, "Event Rhythm"),
        (UUID_CHAR_EVENT_META, on_event_meta, "Event Meta"),
        (UUID_CHAR_EVENT_CHUNK, on_ecg_chunk, "ECG Snippet Chunks"),
        (UUID_CHAR_EVENT_ANNOT, on_beat_annotations, "Beat Annotations"),
        (UUID_CHAR_EVENT_TICKER, on_glitch_ticker, "Glitch Ticker"),
    ]

    subscribed_count = 0
    for char_uuid, handler, desc in subs:
        for attempt in range(2):
            try:
                await client.start_notify(char_uuid, handler)
                print(f"  ✓ Subscribed to {desc}")
                subscribed_count += 1
                break
            except Exception as e:
                if attempt == 0:
                    await asyncio.sleep(0.3)
                else:
                    print(f"  ✗ {desc} subscription note: {e}")

    print(f"\n [✓] {subscribed_count}/{len(subs)} Mode A Telemetry Streams Active.")
    print("=" * 70)
    print("  STREAMING LIVE TARANG POD TELEMETRY (Press Ctrl+C to stop)")
    print("=" * 70 + "\n")

    try:
        await disconnected.wait()
    finally:
        if client.is_connected:
            await client.disconnect()


async def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None

    print("\n" + "=" * 70)
    print("  TARANG POD — RASPBERRY PI MODE A BLE TELEMETRY RECEIVER")
    print("=" * 70)

    while True:
        print("\n [1/3] Scanning for TARANG Pods...")
        scanner, device = await find_tarang_device(target)
        if scanner:
            await scanner.stop()

        if not device:
            print(" [!] No TARANG device detected. Ensure the EFR32 board is powered and advertising.")
            print("     Retrying scan in 3 seconds...")
            await asyncio.sleep(3.0)
            continue

        try:
            await run_session(device, device.name or "TARANG")
        except asyncio.CancelledError:
            break
        except Exception as exc:
            print(f" [!] Session error: {exc}")

        print(" [i] Reconnecting in 3 seconds...")
        await asyncio.sleep(3.0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n [✓] Monitoring stopped cleanly by user.\n")
