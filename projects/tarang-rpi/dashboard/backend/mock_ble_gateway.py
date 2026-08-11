#!/usr/bin/env python3
"""
Tarang Clinical — Mock BLE Gateway (Development / Windows)
===========================================================
Simulates realistic EFR32 clinical telemetry packets and POSTs them
to the FastAPI backend every second — no hardware required.

Simulates:
  - Heart rate drifting between 65–85 BPM
  - Occasional PAC (beat_class=1) or PVC (beat_class=2) events
  - Realistic RR intervals, SDNN/RMSSD variance
  - Occasional rhythm flag events (AFib, Brady, Tachy)

Run (with backend already started):
    python mock_ble_gateway.py
"""

import asyncio
import random
import time
import httpx

BACKEND_URL = "http://localhost:8000"
INGEST_URL = f"{BACKEND_URL}/api/telemetry/ingest"
DIAGNOSTICS_URL = f"{BACKEND_URL}/api/diagnostics/update"
INTERVAL_S = 1.0

# Rhythm flag bitmasks (matches firmware definitions)
RHYTHM_NORMAL = 0x00
RHYTHM_AFIB = 0x01
RHYTHM_SINUS_TACHY = 0x02
RHYTHM_SINUS_BRADY = 0x04
RHYTHM_BIGEMINY = 0x08
RHYTHM_TRIGEMINY = 0x10
RHYTHM_V_RUN = 0x20


async def generate_packet(state: dict) -> dict:
    """Generate one realistic telemetry packet, updating running state."""

    # Drift heart rate ±1 BPM per tick, clamp to 65–85
    delta = random.choice([-1, 0, 0, 1])
    state["hr"] = max(65, min(85, state["hr"] + delta))
    hr = state["hr"]

    rr_ms = round(60000 / hr) + random.randint(-15, 15)
    sdnn = 40 + random.randint(-6, 6)
    rmssd = 35 + random.randint(-5, 5)

    # Occasionally generate a PAC or PVC (5% each)
    rand = random.random()
    if rand < 0.05:
        beat_class = 1   # PAC
        confidence = random.randint(180, 240)
    elif rand < 0.10:
        beat_class = 2   # PVC
        confidence = random.randint(150, 220)
    else:
        beat_class = 0   # Normal
        confidence = random.randint(220, 255)

    # Rhythm flags: mostly normal, occasional episodes
    rand2 = random.random()
    if rand2 < 0.02:
        rhythm_flags = RHYTHM_SINUS_TACHY
    elif rand2 < 0.04:
        rhythm_flags = RHYTHM_SINUS_BRADY
    elif rand2 < 0.045:
        rhythm_flags = RHYTHM_AFIB
    else:
        rhythm_flags = RHYTHM_NORMAL

    # PAC/PVC burden accumulates slowly
    state["pac_burden"] = round(max(0.0, min(10.0, state["pac_burden"] + random.uniform(-0.05, 0.1))), 1)
    state["pvc_burden"] = round(max(0.0, min(5.0, state["pvc_burden"] + random.uniform(-0.03, 0.06))), 1)

    return {
        "timestamp_ms": int(time.time() * 1000),
        "beat_class": beat_class,
        "confidence": confidence,
        "rr_interval_ms": rr_ms,
        "rhythm_flags": rhythm_flags,
        "pac_burden_pct": state["pac_burden"],
        "pvc_burden_pct": state["pvc_burden"],
        "current_hr": hr,
        "sdnn_ms": sdnn,
        "rmssd_ms": rmssd,
    }


async def run_mock_gateway():
    state = {
        "hr": 74,
        "pac_burden": 1.2,
        "pvc_burden": 0.4,
    }
    packets_sent = 0
    start_time = time.monotonic()

    print("[MOCK-BLE] Starting mock telemetry gateway...")
    print(f"[MOCK-BLE] Posting to {INGEST_URL}")
    print("[MOCK-BLE] Press Ctrl+C to stop.\n")

    async with httpx.AsyncClient() as http:
        # Register device as connected
        try:
            await http.post(DIAGNOSTICS_URL, json={
                "ble_connected": True,
                "device_name": "EFR32MG26 (Mock/Sim)",
                "device_mac": "00:11:22:33:44:55",
                "firmware_version": "v1.0.0-EFR32MG26-SIM",
                "rssi_dbm": -60,
                "packets_received": 0,
                "packets_dropped": 0,
                "latency_ms": 0.0,
                "battery_pct": 100,
                "ecg_health": True,
                "ppg_health": True,
                "imu_health": True,
            }, timeout=5.0)
            print("[MOCK-BLE] Registered mock device with backend.")
        except Exception as e:
            print(f"[MOCK-BLE] Backend not ready yet: {e}")
            print("[MOCK-BLE] Make sure the backend is running on port 8000.\n")

        while True:
            packet = await generate_packet(state)
            try:
                r = await http.post(INGEST_URL, json=packet, timeout=2.0)
                packets_sent += 1
                elapsed = time.monotonic() - start_time
                print(
                    f"[{elapsed:>8.1f}s] HR={packet['current_hr']:>3} BPM | "
                    f"RR={packet['rr_interval_ms']:>4}ms | "
                    f"Beat={['N','PAC','PVC','Q'][packet['beat_class']]:>3} | "
                    f"Flags=0x{packet['rhythm_flags']:02X} | "
                    f"Pkt#{packets_sent}"
                )
            except Exception as e:
                print(f"[MOCK-BLE] POST failed: {e} — is backend running?")

            await asyncio.sleep(INTERVAL_S)


if __name__ == "__main__":
    try:
        asyncio.run(run_mock_gateway())
    except KeyboardInterrupt:
        print("\n[MOCK-BLE] Mock gateway stopped.")
