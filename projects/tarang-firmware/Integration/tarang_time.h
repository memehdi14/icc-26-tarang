/***************************************************************************//**
 * @file tarang_time.h
 * @brief TARANG shared clock utility — single source of timestamps.
 *
 * Every sensor module timestamps against tarang_now_us(), nowhere else.
 * Do NOT call sl_sleeptimer_get_tick_count() directly in any sensor module
 * and do your own conversion — one function, one conversion, or you'll get
 * silent unit-mismatch bugs.
 *
 * Target : EFR32MG26B510F3200IM48 (Series 2, Cortex-M33)
 ******************************************************************************/
#ifndef TARANG_TIME_H
#define TARANG_TIME_H

#include <stdint.h>
#include "sl_sleeptimer.h"

#ifdef __cplusplus
extern "C" {
#endif

/***************************************************************************//**
 * @brief Get current time in microseconds from a single monotonic clock.
 *
 * All sensor ISRs and process functions MUST use this for timestamps.
 * Using sl_sleeptimer directly elsewhere risks unit-mismatch bugs.
 ******************************************************************************/
static inline uint64_t tarang_now_us(void)
{
  uint32_t ticks = sl_sleeptimer_get_tick_count();
  return (uint64_t)sl_sleeptimer_tick_to_ms(ticks) * 1000ULL
       + ((uint64_t)(ticks % sl_sleeptimer_get_timer_frequency())
          * 1000000ULL / sl_sleeptimer_get_timer_frequency()) % 1000ULL;
}

/***************************************************************************//**
 * @brief Simplified: get current time in milliseconds.
 *
 * For telemetry and BLE event timestamps where µs precision is unnecessary.
 ******************************************************************************/
static inline uint32_t tarang_now_ms(void)
{
  return sl_sleeptimer_tick_to_ms(sl_sleeptimer_get_tick_count());
}

#ifdef __cplusplus
}
#endif

#endif /* TARANG_TIME_H */
