/***************************************************************************//**
 * @file tarang_pipeline.c
 * @brief TARANG Pipeline Orchestrator — implementation.
 *
 * Connects the 4-tier hierarchy:
 *   Tier 0: DSP heuristics (always-on, pure arithmetic)
 *   Tier 1: Gate CNN (event-driven, only if suspicious)
 *   Tier 2: SV Head CNN (event-driven, only if Gate flags abnormal)
 *   Tier 3: Clinical Event Engine (every beat)
 *
 * ML inference is handled by tarang_ai.cc (C++ TFLite Micro wrapper).
 * This file calls tarang_ai_gate_predict() and tarang_ai_sv_predict()
 * which invoke real INT8-quantized TFLite Micro inference on the MVP.
 *
 * Target : EFR32MG26B510F3200IM48 (Series 2, Cortex-M33 + MVP)
 ******************************************************************************/

#include "tarang_pipeline.h"
#include "tarang_time.h"
#include "tarang_ai.h"
#include <string.h>
#include <stdio.h>
#include <math.h>

/*******************************************************************************
 * Private: last beat cache for packet building
 ******************************************************************************/
static tarang_beat_input_t s_last_beat;

/*******************************************************************************
 * Private: Tier-0 Trigger Heuristics
 *
 * Decides whether to wake the CNN. At rest, >99.9% of beats pass through
 * here as "not suspicious" and the CNN never fires.
 *
 * Checks (Section 2.1, Trigger Heuristics):
 *   1. Prematurity: RR_prev / RR_mean_5 < 0.85
 *   2. RR irregularity: CoV > 0.12 over 30 beats
 *   3. HR extremes: >120 or <45 BPM
 *   4. Compensatory pause: RR_post_ectopic > 1.5 × mean
 *   5. Poor signal quality: SQI < 128
 ******************************************************************************/
static bool beat_is_suspicious(const tarang_pipeline_t *pipeline,
                                uint16_t rr_interval_ms,
                                uint8_t signal_quality)
{
  /* Need at least 2 RR intervals to compute prematurity */
  if (pipeline->rr_history_count < 2) return false;

  /* 1. Prematurity check */
  uint32_t rr_mean_5 = 0;
  uint8_t n = pipeline->rr_history_count;
  for (uint8_t i = 0; i < n; i++) {
    rr_mean_5 += pipeline->rr_history[i];
  }
  rr_mean_5 /= n;

  if (rr_mean_5 > 0) {
    /* rr_interval / rr_mean_5 < 0.85  →  rr_interval * 100 < 85 * rr_mean_5 */
    if ((uint32_t)rr_interval_ms * 100 < 85 * rr_mean_5) {
      return true;
    }
  }

  /* 2. RR irregularity (CoV > 0.12) — simplified: use engine's SDNN/mean */
  if (pipeline->engine.rr_count >= TARANG_RR_WINDOW_SIZE) {
    uint16_t sdnn = pipeline->engine.sdnn_ms;
    uint32_t mean_rr = rr_mean_5;  /* approximate */
    /* CoV > 0.12  →  sdnn * 100 > 12 * mean_rr */
    if (mean_rr > 0 && (uint32_t)sdnn * 100 > 12 * mean_rr) {
      return true;
    }
  }

  /* 3. HR extremes */
  if (pipeline->engine.current_hr > 120) return true;
  if (pipeline->engine.current_hr > 0 && pipeline->engine.current_hr < 45) {
    return true;
  }

  /* 4. Compensatory pause after ectopic */
  if (pipeline->engine.last_beat_class != TARANG_BEAT_N && rr_mean_5 > 0) {
    /* rr_interval > 1.5 × mean  →  rr_interval * 2 > 3 * mean */
    if ((uint32_t)rr_interval_ms * 2 > 3 * rr_mean_5) {
      return true;
    }
  }

  /* 5. Poor signal quality */
  if (signal_quality < TARANG_SQI_MIN) return true;

  return false;  /* All checks pass — likely normal sinus */
}

/*******************************************************************************
 * Private: Tier-1 Gate CNN — REAL TFLite Micro inference
 *
 * Calls tarang_ai_gate_predict() which:
 *   1. Quantizes 130 float ECG samples → INT8 using model's scale/zp
 *   2. Z-score normalizes 4 RR features with training mean/std (rr_scaler.h)
 *   3. Quantizes RR features → INT8
 *   4. Runs interpreter->Invoke() on the Gate CNN (~12.7ms on MVP)
 *   5. Dequantizes INT8 sigmoid output → float P(abnormal)
 *
 * Returns -1.0 if AI not initialized (graceful degradation — all beats
 * classified as N by the heuristic path, Clinical Engine still runs).
 ******************************************************************************/
static float tarang_ai_gate(const float *beat_window_130,
                             const float *rr_features_4)
{
  if (!tarang_ai_is_ready() || beat_window_130 == NULL) {
    /* AI not ready — graceful degradation, classify as normal */
    return 0.0f;
  }
  return tarang_ai_gate_predict(beat_window_130, rr_features_4);
}

/*******************************************************************************
 * Private: Tier-2 SV Head CNN — REAL TFLite Micro inference
 *
 * Calls tarang_ai_sv_predict() which runs the SV Head model:
 *   - Same input shape as Gate (130 ECG + 4 RR)
 *   - TWO independent sigmoid outputs: P(V) and P(S)
 *   - ~10.2ms on MVP
 *
 * P(V) = probability of Ventricular ectopic (PVC) — recall 91.8%
 * P(S) = probability of Supraventricular ectopic (PAC) — F1 ~0.20
 ******************************************************************************/
static void tarang_ai_sv_head(const float *beat_window_130,
                               const float *rr_features_4,
                               float *p_v, float *p_s)
{
  if (!tarang_ai_is_ready() || beat_window_130 == NULL) {
    *p_v = 0.0f;
    *p_s = 0.0f;
    return;
  }
  if (!tarang_ai_sv_predict(beat_window_130, rr_features_4, p_v, p_s)) {
    *p_v = 0.0f;
    *p_s = 0.0f;
  }
}

/*******************************************************************************
 * Private: Compute 4 causal RR features from history
 ******************************************************************************/
static void compute_rr_features(const tarang_pipeline_t *pipeline,
                                 uint16_t rr_interval_ms,
                                 float *features_4)
{
  /* Feature 0: rr_prev_ms */
  features_4[TARANG_RR_FEAT_RR_PREV] = (float)rr_interval_ms;

  /* Feature 1: rr_mean_5_ms */
  uint32_t sum = 0;
  uint8_t n = pipeline->rr_history_count;
  if (n == 0) {
    features_4[TARANG_RR_FEAT_RR_MEAN_5] = (float)rr_interval_ms;
    features_4[TARANG_RR_FEAT_RR_STD_5]  = 0.0f;
    features_4[TARANG_RR_FEAT_LOCAL_HR]  = (rr_interval_ms > 0)
        ? 60000.0f / (float)rr_interval_ms : 0.0f;
    return;
  }

  for (uint8_t i = 0; i < n; i++) {
    sum += pipeline->rr_history[i];
  }
  float mean5 = (float)sum / (float)n;
  features_4[TARANG_RR_FEAT_RR_MEAN_5] = mean5;

  /* Feature 2: rr_std_5_ms */
  float sum_sq = 0.0f;
  for (uint8_t i = 0; i < n; i++) {
    float diff = (float)pipeline->rr_history[i] - mean5;
    sum_sq += diff * diff;
  }
  /* Use sqrtf — acceptable here since this only runs once per beat */
  features_4[TARANG_RR_FEAT_RR_STD_5] = (n > 1)
      ? sqrtf(sum_sq / (float)n) : 0.0f;

  /* Feature 3: local_hr_bpm */
  features_4[TARANG_RR_FEAT_LOCAL_HR] = (mean5 > 0.0f)
      ? 60000.0f / mean5 : 0.0f;
}

/*******************************************************************************
 * Public API
 ******************************************************************************/

void tarang_pipeline_init(tarang_pipeline_t *pipeline)
{
  memset(pipeline, 0, sizeof(tarang_pipeline_t));

  /* Initialize DSP chain (Pan-Tompkins, all filters) */
  tarang_dsp_init(&pipeline->dsp);

  /* Initialize Clinical Event Engine */
  tarang_clinical_engine_init(&pipeline->engine);

  /* Initialize TFLite Micro — load both CNN models */
  bool ai_ok = tarang_ai_init();

  pipeline->initialized = true;

  printf("[PIPELINE] Tarang pipeline initialized.\r\n");
  printf("[PIPELINE] Tier 0: DSP heuristics  — ACTIVE\r\n");
  printf("[PIPELINE] Tier 1: Gate CNN (%lu B) — %s\r\n",
         (unsigned long)tarang_ai_gate_model_size(),
         ai_ok ? "ACTIVE" : "FAILED (degraded mode)");
  printf("[PIPELINE] Tier 2: SV Head (%lu B)  — %s\r\n",
         (unsigned long)tarang_ai_sv_model_size(),
         ai_ok ? "ACTIVE" : "FAILED (degraded mode)");
  printf("[PIPELINE] Tier 3: Clinical Engine — ACTIVE\r\n");
  if (ai_ok) {
    printf("[PIPELINE] Gate arena: %lu bytes, SV arena: %lu bytes\r\n",
           (unsigned long)tarang_ai_gate_arena_size(),
           (unsigned long)tarang_ai_sv_arena_size());
  }
}

void tarang_pipeline_on_rpeak(tarang_pipeline_t *pipeline,
                               uint32_t timestamp_ms,
                               const float *beat_window_130,
                               uint8_t signal_quality)
{
  if (!pipeline->initialized) return;

  /* ── Compute RR interval ────────────────────────────────────────────── */
  uint16_t rr_interval_ms = 0;
  if (pipeline->last_rpeak_ms > 0 && timestamp_ms > pipeline->last_rpeak_ms) {
    uint32_t rr = timestamp_ms - pipeline->last_rpeak_ms;
    rr_interval_ms = (rr > 0xFFFF) ? 0xFFFF : (uint16_t)rr;
  }
  pipeline->last_rpeak_ms = timestamp_ms;

  /* Update RR history (last 5) */
  if (rr_interval_ms > 0) {
    if (pipeline->rr_history_count < 5) {
      pipeline->rr_history[pipeline->rr_history_count++] = rr_interval_ms;
    } else {
      /* Shift left and append */
      for (int i = 0; i < 4; i++) {
        pipeline->rr_history[i] = pipeline->rr_history[i + 1];
      }
      pipeline->rr_history[4] = rr_interval_ms;
    }
  }

  pipeline->total_beats++;
  pipeline->diag.frames_processed++;

  /* ── TIER 0: Heuristic gate ─────────────────────────────────────────── */
  uint8_t beat_class = TARANG_BEAT_N;
  uint8_t confidence = 255;  /* maximum confidence for heuristic-classified N */
  bool suspicious = beat_is_suspicious(pipeline, rr_interval_ms, signal_quality);

  if (suspicious) {
    pipeline->suspicious_beats++;
    pipeline->diag.ai_trigger_count++;

    /* ── TIER 1: Gate CNN ───────────────────────────────────────────── */
    float rr_features[TARANG_RR_FEATURE_COUNT];
    compute_rr_features(pipeline, rr_interval_ms, rr_features);

    uint32_t t0 = tarang_now_ms();
    float gate_prob = tarang_ai_gate(beat_window_130, rr_features);
    uint32_t t1 = tarang_now_ms();
    pipeline->diag.ai_time_us += (t1 - t0) * 1000;

    if (gate_prob > TARANG_GATE_THRESHOLD) {
      pipeline->gate_passed_beats++;

      /* ── TIER 2: SV Head CNN ────────────────────────────────────── */
      float p_v = 0.0f, p_s = 0.0f;
      uint32_t t2 = tarang_now_ms();
      tarang_ai_sv_head(beat_window_130, rr_features, &p_v, &p_s);
      uint32_t t3 = tarang_now_ms();
      pipeline->diag.ai_time_us += (t3 - t2) * 1000;

      if (p_v > TARANG_V_THRESHOLD) {
        beat_class = TARANG_BEAT_V;
        confidence = (uint8_t)(p_v * 255.0f);
      } else if (p_s > TARANG_S_THRESHOLD) {
        beat_class = TARANG_BEAT_S;
        confidence = (uint8_t)(p_s * 255.0f);
      } else {
        /* Gate was wrong — happens, not an error */
        beat_class = TARANG_BEAT_N;
        confidence = 200;
      }
    } else {
      /* Gate rejected — classify as N */
      beat_class = TARANG_BEAT_N;
      confidence = (uint8_t)((1.0f - gate_prob) * 255.0f);
    }
  }
  /* If not suspicious: beat_class = N, confidence = 255 (already set) */

  /* ── TIER 3: Clinical Event Engine (ALWAYS runs) ────────────────────── */
  tarang_beat_input_t beat_input;
  beat_input.timestamp_ms   = timestamp_ms;
  beat_input.beat_class     = beat_class;
  beat_input.confidence     = confidence;
  beat_input.rr_interval_ms = rr_interval_ms;
  beat_input.signal_quality = signal_quality;

  tarang_clinical_engine_process_beat(&pipeline->engine, &beat_input);

  /* Cache for packet building */
  s_last_beat = beat_input;

  /* ── BLE event check ────────────────────────────────────────────────── */
  if (tarang_clinical_engine_rhythm_changed(&pipeline->engine) ||
      tarang_clinical_engine_significant_event(&pipeline->engine)) {
    pipeline->diag.ble_packet_count++;
  }
}

void tarang_pipeline_process_ecg_sample(tarang_pipeline_t *pipeline,
                                         uint32_t raw_adc,
                                         uint32_t timestamp_ms)
{
  (void)timestamp_ms;

  if (!pipeline->initialized) return;

  /* Run the full DSP chain on this single ADC sample.
   * DSP internally manages:
   *   - Morphology bandpass (0.5-40Hz)
   *   - Optional notch (50/60Hz)
   *   - Rolling z-score normalization (30s window)
   *   - QRS bandpass (5-15Hz) → derivative → squaring → MWI
   *   - Adaptive threshold + refractory + search-back
   *   - Detection delay correction (-29 samples)
   *   - Recenter on morphology signal (±15 samples)
   *   - 130-sample beat window extraction + 4 RR features
   *
   * Returns true only when a complete beat is ready (~1 per heartbeat). */
  tarang_beat_output_t dsp_beat;
  bool beat_ready = tarang_dsp_process_sample(&pipeline->dsp, raw_adc, &dsp_beat);

  if (!beat_ready || !dsp_beat.valid) return;

  /* DSP emitted a beat — feed it into the Tier 0→1→2→3 cascade.
   * tarang_pipeline_on_rpeak handles everything from heuristic gating
   * through CNN inference through the Clinical Event Engine. */
  uint32_t rpeak_ms =
      (uint32_t)(((uint64_t)dsp_beat.r_peak_sample_idx * 1000ULL)
                 / TARANG_ECG_SAMPLE_RATE_HZ);

  tarang_pipeline_on_rpeak(pipeline, rpeak_ms,
                            dsp_beat.waveform,
                            dsp_beat.signal_quality);
}

bool tarang_pipeline_should_send_event(tarang_pipeline_t *pipeline)
{
  return pipeline->engine.rhythm_changed || pipeline->engine.significant_event;
}

void tarang_pipeline_get_packet(const tarang_pipeline_t *pipeline,
                                 tarang_event_packet_t *pkt)
{
  tarang_clinical_engine_build_packet(&pipeline->engine, &s_last_beat, pkt);
}

const tarang_diagnostics_t *tarang_pipeline_get_diag(
    const tarang_pipeline_t *pipeline)
{
  return &pipeline->diag;
}
