/***************************************************************************//**
 * @file tarang_ecg.h
 * @brief TARANG ECG acquisition module — public API.
 *
 * Extracted from Separate Testing/ECG/july6/app.c (proven on hardware).
 * LETIMER0 → PRS → IADC0 → DMADRV ping-pong → RAM.
 ******************************************************************************/
#ifndef TARANG_ECG_H
#define TARANG_ECG_H

#include <stdint.h>
#include <stdbool.h>
#include "tarang_sensor_health.h"

#ifdef __cplusplus
extern "C" {
#endif

#define ECG_HALF_SAMPLES     64
#define ECG_BUFFER_SIZE      (ECG_HALF_SAMPLES * 2)

/***************************************************************************//**
 * Initialize ECG acquisition chain.
 * Configures: CMU clocks, EMU, LETIMER0, PRS ch2, IADC0, DMADRV ping-pong.
 * Starts LETIMER (acquisition begins immediately).
 *
 * @note Call GPIOINT_Init() and CMU_ClockEnable(cmuClock_GPIO) BEFORE this.
 ******************************************************************************/
void tarang_ecg_init(void);

/***************************************************************************//**
 * ECG process action — call from app_process_action().
 * Checks ping-pong half-buffer flags, feeds samples to DSP pipeline,
 * and optionally prints raw data when streaming is enabled.
 * Returns immediately if no half is ready.
 ******************************************************************************/
void tarang_ecg_process(void);

/* ─── Status accessors ──────────────────────────────────────────────────── */
uint32_t *tarang_ecg_get_buffer(void);
bool      tarang_ecg_half0_ready(void);
bool      tarang_ecg_half1_ready(void);
uint32_t  tarang_ecg_get_sample_count(void);
uint32_t  tarang_ecg_get_overrun_count(void);
uint32_t  tarang_ecg_get_halves_completed(void);
tarang_sensor_health_t tarang_ecg_get_health(void);
bool      tarang_ecg_is_valid(void);
bool      tarang_ecg_is_lead_off(void);
void      tarang_ecg_set_raw_streaming(bool enable);
bool      tarang_ecg_get_raw_streaming(void);

/* AD8232 Hardware Lead-Off GPIO Pin Configuration */
#define TARANG_ECG_LO_PLUS_PORT   gpioPortA
#define TARANG_ECG_LO_PLUS_PIN    4
#define TARANG_ECG_LO_MINUS_PORT  gpioPortA
#define TARANG_ECG_LO_MINUS_PIN   5
#define TARANG_ECG_LO_PINS_WIRED  0   /* 1 if physical LO+/LO- jumper wires installed, 0 for software SQI/rail detection */

#ifdef __cplusplus
}
#endif

#endif /* TARANG_ECG_H */
