/***************************************************************************//**
 * @file tarang_ble.c
 * @brief TARANG BLE Telemetry — Two-Device Clinical System (Pod ↔ Hub).
 *
 * Implements the BLE GATT server for the EFR32MG26 Patient Pod:
 *   - 30-second boot advertising window (undiscoverable after timeout/connect)
 *   - Just Works bonding with LTK persistence for auto-reconnect
 *   - Clinical Telemetry notifications (16B, event-driven + 1 Hz fallback)
 *   - Device Health notifications (16B, 1 Hz periodic)
 *   - ECG Waveform notifications (32B chunks, 25 Hz — placeholder for Phase 2)
 *   - PPG/IMU Waveform characteristics (reserved, not yet dispatched)
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

/* ── Compile-time GATT handle assertions ──────────────────────────────────── */
#if defined(SL_CATALOG_BLUETOOTH_PRESENT)
  #if !defined(gattdb_telemetry_data)
    #error "gattdb_telemetry_data is not defined — regenerate gatt_db from gatt_configuration.btconf"
  #endif
  #if !defined(gattdb_device_health)
    /* Fallback: old btconf used 'device_status' id instead of 'device_health' */
    #if defined(gattdb_device_status)
      #define gattdb_device_health gattdb_device_status
    #else
      #error "gattdb_device_health is not defined — regenerate gatt_db from gatt_configuration.btconf"
    #endif
  #endif
#endif

#if defined(SL_CATALOG_APP_ASSERT_PRESENT)
#include "app_assert.h"
#else
#define app_assert_status(sc) (void)(sc)
#endif

#ifndef SL_BT_INVALID_CONNECTION_HANDLE
#define SL_BT_INVALID_CONNECTION_HANDLE 0xFFu
#endif

/******************************************************************************
 *                           STATIC STATE
 ******************************************************************************/
static uint8_t tarang_advertising_set_handle = 0xFFu;
static uint8_t tarang_ble_conn_handle = SL_BT_INVALID_CONNECTION_HANDLE;

/* Per-characteristic CCCD tracking */
static bool tarang_ble_telemetry_notifications_enabled = false;
static bool tarang_ble_health_notifications_enabled     = false;
static bool tarang_ble_ecg_waveform_notifications_enabled = false;

/* Periodic dispatch timers */
static uint32_t last_telemetry_notify_ms = 0;
static uint32_t last_health_notify_ms    = 0;

/******************************************************************************
 *                     HEALTH PACKET BUILDER
 ******************************************************************************/
void tarang_ble_build_health_packet(tarang_pipeline_t *pipeline, tarang_health_packet_t *pkt)
{
  (void)pipeline;
  if (!pkt) return;
  memset(pkt, 0, sizeof(tarang_health_packet_t));

  uint32_t now_ms = tarang_now_ms();
  pkt->uptime_s = now_ms / 1000u;

  /* ECG lead-off / signal quality */
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

  /* PPG finger presence & I2C failures */
#if TARANG_ENABLE_PPG
  pkt->ppg_finger_present = tarang_ppg_is_finger_present() ? 1 : 0;
  uint32_t ppg_fails = tarang_ppg_get_consecutive_failures();
  pkt->i2c_failure_count = (uint8_t)(ppg_fails > 255 ? 255 : ppg_fails);
#else
  pkt->ppg_finger_present = 0;
  pkt->i2c_failure_count = 0;
#endif

  /* IMU health */
#if TARANG_ENABLE_IMU
  pkt->imu_ok = tarang_imu_is_healthy() ? 1 : 0;
#else
  pkt->imu_ok = 0;
#endif

  /* DSP overflows */
#if TARANG_ENABLE_ECG
  if (pipeline) {
    uint32_t ovf = tarang_dsp_get_pending_overflow_count(&pipeline->dsp);
    pkt->dsp_overflow_count = (uint8_t)(ovf > 255 ? 255 : ovf);
  }
#endif

  pkt->ble_rssi = 127; /* 127 = unavailable without active RSSI query */
  pkt->battery_pct = 255; /* 255 = unavailable / no hardware fuel gauge */
  pkt->status_flags = 0;
  pkt->fw_version_packed = (uint16_t)((TARANG_FW_VERSION_MAJOR << 8) | TARANG_FW_VERSION_MINOR);
}

/******************************************************************************
 *                       PUBLIC API
 ******************************************************************************/
void tarang_ble_init(void)
{
  printf("[BLE] Module initialized.\r\n");
}

bool tarang_ble_is_connected(void)
{
  return (tarang_ble_conn_handle != SL_BT_INVALID_CONNECTION_HANDLE);
}

bool tarang_ble_is_notifications_enabled(void)
{
  return tarang_ble_telemetry_notifications_enabled;
}

/******************************************************************************
 *                     PERIODIC BLE DISPATCH
 ******************************************************************************/
void tarang_ble_process(tarang_pipeline_t *pipeline)
{
#if defined(SL_CATALOG_BLUETOOTH_PRESENT)
  if (pipeline == NULL) {
    return;
  }

  bool connected = (tarang_ble_conn_handle != SL_BT_INVALID_CONNECTION_HANDLE);
  if (!connected) return;

  uint32_t now_ms = tarang_now_ms();

  /* ── 1. Clinical Telemetry Notification ───────────────────────────── */
  if (tarang_ble_telemetry_notifications_enabled) {
    bool should_send = tarang_pipeline_should_send_event(pipeline);

    /* 1 Hz fallback periodic telemetry when no events pending */
    if (!should_send && (now_ms - last_telemetry_notify_ms >= 1000u)) {
      should_send = true;
    }

    if (should_send) {
      tarang_event_packet_t pkt;
      tarang_pipeline_get_packet(pipeline, &pkt);

      sl_status_t sc = sl_bt_gatt_server_send_notification(
          tarang_ble_conn_handle,
          gattdb_telemetry_data,
          sizeof(pkt),
          (const uint8_t *)&pkt);

      if (sc == SL_STATUS_OK) {
        /* Clear pending flags ONLY after successful dispatch */
        last_telemetry_notify_ms = now_ms;
        pipeline->beat_telemetry_pending = false;
        pipeline->engine.rhythm_changed = false;
        pipeline->engine.significant_event = false;

        printf("[BLE] Telemetry TX: HR=%u rhythm=0x%02X class=%u\r\n",
               (unsigned)pkt.current_hr, (unsigned)pkt.rhythm_flags, (unsigned)pkt.beat_class);
      } else {
        printf("[BLE] Telemetry TX fail: 0x%04lX\r\n", (unsigned long)sc);
      }
    }
  }

  /* ── 2. Device Health Notification (1 Hz periodic) ────────────────── */
  if (tarang_ble_health_notifications_enabled) {
    if (now_ms - last_health_notify_ms >= 1000u) {
      tarang_health_packet_t hpkt;
      tarang_ble_build_health_packet(pipeline, &hpkt);

      sl_status_t sc = sl_bt_gatt_server_send_notification(
          tarang_ble_conn_handle,
          gattdb_device_health,
          sizeof(hpkt),
          (const uint8_t *)&hpkt);

      if (sc == SL_STATUS_OK) {
        last_health_notify_ms = now_ms;
      } else {
        printf("[BLE] Health TX fail: 0x%04lX\r\n", (unsigned long)sc);
      }
    }
  }

  /* ── 3. ECG Waveform Notification (25 Hz — Phase 2 implementation) ─ */
  /* TODO: Tap from DSP morph_ring and dispatch 10-sample chunks here.
   * tarang_ble_ecg_waveform_notifications_enabled tracks the CCCD. */

#else
  (void)pipeline;
#endif
}

/******************************************************************************
 *        BLUETOOTH STACK EVENT HANDLER (called by Simplicity SDK)
 ******************************************************************************/
#if defined(SL_CATALOG_BLUETOOTH_PRESENT)
void sl_bt_on_event(sl_bt_msg_t *evt)
{
  sl_status_t sc;

  switch (SL_BT_MSG_ID(evt->header)) {

    /* ── System Boot: configure security, create adv set, start 30s window ── */
    case sl_bt_evt_system_boot_id:
    {
      printf("TARANG BLE BOOT OK\r\n");

      /* Configure Security Manager: Just Works (No I/O) auto-accept bonding */
      sc = sl_bt_sm_configure(0x00, sl_bt_sm_io_capability_noinputnooutput);
      app_assert_status(sc);

      /* Allow bonding requests */
      sc = sl_bt_sm_set_bondable_mode(1);
      app_assert_status(sc);

      /* Create advertising set */
      sc = sl_bt_advertiser_create_set(&tarang_advertising_set_handle);
      app_assert_status(sc);

      /* ── Dynamic Device Name: TARANG-<last 4 hex of MAC> ──────────── */
      {
        bd_addr address;
        uint8_t addr_type;
        sc = sl_bt_system_get_identity_address(&address, &addr_type);
        if (sc == SL_STATUS_OK) {
          char name_buf[16];
          snprintf(name_buf, sizeof(name_buf), "TARANG-%02X%02X",
                   address.addr[1], address.addr[0]);
          sl_bt_gatt_server_write_attribute_value(
              gattdb_device_name, 0, strlen(name_buf), (const uint8_t *)name_buf);
          printf("[BLE] Device name: %s\r\n", name_buf);
        }
      }

      /* Generate advertising data */
      sc = sl_bt_legacy_advertiser_generate_data(
          tarang_advertising_set_handle,
          sl_bt_advertiser_general_discoverable);
      app_assert_status(sc);

      /* ── Continuous Connectable Advertising ──────────────────────── */
      sc = sl_bt_advertiser_set_timing(
          tarang_advertising_set_handle,
          160,    /* min interval: 160 × 0.625ms = 100ms */
          160,    /* max interval: 160 × 0.625ms = 100ms */
          0,      /* DURATION: 0 = Continuous until connected */
          0);     /* max events: 0 = no event count limit */
      app_assert_status(sc);

      /* Start connectable advertising */
      sc = sl_bt_legacy_advertiser_start(
          tarang_advertising_set_handle,
          sl_bt_legacy_advertiser_connectable);
      app_assert_status(sc);

      printf("[BLE] Connectable advertising started (Ready for RPi Hub).\r\n");
      break;
    }

    /* ── Connection Opened: record handle & reset timers ──── */
    case sl_bt_evt_connection_opened_id:
    {
      tarang_ble_conn_handle = evt->data.evt_connection_opened.connection;
      printf("[BLE] Connection opened! Handle=0x%02X (Waiting for Central SMP request)\r\n",
             tarang_ble_conn_handle);

      /* Reset dispatch timers */
      last_telemetry_notify_ms = 0;
      last_health_notify_ms    = 0;
      break;
    }

    /* ── Connection Closed: clear state, restart advertising ── */
    case sl_bt_evt_connection_closed_id:
      printf("[BLE] Connection closed. Restarting advertising...\r\n");
      tarang_ble_conn_handle = SL_BT_INVALID_CONNECTION_HANDLE;
      tarang_ble_telemetry_notifications_enabled = false;
      tarang_ble_health_notifications_enabled     = false;
      tarang_ble_ecg_waveform_notifications_enabled = false;

      sc = sl_bt_legacy_advertiser_generate_data(
          tarang_advertising_set_handle,
          sl_bt_advertiser_general_discoverable);
      app_assert_status(sc);

      sc = sl_bt_advertiser_set_timing(
          tarang_advertising_set_handle,
          160, 160, 0, 0);
      app_assert_status(sc);

      sc = sl_bt_legacy_advertiser_start(
          tarang_advertising_set_handle,
          sl_bt_legacy_advertiser_connectable);
      app_assert_status(sc);
      break;

    /* ── Bonding Confirm: auto-accept Just Works pairing ──────────── */
    case sl_bt_evt_sm_confirm_bonding_id:
    {
      uint8_t conn = evt->data.evt_sm_confirm_bonding.connection;
      printf("[BLE][SM] Confirming bonding request on connection=0x%02X (Just Works)\r\n", conn);
      sc = sl_bt_sm_bonding_confirm(conn, 1);
      if (sc != SL_STATUS_OK) {
        printf("[BLE][SM] Bonding confirm failed: 0x%04lX\r\n", (unsigned long)sc);
      }
      break;
    }

    case sl_bt_evt_sm_bonded_id:
    {
      uint8_t conn = evt->data.evt_sm_bonded.connection;
      uint8_t bond = evt->data.evt_sm_bonded.bonding;
      printf("[BLE][SM] SUCCESS: Device bonded! Connection=0x%02X BondHandle=0x%02X\r\n", conn, bond);

      /* Log security level for verification */
      uint8_t sec_mode;
      sc = sl_bt_sm_get_bonding_details(bond, NULL, NULL, &sec_mode, NULL);
      if (sc == SL_STATUS_OK) {
        printf("[BLE][SM] Security mode: %u (1=unauthenticated, 2=authenticated)\r\n", sec_mode);
      }
      break;
    }

    case sl_bt_evt_sm_bonding_failed_id:
    {
      uint8_t conn = evt->data.evt_sm_bonding_failed.connection;
      uint16_t reason = evt->data.evt_sm_bonding_failed.reason;
      printf("[BLE][SM] WARNING: Bonding failed! Connection=0x%02X Reason=0x%04X\r\n", conn, (unsigned)reason);
      break;
    }

    /* ── CCCD Write: track per-characteristic notification subscription ── */
    case sl_bt_evt_gatt_server_characteristic_status_id:
    {
      uint16_t characteristic = evt->data.evt_gatt_server_characteristic_status.characteristic;
      uint8_t status_flags = evt->data.evt_gatt_server_characteristic_status.status_flags;
      uint16_t client_config = evt->data.evt_gatt_server_characteristic_status.client_config_flags;

      if (status_flags & sl_bt_gatt_server_client_config) {
        bool enabled = (client_config != sl_bt_gatt_disable);

        printf("[BLE] CCCD write: char=0x%04X config=0x%04X -> %s\r\n",
               (unsigned)characteristic, (unsigned)client_config,
               enabled ? "ENABLED" : "DISABLED");

        /* Clinical Telemetry CCCD */
        if (characteristic == gattdb_telemetry_data) {
          tarang_ble_telemetry_notifications_enabled = enabled;
          printf("[BLE] %s: Clinical Telemetry notifications\r\n",
                 enabled ? "SUBSCRIBED" : "UNSUBSCRIBED");
        }
        /* Device Health CCCD */
        else if (characteristic == gattdb_device_health) {
          tarang_ble_health_notifications_enabled = enabled;
          printf("[BLE] %s: Device Health notifications\r\n",
                 enabled ? "SUBSCRIBED" : "UNSUBSCRIBED");
        }
#if defined(gattdb_ecg_waveform)
        /* ECG Waveform CCCD */
        else if (characteristic == gattdb_ecg_waveform) {
          tarang_ble_ecg_waveform_notifications_enabled = enabled;
          printf("[BLE] %s: ECG Waveform notifications\r\n",
                 enabled ? "SUBSCRIBED" : "UNSUBSCRIBED");
        }
#endif
      }
      break;
    }

    default:
      break;
  }
}
#endif
