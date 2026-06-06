/***************************************************************************//**
 * @file tarang_nlms.c
 * @brief TARANG IMU-assisted NLMS adaptive filter — implementation.
 *
 * Target: EFR32MG26B210F1024IM48 (Cortex-M33). emlib only; no heap.
 *
 * All arithmetic is Q15 fixed-point for weight updates to avoid FPU
 * dependency. The Cortex-M33 DSP extension (saturating MAC) is leveraged
 * via compiler intrinsics where available.
 *
 * Author: Team Ocelleon — IoT Challenge 2026
 ******************************************************************************/

#include "tarang_nlms.h"
#include "tarang_pipeline.h"   /* TARANG_IMU_SPI_FRAME_BYTES, TARANG_ECG_SAMPLES_PER_FRAME */
#include <string.h>

/* ─── Integer square root (no libm) ──────────────────────────────────────── */

/**
 * Integer square root using binary search / Newton's method.
 * Returns floor(sqrt(val)).
 */
static uint32_t isqrt32(uint32_t val)
{
    if (val == 0u) {
        return 0u;
    }

    uint32_t x  = val;
    uint32_t y  = (x + 1u) >> 1u;

    while (y < x) {
        x = y;
        y = (x + (val / x)) >> 1u;
    }
    return x;
}


/* ═══════════════════════════════════════════════════════════════════════════
 * tarang_nlms_init
 * ═══════════════════════════════════════════════════════════════════════════ */
void tarang_nlms_init(tarang_nlms_state_t *state,
                      uint8_t num_taps,
                      uint16_t mu_q15,
                      uint16_t eps_q15)
{
    if (state == NULL) {
        return;
    }

    memset(state, 0, sizeof(*state));

    state->num_taps = (num_taps > TARANG_NLMS_MAX_TAPS)
                        ? TARANG_NLMS_MAX_TAPS
                        : ((num_taps == 0u) ? TARANG_NLMS_MAX_TAPS : num_taps);

    state->mu_q15  = (mu_q15  == 0u) ? TARANG_NLMS_DEFAULT_MU_Q15  : mu_q15;
    state->eps_q15 = (eps_q15 == 0u) ? TARANG_NLMS_DEFAULT_EPS_Q15 : eps_q15;

    state->is_converged      = false;
    state->samples_processed = 0u;
    state->error_power_avg   = 0;
}


/* ═══════════════════════════════════════════════════════════════════════════
 * tarang_nlms_reset
 * ═══════════════════════════════════════════════════════════════════════════ */
void tarang_nlms_reset(tarang_nlms_state_t *state)
{
    if (state == NULL) {
        return;
    }

    memset(state->weights, 0, sizeof(state->weights));
    memset(state->delay_line, 0, sizeof(state->delay_line));
    state->delay_idx         = 0u;
    state->is_converged      = false;
    state->samples_processed = 0u;
    state->error_power_avg   = 0;
}


/* ═══════════════════════════════════════════════════════════════════════════
 * tarang_nlms_parse_imu_accel
 *
 * ICM-20648 register 0x3B burst (big-endian, 14 bytes/sample):
 *   Byte 0: AX_H   Byte 1: AX_L
 *   Byte 2: AY_H   Byte 3: AY_L
 *   Byte 4: AZ_H   Byte 5: AZ_L
 *   Byte 6: TEMP_H Byte 7: TEMP_L
 *   Byte 8: GX_H   Byte 9: GX_L
 *   Byte10: GY_H   Byte11: GY_L
 *   Byte12: GZ_H   Byte13: GZ_L
 *
 * First byte of the SPI burst is the command byte (0xBB) — skip it.
 * ═══════════════════════════════════════════════════════════════════════════ */
uint8_t tarang_nlms_parse_imu_accel(const uint8_t *imu_spi,
                                    tarang_imu_accel_t *accel_out,
                                    uint8_t max_samples)
{
    if ((imu_spi == NULL) || (accel_out == NULL) || (max_samples == 0u)) {
        return 0u;
    }

    /* First byte is the SPI command byte (0xBB = 0x3B | 0x80) — skip */
    const uint8_t *data = &imu_spi[1];
    const uint16_t payload_len = TARANG_IMU_SPI_FRAME_BYTES - 1u;  /* 511 bytes */
    const uint8_t bytes_per_sample = 14u;

    uint8_t available = (uint8_t)(payload_len / bytes_per_sample);
    if (available > max_samples) {
        available = max_samples;
    }

    for (uint8_t i = 0u; i < available; i++) {
        const uint8_t *s = &data[i * bytes_per_sample];

        /* Big-endian to host int16_t */
        accel_out[i].ax = (int16_t)(((uint16_t)s[0] << 8u) | (uint16_t)s[1]);
        accel_out[i].ay = (int16_t)(((uint16_t)s[2] << 8u) | (uint16_t)s[3]);
        accel_out[i].az = (int16_t)(((uint16_t)s[4] << 8u) | (uint16_t)s[5]);
    }

    return available;
}


/* ═══════════════════════════════════════════════════════════════════════════
 * tarang_nlms_accel_magnitude
 *
 * Returns sqrt(ax² + ay² + az²) in raw LSB.
 * Integer square root — no floating point.
 * ═══════════════════════════════════════════════════════════════════════════ */
uint16_t tarang_nlms_accel_magnitude(const tarang_imu_accel_t *accel)
{
    if (accel == NULL) {
        return 0u;
    }

    int32_t ax = (int32_t)accel->ax;
    int32_t ay = (int32_t)accel->ay;
    int32_t az = (int32_t)accel->az;

    uint32_t sum_sq = (uint32_t)(ax * ax) + (uint32_t)(ay * ay) + (uint32_t)(az * az);

    return (uint16_t)isqrt32(sum_sq);
}


/* ─── Single-sample NLMS update (internal) ───────────────────────────────── */

/**
 * Process one sample through the NLMS filter.
 *
 * @param state     Filter state.
 * @param ecg_in    Raw ECG sample (unsigned 16-bit ADC).
 * @param ref_in    Reference signal (IMU accel magnitude).
 * @param adapt     If false, freeze weight adaptation (passthrough mode).
 * @return          Cleaned ECG sample (signed 16-bit).
 */
static int16_t nlms_update_sample(tarang_nlms_state_t *state,
                                  uint16_t ecg_in,
                                  int16_t  ref_in,
                                  bool     adapt)
{
    uint8_t n = state->num_taps;

    /* Push new reference into delay line (circular buffer) */
    state->delay_line[state->delay_idx] = ref_in;

    /* Compute filter output: y = W^T · X  (dot product of weights and delay line) */
    int64_t y_accum = 0;
    for (uint8_t k = 0u; k < n; k++) {
        uint8_t idx = (uint8_t)((state->delay_idx + TARANG_NLMS_MAX_TAPS - k)
                                 % TARANG_NLMS_MAX_TAPS);
        y_accum += (int64_t)state->weights[k] * (int64_t)state->delay_line[idx];
    }

    /* Scale from Q15 accumulator: y_accum is in Q15, shift down */
    int32_t y_est = (int32_t)(y_accum >> 15);

    /* Error signal = desired (ECG) - estimated artifact */
    int32_t ecg_signed = (int32_t)ecg_in - 2048;  /* Center around 0 (12-bit ADC mid-range) */
    int32_t error = ecg_signed - y_est;

    /* Clamp to int16 range */
    if (error > 32767) {
        error = 32767;
    } else if (error < -32768) {
        error = -32768;
    }

    /* Weight update (only if adapting and reference has energy) */
    if (adapt) {
        /* Compute X^T · X (reference power) */
        int64_t x_power = 0;
        for (uint8_t k = 0u; k < n; k++) {
            uint8_t idx = (uint8_t)((state->delay_idx + TARANG_NLMS_MAX_TAPS - k)
                                     % TARANG_NLMS_MAX_TAPS);
            int32_t xk = (int32_t)state->delay_line[idx];
            x_power += (int64_t)(xk * xk);
        }

        /* Normalization: mu / (X^T·X + eps) */
        int64_t norm = x_power + (int64_t)state->eps_q15;

        if (norm > 0) {
            /*
             * Weight update: W[k] += (mu * error * x[k]) / norm
             *
             * To maintain Q15 precision:
             *   delta_w = (mu_q15 * error * x[k]) / norm
             *
             * We compute: numerator = mu_q15 * error (both in natural units)
             *             Then for each tap: delta = (numerator * x[k]) / norm
             */
            int64_t mu_error = (int64_t)state->mu_q15 * error;

            for (uint8_t k = 0u; k < n; k++) {
                uint8_t idx = (uint8_t)((state->delay_idx + TARANG_NLMS_MAX_TAPS - k)
                                         % TARANG_NLMS_MAX_TAPS);
                int64_t delta = (mu_error * (int64_t)state->delay_line[idx]) / norm;

                state->weights[k] += (int32_t)delta;

                /* Clamp weights to prevent overflow */
                if (state->weights[k] > 0x7FFFFF) {
                    state->weights[k] = 0x7FFFFF;
                } else if (state->weights[k] < -0x7FFFFF) {
                    state->weights[k] = -0x7FFFFF;
                }
            }
        }
    }

    /* Advance circular buffer index */
    state->delay_idx = (uint8_t)((state->delay_idx + 1u) % TARANG_NLMS_MAX_TAPS);

    /* Update running stats */
    state->samples_processed++;

    /* Exponential moving average of error power (α = 1/256 for stability) */
    int32_t err_sq = (int32_t)(((int64_t)error * error) >> 8);
    state->error_power_avg = state->error_power_avg
                             - (state->error_power_avg >> 8)
                             + (err_sq >> 8);

    /* Mark converged after sufficient samples with low error */
    if ((state->samples_processed > 512u) && (state->error_power_avg < 1000)) {
        state->is_converged = true;
    }

    return (int16_t)error;
}


/* ═══════════════════════════════════════════════════════════════════════════
 * tarang_nlms_process_frame
 * ═══════════════════════════════════════════════════════════════════════════ */
void tarang_nlms_process_frame(tarang_nlms_state_t *state,
                               const uint16_t *ecg_raw,
                               const uint8_t  *imu_spi,
                               bool            imu_valid,
                               int16_t        *ecg_clean,
                               uint16_t       *snr_out)
{
    if ((state == NULL) || (ecg_raw == NULL) || (ecg_clean == NULL)) {
        return;
    }

    /* Parse IMU accel data if available */
    tarang_imu_accel_t accel_samples[TARANG_NLMS_IMU_SAMPLES_PER_FRAME];
    uint16_t           accel_mag[TARANG_NLMS_IMU_SAMPLES_PER_FRAME];
    uint8_t            imu_count = 0u;
    bool               motion_detected = false;

    if (imu_valid && (imu_spi != NULL)) {
        imu_count = tarang_nlms_parse_imu_accel(
                        imu_spi,
                        accel_samples,
                        TARANG_NLMS_IMU_SAMPLES_PER_FRAME);

        /* Compute magnitudes and detect motion */
        uint32_t max_mag = 0u;
        for (uint8_t i = 0u; i < imu_count; i++) {
            accel_mag[i] = tarang_nlms_accel_magnitude(&accel_samples[i]);
            if (accel_mag[i] > max_mag) {
                max_mag = accel_mag[i];
            }
        }

        /*
         * Subtract 1g gravity baseline (~16384 LSB at ±2g range).
         * Motion is detected when the magnitude deviates significantly
         * from the expected 1g static reading.
         */
        int32_t deviation = (int32_t)max_mag - TARANG_IMU_ACCEL_SENSITIVITY;
        if (deviation < 0) {
            deviation = -deviation;
        }
        motion_detected = ((uint32_t)deviation > TARANG_NLMS_MOTION_GATE_THRESH);
    }

    /* Raw signal power accumulator for SNR estimation */
    int64_t raw_power   = 0;
    int64_t error_power = 0;

    /*
     * Process 256 ECG samples.
     *
     * IMU subsampling: 32 IMU samples map to 256 ECG samples (8:1 ratio).
     * Each IMU reference sample is held for 8 consecutive ECG samples.
     */
    const uint8_t ecg_per_imu = (TARANG_ECG_SAMPLES_PER_FRAME > 0u && imu_count > 0u)
                                ? (uint8_t)(TARANG_ECG_SAMPLES_PER_FRAME / imu_count)
                                : 1u;

    for (uint16_t i = 0u; i < TARANG_ECG_SAMPLES_PER_FRAME; i++) {

        /* Select the IMU reference for this ECG sample */
        int16_t ref = 0;
        if (imu_count > 0u) {
            uint8_t imu_idx = (uint8_t)(i / ecg_per_imu);
            if (imu_idx >= imu_count) {
                imu_idx = imu_count - 1u;
            }

            /*
             * Reference signal: deviation from 1g.
             * Subtract static gravity component so the reference only
             * contains motion-induced acceleration.
             */
            ref = (int16_t)((int32_t)accel_mag[imu_idx] - TARANG_IMU_ACCEL_SENSITIVITY);
        }

        /* Apply NLMS — adapt only when motion is detected */
        ecg_clean[i] = nlms_update_sample(state, ecg_raw[i], ref,
                                          motion_detected);

        /* Accumulate power for SNR computation */
        int32_t ecg_centered = (int32_t)ecg_raw[i] - 2048;
        raw_power   += (int64_t)ecg_centered * ecg_centered;
        error_power += (int64_t)ecg_clean[i] * ecg_clean[i];
    }

    /* Estimate SNR improvement (0–1000 scale) */
    if (snr_out != NULL) {
        if (error_power > 0 && raw_power > error_power) {
            /*
             * SNR improvement ≈ 10 * log10(raw_power / error_power)
             * Approximate: ratio = raw_power / error_power
             * Scale to 0–1000: higher is better artifact suppression.
             *
             * Simple linear approximation:
             *   snr_score = min(1000, (raw - error) * 1000 / raw)
             */
            uint32_t improvement = (uint32_t)(
                ((raw_power - error_power) * 1000) / raw_power
            );
            *snr_out = (improvement > 1000u) ? 1000u : (uint16_t)improvement;
        } else {
            /* No improvement or passthrough */
            *snr_out = 0u;
        }
    }
}
