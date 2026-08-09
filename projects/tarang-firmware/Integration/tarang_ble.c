/***************************************************************************//**
 * @file tarang_ble.c
 * @brief TARANG Bluetooth Low Energy (BLE) Telemetry Implementation.
 ******************************************************************************/
#include "tarang_ble.h"
#include <stdio.h>

#if defined(SL_COMPONENT_CATALOG_PRESENT)
#include "sl_component_catalog.h"
#endif

#if defined(SL_CATALOG_BLUETOOTH_PRESENT)
#include "sl_bt_api.h"
#include "gatt_db.h"
#endif

#if !defined(gattdb_telemetry_data) && defined(gattdb_device_status)
#define gattdb_telemetry_data gattdb_device_status
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

  /* ── BLE telemetry notification ─────────────────────────────────── */
  if (tarang_ble_telemetry_notifications_enabled &&
      tarang_ble_conn_handle != SL_BT_INVALID_CONNECTION_HANDLE &&
      tarang_pipeline_should_send_event(pipeline)) {

    tarang_event_packet_t pkt;
    tarang_pipeline_get_packet(pipeline, &pkt);

    sl_status_t sc = sl_bt_gatt_server_send_notification(
        tarang_ble_conn_handle,
        gattdb_telemetry_data,
        sizeof(pkt),
        (const uint8_t *)&pkt);

    if (sc != SL_STATUS_OK) {
      printf("[BLE] Notification failed: 0x%04lX\r\n", (unsigned long)sc);
    } else {
      printf("[BLE] Telemetry notification sent! (16 bytes, HR=%u rhythm=0x%02X)\r\n",
             (unsigned)pkt.current_hr, (unsigned)pkt.rhythm_flags);
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

    case sl_bt_evt_gatt_server_characteristic_status_id:
      if (evt->data.evt_gatt_server_characteristic_status.status_flags
          == sl_bt_gatt_server_client_config) {

        if (evt->data.evt_gatt_server_characteristic_status.characteristic
            == gattdb_telemetry_data) {

          if (evt->data.evt_gatt_server_characteristic_status.client_config_flags
              == sl_bt_gatt_notification) {
            printf("[BLE] Client subscribed to telemetry notifications!\r\n");
            tarang_ble_telemetry_notifications_enabled = true;
          } else {
            printf("[BLE] Client unsubscribed from telemetry notifications.\r\n");
            tarang_ble_telemetry_notifications_enabled = false;
          }
        }
      }
      break;

    default:
      break;
  }
}
#endif
