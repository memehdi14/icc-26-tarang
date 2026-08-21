# TARANG Demo Runbook - Post-BLE-Fix (RCA-BLE-2026-08)

## Root causes fixed (summary)

| # | Root cause | Fix |
|---|------------|-----|
| 1 | GATT/firmware mismatch: firmware called send_notification() on event_ecg_chunk / event_beat_annotations, but the GATT DB declared them INDICATE-only -> silent confirmation stall -> supervision timeout. | gatt_configuration.btconf + regenerated gatt_db.c now declare notify (bonded+encrypted). Verified: ecg_chunk = properties 0x10 (notify), permissions 0x5800 (secured). |
| 2 | 10-chunk burst in one superloop tick (244 B each, MTU 23 => 13+ LL packets per chunk) overran the TX queue. | Transfer now paced: exactly ONE chunk/annotation packet per ~10 ms process tick, driven by tarang_ble_process(), with a 5 s stall-abort guard. sl_udelay_wait busy-waits removed. |
| 3 | Unpaired central writing secured CCCDs -> WRITE_NOT_PERMITTED + link teardown. | SM fully enabled (bondable, auto-confirm, stale-bond self-heal). Both Pi scripts now call client.pair() immediately after connect. |

## Firmware side (Windows PC - once)

1. Build + flash the Patient Pod in Simplicity Studio. Local cmake_gcc build already
   passed (Integration.out). Do NOT edit the GATT configurator - gatt_db.c is current.
2. At boot, VCOM must show: "configure security manager" OK, "enable bonding" OK,
   "Connectable advertising started (Mode A Ready)."

## Raspberry Pi side (once, ~2 min)

    sudo systemctl restart bluetooth
    sleep 3
    bluetoothctl remove <POD_MAC>     # purge Pi keys + GATT cache
    cd ~/tarang-rpi
    python3 rpi_tarang_ble_receiver.py

The receiver pairs automatically after connect. The pod self-heals stale bonds
(sm_bonding_failed handler deletes its stale entry automatically).

## Healthy-link timeline

    t=0.0s  connect              (pod: "Connection opened!")
    t~0.5s  pair()/encryption    (pod: "[BLE][SM] Bonded: ... security=2")
    t~1.5s  14 CCCD subscribes   (pod: 14 x "CCCD: ... SUBSCRIBED")
    t~4s    warmup ends          (pod: warmup 3500ms)
    t~4s+   vitals every 2.5s    (pod: "[BLE][VITALS] Published: HR=...")
    events  one chunk per tick   (pod: "Event#N ... N chunks")
    NO reason=0x13 / 0x1008 disconnects.

## Demo script (5 min)

1. Pod on wrist/leads; show HR/SpO2 ticking every ~2.5 s.
2. Trigger a clinical event - then WAIT ~6 s (firmware refractory cooldown).
3. Show ECG snippet arriving chunk-by-chunk in receiver log.
4. Mention 5-min analytics rollup; do not wait for it live.

## Triage

| Symptom | Meaning | Action |
|---|---|---|
| pair() failed then WRITE_NOT_PERMITTED | stale keys one side | bluetoothctl remove <POD_MAC>; power-cycle pod; retry (pod auto-deletes its stale bond). |
| Bonds refused repeatedly | old image without SM | re-flash this build. |
| Subscriptions > 3.5 s | slow Pi | safe; warmup only gates TX. |
| Chunks stop mid-transfer | peer vanished | 5 s stall-abort frees slot automatically. |
| HR 0 initially | sensors settling | normal; fusion picks valid source once SQI >= 30. |

## Files changed

- config/btconf/gatt_configuration.btconf - ecg_chunk notify (secured); security restored.
- autogen/gatt_db.c - regenerated (0x10 notify + 0x5800 secured).
- tarang_ble.c - [FIX-4] paced one-packet-per-tick transfer, process() driver +
  5 s stall guard; dead retry path removed from tarang_ble_build_health_packet().
- tarang-rpi/tarang_disconnect_debug.py - client.pair() (15 s timeout) after connect.
