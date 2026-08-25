/***************************************************************************//**
 * @file tarang_nlms.h
 * @brief Streaming, IMU-referenced NLMS motion-artifact cancellation.
 ******************************************************************************/
#ifndef TARANG_NLMS_H
#define TARANG_NLMS_H

#include <stdbool.h>
#include <stdint.h>
#include "tarang_constants.h"

#ifdef __cplusplus
extern "C" {
#endif

#define TARANG_NLMS_TAPS             32u
#define TARANG_NLMS_REFERENCE_COUNT  3u

typedef enum {
  TARANG_NLMS_BYPASS_NONE = 0,
  TARANG_NLMS_BYPASS_DISABLED,
  TARANG_NLMS_BYPASS_WARMUP,
  TARANG_NLMS_BYPASS_IMU_STALE,
  TARANG_NLMS_BYPASS_NO_MOTION,
  TARANG_NLMS_BYPASS_SAFETY_COOLDOWN
} tarang_nlms_bypass_reason_t;

typedef struct {
  float weights[TARANG_NLMS_REFERENCE_COUNT][TARANG_NLMS_TAPS];
  float delay[TARANG_NLMS_REFERENCE_COUNT][TARANG_NLMS_TAPS];
  float gravity[TARANG_NLMS_REFERENCE_COUNT];
  float current_reference[TARANG_NLMS_REFERENCE_COUNT];
  float correction_lpf;
  float previous_ecg;
  float input_power_ema;
  float residual_power_ema;
  float correction_power_ema;
  uint32_t samples_processed;
  uint32_t active_samples;
  uint32_t adaptation_samples;
  uint32_t saturation_count;
  uint32_t safety_reset_count;
  uint16_t motion_mg;
  uint16_t suppression_pct_x10;
  uint16_t cooldown_samples;
  uint16_t warmup_samples;
  uint16_t degradation_samples;
  uint8_t delay_index;
  bool active;
  tarang_nlms_bypass_reason_t bypass_reason;
  float mean_motion_ema;
  float mean_artifact_ema;
  float cov_motion_ecg_ema;
  float var_motion_ema;
  float var_artifact_ema;
  float correlation_r;
  int16_t correlation_r_x1000;
} tarang_nlms_state_t;

void tarang_nlms_init(tarang_nlms_state_t *state);
void tarang_nlms_reset(tarang_nlms_state_t *state);

float tarang_nlms_process_sample(tarang_nlms_state_t *state,
                                 float ecg_centered,
                                 const tarang_imu_sample_t *imu,
                                 bool imu_fresh,
                                 bool apply_cleaning);

const char *tarang_nlms_bypass_reason_string(
    tarang_nlms_bypass_reason_t reason);

int16_t tarang_nlms_get_correlation_r_x1000(const tarang_nlms_state_t *state);

#ifdef __cplusplus
}
#endif

#endif /* TARANG_NLMS_H */
