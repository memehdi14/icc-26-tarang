/***************************************************************************//**
 * @file tarang_nlms.c
 * @brief Streaming three-axis NLMS implementation for TARANG ECG.
 ******************************************************************************/

#include "tarang_nlms.h"

#include <math.h>
#include <stddef.h>
#include <string.h>

#define NLMS_ACCEL_LSB_PER_G        16384.0f
#define NLMS_GRAVITY_ALPHA          0.0100f
#define NLMS_STEP_SIZE              0.0100f
#define NLMS_REGULARIZATION         0.0001f
#define NLMS_MOTION_GATE_G          0.0150f
#define NLMS_QRS_DERIVATIVE_GUARD   350.0f
#define NLMS_MAX_CORRECTION_COUNTS  700.0f
#define NLMS_MAX_WEIGHT             2400.0f
#define NLMS_CORRECTION_LPF_ALPHA   0.2300f
#define NLMS_POWER_ALPHA            0.0050f
#define NLMS_WARMUP_SAMPLES         TARANG_ECG_SAMPLE_RATE_HZ
#define NLMS_DEGRADATION_LIMIT      50u
#define NLMS_COOLDOWN_SAMPLES       (2u * TARANG_ECG_SAMPLE_RATE_HZ)

static float nlms_clampf(float value, float low, float high)
{
  if (value < low) return low;
  if (value > high) return high;
  return value;
}

static void nlms_clear_adaptive_state(tarang_nlms_state_t *state)
{
  memset(state->weights, 0, sizeof(state->weights));
  memset(state->delay, 0, sizeof(state->delay));
  state->delay_index = 0u;
  state->correction_lpf = 0.0f;
  state->degradation_samples = 0u;
}

void tarang_nlms_init(tarang_nlms_state_t *state)
{
  if (state == NULL) return;
  memset(state, 0, sizeof(*state));
  state->bypass_reason = TARANG_NLMS_BYPASS_WARMUP;
}

void tarang_nlms_reset(tarang_nlms_state_t *state)
{
  tarang_nlms_init(state);
}

float tarang_nlms_process_sample(tarang_nlms_state_t *state,
                                 float ecg_centered,
                                 const tarang_imu_sample_t *imu,
                                 bool imu_fresh,
                                 bool apply_cleaning)
{
  if (state == NULL) return ecg_centered;
  state->samples_processed++;

  if (state->warmup_samples < NLMS_WARMUP_SAMPLES) {
    if (imu != NULL && imu_fresh) {
      float accel[3] = {(float)imu->ax, (float)imu->ay, (float)imu->az};
      if (state->warmup_samples == 0u) {
        memcpy(state->gravity, accel, sizeof(accel));
      } else {
        for (uint8_t axis = 0u; axis < TARANG_NLMS_REFERENCE_COUNT; axis++) {
          state->gravity[axis] += NLMS_GRAVITY_ALPHA
                                  * (accel[axis] - state->gravity[axis]);
        }
      }
      state->warmup_samples++;
    }
    state->active = false;
    state->bypass_reason = apply_cleaning
        ? TARANG_NLMS_BYPASS_WARMUP : TARANG_NLMS_BYPASS_DISABLED;
    state->previous_ecg = ecg_centered;
    return ecg_centered;
  }

  if (imu != NULL && imu_fresh) {
    float accel[3] = {(float)imu->ax, (float)imu->ay, (float)imu->az};
    for (uint8_t axis = 0u; axis < TARANG_NLMS_REFERENCE_COUNT; axis++) {
      state->gravity[axis] += NLMS_GRAVITY_ALPHA
                              * (accel[axis] - state->gravity[axis]);
      state->current_reference[axis] =
          (accel[axis] - state->gravity[axis]) / NLMS_ACCEL_LSB_PER_G;
    }
  }

  float motion_sq = 0.0f;
  for (uint8_t axis = 0u; axis < TARANG_NLMS_REFERENCE_COUNT; axis++) {
    float reference = imu_fresh ? state->current_reference[axis] : 0.0f;
    state->delay[axis][state->delay_index] = reference;
    motion_sq += reference * reference;
  }
  float motion_g = sqrtf(motion_sq);
  float motion_mg = motion_g * 1000.0f;
  state->motion_mg = (uint16_t)nlms_clampf(motion_mg, 0.0f, 65535.0f);

  if (state->cooldown_samples > 0u) state->cooldown_samples--;

  bool motion_present = motion_g >= NLMS_MOTION_GATE_G;
  bool can_apply = apply_cleaning && imu_fresh && motion_present
                   && state->cooldown_samples == 0u;

  if (!apply_cleaning) {
    state->bypass_reason = TARANG_NLMS_BYPASS_DISABLED;
  } else if (!imu_fresh) {
    state->bypass_reason = TARANG_NLMS_BYPASS_IMU_STALE;
  } else if (!motion_present) {
    state->bypass_reason = TARANG_NLMS_BYPASS_NO_MOTION;
  } else if (state->cooldown_samples > 0u) {
    state->bypass_reason = TARANG_NLMS_BYPASS_SAFETY_COOLDOWN;
  } else {
    state->bypass_reason = TARANG_NLMS_BYPASS_NONE;
  }

  float estimated_artifact = 0.0f;
  float reference_power = NLMS_REGULARIZATION;
  for (uint8_t axis = 0u; axis < TARANG_NLMS_REFERENCE_COUNT; axis++) {
    for (uint8_t tap = 0u; tap < TARANG_NLMS_TAPS; tap++) {
      uint8_t index = (uint8_t)((state->delay_index + TARANG_NLMS_TAPS - tap)
                                % TARANG_NLMS_TAPS);
      float x = state->delay[axis][index];
      estimated_artifact += state->weights[axis][tap] * x;
      reference_power += x * x;
    }
  }

  float cleaned = ecg_centered;
  float correction = 0.0f;
  if (can_apply) {
    state->correction_lpf += NLMS_CORRECTION_LPF_ALPHA
                             * (estimated_artifact - state->correction_lpf);
    correction = nlms_clampf(state->correction_lpf,
                             -NLMS_MAX_CORRECTION_COUNTS,
                             NLMS_MAX_CORRECTION_COUNTS);
    if (correction != state->correction_lpf) state->saturation_count++;
    cleaned = ecg_centered - correction;
    state->active_samples++;

    float derivative = fabsf(ecg_centered - state->previous_ecg);
    bool qrs_guard = derivative >= NLMS_QRS_DERIVATIVE_GUARD;
    if (!qrs_guard && reference_power > NLMS_REGULARIZATION) {
      float normalized_error = NLMS_STEP_SIZE * cleaned / reference_power;
      for (uint8_t axis = 0u; axis < TARANG_NLMS_REFERENCE_COUNT; axis++) {
        for (uint8_t tap = 0u; tap < TARANG_NLMS_TAPS; tap++) {
          uint8_t index = (uint8_t)((state->delay_index + TARANG_NLMS_TAPS - tap)
                                    % TARANG_NLMS_TAPS);
          float updated = state->weights[axis][tap]
                          + normalized_error * state->delay[axis][index];
          state->weights[axis][tap] = nlms_clampf(updated,
                                                  -NLMS_MAX_WEIGHT,
                                                  NLMS_MAX_WEIGHT);
        }
      }
      state->adaptation_samples++;
    }
  } else {
    state->correction_lpf = 0.0f;
  }

  state->input_power_ema += NLMS_POWER_ALPHA
      * (ecg_centered * ecg_centered - state->input_power_ema);
  state->residual_power_ema += NLMS_POWER_ALPHA
      * (cleaned * cleaned - state->residual_power_ema);
  state->correction_power_ema += NLMS_POWER_ALPHA
      * (correction * correction - state->correction_power_ema);

  if (can_apply && state->input_power_ema > 100.0f
      && state->residual_power_ema > state->input_power_ema * 1.5f) {
    state->degradation_samples++;
  } else if (state->degradation_samples > 0u) {
    state->degradation_samples--;
  }

  if (state->degradation_samples >= NLMS_DEGRADATION_LIMIT) {
    nlms_clear_adaptive_state(state);
    state->cooldown_samples = NLMS_COOLDOWN_SAMPLES;
    state->safety_reset_count++;
    state->bypass_reason = TARANG_NLMS_BYPASS_SAFETY_COOLDOWN;
    cleaned = ecg_centered;
    can_apply = false;
  }

  if (state->input_power_ema > 1.0f
      && state->residual_power_ema < state->input_power_ema) {
    float suppression = 1000.0f
        * (state->input_power_ema - state->residual_power_ema)
        / state->input_power_ema;
    state->suppression_pct_x10 = (uint16_t)nlms_clampf(suppression,
                                                        0.0f, 1000.0f);
  } else {
    state->suppression_pct_x10 = 0u;
  }

  state->active = can_apply;
  state->previous_ecg = ecg_centered;
  state->delay_index = (uint8_t)((state->delay_index + 1u)
                                 % TARANG_NLMS_TAPS);
  return nlms_clampf(cleaned, -2048.0f, 2047.0f);
}

const char *tarang_nlms_bypass_reason_string(
    tarang_nlms_bypass_reason_t reason)
{
  switch (reason) {
    case TARANG_NLMS_BYPASS_NONE: return "active";
    case TARANG_NLMS_BYPASS_DISABLED: return "disabled";
    case TARANG_NLMS_BYPASS_WARMUP: return "warmup";
    case TARANG_NLMS_BYPASS_IMU_STALE: return "imu_stale";
    case TARANG_NLMS_BYPASS_NO_MOTION: return "no_motion";
    case TARANG_NLMS_BYPASS_SAFETY_COOLDOWN: return "safety_cooldown";
    default: return "unknown";
  }
}
