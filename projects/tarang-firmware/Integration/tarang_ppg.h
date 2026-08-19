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

#ifdef __cplusplus
extern "C" {
#endif

#define PPG_BUFFER_SIZE  1024u

typedef struct {
  uint8_t  spo2_pct;
  uint8_t  pulse_rate_bpm;
  uint8_t  signal_quality;
  uint16_t perfusion_index_x100;
  uint32_t window_end_sample;
  bool     finger_present;
  bool     motion_rejected;
  bool     valid;
} tarang_ppg_metrics_t;

/***************************************************************************//**
 * Initialize PPG sensor (MAX30102).
 * Configures: sensor registers, GPIO PC06 interrupt, I2C bus.
 *
 * @note Call GPIOINT_Init() and CMU_ClockEnable(cmuClock_GPIO) BEFORE this.
 ******************************************************************************/
void tarang_ppg_init(void);

/***************************************************************************//**
 * PPG process action — call from app_process_action().
 * Reads FIFO if interrupt has fired. Returns immediately if nothing pending.
 ******************************************************************************/
void tarang_ppg_process(void);

/* Supply the latest high-pass motion magnitude from the IMU in milli-g. */
void tarang_ppg_set_motion_level_mg(uint16_t motion_mg);

/* Copy the latest rolling-window result. Returns true only when valid. */
bool tarang_ppg_get_metrics(tarang_ppg_metrics_t *metrics);

/* ─── Status accessors ──────────────────────────────────────────────────── */
uint32_t tarang_ppg_get_red(void);
uint32_t tarang_ppg_get_ir(void);
uint32_t tarang_ppg_get_sample_count(void);
uint32_t tarang_ppg_get_interrupt_count(void);
bool     tarang_ppg_is_found(void);
bool     tarang_ppg_is_finger_present(void);
uint32_t tarang_ppg_get_consecutive_failures(void);

#ifdef __cplusplus
}
#endif

#endif /* TARANG_PPG_H */
