/***************************************************************************//**
 * @file tarang_ble.h
 * @brief TARANG Bluetooth Low Energy (BLE) Telemetry Module Header.
 ******************************************************************************/
#ifndef TARANG_BLE_H
#define TARANG_BLE_H

#include <stdbool.h>
#include <stdint.h>
#include "tarang_pipeline.h"

#ifdef __cplusplus
extern "C" {
#endif

/***************************************************************************//**
 * @brief Initialize BLE telemetry module.
 ******************************************************************************/
void tarang_ble_init(void);

/***************************************************************************//**
 * @brief Check for pending clinical events and send BLE GATT notification.
 *
 * @param[in,out] pipeline  Pointer to the TARANG pipeline instance.
 ******************************************************************************/
void tarang_ble_process(tarang_pipeline_t *pipeline);

/***************************************************************************//**
 * @brief Check if BLE client is connected.
 ******************************************************************************/
bool tarang_ble_is_connected(void);

/***************************************************************************//**
 * @brief Check if BLE telemetry notifications are enabled by central.
 ******************************************************************************/
bool tarang_ble_is_notifications_enabled(void);

#ifdef __cplusplus
}
#endif

#endif /* TARANG_BLE_H */
