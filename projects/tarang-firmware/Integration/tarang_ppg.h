/***************************************************************************//**
 * @file tarang_ppg.h
 * @brief TARANG PPG acquisition module — public API.
 *
 * Extracted from Separate Testing/PPG/ppg/app.c (proven on hardware).
 * MAX30102 over I2C (sl_i2cspm_mikroe), interrupt-driven via PC06 GPIO.
 ******************************************************************************/
#ifndef TARANG_PPG_H
#define TARANG_PPG_H

#include <stdint.h>
#include <stdbool.h>
#include "tarang_sensor_health.h"

#ifdef __cplusplus
extern "C" {
#endif

#define PPG_BUFFER_SIZE  1024u

/***************************************************************************//**
 * Initialize PPG sensor (MAX30102).
 * Configures: sensor registers, GPIO PC06 interrupt, I2C bus.
 *
 * @param bus_already_clear  If true, skip the initial i2c_bus_clear()
 *                           (caller already cleared the bus, e.g. app.c).
 *                           Retry-on-failure bus clears are still performed.
 *
 * @note Call GPIOINT_Init() and CMU_ClockEnable(cmuClock_GPIO) BEFORE this.
 ******************************************************************************/
void tarang_ppg_init(bool bus_already_clear);

/***************************************************************************//**
 * PPG process action — call from app_process_action().
 * Reads FIFO if interrupt has fired. Returns immediately if nothing pending.
 ******************************************************************************/
void tarang_ppg_process(void);

/* ─── Status accessors ──────────────────────────────────────────────────── */
uint32_t tarang_ppg_get_red(void);
uint32_t tarang_ppg_get_ir(void);
uint32_t tarang_ppg_get_sample_count(void);
uint32_t tarang_ppg_get_interrupt_count(void);
bool     tarang_ppg_is_found(void);
tarang_sensor_health_t tarang_ppg_get_health(void);
bool     tarang_ppg_is_valid(void);

#ifdef __cplusplus
}
#endif

#endif /* TARANG_PPG_H */
