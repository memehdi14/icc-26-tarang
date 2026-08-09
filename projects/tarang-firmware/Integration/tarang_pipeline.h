/***************************************************************************//**
 * @file tarang_pipeline.h
 * @brief TARANG Pipeline Orchestrator — public API.
 *
 * Connects the 4-tier hierarchy:
 *   Tier 0: DSP (Pan-Tompkins, NLMS, z-score) → beat_suspicious heuristics
 *   Tier 1: Gate CNN (~8KB Int8) — only if suspicious
 *   Tier 2: SV Head CNN (~18KB Int8) — only if Gate says abnormal
 *   Tier 3: Clinical Event Engine (every beat)
 *
 * Mirrors the reference project pattern from
 * aiml_soc_anomaly_detection_efr32_baremetal:
 *   app.c → anomaly_detection.h/.cc → imu.h/.cc + predictor.h/.cc
 *   app.c → tarang_pipeline.h/.c → tarang_{ecg,imu,ppg}.h/.c
 *                                 + tarang_clinical_engine.h/.c
 *
 * Target : EFR32MG26B510F3200IM48 (Series 2, Cortex-M33)
 ******************************************************************************/
#ifndef TARANG_PIPELINE_H
#define TARANG_PIPELINE_H

#include <stdint.h>
#include <stdbool.h>
#include "tarang_constants.h"
#include "tarang_clinical_engine.h"
#include "tarang_dsp.h"

#ifdef __cplusplus
extern "C" {
#endif

/*******************************************************************************
 * Pipeline State
 ******************************************************************************/
/* Max pending beats queued for deferred AI processing */
#define TARANG_MAX_PENDING_BEATS  4

typedef struct {
  float    waveform[TARANG_BEAT_WINDOW_SIZE];
  uint32_t timestamp_ms;
  uint16_t rr_interval_ms;
  uint8_t  signal_quality;
  bool     suspicious;
} tarang_pending_beat_t;

typedef struct {
  uint32_t timestamp_ms;
  uint32_t r_peak_sample_idx;
  uint16_t rr_interval_ms;
  uint16_t local_hr_bpm_x10;
  uint8_t  signal_quality;
  int16_t  gate_probability_x1000; /* -1 when Gate did not run */
  int16_t  sv_p_v_x1000;           /* -1 when SV Head did not run */
  int16_t  sv_p_s_x1000;           /* -1 when SV Head did not run */
  uint8_t  beat_class;
  uint8_t  confidence;
  uint8_t  rhythm_flags;
  uint8_t  current_hr;
  uint16_t sdnn_ms;
  uint16_t rmssd_ms;
  uint8_t  prr50_pct;
} tarang_pipeline_beat_telemetry_t;

typedef struct {
  /* DSP state (entire streaming Pan-Tompkins chain) */
  tarang_dsp_state_t       dsp;

  /* Clinical engine instance */
  tarang_clinical_engine_t engine;

  /* Diagnostic counters (Section 6.9) */
  tarang_diagnostics_t     diag;

  /* RR interval tracking for Tier-0 heuristics */
  uint32_t last_rpeak_ms;
  uint16_t rr_history[5];        /* last 5 RR for mean/std */
  uint8_t  rr_history_count;

  /* Beat counter for gating statistics */
  uint32_t total_beats;
  uint32_t suspicious_beats;
  uint32_t gate_passed_beats;

  /* Deferred AI beat queue — filled during ECG processing,
   * drained by tarang_pipeline_run_deferred() in the super loop */
  tarang_pending_beat_t pending_beats[TARANG_MAX_PENDING_BEATS];
  uint8_t  pending_head;
  uint8_t  pending_tail;
  uint8_t  pending_count;

  /* One-shot debug event consumed immediately after each ECG sample. */
  tarang_pipeline_beat_telemetry_t latest_beat_telemetry;
  uint32_t current_rpeak_sample_idx;
  uint32_t latest_sample_timestamp_ms;
  bool     beat_telemetry_pending;

  /* Pipeline initialized flag */
  bool     initialized;
} tarang_pipeline_t;

/*******************************************************************************
 * Public API
 ******************************************************************************/

/***************************************************************************//**
 * @brief Initialize the pipeline. Sets up Clinical Engine, clears counters.
 *
 * @note Call AFTER sensor inits (ECG, IMU, PPG) are complete.
 *       Call BEFORE the main super-loop starts processing.
 *
 * In Phase B, this will also initialize TFLite Micro interpreter,
 * validate model input tensor shape, and allocate the tensor arena.
 *
 * @param[out] pipeline  Pipeline state.
 ******************************************************************************/
void tarang_pipeline_init(tarang_pipeline_t *pipeline);

/***************************************************************************//**
 * @brief Process one detected R-peak through the full 4-tier pipeline.
 *
 * Called by the DSP layer whenever Pan-Tompkins detects an R-peak.
 * Runs Tier-0 heuristics → Tier-1/2 CNN (if suspicious) → Tier-3 Engine.
 *
 * @param[in,out] pipeline         Pipeline state.
 * @param[in]     timestamp_ms     R-peak timestamp from tarang_now_ms().
 * @param[in]     beat_window_130  DSP-processed morphology signal,
 *                                 130 samples (65 pre-R + 65 post-R).
 *                                 NULL if DSP not yet ported (Phase A).
 * @param[in]     signal_quality   Signal quality index (0-255).
 ******************************************************************************/
void tarang_pipeline_on_rpeak(tarang_pipeline_t *pipeline,
                               uint32_t timestamp_ms,
                               const float *beat_window_130,
                               uint8_t signal_quality);

/***************************************************************************//**
 * @brief Check if a BLE event packet should be sent.
 *
 * Returns true if rhythm_flags changed or a significant event occurred
 * (couplet, triplet, V-run, VT). Caller should then call
 * tarang_pipeline_get_packet() to retrieve the packet.
 *
 * @param[in,out] pipeline  Pipeline state.
 * @return true if an event packet should be sent.
 ******************************************************************************/
bool tarang_pipeline_should_send_event(tarang_pipeline_t *pipeline);

/***************************************************************************//**
 * @brief Build and retrieve the 16-byte BLE event packet.
 *
 * @param[in]  pipeline  Pipeline state.
 * @param[out] pkt       Filled event packet.
 ******************************************************************************/
void tarang_pipeline_get_packet(const tarang_pipeline_t *pipeline,
                                 tarang_event_packet_t *pkt);

/***************************************************************************//**
 * @brief Get a const pointer to the diagnostic counters.
 *
 * @param[in] pipeline  Pipeline state.
 * @return Pointer to diagnostics struct.
 ******************************************************************************/
/***************************************************************************//**
 * @brief Process one raw ECG ADC sample through DSP + ML + Clinical Engine.
 *
 * THIS IS THE MAIN ENTRY POINT. Call this at 250Hz from app_process_action()
 * with each raw ADC value from the IADC DMA buffer.
 *
 * Internally runs:
 *   1. Full DSP chain (bandpass, normalize, Pan-Tompkins R-peak detection)
 *   2. If beat detected: Tier-0 heuristics → Tier-1 Gate → Tier-2 SV
 *   3. Always: Tier-3 Clinical Event Engine
 *
 * @param[in,out] pipeline  Pipeline state.
 * @param[in]     raw_adc   Raw 24-bit ADC value from IADC DMA buffer.
 * @param[in]     timestamp_ms  Current sample time. Beat timing is corrected
 *                              internally from the DSP R-peak sample index.
 ******************************************************************************/
void tarang_pipeline_process_ecg_sample(tarang_pipeline_t *pipeline,
                                         uint32_t raw_adc,
                                         uint32_t timestamp_ms);

/***************************************************************************//**
 * @brief Run deferred AI inference on any queued beats.
 *
 * Call this in the super loop AFTER all sensor _process() calls.
 * This drains the pending beat queue and runs Tier-1/2 CNN inference
 * without blocking ECG/PPG/IMU sample collection.
 *
 * @param[in,out] pipeline  Pipeline state.
 ******************************************************************************/
void tarang_pipeline_run_deferred(tarang_pipeline_t *pipeline);

const tarang_dsp_debug_sample_t *tarang_pipeline_get_debug_sample(
    const tarang_pipeline_t *pipeline);

bool tarang_pipeline_take_beat_telemetry(
    tarang_pipeline_t *pipeline,
    tarang_pipeline_beat_telemetry_t *telemetry);

/***************************************************************************//**
 * @brief Get a const pointer to the diagnostic counters.
 *
 * @param[in] pipeline  Pipeline state.
 * @return Pointer to diagnostics struct.
 ******************************************************************************/
const tarang_diagnostics_t *tarang_pipeline_get_diag(
    const tarang_pipeline_t *pipeline);

#ifdef __cplusplus
}
#endif

#endif /* TARANG_PIPELINE_H */
