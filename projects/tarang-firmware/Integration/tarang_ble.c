/***************************************************************************//**
 * @file tarang_ble.c
 * @brief TARANG Bluetooth Low Energy (BLE) Telemetry Implementation.
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

#if !defined(gattdb_telemetry_data) && defined(gattdb_device_status)
#define gattdb_telemetry_data gattdb_device_status
#elif !defined(gattdb_telemetry_data) && defined(gattdb_system_id)
#define gattdb_telemetry_data gattdb_system_id
#elif !defined(gattdb_telemetry_data)
#define gattdb_telemetry_data 21
#endif

#if defined(SL_CATALOG_APP_ASSERT_PRESENT)
#include "app_assert.h"
#else
#define app_assert_status(sc) (void)(sc)
#endif

#ifndef SL_BT_INVALID_CONNECTION_HANDLE
#define SL_BT_INVALID_CONNECTION_HANDLE 0xFFu
#endif

static uint8_t tarang_advertising_set_handle = 0xFFu;
static uint8_t tarang_ble_conn_handle = SL_BT_INVALID_CONNECTION_HANDLE;
static bool tarang_ble_telemetry_notifications_enabled = false;

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

void tarang_ble_process(tarang_pipeline_t *pipeline)
{
#if defined(SL_CATALOG_BLUETOOTH_PRESENT)
  if (pipeline == NULL) {
    return;
  }

  static uint32_t last_periodic_notify_ms = 0;

  bool connected = (tarang_ble_conn_handle != SL_BT_INVALID_CONNECTION_HANDLE);
  bool notif_enabled = tarang_ble_telemetry_notifications_enabled;

  /* Only compute time-based fallback when BLE is actually connected and
   * subscribed — no point tracking the timer when nobody is listening.
   * This also prevents the flag-clear path from running at boot when
   * last_periodic_notify_ms=0 and now_ms >= 1000ms after init delays. */
  bool should_send = tarang_pipeline_should_send_event(pipeline);
  if (connected && notif_enabled && !should_send) {
    uint32_t now_ms = tarang_now_ms();
    if (now_ms - last_periodic_notify_ms >= 1000u) {
      should_send = true; /* 1 Hz fallback periodic telemetry packet */
    }
  }

  /* ── BLE telemetry notification ─────────────────────────────────── */
  if (notif_enabled &&
      connected &&
      should_send) {

    uint32_t now_ms = tarang_now_ms();
    last_periodic_notify_ms = now_ms;

    tarang_event_packet_t pkt;
    tarang_pipeline_get_packet(pipeline, &pkt);

    sl_status_t sc = sl_bt_gatt_server_send_notification(
        tarang_ble_conn_handle,
        gattdb_telemetry_data,
        sizeof(pkt),
        (const uint8_t *)&pkt);

    if (sc != SL_STATUS_OK) {
      printf("[BLE] Notification failed: 0x%04lX (will retry on next tick)\r\n", (unsigned long)sc);
    } else {
      /* Clear pending flags ONLY when successfully dispatched over BLE */
      pipeline->beat_telemetry_pending = false;
      pipeline->engine.rhythm_changed = false;
      pipeline->engine.significant_event = false;

      printf("[BLE] Telemetry notification sent! (16 bytes, HR=%u rhythm=0x%02X class=%u)\r\n",
             (unsigned)pkt.current_hr, (unsigned)pkt.rhythm_flags, (unsigned)pkt.beat_class);
    }
  }
#else
  (void)pipeline;
#endif
}

#if defined(SL_CATALOG_BLUETOOTH_PRESENT)
/***************************************************************************//**
 * Bluetooth stack event handler.
 * Called automatically by Simplicity SDK event dispatcher when BLE events occur.
 ******************************************************************************/
void sl_bt_on_event(sl_bt_msg_t *evt)
{
  sl_status_t sc;

  switch (SL_BT_MSG_ID(evt->header)) {

    case sl_bt_evt_system_boot_id:
      printf("TARANG BLE BOOT OK\r\n");

      /* Configure Security Manager for bonding & encryption with Just Works (No I/O) */
      sc = sl_bt_sm_configure(0x08, sl_bt_sm_io_capability_noinputnooutput);
      app_assert_status(sc);

      /* Allow bonding requests */
      sc = sl_bt_sm_set_bondable_mode(1);
      app_assert_status(sc);

      /* Create advertising set */
      sc = sl_bt_advertiser_create_set(&tarang_advertising_set_handle);
      app_assert_status(sc);

      /* Generate advertising data */
      sc = sl_bt_legacy_advertiser_generate_data(
          tarang_advertising_set_handle,
          sl_bt_advertiser_general_discoverable);
      app_assert_status(sc);

      /* 100 ms advertising interval (160 * 0.625ms = 100ms) */
      sc = sl_bt_advertiser_set_timing(
          tarang_advertising_set_handle,
          160,
          160,
          0,
          0);
      app_assert_status(sc);

      /* Start connectable advertising */
      sc = sl_bt_legacy_advertiser_start(
          tarang_advertising_set_handle,
          sl_bt_legacy_advertiser_connectable);
      app_assert_status(sc);
      break;

    case sl_bt_evt_connection_opened_id:
      tarang_ble_conn_handle = evt->data.evt_connection_opened.connection;
      printf("[BLE] Connection opened! Handle=0x%02X. Requesting 20ms interval...\r\n",
             tarang_ble_conn_handle);

      /* Request 20 ms connection interval (16 * 1.25ms = 20ms),
         0 slave latency, 1 second supervision timeout */
      sc = sl_bt_connection_set_parameters(
          tarang_ble_conn_handle,
          16,
          16,
          0,
          100,
          0,
          0xFFFF);
      app_assert_status(sc);
      break;

    case sl_bt_evt_connection_closed_id:
      printf("[BLE] Connection closed. Restarting advertising...\r\n");
      tarang_ble_conn_handle = SL_BT_INVALID_CONNECTION_HANDLE;
      tarang_ble_telemetry_notifications_enabled = false;

      /* Restart advertising */
      sc = sl_bt_legacy_advertiser_generate_data(
          tarang_advertising_set_handle,
          sl_bt_advertiser_general_discoverable);
      app_assert_status(sc);

      sc = sl_bt_legacy_advertiser_start(
          tarang_advertising_set_handle,
          sl_bt_legacy_advertiser_connectable);
      app_assert_status(sc);
      break;

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
      break;
    }

    case sl_bt_evt_sm_bonding_failed_id:
    {
      uint8_t conn = evt->data.evt_sm_bonding_failed.connection;
      uint16_t reason = evt->data.evt_sm_bonding_failed.reason;
      printf("[BLE][SM] WARNING: Bonding failed! Connection=0x%02X Reason=0x%04X\r\n", conn, (unsigned)reason);
      break;
    }

    case sl_bt_evt_gatt_server_characteristic_status_id:
    {
      uint16_t characteristic = evt->data.evt_gatt_server_characteristic_status.characteristic;
      uint8_t status_flags = evt->data.evt_gatt_server_characteristic_status.status_flags;
      uint16_t client_config_flags = evt->data.evt_gatt_server_characteristic_status.client_config_flags;

      printf("[BLE] Characteristic status change: char=0x%04X status=0x%02X config=0x%04X (telemetry char=0x%04X)\r\n",
             (unsigned)characteristic, (unsigned)status_flags, (unsigned)client_config_flags,
             (unsigned)gattdb_telemetry_data);

      if (status_flags & sl_bt_gatt_server_client_config) {
        if (characteristic == gattdb_telemetry_data || characteristic == (gattdb_telemetry_data - 1)) {
          if (client_config_flags != sl_bt_gatt_disable) {
            printf("[BLE] SUCCESS: Client subscribed to telemetry notifications!\r\n");
            tarang_ble_telemetry_notifications_enabled = true;
          } else {
            printf("[BLE] Client unsubscribed from telemetry notifications.\r\n");
            tarang_ble_telemetry_notifications_enabled = false;
          }
        }
      }
      break;
    }

    default:
      break;
  }
}
#endif
