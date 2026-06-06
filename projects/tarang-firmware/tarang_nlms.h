/***************************************************************************//**
 * @file tarang_nlms.h
 * @brief TARANG IMU-assisted NLMS adaptive filter for ECG motion artifact
 *        removal.
 *
 * Target: EFR32MG26 (Cortex-M33). Static allocation only.
 *
 * Algorithm:
 *   Reference signal  x[n] = accel_magnitude (from IMU)
 *   Error (clean ECG) e[n] = ECG[n] - W^T · X[n]
 *   Weight update      W[n+1] = W[n] + (mu / (X^T·X + eps)) · e[n] · X[n]
 *
 * Author: Team Ocelleon — IoT Challenge 2026
 ******************************************************************************/
#ifndef TARANG_NLMS_H
#define TARANG_NLMS_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ─── Compile-time configuration ─────────────────────────────────────────── */

/** Maximum filter taps (statically allocated). 32 taps covers motion
 *  artifacts at 1–10 Hz with 250 Hz ECG sample rate (~128 ms window). */
#define TARANG_NLMS_MAX_TAPS         32u

/** Default NLMS step size (mu) in Q15 fixed-point.
 *  0.01 × 32768 ≈ 328. Conservative for stable convergence. */
#define TARANG_NLMS_DEFAULT_MU_Q15   328

/** Regularization constant (epsilon) to prevent division by zero.
 *  In Q15: small value scaled to prevent instability. */
#define TARANG_NLMS_DEFAULT_EPS_Q15  1u

/** Motion magnitude threshold (raw units) below which NLMS adaptation
 *  is frozen to avoid distorting the ECG during rest. */
#define TARANG_NLMS_MOTION_GATE_THRESH  200

/** ICM-20648 accel sensitivity: ±2g range → 16384 LSB/g */
#define TARANG_IMU_ACCEL_SENSITIVITY    16384

/** Number of IMU accel samples in one SPI burst frame.
 *  ICM-20648 burst: 14 bytes per sample set (AX,AY,AZ,TEMP,GX,GY,GZ).
 *  512 bytes / 14 ≈ 36 sample sets. We use the first 32 to align with
 *  the ECG decimation ratio (256 ECG / 8 = 32 IMU subsamples). */
#define TARANG_NLMS_IMU_SAMPLES_PER_FRAME  32u

/* ─── Filter state ───────────────────────────────────────────────────────── */

typedef struct {
  /* Adaptive filter weights (Q15 fixed-point) */
  int32_t weights[TARANG_NLMS_MAX_TAPS];

  /* Reference signal delay line (circular buffer) */
  int16_t delay_line[TARANG_NLMS_MAX_TAPS];
  uint8_t delay_idx;

  /* Configuration */
  uint16_t mu_q15;           /**< Step size in Q15 */
  uint16_t eps_q15;          /**< Regularization in Q15 */
  uint8_t  num_taps;         /**< Active filter order (≤ MAX_TAPS) */

  /* Runtime state */
  bool     is_converged;     /**< True once error power drops below threshold */
  uint32_t samples_processed;
  int32_t  error_power_avg;  /**< Running average of |e[n]|² (Q15) */
} tarang_nlms_state_t;

/* ─── Parsed IMU acceleration (from raw SPI burst) ───────────────────────── */

typedef struct {
  int16_t ax;    /**< Accel X in raw LSB (±2g = ±16384) */
  int16_t ay;    /**< Accel Y */
  int16_t az;    /**< Accel Z */
} tarang_imu_accel_t;

/* ─── API ────────────────────────────────────────────────────────────────── */

/***************************************************************************//**
 * Initialize the NLMS filter state.
 *
 * @param[out] state   Filter state to initialize.
 * @param[in]  num_taps Number of filter taps (clamped to TARANG_NLMS_MAX_TAPS).
 * @param[in]  mu_q15  Step size in Q15. Use 0 for default.
 * @param[in]  eps_q15 Regularization in Q15. Use 0 for default.
 ******************************************************************************/
void tarang_nlms_init(tarang_nlms_state_t *state,
                      uint8_t num_taps,
                      uint16_t mu_q15,
                      uint16_t eps_q15);

/***************************************************************************//**
 * Reset filter weights and delay line to zero (e.g. after prolonged rest).
 *
 * @param[in,out] state  Filter state to reset.
 ******************************************************************************/
void tarang_nlms_reset(tarang_nlms_state_t *state);

/***************************************************************************//**
 * Parse raw ICM-20648 SPI burst into acceleration samples.
 *
 * ICM-20648 register 0x3B burst format (big-endian):
 *   [AX_H, AX_L, AY_H, AY_L, AZ_H, AZ_L, TEMP_H, TEMP_L,
 *    GX_H, GX_L, GY_H, GY_L, GZ_H, GZ_L]  — 14 bytes per sample set
 *
 * @param[in]  imu_spi    Raw SPI burst data (512 bytes).
 * @param[out] accel_out  Array to receive parsed accel samples.
 * @param[in]  max_samples  Maximum samples to parse.
 * @return     Number of samples actually parsed.
 ******************************************************************************/
uint8_t tarang_nlms_parse_imu_accel(const uint8_t *imu_spi,
                                    tarang_imu_accel_t *accel_out,
                                    uint8_t max_samples);

/***************************************************************************//**
 * Compute accelerometer magnitude from parsed sample.
 * Uses integer square root — no libm dependency.
 *
 * @param[in]  accel  Parsed acceleration sample.
 * @return     Magnitude in raw LSB units.
 ******************************************************************************/
uint16_t tarang_nlms_accel_magnitude(const tarang_imu_accel_t *accel);

/***************************************************************************//**
 * Process one ECG frame through the NLMS adaptive filter.
 *
 * For each ECG sample, the corresponding IMU reference is interpolated
 * from the parsed accel magnitude array (32 IMU → 256 ECG via 8× repeat).
 *
 * When motion is below the gate threshold, adaptation is frozen and the
 * ECG is passed through unmodified to avoid distortion during rest.
 *
 * @param[in,out] state       NLMS filter state.
 * @param[in]     ecg_raw     Raw ECG samples (256 × uint16_t).
 * @param[in]     imu_spi     Raw IMU SPI burst (512 bytes). NULL if no IMU.
 * @param[in]     imu_valid   True if IMU data is valid this frame.
 * @param[out]    ecg_clean   Cleaned ECG output (256 × int16_t).
 * @param[out]    snr_out     Estimated SNR improvement (0–1000 scale). May be NULL.
 ******************************************************************************/
void tarang_nlms_process_frame(tarang_nlms_state_t *state,
                               const uint16_t *ecg_raw,
                               const uint8_t  *imu_spi,
                               bool            imu_valid,
                               int16_t        *ecg_clean,
                               uint16_t       *snr_out);

#ifdef __cplusplus
}
#endif

#endif /* TARANG_NLMS_H */
