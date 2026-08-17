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

static int16_t probability_to_x1000(float probability)
{
  if (probability < 0.0f) return -1;
  if (probability > 1.0f) probability = 1.0f;
  return (int16_t)(probability * 1000.0f + 0.5f);
}

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
                                uint8_t signal_quality,
                                const char **reason_out)
{
  if (reason_out) *reason_out = "normal";

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
    if ((uint32_t)rr_interval_ms * TARANG_PREMATURITY_RATIO_DENOM < (uint32_t)TARANG_PREMATURITY_RATIO_NUM * rr_mean_5) {
      if (reason_out) *reason_out = "prematurity";
      return true;
    }
  }

  /* 2. RR irregularity (CoV > 0.12) — simplified: use engine's SDNN/mean */
  if (pipeline->engine.rr_count >= TARANG_RR_WINDOW_SIZE) {
    uint16_t sdnn = pipeline->engine.sdnn_ms;
    uint32_t mean_rr = rr_mean_5;  /* approximate */
    /* CoV > 0.12  →  sdnn * 100 > 12 * mean_rr */
    uint32_t cov_pct = (uint32_t)(TARANG_AFIB_COV_THRESHOLD * 100.0f + 0.5f);
    if (mean_rr > 0 && (uint32_t)sdnn * 100 > cov_pct * mean_rr) {
      if (reason_out) *reason_out = "cov";
      return true;
    }
  }

  /* 3. HR extremes */
  if (pipeline->engine.current_hr > TARANG_TACHYCARDIA_BPM || (pipeline->engine.current_hr > 0 && pipeline->engine.current_hr < TARANG_BRADYCARDIA_BPM)) {
    if (reason_out) *reason_out = "hr_extreme";
    return true;
  }

  /* 4. Compensatory pause after ectopic */
  if (pipeline->engine.last_beat_class != TARANG_BEAT_N && rr_mean_5 > 0) {
    /* rr_interval > 1.5 × mean  →  rr_interval * 2 > 3 * mean */
    if ((uint32_t)rr_interval_ms * TARANG_COMPENSATORY_PAUSE_DENOM > (uint32_t)TARANG_COMPENSATORY_PAUSE_NUM * rr_mean_5) {
      if (reason_out) *reason_out = "pause";
      return true;
    }
  }

  /* 5. Poor signal quality */
  if (signal_quality < TARANG_SQI_MIN) {
    if (reason_out) *reason_out = "sqi";
    return true;
  }

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

static tarang_pipeline_t s_global_pipeline;

tarang_pipeline_t *tarang_pipeline_get_instance(void)
{
  return &s_global_pipeline;
}

void tarang_pipeline_init(tarang_pipeline_t *pipeline)
{
  if (!pipeline) pipeline = &s_global_pipeline;
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
  pipeline->tier0_evals++;
  uint8_t beat_class = TARANG_BEAT_N;
  uint8_t confidence = 255;  /* maximum confidence for heuristic-classified N */
  const char *suspicious_reason = "normal";
  bool suspicious = beat_is_suspicious(pipeline, rr_interval_ms, signal_quality, &suspicious_reason);
  bool gate_ran = false;
  bool sv_ran = false;
  float gate_prob = 0.0f;
  float p_v = 0.0f;
  float p_s = 0.0f;

  /* ── ISSUE-1 FIX: Update circuit breaker state ───────────────────────── */
  /* Update rolling window */
  if (pipeline->circuit_breaker_count < CIRCUIT_BREAKER_WINDOW) {
    pipeline->circuit_breaker_ring[pipeline->circuit_breaker_idx] = suspicious ? 1 : 0;
    if (suspicious) pipeline->circuit_breaker_suspicious_count++;
    pipeline->circuit_breaker_count++;
  } else {
    /* Window full — evict oldest, add newest */
    uint8_t evicted = pipeline->circuit_breaker_ring[pipeline->circuit_breaker_idx];
    if (evicted) pipeline->circuit_breaker_suspicious_count--;
    pipeline->circuit_breaker_ring[pipeline->circuit_breaker_idx] = suspicious ? 1 : 0;
    if (suspicious) pipeline->circuit_breaker_suspicious_count++;
  }
  pipeline->circuit_breaker_idx = (pipeline->circuit_breaker_idx + 1) % CIRCUIT_BREAKER_WINDOW;

  /* Check if circuit breaker should trip (>20% suspicious over 30 beats) */
  if (pipeline->circuit_breaker_count >= CIRCUIT_BREAKER_WINDOW) {
    uint8_t threshold = (CIRCUIT_BREAKER_WINDOW * TARANG_CIRCUIT_BREAKER_MAX_SUSP_PCT) / 100;  /* 20% of 30 = 6 */
    bool should_trip = pipeline->circuit_breaker_suspicious_count > threshold;
    if (should_trip && !pipeline->circuit_breaker_tripped) {
      printf("[PIPELINE] ⚠ Circuit breaker TRIPPED: %u/%u beats suspicious (>20%%). "
             "Disabling Tier-1 CNN until recovery.\r\n",
             pipeline->circuit_breaker_suspicious_count, CIRCUIT_BREAKER_WINDOW);
      pipeline->circuit_breaker_tripped = true;
    } else if (!should_trip && pipeline->circuit_breaker_tripped) {
      printf("[PIPELINE] ✓ Circuit breaker RESET: %u/%u beats suspicious (<20%%). "
             "Re-enabling Tier-1 CNN.\r\n",
             pipeline->circuit_breaker_suspicious_count, CIRCUIT_BREAKER_WINDOW);
      pipeline->circuit_breaker_tripped = false;
    }
  }

  if (suspicious) {
    pipeline->suspicious_beats++;
    pipeline->diag.ai_trigger_count++;

    /* ── TIER 1: Gate CNN (disabled if circuit breaker tripped) ───────── */
    if (!pipeline->circuit_breaker_tripped) {
      float rr_features[TARANG_RR_FEATURE_COUNT];
      compute_rr_features(pipeline, rr_interval_ms, rr_features);

      uint32_t t0 = tarang_now_ms();
      gate_ran = tarang_ai_is_ready() && beat_window_130 != NULL;
      gate_prob = tarang_ai_gate(beat_window_130, rr_features);
      uint32_t t1 = tarang_now_ms();
      pipeline->diag.ai_time_us += (t1 - t0) * 1000;
      pipeline->tier1_fires++;

      printf("[AI] TIER1 gate_prob_x10k=%lu suspicious_reason=%s\r\n",
             (unsigned long)(gate_prob * 10000.0f), suspicious_reason);

      if (gate_prob > TARANG_GATE_THRESHOLD) {
        pipeline->gate_passed_beats++;
        pipeline->tier2_fires++;

        /* ── TIER 2: SV Head CNN ────────────────────────────────── */
        uint32_t t2 = tarang_now_ms();
        sv_ran = tarang_ai_is_ready() && beat_window_130 != NULL;
        tarang_ai_sv_head(beat_window_130, rr_features, &p_v, &p_s);
        uint32_t t3 = tarang_now_ms();
        pipeline->diag.ai_time_us += (t3 - t2) * 1000;

        char class_char = 'N';
        if (p_v > TARANG_V_THRESHOLD) {
          beat_class = TARANG_BEAT_V;
          confidence = (uint8_t)(p_v * 255.0f);
          class_char = 'V';
        } else if (p_s > TARANG_S_THRESHOLD) {
          beat_class = TARANG_BEAT_S;
          confidence = (uint8_t)(p_s * 255.0f);
          class_char = 'S';
        } else {
          /* Gate was wrong — happens, not an error */
          beat_class = TARANG_BEAT_N;
          confidence = 200;
          class_char = 'N';
        }
        printf("[AI] TIER2 p_v_x10k=%lu p_s_x10k=%lu beat_class=%c\r\n",
               (unsigned long)(p_v * 10000.0f), (unsigned long)(p_s * 10000.0f), class_char);
      } else {
        /* Gate rejected — classify as N */
        beat_class = TARANG_BEAT_N;
        confidence = (uint8_t)((1.0f - gate_prob) * 255.0f);
      }
    } else {
      /* Circuit breaker tripped — skip CNN, classify as N via Tier-0 only */
      beat_class = TARANG_BEAT_N;
      confidence = 255;
    }
  }
  /* If not suspicious: beat_class = N, confidence = 255 (already set) */

  /* Update running class counters */
  if (beat_class == TARANG_BEAT_V) {
    pipeline->class_v_count++;
  } else if (beat_class == TARANG_BEAT_S) {
    pipeline->class_s_count++;
  } else {
    pipeline->class_n_count++;
  }

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

  tarang_pipeline_beat_telemetry_t *telemetry =
      &pipeline->latest_beat_telemetry;
  telemetry->timestamp_ms = timestamp_ms;
  telemetry->r_peak_sample_idx = pipeline->current_rpeak_sample_idx;
  telemetry->rr_interval_ms = rr_interval_ms;
  telemetry->local_hr_bpm_x10 = rr_interval_ms > 0
      ? (uint16_t)(600000u / rr_interval_ms) : 0u;
  telemetry->signal_quality = signal_quality;
  telemetry->gate_probability_x1000 = probability_to_x1000(
      gate_ran ? gate_prob : -1.0f);
  telemetry->sv_p_v_x1000 = probability_to_x1000(sv_ran ? p_v : -1.0f);
  telemetry->sv_p_s_x1000 = probability_to_x1000(sv_ran ? p_s : -1.0f);
  telemetry->beat_class = beat_class;
  telemetry->confidence = confidence;
  telemetry->rhythm_flags = pipeline->engine.rhythm_flags;
  telemetry->current_hr = pipeline->engine.current_hr;
  telemetry->sdnn_ms = pipeline->engine.sdnn_ms;
  telemetry->rmssd_ms = pipeline->engine.rmssd_ms;
  telemetry->prr50_pct = pipeline->engine.prr50_pct;
  pipeline->beat_telemetry_pending = true;

  /* ── BLE event check ────────────────────────────────────────────────── */
  if (pipeline->engine.rhythm_changed || pipeline->engine.significant_event) {
    pipeline->diag.ble_packet_count++;
  }
}

void tarang_pipeline_process_ecg_sample(tarang_pipeline_t *pipeline,
                                         uint32_t raw_adc,
                                         uint32_t timestamp_ms)
{
  if (!pipeline->initialized) return;
  pipeline->latest_sample_timestamp_ms = timestamp_ms;

  static uint32_t s_pipeline_sample_counter = 0;
  s_pipeline_sample_counter++;
  if (s_pipeline_sample_counter % 500 == 0) {
    printf("[AI] pipeline receiving samples, count=%lu\r\n", (unsigned long)s_pipeline_sample_counter);
  }

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
  uint32_t sample_delta = pipeline->dsp.debug_sample.sample_idx -
                          dsp_beat.r_peak_sample_idx;
  uint32_t rpeak_age_ms =
      (uint32_t)(((uint64_t)sample_delta * 1000ULL) /
                 TARANG_ECG_SAMPLE_RATE_HZ);
  uint32_t rpeak_ms = timestamp_ms >= rpeak_age_ms
      ? timestamp_ms - rpeak_age_ms : 0u;

  pipeline->current_rpeak_sample_idx = dsp_beat.r_peak_sample_idx;
  tarang_pipeline_on_rpeak(pipeline, rpeak_ms,
                            dsp_beat.waveform,
                            dsp_beat.signal_quality);
}

bool tarang_pipeline_should_send_event(tarang_pipeline_t *pipeline)
{
  if (pipeline == NULL) return false;
  /* NOTE: beat_telemetry_pending is intentionally NOT included here.
   * That flag drives the per-beat CSV telemetry log (app.c), not BLE sends.
   * Including it here caused tarang_ble_process() to clear engine flags on
   * every superloop tick even when BLE was disconnected, corrupting state. */
  return pipeline->engine.rhythm_changed ||
         pipeline->engine.significant_event;
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

const tarang_dsp_debug_sample_t *tarang_pipeline_get_debug_sample(
    const tarang_pipeline_t *pipeline)
{
  return &pipeline->dsp.debug_sample;
}

bool tarang_pipeline_take_beat_telemetry(
    tarang_pipeline_t *pipeline,
    tarang_pipeline_beat_telemetry_t *telemetry)
{
  if (!pipeline->beat_telemetry_pending || telemetry == NULL) {
    return false;
  }

  *telemetry = pipeline->latest_beat_telemetry;
  pipeline->beat_telemetry_pending = false;
  return true;
}
