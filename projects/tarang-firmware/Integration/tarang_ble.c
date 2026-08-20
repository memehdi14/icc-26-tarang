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
 * Target : EFR32MG26B510F3200IM48 (Series 2, Cortex-M33)
 ******************************************************************************/
#include "tarang_ble.h"
#include "tarang_time.h"
#include "tarang_constants.h"
#include "tarang_ecg.h"
#include "tarang_ppg.h"
#include "tarang_imu.h"
#include <stdio.h>
#include <string.h>

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

/* Bonding is enabled only when the generated project includes Security Manager. */
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
#define TARANG_BLE_WARMUP_MS           3500u  /* 3.5s: covers 14 CCCDs + pairing */

static bool tarang_ble_warmup_done(void)
{
  if (connection_opened_ms == 0u) return false;
  return (tarang_now_ms() - connection_opened_ms) >= TARANG_BLE_WARMUP_MS;
}

#define TARANG_EVENT_MAX_ANNOTATIONS TARANG_EVENT_ANNOTATION_HISTORY

typedef struct {
  bool active;
  bool waiting_confirmation;
  uint16_t event_id;
  uint16_t sample_count;
  uint16_t samples_per_chunk;
  uint16_t total_chunks;
  uint16_t next_chunk;
  uint8_t annotation_count;
  uint8_t next_annotation;
  uint32_t confirmation_sent_ms;
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

static bool tarang_ble_status_ok(const char *operation, sl_status_t status)
{
  if (status == SL_STATUS_OK) {
    printf("[BLE][OK] %s\r\n", operation);
    return true;
  }
  printf("[BLE][ERROR] %s failed: 0x%08lX\r\n", operation, (unsigned long)status);
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
  if (!event_transfer.active || event_transfer.waiting_confirmation
      || tarang_ble_conn_handle == SL_BT_INVALID_CONNECTION_HANDLE) {
    return;
  }

  sl_status_t sc;
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
    sc = sl_bt_gatt_server_send_indication(
        tarang_ble_conn_handle,
        gattdb_event_ecg_chunk,
        packet_len,
        (const uint8_t *)&chunk);
    if (sc == SL_STATUS_OK) {
      event_transfer.next_chunk++;
      event_transfer.waiting_confirmation = true;
      event_transfer.confirmation_sent_ms = tarang_now_ms();
    }
    return;
  }

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
    sc = sl_bt_gatt_server_send_indication(
        tarang_ble_conn_handle,
        gattdb_event_beat_annotations,
        (uint16_t)(entry_count * sizeof(*first)),
        (const uint8_t *)first);
    if (sc == SL_STATUS_OK) {
      event_transfer.next_annotation = (uint8_t)(
          event_transfer.next_annotation + entry_count);
      event_transfer.waiting_confirmation = true;
      event_transfer.confirmation_sent_ms = tarang_now_ms();
    }
    return;
  }

  printf("[BLE][EVENT] Event#%u transfer complete: %u chunks, %u annotations\r\n",
         event_transfer.event_id,
         event_transfer.total_chunks,
         event_transfer.annotation_count);
  event_transfer.active = false;
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
  if (!sub_event_meta && !sub_event_rhythm) {
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
  if (event_transfer.active && event_transfer.waiting_confirmation
      && now_ms - event_transfer.confirmation_sent_ms > 5000u) {
    printf("[BLE][EVENT] Event#%u indication confirmation timed out\r\n",
           event_transfer.event_id);
    memset(&event_transfer, 0, sizeof(event_transfer));
  }
  event_transfer_send_next();
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

  uint32_t now_ms = tarang_now_ms();

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
    hr = tarang_fuse_heart_rate(pipeline, &ppg_metrics, &hr_source);
    if (ppg_metrics.valid && ppg_metrics.finger_present) {
      spo2 = ppg_metrics.spo2_pct;
    }
    tarang_ble_send_vitals(hr, spo2, now_ms);
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
  }

  /* ── 3. Event-Driven Anomaly Push ─────────────────────────────────── */
  if (pipeline && tarang_pipeline_should_send_event(pipeline)) {
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

  switch (SL_BT_MSG_ID(evt->header)) {

    /* ── System Boot: configure timing & start connectable advertising ── */
    case sl_bt_evt_system_boot_id:
    {
      printf("TARANG BLE BOOT OK (Mode A Event-Driven)\r\n");

      sc = sl_bt_advertiser_create_set(&tarang_advertising_set_handle);
      if (!tarang_ble_status_ok("create advertising set", sc)) break;

#if defined(SL_CATALOG_BLUETOOTH_FEATURE_SM_PRESENT)
      /*
       * Request an application confirmation for every new bond. Besides making
       * the policy explicit, this lets a central deliberately replace an old
       * bond whose key it no longer has. The confirm event reports the existing
       * bonding handle and sl_bt_sm_bonding_confirm(..., 1) authorizes the
       * stack to overwrite it with the newly negotiated keys.
       */
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
          printf("[BLE] Device name: %s\r\n", name_buf);
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

      printf("[BLE] Connectable advertising started (Mode A Ready).\r\n");
      break;
    }

    /* ── Connection Opened ──── */
    case sl_bt_evt_connection_opened_id:
    {
      const sl_bt_evt_connection_opened_t *opened =
          &evt->data.evt_connection_opened;
      tarang_ble_conn_handle = opened->connection;
      tarang_ble_bonding_handle = opened->bonding;
      printf("[BLE] Connection opened! Handle=0x%02X bond=0x%02X\r\n",
             tarang_ble_conn_handle,
             tarang_ble_bonding_handle);

      /*
       * FIX 1: Request MTU 247 — the default 23 causes maximum packet
       * fragmentation and TX queue saturation during the notification storm.
       * Both EFR32 and BlueZ support 247; we just need someone to ask.
       */
      sc = sl_bt_gatt_server_set_max_mtu(247, NULL);
      tarang_ble_status_ok("request MTU 247", sc);

      /*
       * FIX 2: Request connection parameters that give the radio enough
       * breathing room.  BlueZ's defaults can be too aggressive (7.5ms
       * interval with a short supervision timeout).  We ask for:
       *   - Interval: 30-50ms  (48-80 * 1.25ms)
       *   - Slave latency: 0   (respond every interval)
       *   - Supervision timeout: 8s (640 * 10ms)
       * The central may reject, but in practice BlueZ and phones accept.
       */
      sc = sl_bt_connection_set_preferred_phy(
          opened->connection, 0x01, 0x01);  /* 1M PHY both directions */
      tarang_ble_status_ok("request 1M PHY", sc);

      sc = sl_bt_connection_set_parameters(
          opened->connection,
          24,     /* min interval: 24 * 1.25ms = 30ms */
          40,     /* max interval: 40 * 1.25ms = 50ms */
          0,      /* slave latency: 0 (respond every event) */
          600,    /* supervision timeout: 600 * 10ms = 6.0s */
          0,      /* ce_len min */
          0xFFFF);/* ce_len max */
      tarang_ble_status_ok("request connection parameters", sc);

      /* Start the warmup timer — no notifications until CCCD storm is over */
      connection_opened_ms = tarang_now_ms();
      last_vitals_send_ms    = connection_opened_ms;
      last_analytics_send_ms = connection_opened_ms;
      printf("[BLE] Warmup: suppressing notifications for %ums while central subscribes.\r\n",
             (unsigned)TARANG_BLE_WARMUP_MS);
      break;
    }

    case sl_bt_evt_connection_parameters_id:
    {
      const sl_bt_evt_connection_parameters_t *parameters =
          &evt->data.evt_connection_parameters;
      printf("[BLE] Connection security=%u interval=%u timeout=%u\r\n",
             parameters->security_mode,
             parameters->interval,
             parameters->timeout);
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
      printf("[BLE][SM] Bonding failed: conn=0x%02X reason=0x%04X\r\n",
             failed->connection,
             (unsigned)failed->reason);

      /*
       * A peer that forgot its key while this device retained the old bond
       * produces one of these controller errors. Delete only that stale local
       * entry. The delete closes the affected connection; the central can then
       * reconnect and create a clean bond without erasing the whole device.
       */
      if ((failed->reason == SL_STATUS_BT_CTRL_AUTHENTICATION_FAILURE
           || failed->reason == SL_STATUS_BT_CTRL_PIN_OR_KEY_MISSING)
          && tarang_ble_bonding_handle != SL_BT_INVALID_BONDING_HANDLE) {
        uint8_t stale_bonding_handle = tarang_ble_bonding_handle;
        tarang_ble_bonding_handle = SL_BT_INVALID_BONDING_HANDLE;
        printf("[BLE][SM] Removing stale bond handle=0x%02X; reconnect and pair again.\r\n",
               stale_bonding_handle);
        sc = sl_bt_sm_delete_bonding(stale_bonding_handle);
        tarang_ble_status_ok("delete stale peer bond", sc);
      } else if (failed->reason == SL_STATUS_BT_CTRL_AUTHENTICATION_FAILURE
                 || failed->reason == SL_STATUS_BT_CTRL_PIN_OR_KEY_MISSING) {
        printf("[BLE][SM] No local bond exists; the peer must discard its stale key.\r\n");
      }
      break;
    }

    case sl_bt_evt_sm_confirm_bonding_id:
    {
      const sl_bt_evt_sm_confirm_bonding_t *request =
          &evt->data.evt_sm_confirm_bonding;
      uint8_t conn = request->connection;
      printf("[BLE][SM] Confirming bonding on conn=0x%02X existing=0x%02X\r\n",
             conn,
             request->bonding_handle);
      sc = sl_bt_sm_bonding_confirm(conn, 1);
      tarang_ble_status_ok("confirm bonding request", sc);
      break;
    }
#endif

    /* ── Connection Closed ──── */
    case sl_bt_evt_connection_closed_id:
    {
      uint16_t reason = evt->data.evt_connection_closed.reason;
      printf("[BLE] Connection closed: reason=0x%04X. Restarting advertising...\r\n",
             (unsigned)reason);

      tarang_ble_conn_handle = SL_BT_INVALID_CONNECTION_HANDLE;
      tarang_ble_bonding_handle = SL_BT_INVALID_BONDING_HANDLE;
      memset(&event_transfer, 0, sizeof(event_transfer));
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

        printf("[BLE] CCCD: char=0x%04X -> %s\r\n",
               (unsigned)characteristic, enabled ? "SUBSCRIBED" : "UNSUBSCRIBED");

        /*
         * FIX 3: Do NOT force an immediate send on CCCD subscribe.
         * The old code set last_vitals_send_ms = now - 2500 and
         * last_analytics_send_ms = now - 300000, causing an immediate
         * burst of notifications during the subscription storm.  This
         * was the primary cause of the connect-disconnect loop.
         *
         * Instead, the warmup guard already suppresses all sends for
         * TARANG_BLE_WARMUP_MS after connection open.  After warmup,
         * the first natural timer tick will send the data.
         */
      }

      if ((status_flags & sl_bt_gatt_server_confirmation) != 0u
          && event_transfer.active
          && event_transfer.waiting_confirmation
          && (characteristic == gattdb_event_ecg_chunk
              || characteristic == gattdb_event_beat_annotations)) {
        event_transfer.waiting_confirmation = false;
        event_transfer_send_next();
      }
      break;
    }

    default:
      break;
  }
}
#endif
