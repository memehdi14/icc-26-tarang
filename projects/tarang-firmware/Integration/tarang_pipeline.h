/***************************************************************************//**
 * @file tarang_pipeline.h
 * @brief TARANG Pipeline Orchestrator — public API.
 *
 * Connects the 4-tier hierarchy:
 *   Tier 0: DSP (Pan-Tompkins, bandpass/notch, z-score) → beat heuristics
 *   Tier 1: Gate CNN (~8KB Int8) — only if suspicious
 *   Tier 2: SV Head CNN (~18KB Int8) — only if Gate says abnormal
 *   Tier 3: Clinical Event Engine (every beat)
 *
 * IMU-assisted NLMS runs ahead of the morphology/QRS DSP. It is guarded by
 * motion, timestamp-freshness, QRS-preservation, and degradation fallbacks.
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
#include "tarang_nlms.h"

#ifdef __cplusplus
extern "C" {
#endif

/*******************************************************************************
 * Pipeline State
 ******************************************************************************/

#ifdef __cplusplus
extern "C" {
#endif

/*******************************************************************************
 * Pipeline State
 ******************************************************************************/
/* Max pending beats queued for deferred AI processing */
#define TARANG_MAX_PENDING_BEATS  4
#define TARANG_EVENT_SNIPPET_SAMPLES \
  (4u * TARANG_ECG_SAMPLE_RATE_HZ)
#define TARANG_EVENT_ANNOTATION_HISTORY 16u

typedef struct {
  float    waveform[TARANG_BEAT_WINDOW_SIZE];
  uint32_t timestamp_ms;
  uint32_t r_peak_sample_idx;
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
  int16_t  correlation_r_x1000;
} tarang_pipeline_beat_telemetry_t;

typedef struct {
  uint32_t sample_idx;
  uint8_t  beat_class;
  uint8_t  confidence;
} tarang_pipeline_annotation_history_t;

typedef struct {
  uint16_t offset_ms;
  uint8_t  beat_class;
  uint8_t  confidence;
} tarang_pipeline_event_annotation_t;


typedef struct {
  /* DSP state (entire streaming Pan-Tompkins chain) */
  tarang_dsp_state_t       dsp;

  /* Causally aligned IMU-referenced motion cancellation. */
  tarang_nlms_state_t      nlms;

  /* EMA Baseline tracker for raw ADC (Issues 1.1, 1.2, 1.3: fc=0.15Hz @ 250Hz -> alpha=0.00377) */
  float                    ecg_baseline_ema;
  bool                     ecg_baseline_initialized;

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

  /* Suspicious-rate monitor for the last 30 beats. It only disables Tier-1
   * when TARANG_ENABLE_AI_CIRCUIT_BREAKER is explicitly enabled after
   * overload and clinical-validation testing. */
  #define CIRCUIT_BREAKER_WINDOW 30
  uint8_t  circuit_breaker_ring[CIRCUIT_BREAKER_WINDOW];
  uint8_t  circuit_breaker_idx;
  uint8_t  circuit_breaker_count;
  uint8_t  circuit_breaker_suspicious_count;
  bool     circuit_breaker_tripped;

  /* Deferred AI beat queue — filled during ECG processing,
   * drained by tarang_pipeline_run_deferred() in the super loop */
  tarang_pending_beat_t pending_beats[TARANG_MAX_PENDING_BEATS];
  uint8_t  pending_head;
  uint8_t  pending_tail;
  uint8_t  pending_count;

  /* Clean, normalized ECG history used to build real event snapshots. */
  int16_t  clean_ecg_ring[TARANG_EVENT_SNIPPET_SAMPLES];
  uint16_t clean_ecg_head;
  uint16_t clean_ecg_count;

  /* Beat labels associated with absolute DSP sample indices. */
  tarang_pipeline_annotation_history_t
      annotation_history[TARANG_EVENT_ANNOTATION_HISTORY];
  uint8_t annotation_head;
  uint8_t annotation_count;

  /* One-shot debug event consumed immediately after each ECG sample. */
  tarang_pipeline_beat_telemetry_t latest_beat_telemetry;
  uint32_t current_rpeak_sample_idx;
  uint32_t latest_sample_timestamp_ms;
  bool     beat_telemetry_pending;

  /* Pipeline initialized flag */
  bool     initialized;

  /* AI Tier Evaluation Running Counters */
  uint32_t tier0_evals;
  uint32_t tier1_fires;
  uint32_t tier2_fires;
  uint32_t class_n_count;
  uint32_t class_s_count;
  uint32_t class_v_count;
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
 * This also initializes the TFLite Micro interpreters, validates model input
 * tensor shapes, and allocates the tensor arenas.
 *
 * @param[out] pipeline  Pipeline state.
 ******************************************************************************/
void tarang_pipeline_init(tarang_pipeline_t *pipeline);
tarang_pipeline_t *tarang_pipeline_get_instance(void);

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
 * ECG DMA processing only queues complete beat windows. This function drains
 * the queue and runs Tier 0-3 outside the acquisition loop.
 *
 * @param[in,out] pipeline  Pipeline state.
 ******************************************************************************/
void tarang_pipeline_run_deferred(tarang_pipeline_t *pipeline);

bool tarang_pipeline_snippet_ready(
    const tarang_pipeline_t *pipeline);

uint16_t tarang_pipeline_copy_event_snippet(
    const tarang_pipeline_t *pipeline,
    int16_t *samples,
    uint16_t max_samples,
    uint32_t *start_sample_idx);

uint8_t tarang_pipeline_copy_event_annotations(
    const tarang_pipeline_t *pipeline,
    uint32_t start_sample_idx,
    uint16_t sample_count,
    tarang_pipeline_event_annotation_t *annotations,
    uint8_t max_annotations);

const tarang_nlms_state_t *tarang_pipeline_get_nlms_state(
    const tarang_pipeline_t *pipeline);

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
