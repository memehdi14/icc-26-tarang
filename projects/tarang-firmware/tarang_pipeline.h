/***************************************************************************//**
 * @file tarang_pipeline.h
 * @brief TARANG synchronized physiological frame pipeline — types and handoffs.
 *
 * Target: EFR32MG26B210F1024IM48 (Series 2). emlib only; no heap/RTOS.
 ******************************************************************************/
#ifndef TARANG_PIPELINE_H
#define TARANG_PIPELINE_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ─── Acquisition geometry (must match app.c LDMA descriptors) ───────────── */
#define TARANG_ECG_SAMPLES_PER_FRAME  256u
#define TARANG_IMU_SPI_FRAME_BYTES    512u
#define TARANG_PPG_SAMPLES_PER_FRAME  32u

/* ─── Buffer ownership (DMA / CPU contract) ─────────────────────────────── */
typedef enum {
  BUFFER_STATE_FREE = 0,
  BUFFER_STATE_DMA_OWNED,
  BUFFER_STATE_READY_FOR_AI,
  BUFFER_STATE_PROCESSING
} buffer_state_t;

/* ─── Deferred event engine (bitmask, ISR posts / EM0 dispatches) ───────── */
typedef enum {
  TARANG_EVT_NONE       = 0u,
  TARANG_EVT_ACQ_FRAME  = (1u << 0),  /* ECG LDMA block complete */
  TARANG_EVT_PROCESS    = (1u << 1),  /* DSP / NLMS / motion cancel */
  TARANG_EVT_AI         = (1u << 2),  /* TFLM inference window */
  TARANG_EVT_BLE        = (1u << 3),  /* Anomaly telemetry (Kartik) */
  TARANG_EVT_FAULT      = (1u << 4)
} tarang_event_mask_t;

/* ─── Synchronization flags (per frame) ─────────────────────────────────── */
typedef enum {
  TARANG_SYNC_ECG_VALID = (1u << 0),
  TARANG_SYNC_IMU_VALID = (1u << 1),
  TARANG_SYNC_PPG_VALID = (1u << 2),
  TARANG_SYNC_COMMITTED = (1u << 3)
} tarang_sync_flag_t;

/* ─── Fault flags (per frame + global diagnostics) ──────────────────────── */
typedef enum {
  TARANG_FAULT_NONE              = 0u,
  TARANG_FAULT_DMA_OVERRUN       = (1u << 0),
  TARANG_FAULT_STALE_FRAME       = (1u << 1),
  TARANG_FAULT_IMU_TIMEOUT       = (1u << 2),
  TARANG_FAULT_PPG_TIMEOUT       = (1u << 3),
  TARANG_FAULT_IMU_WHOAMI        = (1u << 4),
  TARANG_FAULT_OWNERSHIP         = (1u << 5),
  TARANG_FAULT_I2C_STUCK         = (1u << 6)
} tarang_fault_flag_t;

/***************************************************************************//**
 * LETIMER-domain timestamp + sequence (LFXO / 32.768 kHz tick domain).
 ******************************************************************************/
typedef struct {
  uint32_t letimer_ticks;      /**< LETIMER0 counter snapshot at frame edge */
  uint32_t frame_sequence;     /**< Monotonic frame index (ECG block rate) */
  uint32_t sample_time_us;     /**< Derived: sequence * 1024000 / 250 us */
} synchronization_metadata_t;

/***************************************************************************//**
 * Per-frame metadata header (ownership + quality + fusion readiness).
 ******************************************************************************/
typedef struct {
  buffer_state_t          state;
  uint8_t                 pool_index;
  uint8_t                 ownership_token;
  synchronization_metadata_t sync;
  uint32_t                sync_flags;
  uint32_t                fault_flags;
  uint16_t                ecg_quality;   /**< 0..1000, hooks for SNR estimator */
  uint16_t                imu_quality;
  uint16_t                ppg_quality;
} frame_metadata_t;

/***************************************************************************//**
 * Unified physiological payload (zero-copy target for LDMA + sensors).
 ******************************************************************************/
typedef struct {
  uint16_t ecg[TARANG_ECG_SAMPLES_PER_FRAME];
  uint8_t  imu_spi[TARANG_IMU_SPI_FRAME_BYTES];
  uint32_t ppg[TARANG_PPG_SAMPLES_PER_FRAME];
} sensor_payload_t;

/***************************************************************************//**
 * Double-buffered sensor frame matrix entry.
 ******************************************************************************/
typedef struct {
  frame_metadata_t meta;
  sensor_payload_t data;
} sensor_frame_matrix_t;

/***************************************************************************//**
 * Pipeline-wide diagnostic counters (read-only via tarang_diag_get()).
 ******************************************************************************/
typedef struct {
  uint32_t dma_overruns;
  uint32_t stale_frames;
  uint32_t dropped_frames;
  uint32_t sync_faults;
  uint32_t ownership_violations;
  uint32_t imu_timeouts;
  uint32_t ppg_timeouts;
  uint32_t i2c_recoveries;
  uint32_t spi_recoveries;
  uint32_t wdog_feeds;
  uint32_t missed_processing;
  uint32_t sequence_gaps;
} tarang_diagnostics_t;

/* ─── Mehdi — NLMS / TFLM staging (consume READY frames only) ───────────── */
typedef struct {
  const uint16_t *ecg;
  const uint32_t *ppg;
  const uint8_t  *imu_spi;       /**< Raw IMU SPI burst for NLMS reference */
  uint32_t        sync_flags;     /**< Sync flags to check IMU validity */
  uint32_t        sequence;
  uint32_t        timestamp_us;
} tarang_dsp_input_t;

typedef struct {
  float confidence_afib;
  float confidence_pvc;
  float confidence_normal;
  float spo2_percent;
  float heart_rate_bpm;
  int16_t clean_ecg[TARANG_ECG_SAMPLES_PER_FRAME]; /**< NLMS-cleaned ECG */
  uint16_t ecg_snr;              /**< Motion artifact suppression score 0..1000 */
} tarang_dsp_output_t;

void tarang_dsp_process(const tarang_dsp_input_t *in, tarang_dsp_output_t *out);

/* ─── Kartik — IMU motion + BLE anomaly hooks ───────────────────────────── */
typedef struct {
  const uint8_t *imu_spi;
  uint32_t         sequence;
} tarang_imu_input_t;

typedef struct {
  float motion_magnitude;
  bool  is_in_motion;
} tarang_imu_output_t;

void tarang_imu_process(const tarang_imu_input_t *in, tarang_imu_output_t *out);

/** PPG dynamic LED scaling hook (Mehdi / optical team). */
void tarang_ppg_apply_led_scale(uint8_t ir_current, uint8_t red_current);

/** Motion-quality score input for NLMS gating. */
typedef struct {
  float motion_magnitude;
  bool  is_in_motion;
  uint16_t imu_quality;
} tarang_motion_quality_t;

void tarang_motion_quality_score(const tarang_imu_output_t *imu,
                                 tarang_motion_quality_t *quality);

typedef struct {
  uint32_t frame_sequence;
  float    confidence_afib;
  float    confidence_pvc;
  bool     anomaly_detected;
} tarang_ble_anomaly_t;

/** Non-blocking BLE telemetry contract (Kartik). */
typedef struct {
  uint32_t frame_sequence;
  uint32_t timestamp_us;
  uint16_t ecg_sample_count;
  uint8_t  sync_flags;
  uint8_t  fault_flags;
} tarang_ble_telemetry_t;

void tarang_ble_submit_anomaly(const tarang_ble_anomaly_t *pkt);
void tarang_ble_submit_telemetry(const tarang_ble_telemetry_t *pkt);
void tarang_ble_on_radio_wake(void);
void tarang_ble_on_radio_sleep(void);

/** TFLM / MVP staging — Mehdi wires tensor arena here. */
typedef struct {
  const sensor_frame_matrix_t *frame;
  uint8_t                      ownership_token;
} tarang_ai_input_t;

void tarang_ai_process(const tarang_ai_input_t *in);

/* ─── Safe frame API for teammates ──────────────────────────────────────── */
bool tarang_frame_try_acquire_processing(sensor_frame_matrix_t **frame_out,
                                         uint8_t *token_out);
void tarang_frame_release_processing(uint8_t token);

const tarang_diagnostics_t *tarang_diag_get(void);
uint32_t tarang_time_us_from_sequence(uint32_t sequence);

#ifdef __cplusplus
}
#endif

#endif /* TARANG_PIPELINE_H */
