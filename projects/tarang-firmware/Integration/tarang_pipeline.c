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
#include "tarang_imu.h"
#include "tarang_validation_stream.h"
#include <string.h>
#include <stdio.h>
#include <math.h>

/*******************************************************************************
 * Private: last beat cache for packet building
 ******************************************************************************/
static tarang_beat_input_t s_last_beat;

static int16_t clamp_i16_from_float(float value)
{
  if (value > 32767.0f) return INT16_MAX;
  if (value < -32768.0f) return INT16_MIN;
  return (int16_t)(value >= 0.0f ? value + 0.5f : value - 0.5f);
}

static uint32_t clamp_clean_adc(float centered)
{
  float adc = centered + 2048.0f;
  if (adc < 0.0f) adc = 0.0f;
  if (adc > 4095.0f) adc = 4095.0f;
  return (uint32_t)(adc + 0.5f);
}

#if TARANG_VALIDATION_STREAM_ACTIVE
#define TARANG_VALIDATION_ECG_BLOCK_SAMPLES 10u
#define TARANG_VALIDATION_ECG_SAMPLE_BYTES  13u

static uint8_t s_validation_ecg_payload[
    9u + TARANG_VALIDATION_ECG_BLOCK_SAMPLES
       * TARANG_VALIDATION_ECG_SAMPLE_BYTES];
static uint8_t s_validation_ecg_count = 0u;
static size_t s_validation_ecg_length = 0u;

static void emit_validation_ecg_sample(const tarang_dsp_debug_sample_t *debug,
                                       uint32_t timestamp_ms,
                                       uint32_t clean_adc)
{
  if (s_validation_ecg_count == 0u) {
    tarang_validation_put_u32(&s_validation_ecg_payload[0], debug->sample_idx);
    tarang_validation_put_u32(&s_validation_ecg_payload[4], timestamp_ms);
    s_validation_ecg_payload[8] = 0u;
    s_validation_ecg_length = 9u;
  }

  uint8_t *sample = &s_validation_ecg_payload[s_validation_ecg_length];
  tarang_validation_put_u16(&sample[0], (uint16_t)(debug->raw_adc & 0x0FFFu));
  tarang_validation_put_u16(&sample[2], (uint16_t)clean_adc);
  tarang_validation_put_u16(&sample[4],
      (uint16_t)tarang_validation_i16(debug->bandpassed, 1.0f));
  tarang_validation_put_u16(&sample[6],
      (uint16_t)tarang_validation_i16(debug->zscored, 1000.0f));
  tarang_validation_put_u16(&sample[8],
      tarang_validation_u16(debug->mwi, 1000.0f));
  tarang_validation_put_u16(&sample[10],
      tarang_validation_u16(debug->threshold_th1, 1000.0f));
  sample[12] = debug->warmed_up ? 1u : 0u;

  s_validation_ecg_length += TARANG_VALIDATION_ECG_SAMPLE_BYTES;
  s_validation_ecg_count++;
  s_validation_ecg_payload[8] = s_validation_ecg_count;

  if (s_validation_ecg_count >= TARANG_VALIDATION_ECG_BLOCK_SAMPLES) {
    tarang_validation_emit('E', s_validation_ecg_payload,
                           s_validation_ecg_length);
    s_validation_ecg_count = 0u;
    s_validation_ecg_length = 0u;
  }
}
#endif

static void store_clean_ecg_sample(tarang_pipeline_t *pipeline)
{
  float scaled = pipeline->dsp.debug_sample.zscored * 1000.0f;
  pipeline->clean_ecg_ring[pipeline->clean_ecg_head] =
      clamp_i16_from_float(scaled);
  pipeline->clean_ecg_head = (uint16_t)((pipeline->clean_ecg_head + 1u)
      % TARANG_EVENT_SNIPPET_SAMPLES);
  if (pipeline->clean_ecg_count < TARANG_EVENT_SNIPPET_SAMPLES) {
    pipeline->clean_ecg_count++;
  }
}

static void store_annotation(tarang_pipeline_t *pipeline,
                             uint32_t sample_idx,
                             uint8_t beat_class,
                             uint8_t confidence)
{
  tarang_pipeline_annotation_history_t *slot =
      &pipeline->annotation_history[pipeline->annotation_head];
  slot->sample_idx = sample_idx;
  slot->beat_class = beat_class;
  slot->confidence = confidence;
  pipeline->annotation_head = (uint8_t)((pipeline->annotation_head + 1u)
      % TARANG_EVENT_ANNOTATION_HISTORY);
  if (pipeline->annotation_count < TARANG_EVENT_ANNOTATION_HISTORY) {
    pipeline->annotation_count++;
  }
}

static bool queue_pending_beat(tarang_pipeline_t *pipeline,
                               const tarang_beat_output_t *beat,
                               uint32_t timestamp_ms)
{
  if (pipeline->pending_count >= TARANG_MAX_PENDING_BEATS) {
    pipeline->diag.dropped_frames++;
    return false;
  }

  tarang_pending_beat_t *pending =
      &pipeline->pending_beats[pipeline->pending_tail];
  memcpy(pending->waveform, beat->waveform, sizeof(pending->waveform));
  pending->timestamp_ms = timestamp_ms;
  pending->r_peak_sample_idx = beat->r_peak_sample_idx;
  pending->signal_quality = beat->signal_quality;
  pending->rr_interval_ms = 0u;
  pending->suspicious = false;
  pipeline->pending_tail = (uint8_t)((pipeline->pending_tail + 1u)
      % TARANG_MAX_PENDING_BEATS);
  pipeline->pending_count++;
  return true;
}

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

  /* Initialize guarded IMU-referenced ECG motion cancellation. */
  tarang_nlms_init(&pipeline->nlms);

  /* Initialize Clinical Event Engine */
  tarang_clinical_engine_init(&pipeline->engine);

  /* Initialize TFLite Micro — load both CNN models */
  bool ai_ok = tarang_ai_init();

  pipeline->initialized = true;

  printf("[PIPELINE] Tarang pipeline initialized.\r\n");
  printf("[PIPELINE] Tier 0: DSP heuristics  — ACTIVE\r\n");
  printf("[PIPELINE] IMU-NLMS: %s\r\n",
         TARANG_ENABLE_NLMS && TARANG_NLMS_APPLY_TO_DSP
             ? "ACTIVE (guarded)" : "BYPASS");
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
      printf("[PIPELINE] Suspicious-rate guard: %u/%u beats (>20%%), AI policy=%s.\r\n",
             pipeline->circuit_breaker_suspicious_count,
             CIRCUIT_BREAKER_WINDOW,
             TARANG_ENABLE_AI_CIRCUIT_BREAKER ? "BYPASS" : "MONITOR_ONLY");
      pipeline->circuit_breaker_tripped = true;
    } else if (!should_trip && pipeline->circuit_breaker_tripped) {
      printf("[PIPELINE] Suspicious-rate guard recovered: %u/%u beats.\r\n",
             pipeline->circuit_breaker_suspicious_count, CIRCUIT_BREAKER_WINDOW);
      pipeline->circuit_breaker_tripped = false;
    }
  }

  if (suspicious) {
    pipeline->suspicious_beats++;
    pipeline->diag.ai_trigger_count++;

    /* ── TIER 1: Gate CNN (disabled if circuit breaker tripped) ───────── */
    if (!TARANG_ENABLE_AI_CIRCUIT_BREAKER
        || !pipeline->circuit_breaker_tripped) {
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

#if TARANG_VALIDATION_STREAM_ACTIVE
  printf("@A,%lu,%lu,%u,%u,%u,%d,%d,%d,%u,%u,%u,%u,%u,%u,%u\r\n",
         (unsigned long)telemetry->timestamp_ms,
         (unsigned long)telemetry->r_peak_sample_idx,
         telemetry->rr_interval_ms,
         telemetry->local_hr_bpm_x10,
         telemetry->signal_quality,
         telemetry->gate_probability_x1000,
         telemetry->sv_p_v_x1000,
         telemetry->sv_p_s_x1000,
         telemetry->beat_class,
         telemetry->confidence,
         telemetry->rhythm_flags,
         telemetry->current_hr,
         telemetry->sdnn_ms,
         telemetry->rmssd_ms,
         telemetry->prr50_pct);
#endif

  store_annotation(pipeline,
                   pipeline->current_rpeak_sample_idx,
                   beat_class,
                   confidence);

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

  uint64_t sample_timestamp_us = (uint64_t)timestamp_ms * 1000ULL;
  tarang_imu_sample_t causal_imu = {0};
  tarang_imu_sample_t aligned_imu = {0};
  bool have_causal = tarang_imu_get_sample_at_or_before(
      sample_timestamp_us, &causal_imu);
  bool imu_fresh = have_causal
      && sample_timestamp_us >= causal_imu.t_us
      && (sample_timestamp_us - causal_imu.t_us) <= 50000ULL;
  bool have_aligned = imu_fresh && tarang_imu_get_interpolated_sample(
      sample_timestamp_us, &aligned_imu);
  if (!have_aligned && have_causal) aligned_imu = causal_imu;

  uint64_t nlms_start_us = tarang_now_us();
  float centered = (float)(raw_adc & 0x0FFFu) - 2048.0f;
  float cleaned = tarang_nlms_process_sample(
      &pipeline->nlms,
      centered,
      have_causal ? &aligned_imu : NULL,
      imu_fresh,
      TARANG_ENABLE_NLMS && TARANG_NLMS_APPLY_TO_DSP);
  pipeline->diag.nlms_time_us +=
      (uint32_t)(tarang_now_us() - nlms_start_us);
  uint32_t clean_adc = clamp_clean_adc(cleaned);

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
  bool beat_ready = tarang_dsp_process_sample(&pipeline->dsp,
                                               clean_adc,
                                               &dsp_beat);

  store_clean_ecg_sample(pipeline);

#if TARANG_VALIDATION_STREAM_ACTIVE
  const tarang_dsp_debug_sample_t *debug = &pipeline->dsp.debug_sample;
  emit_validation_ecg_sample(debug, timestamp_ms, clean_adc);
#endif

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

  (void)queue_pending_beat(pipeline, &dsp_beat, rpeak_ms);
}

void tarang_pipeline_run_deferred(tarang_pipeline_t *pipeline)
{
  if (pipeline == NULL || !pipeline->initialized) return;

  while (pipeline->pending_count > 0u) {
    tarang_pending_beat_t beat = pipeline->pending_beats[pipeline->pending_head];
    pipeline->pending_head = (uint8_t)((pipeline->pending_head + 1u)
        % TARANG_MAX_PENDING_BEATS);
    pipeline->pending_count--;

    pipeline->current_rpeak_sample_idx = beat.r_peak_sample_idx;
    tarang_pipeline_on_rpeak(pipeline,
                             beat.timestamp_ms,
                             beat.waveform,
                             beat.signal_quality);
  }
}

uint16_t tarang_pipeline_copy_event_snippet(
    const tarang_pipeline_t *pipeline,
    int16_t *samples,
    uint16_t max_samples,
    uint32_t *start_sample_idx)
{
  if (pipeline == NULL || samples == NULL || max_samples == 0u) return 0u;

  uint16_t count = pipeline->clean_ecg_count;
  if (count > max_samples) count = max_samples;
  uint16_t oldest = (uint16_t)((pipeline->clean_ecg_head
      + TARANG_EVENT_SNIPPET_SAMPLES - count)
      % TARANG_EVENT_SNIPPET_SAMPLES);
  for (uint16_t i = 0u; i < count; i++) {
    samples[i] = pipeline->clean_ecg_ring[
        (oldest + i) % TARANG_EVENT_SNIPPET_SAMPLES];
  }

  uint32_t latest_idx = pipeline->dsp.debug_sample.sample_idx;
  if (start_sample_idx != NULL) {
    *start_sample_idx = latest_idx + 1u - count;
  }
  return count;
}

uint8_t tarang_pipeline_copy_event_annotations(
    const tarang_pipeline_t *pipeline,
    uint32_t start_sample_idx,
    uint16_t sample_count,
    tarang_pipeline_event_annotation_t *annotations,
    uint8_t max_annotations)
{
  if (pipeline == NULL || annotations == NULL || max_annotations == 0u) {
    return 0u;
  }

  uint8_t written = 0u;
  uint32_t end_sample_idx = start_sample_idx + sample_count;
  uint8_t oldest = (uint8_t)((pipeline->annotation_head
      + TARANG_EVENT_ANNOTATION_HISTORY - pipeline->annotation_count)
      % TARANG_EVENT_ANNOTATION_HISTORY);

  for (uint8_t i = 0u;
       i < pipeline->annotation_count && written < max_annotations;
       i++) {
    const tarang_pipeline_annotation_history_t *entry =
        &pipeline->annotation_history[
            (oldest + i) % TARANG_EVENT_ANNOTATION_HISTORY];
    if (entry->sample_idx < start_sample_idx
        || entry->sample_idx >= end_sample_idx) {
      continue;
    }
    uint32_t offset_samples = entry->sample_idx - start_sample_idx;
    uint32_t offset_ms = (offset_samples * 1000u)
                         / TARANG_ECG_SAMPLE_RATE_HZ;
    annotations[written].offset_ms = offset_ms > UINT16_MAX
        ? UINT16_MAX : (uint16_t)offset_ms;
    annotations[written].beat_class = entry->beat_class;
    annotations[written].confidence = entry->confidence;
    written++;
  }
  return written;
}

const tarang_nlms_state_t *tarang_pipeline_get_nlms_state(
    const tarang_pipeline_t *pipeline)
{
  return pipeline == NULL ? NULL : &pipeline->nlms;
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
