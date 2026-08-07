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
 * Checks ping-pong half-buffer flags and prints data when ready.
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

#ifdef __cplusplus
}
#endif

#endif /* TARANG_ECG_H */
