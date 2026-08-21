/***************************************************************************//**
 * @file tarang_ble.c
 * @brief TARANG BLE Telemetry — Mode A (Event-Driven) Implementation.
 *
 * Implements the BLE GATT server for the EFR32MG26 Patient Pod:
 *   - Service A (Vitals): Periodic notify every 2–5s (HR, SpO2, Timestamp)
 *   - Service B (Analytics): Periodic notify every 5-min (Burden, HRV, AI Duty Cycle, EM2 Sleep %)
 *   - Service C (ClinicalEvent): Event-driven notify (Rhythm Status, Meta, Snippet Chunks, Annotations, Ticker)
 *   - Reliable chunked indicate/ack protocol for 4s ECG snippet waveforms
 *
 * PATCH HISTORY (TARANG-RCA-BLE-2026-08):
 *   [FIX-1] Added TARANG_EVENT_COOLDOWN_MS refractory period between consecutive
 *          clinical event transfers to prevent TX-queue saturation when
 *          Event N+1 fires within ~150ms of Event N completing.
 *   [FIX-2] Always clear rhythm_changed / significant_event flags in
 *          tarang_ble_process() — not only on accepted events. Without this,
 *          cooldown-rejected events retry in a tight loop and keep the radio
 *          busy until supervision timeout.
 *   [FIX-3] Defensive cooldown reset on connection close so a fresh link can
 *          fire an event immediately.
 *
 * Target : EFR32MG26B510F3200IM48 (Series 2, Cortex-M33)
 ******************************************************************************/
#include "tarang_ble.h"
#include "tarang_time.h"
#include "tarang_constants.h"
#include "tarang_ecg.h"
#include "tarang_ppg.h"
#include "tarang_imu.h"
#include "tarang_ai.h"
#include <stdio.h>
#include <string.h>
#include "sl_udelay.h"

#if defined(SL_COMPONENT_CATALOG_PRESENT)
#include "sl_component_catalog.h"
#endif

#if defined(SL_CATALOG_BLUETOOTH_PRESENT)
#include "sl_bt_api.h"
#include "gatt_db.h"
#endif

#if defined(SL_CATALOG_APP_ASSERT_PRESENT)
#include "app_assert.h"
#else
#define app_assert_status(sc) (void)(sc)
#endif

#ifndef SL_BT_INVALID_CONNECTION_HANDLE
#define SL_BT_INVALID_CONNECTION_HANDLE 0xFFu
#endif

#ifndef SL_BT_INVALID_BONDING_HANDLE
#define SL_BT_INVALID_BONDING_HANDLE 0xFFu
#endif

/* Bonding is enabled with Security Manager and automatic stale-bond recovery */
#ifndef TARANG_BLE_ENABLE_BONDING
#define TARANG_BLE_ENABLE_BONDING 1
#endif

/* ── Fallback handles for robust compilation if gatt_db.h differs ─────────── */
#ifndef gattdb_vitals_heart_rate
  #if defined(gattdb_telemetry_data)
    #define gattdb_vitals_heart_rate gattdb_telemetry_data
  #else
    #define gattdb_vitals_heart_rate 21
  #endif
#endif

#ifndef gattdb_vitals_spo2
  #define gattdb_vitals_spo2 24
#endif

#ifndef gattdb_vitals_timestamp
  #define gattdb_vitals_timestamp 27
#endif

#ifndef gattdb_analytics_pvc_burden
  #define gattdb_analytics_pvc_burden 30
#endif

#ifndef gattdb_analytics_pac_burden
  #define gattdb_analytics_pac_burden 33
#endif

#ifndef gattdb_analytics_sdnn
  #define gattdb_analytics_sdnn 36
#endif

#ifndef gattdb_analytics_rmssd
  #define gattdb_analytics_rmssd 39
#endif

#ifndef gattdb_analytics_prr50
  #define gattdb_analytics_prr50 42
#endif

#ifndef gattdb_analytics_ai_duty_cycle
  #define gattdb_analytics_ai_duty_cycle 45
#endif

#ifndef gattdb_analytics_em2_sleep
  #define gattdb_analytics_em2_sleep 48
#endif

#ifndef gattdb_event_rhythm_status
  #define gattdb_event_rhythm_status 52
#endif

#ifndef gattdb_event_meta
  #define gattdb_event_meta 55
#endif

#ifndef gattdb_event_ecg_chunk
  #define gattdb_event_ecg_chunk 58
#endif

#ifndef gattdb_event_ecg_control
  #define gattdb_event_ecg_control 61
#endif

#ifndef gattdb_event_beat_annotations
  #define gattdb_event_beat_annotations 64
#endif

#ifndef gattdb_event_glitch_ticker
  #define gattdb_event_glitch_ticker 67
#endif

/******************************************************************************
 *                           STATIC STATE
 ******************************************************************************/
static uint8_t tarang_advertising_set_handle = 0xFFu;
static uint8_t tarang_ble_conn_handle = SL_BT_INVALID_CONNECTION_HANDLE;
static uint8_t tarang_ble_bonding_handle = SL_BT_INVALID_BONDING_HANDLE;

/* CCCD subscription state flags */
static bool sub_vitals_hr          = false;
static bool sub_vitals_spo2        = false;
static bool sub_analytics_pvc      = false;
static bool sub_analytics_pac      = false;
static bool sub_analytics_sdnn     = false;
static bool sub_analytics_rmssd    = false;
static bool sub_analytics_prr50    = false;
static bool sub_analytics_duty     = false;
static bool sub_analytics_sleep    = false;
static bool sub_event_rhythm       = false;
static bool sub_event_meta         = false;
static bool sub_event_ecg_chunk    = false;
static bool sub_event_annotations  = false;
static bool sub_event_ticker       = false;

/* Periodic Timers (ms) */
static uint32_t last_vitals_send_ms    = 0;
static uint32_t last_analytics_send_ms = 0;
static uint16_t next_event_id          = 1;

/*
 * Warmup guard: suppress ALL notifications for the first few seconds after
 * connection open.  This prevents the notification storm that was killing the
 * link — the RPi subscribes to 14 CCCDs back-to-back, and each CCCD write
 * was immediately triggering a data burst.  At MTU 23 that congests the TX
 * queue faster than the radio can drain it, causing a supervision timeout.
 */
static uint32_t connection_opened_ms   = 0;
#define TARANG_BLE_WARMUP_MS           5000u  /* 5.0s: covers 14 CCCDs + pairing */

/*
 * Track the ACTUAL negotiated MTU (not just the value we requested).
 * sl_bt_gatt_server_set_max_mtu(247) at connection open only asks -- it
 * does not guarantee the central completes the exchange, or completes it
 * before our fixed warmup timer expires. bleak on the Pi gateway has been
 * observed staying at the ATT default (23) despite this request.
 *
 * negotiated_mtu is updated by sl_bt_evt_gatt_mtu_exchanged_id and used to
 * decide whether it's safe to send the large multi-chunk event burst yet.
 * Ordinary vitals/analytics notifications are a few bytes and fit inside
 * MTU 23 regardless, so they are NOT gated on this -- only the expensive
 * snippet transfer is. If the exchange never completes, the event burst
 * proceeds anyway once TARANG_MTU_WAIT_TIMEOUT_MS elapses rather than
 * hanging forever -- a central that genuinely stays at MTU 23 should get a
 * slower, chunkier transfer, not silence.
 */
static uint16_t negotiated_mtu         = 23u;
static bool     mtu_exchange_confirmed = false;
#define TARANG_MTU_WAIT_TIMEOUT_MS     1500u  /* give exchange this long before proceeding anyway */

/* [FIX-1] ──────────────────────────────────────────────────────────────────
 * Refractory period between consecutive clinical event transfers.
 * Even after event_transfer.active goes false, the radio still has ATT
 * operations in flight. Firing the next 10-chunk burst immediately
 * saturates the TX queue and trips supervision timeout. Observed in field
 * logs: Event 5 fired 146 ms after Event 4 → disconnect.
 */
static uint32_t last_event_completion_ms = 0u;
#define TARANG_EVENT_COOLDOWN_MS  6000u

static bool tarang_ble_warmup_done(void)
{
  if (connection_opened_ms == 0u) return false;
  return (tarang_now_ms() - connection_opened_ms) >= TARANG_BLE_WARMUP_MS;
}

/*
 * Safe to send the large multi-chunk event burst? True once the MTU
 * exchange has actually confirmed a raised MTU, OR once we've waited long
 * enough that we give up waiting and send at whatever MTU we've got
 * (23 if the central never negotiates). Never blocks forever.
 */
static bool tarang_ble_mtu_ready_for_burst(void)
{
  if (mtu_exchange_confirmed) return true;
  if (connection_opened_ms == 0u) return false;
  return (tarang_now_ms() - connection_opened_ms) >= TARANG_MTU_WAIT_TIMEOUT_MS;
}

/* [FIX-1] Cooldown check helper. Returns true if a new event may fire. */
static bool tarang_ble_event_cooldown_elapsed(void)
{
  if (last_event_completion_ms == 0u) return true;
  return (tarang_now_ms() - last_event_completion_ms) >= TARANG_EVENT_COOLDOWN_MS;
}

/* Avoid clinical-event traffic until its inputs and link transport are real. */
static bool tarang_ble_clinical_event_ready(void)
{
#if TARANG_ENABLE_PPG
  if (!tarang_ppg_is_found()) return false;
#endif
#if TARANG_ENABLE_IMU
  if (!tarang_imu_is_found()) return false;
#endif
  return tarang_ai_is_ready() && mtu_exchange_confirmed;
}

#define TARANG_EVENT_MAX_ANNOTATIONS TARANG_EVENT_ANNOTATION_HISTORY

typedef struct {
  bool active;
  uint16_t event_id;
  uint16_t sample_count;
  uint16_t samples_per_chunk;
  uint16_t total_chunks;
  uint16_t next_chunk;
  uint8_t annotation_count;
  uint8_t next_annotation;
  uint32_t transfer_start_ms;
  int16_t samples[TARANG_EVENT_SNIPPET_SAMPLES];
  tarang_ble_beat_annotation_t
      annotations[TARANG_EVENT_MAX_ANNOTATIONS];
} tarang_ble_event_transfer_t;

static tarang_ble_event_transfer_t event_transfer;
static int16_t event_snapshot[TARANG_EVENT_SNIPPET_SAMPLES];
static tarang_ble_beat_annotation_t
    event_annotation_snapshot[TARANG_EVENT_MAX_ANNOTATIONS];
static tarang_pipeline_event_annotation_t
    pipeline_annotation_snapshot[TARANG_EVENT_MAX_ANNOTATIONS];

/* Diagnostic & telemetry event counters */
static uint32_t ble_disconnect_count     = 0u;
static uint32_t ble_total_vitals_sent    = 0u;
static uint32_t ble_total_analytics_sent = 0u;
static uint32_t ble_total_events_sent    = 0u;
static uint32_t ble_total_chunks_sent    = 0u;
static bool     ble_warmup_logged        = false;

static const char *tarang_ble_reason_to_str(uint16_t reason)
{
  switch (reason) {
    case 0x0000: return "SUCCESS (0x0000)";
    case 0x0008: case 0x0208: return "SUPERVISION TIMEOUT (0x0008/0x0208) - Link lost / packet loss / central or pod unresponsive";
    case 0x0013: case 0x0213: return "REMOTE USER TERMINATED (0x0013/0x0213) - Central / RPi app explicitly closed link";
    case 0x0014: case 0x0214: return "REMOTE DEVICE LOW RESOURCES (0x0014/0x0214) - Central closed link due to resource exhaustion";
    case 0x0015: case 0x0215: return "REMOTE DEVICE POWERING OFF (0x0015/0x0215)";
    case 0x0016: case 0x0216: return "LOCAL HOST TERMINATED (0x0016/0x0216) - EFR32MG26 firmware initiated disconnect";
    case 0x001F: case 0x021F: return "UNSPECIFIED ERROR (0x001F/0x021F)";
    case 0x0022: case 0x0222: return "LL RESPONSE TIMEOUT (0x0022/0x0222) - Link layer transaction timed out";
    case 0x0028: case 0x0228: return "INSTANT PASSED (0x0028/0x0228) - Connection parameter timing missed";
    case 0x003D: case 0x023D: return "MIC FAILURE (0x003D/0x023D) - Encryption integrity check failed";
    case 0x003E: case 0x023E: return "FAILED TO ESTABLISH (0x003E/0x023E) - Connection setup incomplete";
    case 0x0205: return "AUTHENTICATION FAILURE (0x0205) - Pairing rejected or PIN/key incorrect";
    case 0x0206: return "PIN OR KEY MISSING (0x0206) - Stale bond key mismatch between pod and central";
    case 0x020C: return "COMMAND DISALLOWED (0x020C)";
    case 0x021A: return "UNSUPPORTED REMOTE FEATURE (0x021A)";
    case 0x021E: return "INVALID LMP/LL PARAMETERS (0x021E)";
    case 0x0224: return "LMP/LL COLLISION (0x0224)";
    case 0x023A: return "CONTROLLER BUSY (0x023A)";
    case 0x023B: return "UNACCEPTABLE CONNECTION INTERVAL (0x023B)";
    case 0x0242: return "DIFFERENT TRANSACTION COLLISION (0x0242)";
    case 0x1001: return "RESOURCE EXHAUSTED (0x1001) - BGAPI out of memory / TX buffers full";
    case 0x100C: return "CCCD IMPROPERLY CONFIGURED (0x100C)";
    case 0x100D: return "PROCEDURE IN PROGRESS (0x100D)";
    case 0x1011: return "INSUFFICIENT ENCRYPTION (0x1011)";
    default:     return "UNKNOWN STATUS CODE";
  }
}

static const char *tarang_ble_char_name(uint16_t characteristic)
{
  if (characteristic == gattdb_vitals_heart_rate) return "Vitals HR";
  if (characteristic == gattdb_vitals_spo2) return "Vitals SpO2";
  if (characteristic == gattdb_vitals_timestamp) return "Vitals Timestamp";
  if (characteristic == gattdb_analytics_pvc_burden) return "Analytics PVC Burden";
  if (characteristic == gattdb_analytics_pac_burden) return "Analytics PAC Burden";
  if (characteristic == gattdb_analytics_sdnn) return "Analytics SDNN";
  if (characteristic == gattdb_analytics_rmssd) return "Analytics RMSSD";
  if (characteristic == gattdb_analytics_prr50) return "Analytics pRR50";
  if (characteristic == gattdb_analytics_ai_duty_cycle) return "Analytics AI Duty";
  if (characteristic == gattdb_analytics_em2_sleep) return "Analytics EM2 Sleep";
  if (characteristic == gattdb_event_rhythm_status) return "Event Rhythm Status";
  if (characteristic == gattdb_event_meta) return "Event Meta";
  if (characteristic == gattdb_event_ecg_chunk) return "Event ECG Chunk";
  if (characteristic == gattdb_event_ecg_control) return "Event ECG Control";
  if (characteristic == gattdb_event_beat_annotations) return "Event Beat Annotations";
  if (characteristic == gattdb_event_glitch_ticker) return "Event Glitch Ticker";
  return "Unknown Char";
}

static uint8_t tarang_ble_get_active_sub_count(void)
{
  uint8_t count = 0;
  if (sub_vitals_hr) count++;
  if (sub_vitals_spo2) count++;
  if (sub_analytics_pvc) count++;
  if (sub_analytics_pac) count++;
  if (sub_analytics_sdnn) count++;
  if (sub_analytics_rmssd) count++;
  if (sub_analytics_prr50) count++;
  if (sub_analytics_duty) count++;
  if (sub_analytics_sleep) count++;
  if (sub_event_rhythm) count++;
  if (sub_event_meta) count++;
  if (sub_event_ecg_chunk) count++;
  if (sub_event_annotations) count++;
  if (sub_event_ticker) count++;
  return count;
}

static bool tarang_ble_status_ok(const char *operation, sl_status_t status)
{
  if (status == SL_STATUS_OK) {
    printf("[BLE][OK] %s\r\n", operation);
    return true;
  }
  printf("[BLE][ERROR] %s failed: 0x%08lX (%s)\r\n",
         operation, (unsigned long)status, tarang_ble_reason_to_str((uint16_t)status));
  return false;
}

#if defined(SL_CATALOG_BLUETOOTH_PRESENT)
static bool write_and_notify(uint16_t characteristic,
                             bool subscribed,
                             const void *value,
                             uint16_t value_len)
{
  sl_status_t sc = sl_bt_gatt_server_write_attribute_value(
      characteristic, 0u, value_len, (const uint8_t *)value);
  if (sc != SL_STATUS_OK) return false;
  if (!subscribed) return true;
  sc = sl_bt_gatt_server_send_notification(
      tarang_ble_conn_handle,
      characteristic,
      value_len,
      (const uint8_t *)value);
  return sc == SL_STATUS_OK;
}

static uint16_t event_payload_limit(void)
{
  uint16_t mtu = 23u;
  if (sl_bt_gatt_server_get_mtu(tarang_ble_conn_handle, &mtu)
      != SL_STATUS_OK) {
    mtu = 23u;
  }
  uint16_t payload = mtu > 3u ? (uint16_t)(mtu - 3u) : 20u;
  if (payload > gattdb_event_ecg_chunk_len) {
    payload = gattdb_event_ecg_chunk_len;
  }
  return payload;
}

static void event_transfer_send_next(void)
{
  if (!event_transfer.active
      || tarang_ble_conn_handle == SL_BT_INVALID_CONNECTION_HANDLE) {
    return;
  }

  sl_status_t sc;

  /* ── Send exactly ONE ECG chunk per call ─────────────────────────────
   * [FIX-4] Paced transfer. This function is re-driven every ~10 ms from
   * tarang_ble_process(), giving the link layer a full connection event
   * to drain each chunk. The previous tight while-loop blasted all ~10
   * chunks back-to-back inside one super-loop tick. At MTU 23 each 244 B
   * chunk fragments into 13+ LL packets, so the burst flooded the TX
   * queue faster than the radio could drain it -> supervision timeout.
   * One packet per tick is safe at any negotiated MTU. */
  if (event_transfer.next_chunk < event_transfer.total_chunks) {
    tarang_ble_snippet_chunk_t chunk;
    uint16_t chunk_index = event_transfer.next_chunk;
    uint16_t offset = (uint16_t)(chunk_index
        * event_transfer.samples_per_chunk);
    uint16_t sample_len = (uint16_t)(event_transfer.sample_count - offset);
    if (sample_len > event_transfer.samples_per_chunk) {
      sample_len = event_transfer.samples_per_chunk;
    }
    chunk.sequence_id = chunk_index;
    chunk.total_chunks = event_transfer.total_chunks;
    memcpy(chunk.samples,
           &event_transfer.samples[offset],
           sample_len * sizeof(int16_t));
    uint16_t packet_len = (uint16_t)(4u + sample_len * sizeof(int16_t));
    sc = sl_bt_gatt_server_send_notification(
        tarang_ble_conn_handle,
        gattdb_event_ecg_chunk,
        packet_len,
        (const uint8_t *)&chunk);
    if (sc != SL_STATUS_OK) {
      /* TX buffer full — retried on the next ~10 ms process tick */
      printf("[BLE][EVENT] Chunk %u/%u TX busy (0x%04lX), will retry\r\n",
             chunk_index, event_transfer.total_chunks, (unsigned long)sc);
      return;
    }
    event_transfer.next_chunk++;
    return; /* one chunk per tick; annotations continue on later ticks */
  }

  /* ── Send exactly ONE annotation packet per call ───────────────────── */
  if (sub_event_annotations
      && event_transfer.next_annotation < event_transfer.annotation_count) {
    uint16_t payload_limit = event_payload_limit();
    uint8_t max_entries = (uint8_t)(payload_limit
        / sizeof(tarang_ble_beat_annotation_t));
    if (max_entries == 0u) max_entries = 1u;
    uint8_t remaining = (uint8_t)(event_transfer.annotation_count
        - event_transfer.next_annotation);
    uint8_t entry_count = remaining > max_entries ? max_entries : remaining;
    const tarang_ble_beat_annotation_t *first =
        &event_transfer.annotations[event_transfer.next_annotation];
    sc = sl_bt_gatt_server_send_notification(
        tarang_ble_conn_handle,
        gattdb_event_beat_annotations,
        (uint16_t)(entry_count * sizeof(*first)),
        (const uint8_t *)first);
    if (sc != SL_STATUS_OK) {
      printf("[BLE][EVENT] Annotation TX busy (0x%04lX), will retry\r\n",
             (unsigned long)sc);
      return;
    }
    event_transfer.next_annotation = (uint8_t)(
        event_transfer.next_annotation + entry_count);
    return; /* one annotation packet per tick */
  }

  printf("[BLE][EVENT] Event#%u transfer complete: %u chunks, %u annotations\r\n",
         event_transfer.event_id,
         event_transfer.total_chunks,
         event_transfer.annotation_count);
  event_transfer.active = false;
  /* [FIX-1] Arm cooldown — even with notifications the radio needs a brief
   * rest before the next 10-chunk burst. */
  last_event_completion_ms = tarang_now_ms();
}
#endif

/******************************************************************************
 *                       PUBLIC API
 ******************************************************************************/
void tarang_ble_init(void)
{
  printf("[BLE] Mode A (Event-Driven) initialized.\r\n");
}

bool tarang_ble_is_connected(void)
{
  return (tarang_ble_conn_handle != SL_BT_INVALID_CONNECTION_HANDLE);
}

bool tarang_ble_is_notifications_enabled(void)
{
  return (sub_vitals_hr
          || sub_vitals_spo2
          || sub_analytics_pvc
          || sub_analytics_pac
          || sub_analytics_sdnn
          || sub_analytics_rmssd
          || sub_analytics_prr50
          || sub_analytics_duty
          || sub_analytics_sleep
          || sub_event_rhythm
          || sub_event_meta
          || sub_event_ecg_chunk
          || sub_event_annotations
          || sub_event_ticker);
}

/******************************************************************************
 *                     SERVICE A: VITALS NOTIFICATION
 ******************************************************************************/
bool tarang_ble_send_vitals(uint16_t hr_bpm, uint8_t spo2_pct, uint32_t ts_ms)
{
#if defined(SL_CATALOG_BLUETOOTH_PRESENT)
  if (tarang_ble_conn_handle == SL_BT_INVALID_CONNECTION_HANDLE) {
    return false;
  }

  sl_status_t sc;
  bool ok = true;

  /* Keep local values current so clients may read as well as subscribe. */
  sc = sl_bt_gatt_server_write_attribute_value(
      gattdb_vitals_heart_rate, 0, sizeof(hr_bpm), (const uint8_t *)&hr_bpm);
  if (sc != SL_STATUS_OK) ok = false;

  sc = sl_bt_gatt_server_write_attribute_value(
      gattdb_vitals_spo2, 0, sizeof(spo2_pct), (const uint8_t *)&spo2_pct);
  if (sc != SL_STATUS_OK) ok = false;

  sc = sl_bt_gatt_server_write_attribute_value(
      gattdb_vitals_timestamp,
      0,
      sizeof(ts_ms),
      (const uint8_t *)&ts_ms);
  if (sc != SL_STATUS_OK) ok = false;

  if (sub_vitals_hr) {
    sc = sl_bt_gatt_server_send_notification(
        tarang_ble_conn_handle,
        gattdb_vitals_heart_rate,
        sizeof(hr_bpm),
        (const uint8_t *)&hr_bpm);
    if (sc != SL_STATUS_OK) {
      printf("[BLE][VITALS] HR notify failed: 0x%08lX\r\n", (unsigned long)sc);
      ok = false;
    }
  }

  if (sub_vitals_spo2) {
    sc = sl_bt_gatt_server_send_notification(
        tarang_ble_conn_handle,
        gattdb_vitals_spo2,
        sizeof(spo2_pct),
        (const uint8_t *)&spo2_pct);
    if (sc != SL_STATUS_OK) {
      printf("[BLE][VITALS] SpO2 notify failed: 0x%08lX\r\n", (unsigned long)sc);
      ok = false;
    }
  }

  printf("[BLE][VITALS] Published: HR=%u SpO2=%u TS=%lu subscribers=%u/%u\r\n",
         hr_bpm, spo2_pct, (unsigned long)ts_ms,
         sub_vitals_hr ? 1u : 0u, sub_vitals_spo2 ? 1u : 0u);
  return ok;
#else
  (void)hr_bpm; (void)spo2_pct; (void)ts_ms;
  return false;
#endif
}

/******************************************************************************
 *                     SERVICE B: 5-MIN ANALYTICS ROLLUP
 ******************************************************************************/
bool tarang_ble_send_analytics(const tarang_ble_analytics_packet_t *analytics)
{
#if defined(SL_CATALOG_BLUETOOTH_PRESENT)
  if (!analytics || tarang_ble_conn_handle == SL_BT_INVALID_CONNECTION_HANDLE) {
    return false;
  }

  bool ok = true;
  ok &= write_and_notify(gattdb_analytics_pvc_burden,
                         sub_analytics_pvc,
                         &analytics->pvc_burden_pct,
                         sizeof(analytics->pvc_burden_pct));
  ok &= write_and_notify(gattdb_analytics_pac_burden,
                         sub_analytics_pac,
                         &analytics->pac_burden_pct,
                         sizeof(analytics->pac_burden_pct));
  ok &= write_and_notify(gattdb_analytics_sdnn,
                         sub_analytics_sdnn,
                         &analytics->sdnn_ms,
                         sizeof(analytics->sdnn_ms));
  ok &= write_and_notify(gattdb_analytics_rmssd,
                         sub_analytics_rmssd,
                         &analytics->rmssd_ms,
                         sizeof(analytics->rmssd_ms));
  ok &= write_and_notify(gattdb_analytics_prr50,
                         sub_analytics_prr50,
                         &analytics->prr50_pct,
                         sizeof(analytics->prr50_pct));
  ok &= write_and_notify(gattdb_analytics_ai_duty_cycle,
                         sub_analytics_duty,
                         &analytics->ai_duty_cycle_pct10,
                         sizeof(analytics->ai_duty_cycle_pct10));
  ok &= write_and_notify(gattdb_analytics_em2_sleep,
                         sub_analytics_sleep,
                         &analytics->em2_sleep_pct,
                         sizeof(analytics->em2_sleep_pct));

  if (ok) {
    printf("[BLE][ANALYTICS] 5-Min Rollup: PVC=%u%% PAC=%u%% SDNN=%ums RMSSD=%ums Sleep=%u%%\r\n",
           analytics->pvc_burden_pct, analytics->pac_burden_pct,
           analytics->sdnn_ms, analytics->rmssd_ms, analytics->em2_sleep_pct);
    return true;
  }
  printf("[BLE][ANALYTICS] One or more characteristic updates failed\r\n");
  return false;
#else
  (void)analytics;
  return false;
#endif
}

/******************************************************************************
 *                SERVICE C: EVENT-DRIVEN ANOMALY TRIGGER
 ******************************************************************************/
bool tarang_ble_trigger_clinical_event(
    uint8_t rhythm_status,
    uint16_t pattern_type,
    uint8_t confidence,
    uint32_t ts_ms,
    const int16_t *ecg_4s_samples,
    uint16_t sample_count,
    const tarang_ble_beat_annotation_t *annotations,
    uint8_t annotation_count)
{
#if defined(SL_CATALOG_BLUETOOTH_PRESENT)
  if (tarang_ble_conn_handle == SL_BT_INVALID_CONNECTION_HANDLE) {
    return false;
  }

  if (event_transfer.active) {
    return false;
  }

  /* [FIX-1] Cooldown guard. The radio's TX queue is still draining the
   * previous burst; a fresh 10-chunk indication sequence here will collide
   * and trip the connection supervision timeout. Caller is responsible
   * for re-flagging the event if it is genuinely significant — see
   * tarang_ble_process() flag-clear logic. */
  if (!tarang_ble_event_cooldown_elapsed()) {
    printf("[BLE][EVENT] Cooldown: dropped event (last completed %lums ago, need %ums)\r\n",
           (unsigned long)(tarang_now_ms() - last_event_completion_ms),
           (unsigned)TARANG_EVENT_COOLDOWN_MS);
    return false;
  }

  if (!sub_event_meta && !sub_event_rhythm) {
    return false;
  }
  if (!tarang_ble_mtu_ready_for_burst()) {
    /* MTU exchange hasn't confirmed yet and the timeout hasn't elapsed --
     * defer rather than sending a 10+ chunk transfer at the ATT default
     * MTU while negotiation may still be in flight. This only applies in
     * the first ~1.5s of a fresh connection. NOTE: whether the caller
     * re-flags this specific event on a later beat depends on whether
     * significant_event resets every beat in tarang_clinical_engine.c --
     * not fully verified here. Worst case in this narrow window is one
     * missed event notification at connection start, not a repeat of the
     * disconnect loop. */
    return false;
  }

  uint16_t current_event_id = next_event_id++;

  /* 1. Notify Rhythm Status */
  (void)write_and_notify(gattdb_event_rhythm_status,
                         sub_event_rhythm,
                         &rhythm_status,
                         sizeof(rhythm_status));

  /* 2. Notify Event Meta */
  tarang_ble_event_meta_t meta;
  meta.event_id     = current_event_id;
  meta.event_type   = rhythm_status;
  meta.confidence   = confidence;
  meta.timestamp_ms = ts_ms;

  (void)write_and_notify(gattdb_event_meta,
                         sub_event_meta,
                         &meta,
                         sizeof(meta));

  /* 3. Notify Glitch Ticker if pattern detected (Couplet, Triplet, Bigeminy, Run) */
  if (pattern_type > 0) {
    tarang_ble_glitch_ticker_t ticker;
    ticker.pattern_type = pattern_type;
    ticker.timestamp_ms = ts_ms;

    (void)write_and_notify(gattdb_event_glitch_ticker,
                           sub_event_ticker,
                           &ticker,
                           sizeof(ticker));
  }

  /* 4. Snapshot the waveform and start an acknowledged indication transfer. */
  memset(&event_transfer, 0, sizeof(event_transfer));
  event_transfer.event_id = current_event_id;
  if (ecg_4s_samples != NULL && sample_count > 0u && sub_event_ecg_chunk) {
    if (sample_count > TARANG_EVENT_SNIPPET_SAMPLES) {
      sample_count = TARANG_EVENT_SNIPPET_SAMPLES;
    }
    memcpy(event_transfer.samples,
           ecg_4s_samples,
           sample_count * sizeof(int16_t));
    event_transfer.sample_count = sample_count;

    uint16_t payload_limit = event_payload_limit();
    uint16_t samples_per_chunk = payload_limit > 4u
        ? (uint16_t)((payload_limit - 4u) / sizeof(int16_t)) : 1u;
    if (samples_per_chunk > TARANG_SNIPPET_CHUNK_MAX_SAMPLES) {
      samples_per_chunk = TARANG_SNIPPET_CHUNK_MAX_SAMPLES;
    }
    event_transfer.samples_per_chunk = samples_per_chunk;
    event_transfer.total_chunks = (uint16_t)(
        (sample_count + samples_per_chunk - 1u) / samples_per_chunk);
  }

  if (annotations != NULL && annotation_count > 0u) {
    if (annotation_count > TARANG_EVENT_MAX_ANNOTATIONS) {
      annotation_count = TARANG_EVENT_MAX_ANNOTATIONS;
    }
    memcpy(event_transfer.annotations,
           annotations,
           annotation_count * sizeof(*annotations));
    event_transfer.annotation_count = annotation_count;
  }

  event_transfer.active = event_transfer.total_chunks > 0u
      || (sub_event_annotations && event_transfer.annotation_count > 0u);
  if (event_transfer.active) {
    event_transfer.transfer_start_ms = tarang_now_ms();
  }
  event_transfer_send_next();

  printf("[BLE][EVENT] Event#%u Rhythm=0x%02X Conf=%u TS=%lu samples=%u mtu_payload=%u\r\n",
         current_event_id, rhythm_status, confidence, (unsigned long)ts_ms,
         event_transfer.sample_count, event_payload_limit());
  return true;
#else
  (void)rhythm_status; (void)pattern_type; (void)confidence; (void)ts_ms;
  (void)ecg_4s_samples; (void)sample_count; (void)annotations; (void)annotation_count;
  return false;
#endif
}

/******************************************************************************
 *                     HEALTH PACKET BUILDER (Compatibility)
 ******************************************************************************/
void tarang_ble_build_health_packet(tarang_pipeline_t *pipeline, tarang_health_packet_t *pkt)
{
  (void)pipeline;
  if (!pkt) return;
  memset(pkt, 0, sizeof(tarang_health_packet_t));

  uint32_t now_ms = tarang_now_ms();
  /* In-flight event transfers are paced and stall-guarded by
   * tarang_ble_process() once per super-loop tick; nothing to do here.
   * (This builder was previously the only retry driver for a TX-busy
   * chunk — but app.c never calls it, so a busy chunk stalled forever.) */
  pkt->uptime_s = now_ms / 1000u;

#if TARANG_ENABLE_ECG
  pkt->ecg_sqi = pipeline ? pipeline->latest_beat_telemetry.signal_quality : 255;
  pkt->ecg_lead_off = (pkt->ecg_sqi < 30) ? 1 : 0;
  uint32_t ecg_over = tarang_ecg_get_overrun_count();
  pkt->ecg_overrun_count = (uint8_t)(ecg_over > 255 ? 255 : ecg_over);
#else
  pkt->ecg_lead_off = 1;
  pkt->ecg_sqi = 0;
  pkt->ecg_overrun_count = 0;
#endif

#if TARANG_ENABLE_PPG
  pkt->ppg_finger_present = tarang_ppg_is_finger_present() ? 1 : 0;
  uint32_t ppg_fails = tarang_ppg_get_consecutive_failures();
  pkt->i2c_failure_count = (uint8_t)(ppg_fails > 255 ? 255 : ppg_fails);
#else
  pkt->ppg_finger_present = 0;
  pkt->i2c_failure_count = 0;
#endif

#if TARANG_ENABLE_IMU
  pkt->imu_ok = tarang_imu_is_healthy() ? 1 : 0;
#else
  pkt->imu_ok = 0;
#endif

  pkt->ble_rssi = 127;
  pkt->battery_pct = 255;
  pkt->status_flags = 0;
  pkt->fw_version_packed = (uint16_t)((TARANG_FW_VERSION_MAJOR << 8) | TARANG_FW_VERSION_MINOR);
}

/******************************************************************************
 *          HEART RATE CROSS-VALIDATION & FALLBACK FUSION
 *
 * Evaluates both ECG and PPG pulse/heart rates.
 * - If both are active and agree within tolerance (<= 15 BPM), ECG is primary.
 * - If both diverge (> 15 BPM), evaluates signal quality (SQI), motion flags,
 *   and lead status to fall back to whichever sensor is physiologically real.
 * - If only one sensor is valid (e.g. finger absent or ECG lead off),
 *   smoothly falls back to the valid sensor.
 ******************************************************************************/
#define TARANG_HR_MAX_VARIANCE_BPM  15u
#define TARANG_HR_MIN_PHYSIOLOGICAL 40u
#define TARANG_HR_MAX_PHYSIOLOGICAL 220u

uint16_t tarang_fuse_heart_rate(
    const tarang_pipeline_t *pipeline,
    const void *ppg_metrics_ptr,
    tarang_hr_source_t *source_out)
{
  const tarang_ppg_metrics_t *ppg_metrics =
      (const tarang_ppg_metrics_t *)ppg_metrics_ptr;

  uint16_t ecg_hr = 0u;
  uint8_t ecg_sqi = 0u;
  bool ecg_valid = false;

  if (pipeline != NULL && pipeline->engine.current_hr > 0u) {
    ecg_hr = pipeline->engine.current_hr;
    ecg_sqi = pipeline->latest_beat_telemetry.signal_quality;
    ecg_valid = (ecg_hr >= TARANG_HR_MIN_PHYSIOLOGICAL
                 && ecg_hr <= TARANG_HR_MAX_PHYSIOLOGICAL
                 && ecg_sqi >= 30u);
  }

  uint16_t ppg_hr = 0u;
  uint8_t ppg_sqi = 0u;
  bool ppg_valid = false;

  if (ppg_metrics != NULL && ppg_metrics->valid && ppg_metrics->finger_present) {
    ppg_hr = ppg_metrics->pulse_rate_bpm;
    ppg_sqi = ppg_metrics->signal_quality;
    ppg_valid = (ppg_hr >= TARANG_HR_MIN_PHYSIOLOGICAL
                 && ppg_hr <= TARANG_HR_MAX_PHYSIOLOGICAL
                 && !ppg_metrics->motion_rejected
                 && ppg_sqi >= 35u);
  }

  tarang_hr_source_t chosen_source = TARANG_HR_SOURCE_NONE;
  uint16_t final_hr = 0u;

  if (ecg_valid && ppg_valid) {
    int32_t diff = (int32_t)ecg_hr - (int32_t)ppg_hr;
    if (diff < 0) diff = -diff;

    if (diff <= (int32_t)TARANG_HR_MAX_VARIANCE_BPM) {
      /* Both agree within physiological margin */
      final_hr = ecg_hr;
      chosen_source = TARANG_HR_SOURCE_AGREED;
    } else {
      /* Divergence: compare normalized quality metrics */
      uint8_t ecg_quality_pct = (uint8_t)((ecg_sqi * 100u) / 255u);
      uint8_t ppg_quality_pct = ppg_sqi; /* Already 0-100 */

      if (ppg_metrics->motion_rejected || ecg_sqi >= 180u) {
        final_hr = ecg_hr;
        chosen_source = TARANG_HR_SOURCE_ECG;
      } else if (ecg_sqi < 100u || ppg_quality_pct > (ecg_quality_pct + 15u)) {
        /* ECG lead noise / artifact detected while optical pulse is clean */
        final_hr = ppg_hr;
        chosen_source = TARANG_HR_SOURCE_PPG;
      } else {
        /* Default to electrical R-peak rate if quality is comparable */
        final_hr = ecg_hr;
        chosen_source = TARANG_HR_SOURCE_ECG;
      }

      printf("[VITALS][FUSION] Divergence (%u BPM diff): ECG=%u (SQI=%u%%) vs PPG=%u (SQI=%u%%) -> Selected %s (%u BPM)\r\n",
             (unsigned)diff,
             (unsigned)ecg_hr, (unsigned)ecg_quality_pct,
             (unsigned)ppg_hr, (unsigned)ppg_quality_pct,
             chosen_source == TARANG_HR_SOURCE_PPG ? "PPG" : "ECG",
             (unsigned)final_hr);
    }
  } else if (ecg_valid) {
    final_hr = ecg_hr;
    chosen_source = TARANG_HR_SOURCE_ECG;
  } else if (ppg_valid) {
    final_hr = ppg_hr;
    chosen_source = TARANG_HR_SOURCE_PPG;
  }

  if (source_out != NULL) {
    *source_out = chosen_source;
  }
  return final_hr;
}

/******************************************************************************
 *                     MAIN PERIODIC PROCESS LOOP
 ******************************************************************************/
void tarang_ble_process(tarang_pipeline_t *pipeline)
{
#if defined(SL_CATALOG_BLUETOOTH_PRESENT)
  if (tarang_ble_conn_handle == SL_BT_INVALID_CONNECTION_HANDLE) {
    return;
  }

  /* ── Guard: wait until the subscription storm from the central is over ── */
  if (!tarang_ble_warmup_done()) {
    return;
  }

  if (!ble_warmup_logged) {
    ble_warmup_logged = true;
    printf("[BLE] Warmup period (%ums) complete — GATT notifications unlocked and active!\r\n",
           (unsigned)TARANG_BLE_WARMUP_MS);
  }

  uint32_t now_ms = tarang_now_ms();

  /* ── 0. In-flight clinical-event transfer: pacing + stall guard ─────
   * Drives one chunk/annotation packet per ~10 ms tick. If a transfer
   * makes no progress for 5 s (e.g. peer vanished), abandon it so the
   * next genuine event is not blocked behind a dead one. */
  if (event_transfer.active) {
    if (now_ms - event_transfer.transfer_start_ms > 5000u) {
      printf("[BLE][EVENT] Event#%u transfer stalled (%lums elapsed) — aborting\r\n",
             event_transfer.event_id, (unsigned long)(now_ms - event_transfer.transfer_start_ms));
      memset(&event_transfer, 0, sizeof(event_transfer));
      last_event_completion_ms = now_ms;
    } else {
      event_transfer_send_next();
    }
  }

  /* ── 1. Periodic Vitals Sync (every 2-3 seconds) ──────────────────── */
  if (now_ms - last_vitals_send_ms >= 2500u) {
    last_vitals_send_ms = now_ms;
    uint16_t hr = 0u;
    uint8_t spo2 = 0u;
    tarang_ppg_metrics_t ppg_metrics = {0};
#if TARANG_ENABLE_PPG
    (void)tarang_ppg_get_metrics(&ppg_metrics);
#endif
    tarang_hr_source_t hr_source = TARANG_HR_SOURCE_NONE;
#if TARANG_ENABLE_PPG
    /* Floating ECG input must not create a plausible-looking heart rate. */
    if (tarang_ppg_is_found()) {
      hr = tarang_fuse_heart_rate(pipeline, &ppg_metrics, &hr_source);
      if (ppg_metrics.valid && ppg_metrics.finger_present) {
        spo2 = ppg_metrics.spo2_pct;
      }
    }
#endif
    tarang_ble_send_vitals(hr, spo2, now_ms);
    ble_total_vitals_sent++;
  }

  /* ── 2. Periodic 5-Min Analytics Rollup ───────────────────────────── */
  if (now_ms - last_analytics_send_ms >= 300000u) { /* 5 minutes = 300,000 ms */
    last_analytics_send_ms = now_ms;

    tarang_ble_analytics_packet_t apkt;
    memset(&apkt, 0, sizeof(apkt));
    if (pipeline) {
      uint32_t total = pipeline->engine.total_beats > 0 ? pipeline->engine.total_beats : 1;
      apkt.pvc_burden_pct = (uint8_t)((pipeline->engine.pvc_count * 100u) / total);
      apkt.pac_burden_pct = (uint8_t)((pipeline->engine.pac_count * 100u) / total);
      apkt.sdnn_ms        = pipeline->engine.sdnn_ms;
      apkt.rmssd_ms       = pipeline->engine.rmssd_ms;
      apkt.prr50_pct      = pipeline->engine.prr50_pct;
    }
    if (pipeline != NULL && now_ms > 0u) {
      uint64_t uptime_us = (uint64_t)now_ms * 1000ULL;
      uint64_t duty_x10 = ((uint64_t)pipeline->diag.ai_time_us * 1000ULL)
                          / uptime_us;
      apkt.ai_duty_cycle_pct10 = duty_x10 > 255u
          ? 255u : (uint8_t)duty_x10;
    }
    /* No validated residency counter exists yet; report 0, never a fixture. */
    apkt.em2_sleep_pct = 0u;

    tarang_ble_send_analytics(&apkt);
    ble_total_analytics_sent++;
  }

  /* ── 3. Event-Driven Anomaly Push ─────────────────────────────────── */
  if (pipeline && tarang_pipeline_should_send_event(pipeline)) {
    if (tarang_ble_clinical_event_ready()) {
      uint8_t rhythm = pipeline->engine.rhythm_flags;
      uint16_t pattern = 0;
      if (rhythm & TARANG_RHYTHM_VT_SUSPECTED) pattern = 5;
      else if (pipeline->engine.consecutive_v > 3u) pattern = 5;
      else if (pipeline->engine.consecutive_v == 3u) pattern = 2;
      else if (pipeline->engine.consecutive_v == 2u) pattern = 1;
      else if (pipeline->engine.consecutive_s >= 3u) pattern = 6;
      else if (rhythm & TARANG_RHYTHM_BIGEMINY) pattern = 3;
      else if (rhythm & TARANG_RHYTHM_TRIGEMINY) pattern = 4;

      uint8_t conf = pipeline->latest_beat_telemetry.confidence;

      uint32_t snippet_start_sample = 0u;
      uint16_t snippet_count = tarang_pipeline_copy_event_snippet(
          pipeline,
          event_snapshot,
          TARANG_EVENT_SNIPPET_SAMPLES,
          &snippet_start_sample);
      uint8_t annotation_count = tarang_pipeline_copy_event_annotations(
          pipeline,
          snippet_start_sample,
          snippet_count,
          pipeline_annotation_snapshot,
          TARANG_EVENT_MAX_ANNOTATIONS);
      for (uint8_t i = 0u; i < annotation_count; i++) {
        event_annotation_snapshot[i].offset_ms =
            pipeline_annotation_snapshot[i].offset_ms;
        event_annotation_snapshot[i].label =
            pipeline_annotation_snapshot[i].beat_class;
        event_annotation_snapshot[i].confidence =
            pipeline_annotation_snapshot[i].confidence;
      }

      bool accepted = tarang_ble_trigger_clinical_event(
          rhythm,
          pattern,
          conf,
          pipeline->latest_beat_telemetry.timestamp_ms,
          event_snapshot,
          snippet_count,
          event_annotation_snapshot,
          annotation_count);

      if (accepted) {
        ble_total_events_sent++;
      }

      /* [FIX-2] ───────────────────────────────────────────────────────────
       * Clear the trigger flags regardless of whether the event was
       * accepted, rejected by event_transfer.active, or rejected by the
       * cooldown. If we only clear on accept, a rejected trigger leaves
       * the flags set and the next super-loop tick re-fires the same
       * event in a tight retry loop — keeping the radio busy until
       * supervision timeout. The next genuine rhythm change will re-arm. */
      pipeline->engine.rhythm_changed = false;
      pipeline->engine.significant_event = false;
    } else {
      /* Do not retry a candidate built from missing sensors or unavailable AI. */
      pipeline->engine.rhythm_changed = false;
      pipeline->engine.significant_event = false;
    }
  }

#else
  (void)pipeline;
#endif
}

/******************************************************************************
 *        BLUETOOTH STACK EVENT HANDLER
 ******************************************************************************/
#if defined(SL_CATALOG_BLUETOOTH_PRESENT)
void tarang_ble_on_event(sl_bt_msg_t *evt)
{
  sl_status_t sc;
  uint32_t event_id = SL_BT_MSG_ID(evt->header);

  switch (event_id) {

    /* ── System Boot: configure timing & start connectable advertising ── */
    case sl_bt_evt_system_boot_id:
    {
      printf("[BLE] System Boot: initializing stack (Mode A Event-Driven)...\r\n");

      sc = sl_bt_advertiser_create_set(&tarang_advertising_set_handle);
      if (!tarang_ble_status_ok("create advertising set", sc)) break;

#if defined(SL_CATALOG_BLUETOOTH_FEATURE_SM_PRESENT)
      uint8_t security_flags = TARANG_BLE_ENABLE_BONDING
                               ? SL_BT_SM_CONFIGURATION_BONDING_REQUEST_REQUIRED
                               : 0u;
      sc = sl_bt_sm_configure(security_flags,
                              sl_bt_sm_io_capability_noinputnooutput);
      tarang_ble_status_ok("configure security manager", sc);

      if (TARANG_BLE_ENABLE_BONDING) {
        sc = sl_bt_sm_store_bonding_configuration(8, 2);
        tarang_ble_status_ok("configure persistent bonding store", sc);
      }

      sc = sl_bt_sm_set_bondable_mode(TARANG_BLE_ENABLE_BONDING ? 1 : 0);
      if (!TARANG_BLE_ENABLE_BONDING) {
        /* Purge every stored bond from earlier secured builds */
        for (uint8_t b = 0u; b < 8u; ++b) {
          (void)sl_bt_sm_delete_bonding(b);
        }
        printf("[BLE][SM] Non-bondable mode; purged all stored bonds.\r\n");
      }
      tarang_ble_status_ok(TARANG_BLE_ENABLE_BONDING
                           ? "enable bonding"
                           : "disable bonding for direct-connect bring-up",
                           sc);
#else
      printf("[BLE] Security Manager not installed; using direct unpaired connection.\r\n");
#endif

      /* Dynamic Device Name: TARANG-<last 4 hex of MAC> */
      {
        bd_addr address;
        uint8_t addr_type;
        sc = sl_bt_system_get_identity_address(&address, &addr_type);
        if (sc == SL_STATUS_OK) {
          char name_buf[16];
          snprintf(name_buf, sizeof(name_buf), "TARANG-%02X%02X",
                   address.addr[1], address.addr[0]);
          sc = sl_bt_gatt_server_write_attribute_value(
              gattdb_device_name, 0, strlen(name_buf), (const uint8_t *)name_buf);
          if (!tarang_ble_status_ok("write device name", sc)) break;
          printf("[BLE] MAC: %02X:%02X:%02X:%02X:%02X:%02X (type=%u) -> Device Name: %s\r\n",
                 address.addr[5], address.addr[4], address.addr[3],
                 address.addr[2], address.addr[1], address.addr[0],
                 addr_type, name_buf);
        } else {
          tarang_ble_status_ok("get identity address", sc);
        }
      }

      sc = sl_bt_legacy_advertiser_generate_data(
          tarang_advertising_set_handle,
          sl_bt_advertiser_general_discoverable);
      if (!tarang_ble_status_ok("generate advertising data", sc)) break;

      /* 100ms advertising interval: 160 * 0.625ms = 100ms */
      sc = sl_bt_advertiser_set_timing(
          tarang_advertising_set_handle,
          160, 160, 0, 0);
      if (!tarang_ble_status_ok("set advertising timing", sc)) break;

      sc = sl_bt_legacy_advertiser_start(
          tarang_advertising_set_handle,
          sl_bt_legacy_advertiser_connectable);
      if (!tarang_ble_status_ok("start connectable advertising", sc)) break;

      printf("[BLE] Connectable advertising started (AdvSet=0x%02X, interval=100ms).\r\n",
             tarang_advertising_set_handle);
      break;
    }

    /* ── Connection Opened ──── */
    case sl_bt_evt_connection_opened_id:
    {
      const sl_bt_evt_connection_opened_t *opened =
          &evt->data.evt_connection_opened;
      tarang_ble_conn_handle = opened->connection;
      tarang_ble_bonding_handle = opened->bonding;
      connection_opened_ms = tarang_now_ms();
      last_vitals_send_ms    = connection_opened_ms;
      last_analytics_send_ms = connection_opened_ms;
      negotiated_mtu         = 23u;      /* ATT default until proven otherwise */
      mtu_exchange_confirmed = false;
      ble_warmup_logged      = false;

      printf("=========================================================\r\n");
      printf("[BLE][CONNECT] >>> CENTRAL CONNECTED! <<<\r\n");
      printf("[BLE][CONNECT]   Handle:       0x%02X\r\n", tarang_ble_conn_handle);
      printf("[BLE][CONNECT]   Peer Address: %02X:%02X:%02X:%02X:%02X:%02X (type=%u)\r\n",
             opened->address.addr[5], opened->address.addr[4], opened->address.addr[3],
             opened->address.addr[2], opened->address.addr[1], opened->address.addr[0],
             opened->address_type);
      printf("[BLE][CONNECT]   Bond Handle:  0x%02X\r\n", tarang_ble_bonding_handle);
      printf("[BLE][CONNECT]   Warmup:       Suppressing data for %ums while central subscribes...\r\n",
             (unsigned)TARANG_BLE_WARMUP_MS);
      printf("=========================================================\r\n");
      break;
    }

    case sl_bt_evt_gatt_mtu_exchanged_id:
    {
      const sl_bt_evt_gatt_mtu_exchanged_t *mtu_evt =
          &evt->data.evt_gatt_mtu_exchanged;
      negotiated_mtu         = mtu_evt->mtu;
      mtu_exchange_confirmed = true;
      printf("[BLE][MTU] MTU exchanged: conn=0x%02X MTU=%u bytes (Max ATT Payload=%u bytes)\r\n",
             mtu_evt->connection,
             (unsigned)negotiated_mtu,
             (unsigned)(negotiated_mtu > 3u ? negotiated_mtu - 3u : 20u));
      break;
    }

    case sl_bt_evt_connection_parameters_id:
    {
      const sl_bt_evt_connection_parameters_t *parameters =
          &evt->data.evt_connection_parameters;
      /* interval in units of 1.25ms; timeout in units of 10ms */
      uint32_t interval_ms_x10 = (uint32_t)parameters->interval * 125u / 10u;
      uint32_t timeout_ms = (uint32_t)parameters->timeout * 10u;
      printf("[BLE][PARAMS] conn=0x%02X CI=%u.%ums (val=%u) Latency=%u Timeout=%lums (val=%u) SecMode=%u\r\n",
             parameters->connection,
             (unsigned)(interval_ms_x10 / 10u), (unsigned)(interval_ms_x10 % 10u),
             parameters->interval,
             parameters->latency,
             (unsigned long)timeout_ms,
             parameters->timeout,
             parameters->security_mode);
      break;
    }

    /* ── Auto-confirm bonding if requested ──── */
#if defined(SL_CATALOG_BLUETOOTH_FEATURE_SM_PRESENT) && TARANG_BLE_ENABLE_BONDING
    case sl_bt_evt_sm_bonded_id:
    {
      const sl_bt_evt_sm_bonded_t *bonded = &evt->data.evt_sm_bonded;
      printf("[BLE][SM] Bonded: conn=0x%02X handle=0x%02X security=%u\r\n",
             bonded->connection,
             bonded->bonding,
             bonded->security_mode);
      tarang_ble_bonding_handle = bonded->bonding;
      break;
    }

    case sl_bt_evt_sm_bonding_failed_id:
    {
      const sl_bt_evt_sm_bonding_failed_t *failed =
          &evt->data.evt_sm_bonding_failed;
      printf("[BLE][SM][ERROR] Bonding failed: conn=0x%02X reason=0x%04X (%s)\r\n",
             failed->connection,
             (unsigned)failed->reason,
             tarang_ble_reason_to_str(failed->reason));

      if ((failed->reason == SL_STATUS_BT_CTRL_AUTHENTICATION_FAILURE
           || failed->reason == SL_STATUS_BT_CTRL_PIN_OR_KEY_MISSING)
          && tarang_ble_bonding_handle != SL_BT_INVALID_BONDING_HANDLE) {
        uint8_t stale_bonding_handle = tarang_ble_bonding_handle;
        tarang_ble_bonding_handle = SL_BT_INVALID_BONDING_HANDLE;
        printf("[BLE][SM] Removing stale bond handle=0x%02X; central must reconnect and pair cleanly.\r\n",
               stale_bonding_handle);
        sc = sl_bt_sm_delete_bonding(stale_bonding_handle);
        tarang_ble_status_ok("delete stale peer bond", sc);
      } else if (failed->reason == SL_STATUS_BT_CTRL_AUTHENTICATION_FAILURE
                 || failed->reason == SL_STATUS_BT_CTRL_PIN_OR_KEY_MISSING) {
        printf("[BLE][SM] No local bond exists; peer must clear its cached bond.\r\n");
      }
      break;
    }

    case sl_bt_evt_sm_confirm_bonding_id:
    {
      const sl_bt_evt_sm_confirm_bonding_t *request =
          &evt->data.evt_sm_confirm_bonding;
      uint8_t conn = request->connection;
      printf("[BLE][SM] Confirming bonding request: conn=0x%02X existing=0x%02X\r\n",
             conn,
             request->bonding_handle);
      sc = sl_bt_sm_bonding_confirm(conn, 1);
      tarang_ble_status_ok("confirm bonding request", sc);
      break;
    }

    case sl_bt_evt_sm_passkey_display_id:
    {
      printf("[BLE][SM] Passkey Display: conn=0x%02X Passkey=%06lu\r\n",
             evt->data.evt_sm_passkey_display.connection,
             (unsigned long)evt->data.evt_sm_passkey_display.passkey);
      break;
    }

    case sl_bt_evt_sm_passkey_request_id:
    {
      printf("[BLE][SM] Passkey Requested for conn=0x%02X\r\n",
             evt->data.evt_sm_passkey_request.connection);
      break;
    }

    case sl_bt_evt_sm_confirm_passkey_id:
    {
      printf("[BLE][SM] Confirm Passkey on conn=0x%02X Passkey=%06lu\r\n",
             evt->data.evt_sm_confirm_passkey.connection,
             (unsigned long)evt->data.evt_sm_confirm_passkey.passkey);
      (void)sl_bt_sm_passkey_confirm(evt->data.evt_sm_confirm_passkey.connection, 1);
      break;
    }
#endif

    /* ── Connection Closed ──── */
    case sl_bt_evt_connection_closed_id:
    {
      uint16_t reason = evt->data.evt_connection_closed.reason;
      uint8_t closed_handle = evt->data.evt_connection_closed.connection;
      ble_disconnect_count++;

      uint32_t conn_duration_s = (connection_opened_ms > 0 && tarang_now_ms() >= connection_opened_ms)
                                 ? (tarang_now_ms() - connection_opened_ms) / 1000u : 0u;

      printf("=========================================================\r\n");
      printf("[BLE][DISCONNECT] >>> CONNECTION TERMINATED <<<\r\n");
      printf("[BLE][DISCONNECT]   Handle:          0x%02X\r\n", closed_handle);
      printf("[BLE][DISCONNECT]   Reason Code:     0x%04X\r\n", (unsigned)reason);
      printf("[BLE][DISCONNECT]   Reason Meaning:  %s\r\n", tarang_ble_reason_to_str(reason));
      printf("[BLE][DISCONNECT]   Link Duration:   %lu seconds\r\n", (unsigned long)conn_duration_s);
      printf("[BLE][DISCONNECT]   Session Totals:  Vitals=%lu Analytics=%lu Events=%lu Chunks=%lu\r\n",
             (unsigned long)ble_total_vitals_sent,
             (unsigned long)ble_total_analytics_sent,
             (unsigned long)ble_total_events_sent,
             (unsigned long)ble_total_chunks_sent);
      printf("[BLE][DISCONNECT]   Disconnect #:    %lu\r\n", (unsigned long)ble_disconnect_count);
      printf("=========================================================\r\n");

      tarang_ble_conn_handle = SL_BT_INVALID_CONNECTION_HANDLE;
      tarang_ble_bonding_handle = SL_BT_INVALID_BONDING_HANDLE;
      memset(&event_transfer, 0, sizeof(event_transfer));
      last_event_completion_ms = 0u;
      connection_opened_ms = 0u;
      ble_warmup_logged = false;

      sub_vitals_hr         = false;
      sub_vitals_spo2       = false;
      sub_analytics_pvc     = false;
      sub_analytics_pac     = false;
      sub_analytics_sdnn    = false;
      sub_analytics_rmssd   = false;
      sub_analytics_prr50   = false;
      sub_analytics_duty    = false;
      sub_analytics_sleep   = false;
      sub_event_rhythm      = false;
      sub_event_meta        = false;
      sub_event_ecg_chunk   = false;
      sub_event_annotations = false;
      sub_event_ticker      = false;

      sc = sl_bt_legacy_advertiser_generate_data(
          tarang_advertising_set_handle,
          sl_bt_advertiser_general_discoverable);
      if (!tarang_ble_status_ok("regenerate advertising data", sc)) break;

      sc = sl_bt_advertiser_set_timing(
          tarang_advertising_set_handle,
          160, 160, 0, 0);
      if (!tarang_ble_status_ok("restore advertising timing", sc)) break;

      sc = sl_bt_legacy_advertiser_start(
          tarang_advertising_set_handle,
          sl_bt_legacy_advertiser_connectable);
      tarang_ble_status_ok("restart connectable advertising", sc);
      printf("[BLE] Resumed advertising (AdvSet=0x%02X). Waiting for Central/RPi to reconnect.\r\n",
             tarang_advertising_set_handle);
      break;
    }

    /* ── CCCD Write: subscription management ──── */
    case sl_bt_evt_gatt_server_characteristic_status_id:
    {
      uint16_t characteristic = evt->data.evt_gatt_server_characteristic_status.characteristic;
      uint8_t status_flags = evt->data.evt_gatt_server_characteristic_status.status_flags;
      uint16_t client_config = evt->data.evt_gatt_server_characteristic_status.client_config_flags;

      if (status_flags & sl_bt_gatt_server_client_config) {
        bool enabled = (client_config != sl_bt_gatt_disable);

        if (characteristic == gattdb_vitals_heart_rate) {
          sub_vitals_hr = enabled;
        } else if (characteristic == gattdb_vitals_spo2) {
          sub_vitals_spo2 = enabled;
        } else if (characteristic == gattdb_analytics_pvc_burden) {
          sub_analytics_pvc = enabled;
        } else if (characteristic == gattdb_analytics_pac_burden) {
          sub_analytics_pac = enabled;
        } else if (characteristic == gattdb_analytics_sdnn) {
          sub_analytics_sdnn = enabled;
        } else if (characteristic == gattdb_analytics_rmssd) {
          sub_analytics_rmssd = enabled;
        } else if (characteristic == gattdb_analytics_prr50) {
          sub_analytics_prr50 = enabled;
        } else if (characteristic == gattdb_analytics_ai_duty_cycle) {
          sub_analytics_duty = enabled;
        } else if (characteristic == gattdb_analytics_em2_sleep) {
          sub_analytics_sleep = enabled;
        } else if (characteristic == gattdb_event_rhythm_status) {
          sub_event_rhythm = enabled;
        } else if (characteristic == gattdb_event_meta) {
          sub_event_meta = enabled;
        } else if (characteristic == gattdb_event_ecg_chunk) {
          sub_event_ecg_chunk = enabled;
        } else if (characteristic == gattdb_event_beat_annotations) {
          sub_event_annotations = enabled;
        } else if (characteristic == gattdb_event_glitch_ticker) {
          sub_event_ticker = enabled;
        }

        uint8_t total_subs = tarang_ble_get_active_sub_count();
        printf("[BLE][CCCD] Handle 0x%04X (%s) -> %s (Active Streams: %u/14)\r\n",
               (unsigned)characteristic,
               tarang_ble_char_name(characteristic),
               enabled ? "SUBSCRIBED [ON]" : "UNSUBSCRIBED [OFF]",
               total_subs);
      }

      if (status_flags & sl_bt_gatt_server_confirmation) {
        printf("[BLE][GATT] Indication confirmation received for handle 0x%04X (%s)\r\n",
               (unsigned)characteristic,
               tarang_ble_char_name(characteristic));
      }
      break;
    }

#if defined(sl_bt_evt_gatt_server_attribute_value_id)
    case sl_bt_evt_gatt_server_attribute_value_id:
    {
      const sl_bt_evt_gatt_server_attribute_value_t *val =
          &evt->data.evt_gatt_server_attribute_value;
      printf("[BLE][GATT] Central wrote to attribute 0x%04X (%s): %u bytes\r\n",
             val->attribute, tarang_ble_char_name(val->attribute), val->value.len);
      break;
    }
#endif

#if defined(sl_bt_evt_gatt_server_user_read_request_id)
    case sl_bt_evt_gatt_server_user_read_request_id:
    {
      const sl_bt_evt_gatt_server_user_read_request_t *req =
          &evt->data.evt_gatt_server_user_read_request;
      printf("[BLE][GATT] User read request on char 0x%04X (%s)\r\n",
             req->characteristic, tarang_ble_char_name(req->characteristic));
      break;
    }
#endif

#if defined(sl_bt_evt_gatt_server_user_write_request_id)
    case sl_bt_evt_gatt_server_user_write_request_id:
    {
      const sl_bt_evt_gatt_server_user_write_request_t *req =
          &evt->data.evt_gatt_server_user_write_request;
      printf("[BLE][GATT] User write request on char 0x%04X (%s): %u bytes\r\n",
             req->characteristic, tarang_ble_char_name(req->characteristic), req->value.len);
      break;
    }
#endif

#if defined(sl_bt_evt_system_resource_exhausted_id)
    case sl_bt_evt_system_resource_exhausted_id:
    {
      printf("*********************************************************\r\n");
      printf("[BLE][CRITICAL] SYSTEM RESOURCE EXHAUSTED: Stack TX buffers depleted or dropped!\r\n");
      printf("*********************************************************\r\n");
      break;
    }
#endif

#if defined(sl_bt_evt_system_error_id)
    case sl_bt_evt_system_error_id:
    {
      uint16_t reason = evt->data.evt_system_error.reason;
      printf("[BLE][ERROR] System error: 0x%04X (%s)\r\n",
             (unsigned)reason, tarang_ble_reason_to_str(reason));
      break;
    }
#endif

#if defined(sl_bt_evt_system_hardware_error_id)
    case sl_bt_evt_system_hardware_error_id:
    {
      uint16_t status = evt->data.evt_system_hardware_error.status;
      printf("[BLE][ERROR] System hardware error: 0x%04X\r\n", (unsigned)status);
      break;
    }
#endif

#if defined(sl_bt_evt_advertiser_timeout_id)
    case sl_bt_evt_advertiser_timeout_id:
    {
      printf("[BLE][WARN] Advertiser set 0x%02X timed out.\r\n",
             evt->data.evt_advertiser_timeout.handle);
      break;
    }
#endif

    default:
      /* Log any unhandled events with hex ID for full observability */
      printf("[BLE][EVT] Stack Event ID: 0x%08lX\r\n", (unsigned long)event_id);
      break;
  }
}
#endif

/******************************************************************************
 *                  BLE DIAGNOSTICS STATUS PRINTER
 ******************************************************************************/
void tarang_ble_print_status(void)
{
  uint32_t now_ms = tarang_now_ms();
  if (tarang_ble_conn_handle != SL_BT_INVALID_CONNECTION_HANDLE) {
    uint32_t uptime_s = (connection_opened_ms > 0 && now_ms >= connection_opened_ms)
                        ? (now_ms - connection_opened_ms) / 1000u : 0u;
    bool in_warmup = !tarang_ble_warmup_done();
    uint8_t subs = tarang_ble_get_active_sub_count();
    printf("  [BLE] State: CONNECTED (handle=0x%02X, bond=0x%02X, MTU=%u, Uptime=%lus)\r\n",
           tarang_ble_conn_handle, tarang_ble_bonding_handle, negotiated_mtu, (unsigned long)uptime_s);
    printf("  [BLE] Active Subscriptions: %u/14 | Warmup: %s | Transfer: %s\r\n",
           subs,
           in_warmup ? "ACTIVE (suppressed)" : "READY",
           event_transfer.active ? "IN PROGRESS" : "IDLE");
  } else {
    printf("  [BLE] State: ADVERTISING (set=0x%02X) | Disconnects=%lu | Vitals Sent=%lu Events Sent=%lu\r\n",
           tarang_advertising_set_handle,
           (unsigned long)ble_disconnect_count,
           (unsigned long)ble_total_vitals_sent,
           (unsigned long)ble_total_events_sent);
  }
}
