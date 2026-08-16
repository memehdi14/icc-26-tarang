/***************************************************************************//**
 * @file tarang_clinical_engine.c
 * @brief TARANG Clinical Event Engine — implementation.
 *
 * Tier 3: Deterministic rhythm analysis. Runs on EVERY beat regardless of
 * whether the CNN fired. No neural network, no heap, pure C arithmetic
 * on static ring buffers.
 *
 * Algorithm dependency order (Phase C, Section 4.3):
 *   1. HR computation
 *   2. PAC/PVC burden
 *   3. Couplets / Triplets
 *   4. Bigeminy / Trigeminy (pattern match on 8-beat ring)
 *   5. V-Run → VT (≥5 V + HR>100)
 *   6. SVT-Run
 *   7. AFib screening (CoV, pRR50, RMSSD — NO CNN involved)
 *   8. Sinus Tachycardia / Bradycardia
 *   9. HRV metrics (SDNN, RMSSD, pRR50)
 *
 * References:
 *   - Lynn 1991, Tateno 2001, Linker 2003 (RR-based AFib detection)
 *   - MIT-BIH AFDB validation: ≥95% sensitivity
 *
 * Target : EFR32MG26B510F3200IM48 (Series 2, Cortex-M33)
 ******************************************************************************/

#include "tarang_clinical_engine.h"
#include "tarang_time.h"
#include <string.h>
#include <math.h>

/*******************************************************************************
 * Private helpers — integer-only where possible for Cortex-M33 efficiency
 ******************************************************************************/

/**
 * @brief Push a value into a uint16_t ring buffer.
 */
static void rr_ring_push(uint16_t *buf, uint8_t *head, uint8_t *count,
                          uint8_t capacity, uint16_t value)
{
  buf[*head] = value;
  *head = (*head + 1) % capacity;
  if (*count < capacity) {
    (*count)++;
  }
}

/**
 * @brief Push a value into a uint8_t ring buffer.
 */
static void pattern_ring_push(uint8_t *buf, uint8_t *head, uint8_t *count,
                               uint8_t capacity, uint8_t value)
{
  buf[*head] = value;
  *head = (*head + 1) % capacity;
  if (*count < capacity) {
    (*count)++;
  }
}

/**
 * @brief Read from ring buffer at logical index (0 = oldest).
 */
static uint16_t rr_ring_read(const uint16_t *buf, uint8_t head,
                              uint8_t count, uint8_t capacity, uint8_t index)
{
  if (index >= count) return 0;
  uint8_t pos = (head + capacity - count + index) % capacity;
  return buf[pos];
}

/**
 * @brief Read from pattern ring at logical index (0 = oldest).
 */
static uint8_t pattern_ring_read(const uint8_t *buf, uint8_t head,
                                  uint8_t count, uint8_t capacity, uint8_t index)
{
  if (index >= count) return 0xFF;
  uint8_t pos = (head + capacity - count + index) % capacity;
  return buf[pos];
}

/**
 * @brief Compute mean of last N entries in the RR ring buffer.
 *        Returns 0 if buffer is empty.
 */
static uint32_t rr_mean(const uint16_t *buf, uint8_t head,
                         uint8_t count, uint8_t capacity, uint8_t n)
{
  if (count == 0) return 0;
  uint8_t use = (n < count) ? n : count;
  uint32_t sum = 0;
  for (uint8_t i = count - use; i < count; i++) {
    sum += rr_ring_read(buf, head, count, capacity, i);
  }
  return sum / use;
}

/**
 * @brief Compute SDNN (standard deviation of NN intervals) in ms.
 *        Integer square root via Newton's method.
 */
static uint16_t compute_sdnn(const uint16_t *buf, uint8_t head,
                              uint8_t count, uint8_t capacity)
{
  if (count < 2) return 0;

  uint32_t mean_rr = rr_mean(buf, head, count, capacity, count);
  if (mean_rr == 0) return 0;

  uint64_t sum_sq_diff = 0;
  for (uint8_t i = 0; i < count; i++) {
    int32_t diff = (int32_t)rr_ring_read(buf, head, count, capacity, i)
                 - (int32_t)mean_rr;
    sum_sq_diff += (uint64_t)((int64_t)diff * diff);
  }

  uint32_t variance = (uint32_t)(sum_sq_diff / count);

  /* Integer square root via Newton's method */
  if (variance == 0) return 0;
  if (variance >= 0x3FFFFFFFu) variance = 0x3FFFFFFFu;
  uint32_t x = variance;
  uint32_t y = (x + 1) / 2;
  while (y < x) {
    x = y;
    y = (x + variance / x) / 2;
  }
  return (uint16_t)x;
}

/**
 * @brief Compute RMSSD (root mean square of successive differences) in ms.
 */
static uint16_t compute_rmssd(const uint16_t *buf, uint8_t head,
                               uint8_t count, uint8_t capacity)
{
  if (count < 2) return 0;

  uint64_t sum_sq = 0;
  uint8_t  n_diffs = 0;

  for (uint8_t i = 1; i < count; i++) {
    int32_t curr = (int32_t)rr_ring_read(buf, head, count, capacity, i);
    int32_t prev = (int32_t)rr_ring_read(buf, head, count, capacity, i - 1);
    int32_t diff = curr - prev;
    sum_sq += (uint64_t)((int64_t)diff * diff);
    n_diffs++;
  }

  if (n_diffs == 0) return 0;
  uint32_t mean_sq = (uint32_t)(sum_sq / n_diffs);

  /* Integer square root */
  if (mean_sq == 0) return 0;
  if (mean_sq >= 0x3FFFFFFFu) mean_sq = 0x3FFFFFFFu;
  uint32_t x = mean_sq;
  uint32_t y = (x + 1) / 2;
  while (y < x) {
    x = y;
    y = (x + mean_sq / x) / 2;
  }
  return (uint16_t)x;
}

/**
 * @brief Compute pRR50 — fraction of successive RR diffs > 50ms.
 *        Returns value as percentage (0–100).
 */
static uint8_t compute_prr50(const uint16_t *buf, uint8_t head,
                              uint8_t count, uint8_t capacity)
{
  if (count < 2) return 0;

  uint8_t over50 = 0;
  uint8_t n_diffs = 0;

  for (uint8_t i = 1; i < count; i++) {
    int32_t curr = (int32_t)rr_ring_read(buf, head, count, capacity, i);
    int32_t prev = (int32_t)rr_ring_read(buf, head, count, capacity, i - 1);
    int32_t diff = curr - prev;
    if (diff < 0) diff = -diff;
    if (diff > 50) over50++;
    n_diffs++;
  }

  if (n_diffs == 0) return 0;
  return (uint8_t)((uint16_t)over50 * 100 / n_diffs);
}

/*******************************************************************************
 * 1. HR computation — 60000 / mean(last 8 RR)
 ******************************************************************************/
static void update_hr(tarang_clinical_engine_t *engine,
                       const tarang_beat_input_t *beat)
{
  /* Hold previous HR if signal quality is poor */
  if (beat->signal_quality < TARANG_SQI_MIN) return;

  /* FIX: Gate HR output until ≥5 consistent beats detected
   * (prevents bootstrap garbage from appearing in telemetry) */
  if (engine->rr_count < 5) {
    engine->current_hr = 0;
    return;
  }

  uint32_t mean8 = rr_mean(engine->rr_buffer, engine->rr_head,
                            engine->rr_count, TARANG_RR_WINDOW_SIZE,
                            TARANG_HR_WINDOW_SIZE);
  if (mean8 > 0) {
    uint32_t hr = 60000 / mean8;
    engine->current_hr = (hr > 255) ? 255 : (uint8_t)hr;
  }
}

/*******************************************************************************
 * 2. PAC/PVC burden — computed at reporting time, not every beat
 ******************************************************************************/
static uint8_t compute_burden(uint32_t ectopic_count, uint32_t total_beats)
{
  if (total_beats == 0) return 0;
  uint32_t pct = (ectopic_count * 100) / total_beats;
  return (pct > 100) ? 100 : (uint8_t)pct;
}

/*******************************************************************************
 * 3. Couplets / Triplets — 2 or 3 consecutive same-class ectopics
 ******************************************************************************/
static void check_consecutive_ectopics(tarang_clinical_engine_t *engine,
                                        uint8_t beat_class)
{
  engine->significant_event = false;

  /* Track consecutive V beats */
  if (beat_class == TARANG_BEAT_V) {
    engine->consecutive_v++;
    if (engine->consecutive_v > engine->max_consecutive_v) {
      engine->max_consecutive_v = engine->consecutive_v;
    }
    /* Couplet = exactly 2, Triplet = exactly 3 — significant events */
    if (engine->consecutive_v == 2 || engine->consecutive_v == 3) {
      engine->significant_event = true;
    }
  } else {
    engine->consecutive_v = 0;
  }

  /* Track consecutive S beats */
  if (beat_class == TARANG_BEAT_S) {
    engine->consecutive_s++;
  } else {
    engine->consecutive_s = 0;
  }
}

/*******************************************************************************
 * 4. Bigeminy / Trigeminy — pattern match on 8-beat ring buffer
 ******************************************************************************/
static void check_rhythm_patterns(tarang_clinical_engine_t *engine)
{
  if (engine->pattern_count < 6) return;

  /* Read last 6 beats (most recent first → indices count-1 .. count-6) */
  uint8_t p[6];
  for (int i = 0; i < 6; i++) {
    p[i] = pattern_ring_read(engine->pattern_buffer, engine->pattern_head,
                              engine->pattern_count, TARANG_PATTERN_WINDOW_SIZE,
                              engine->pattern_count - 6 + i);
  }

  /* Bigeminy: N-V-N-V-N-V */
  if (p[0] == TARANG_BEAT_N && p[1] == TARANG_BEAT_V &&
      p[2] == TARANG_BEAT_N && p[3] == TARANG_BEAT_V &&
      p[4] == TARANG_BEAT_N && p[5] == TARANG_BEAT_V) {
    engine->rhythm_flags |= TARANG_RHYTHM_BIGEMINY;
  } else {
    engine->rhythm_flags &= ~TARANG_RHYTHM_BIGEMINY;
  }

  /* Trigeminy: N-N-V-N-N-V */
  if (p[0] == TARANG_BEAT_N && p[1] == TARANG_BEAT_N &&
      p[2] == TARANG_BEAT_V && p[3] == TARANG_BEAT_N &&
      p[4] == TARANG_BEAT_N && p[5] == TARANG_BEAT_V) {
    engine->rhythm_flags |= TARANG_RHYTHM_TRIGEMINY;
  } else {
    engine->rhythm_flags &= ~TARANG_RHYTHM_TRIGEMINY;
  }
}

/*******************************************************************************
 * 5. V-Run → VT detection
 ******************************************************************************/
static void check_v_run(tarang_clinical_engine_t *engine)
{
  if (engine->consecutive_v >= 3) {
    engine->rhythm_flags |= TARANG_RHYTHM_V_RUN;
    engine->significant_event = true;

    /* VT: ≥5 consecutive V beats AND HR > 100 */
    if (engine->consecutive_v >= TARANG_VT_MIN_CONSECUTIVE_V &&
        engine->current_hr > TARANG_VT_MIN_HR) {
      engine->rhythm_flags |= TARANG_RHYTHM_VT_SUSPECTED;
      /* VT is life-threatening — always flag as significant */
    }
  } else {
    engine->rhythm_flags &= ~TARANG_RHYTHM_V_RUN;
    engine->rhythm_flags &= ~TARANG_RHYTHM_VT_SUSPECTED;
  }
}

/*******************************************************************************
 * 6. SVT-Run — ≥3 consecutive S beats
 *    NOTE: inherits S-class detection weakness (F1 ~0.20–0.35)
 ******************************************************************************/
static void check_svt_run(tarang_clinical_engine_t *engine)
{
  if (engine->consecutive_s >= 3) {
    engine->rhythm_flags |= TARANG_RHYTHM_SVT_RUN;
    engine->significant_event = true;
  } else {
    engine->rhythm_flags &= ~TARANG_RHYTHM_SVT_RUN;
  }
}

/*******************************************************************************
 * 7. AFib screening — the most important detection, NO CNN involved
 *
 *    ALL criteria must hold simultaneously over last 30 RR intervals:
 *      - CoV > 0.12
 *      - pRR50 > 10%
 *      - RMSSD > 30ms
 *      - No dominant V pattern (excludes V bigeminy mimicking AFib)
 *      - 600ms < mean_rr < 1000ms (excludes extreme brady/tachy)
 *
 *    Published sensitivity ≥95% on MIT-BIH AFDB.
 *    This is lead-agnostic (RR-based) — works with any ECG lead config.
 ******************************************************************************/
static void check_afib(tarang_clinical_engine_t *engine)
{
  /* Need full 30-beat window for reliable detection */
  if (engine->rr_count < TARANG_RR_WINDOW_SIZE) {
    engine->rhythm_flags &= ~TARANG_RHYTHM_AFIB;
    engine->afib_consecutive_beats = 0;
    return;
  }

  uint32_t mean_rr = rr_mean(engine->rr_buffer, engine->rr_head,
                              engine->rr_count, TARANG_RR_WINDOW_SIZE,
                              TARANG_RR_WINDOW_SIZE);

  /* Guard: exclude extreme HR ranges (brady/tachy not AFib) */
  if (mean_rr < TARANG_AFIB_MIN_RR_MS || mean_rr > TARANG_AFIB_MAX_RR_MS) {
    engine->afib_consecutive_beats = 0;
    engine->rhythm_flags &= ~TARANG_RHYTHM_AFIB;
    return;
  }

  /* Compute SDNN for CoV = SDNN / mean_rr */
  uint16_t sdnn = compute_sdnn(engine->rr_buffer, engine->rr_head,
                                engine->rr_count, TARANG_RR_WINDOW_SIZE);

  /* CoV check: SDNN * 100 / mean_rr > 12 (avoids float division) */
  bool cov_met = ((uint32_t)sdnn * 100 > (uint32_t)(TARANG_AFIB_COV_THRESHOLD * 100.0f) * mean_rr);

  /* pRR50 check */
  uint8_t prr50_pct = compute_prr50(engine->rr_buffer, engine->rr_head,
                                     engine->rr_count, TARANG_RR_WINDOW_SIZE);
  bool prr50_met = (prr50_pct > (uint8_t)(TARANG_AFIB_PRR50_THRESHOLD * 100.0f));

  /* RMSSD check */
  uint16_t rmssd = compute_rmssd(engine->rr_buffer, engine->rr_head,
                                  engine->rr_count, TARANG_RR_WINDOW_SIZE);
  bool rmssd_met = (rmssd > (uint16_t)TARANG_AFIB_RMSSD_THRESHOLD_MS);

  /* Exclude V bigeminy mimicking AFib irregularity */
  bool v_pattern_dominant = (engine->rhythm_flags & TARANG_RHYTHM_BIGEMINY) != 0;

  /* All criteria must be met */
  if (cov_met && prr50_met && rmssd_met && !v_pattern_dominant) {
    engine->afib_consecutive_beats++;
    /* Require sustained detection over 30 consecutive beats */
    if (engine->afib_consecutive_beats >= TARANG_RR_WINDOW_SIZE) {
      engine->rhythm_flags |= TARANG_RHYTHM_AFIB;
    }
  } else {
    engine->afib_consecutive_beats = 0;
    engine->rhythm_flags &= ~TARANG_RHYTHM_AFIB;
  }
}

/*******************************************************************************
 * 8. Sinus Tachycardia / Bradycardia — gated on NOT AFIB
 ******************************************************************************/
static void check_sinus_rate(tarang_clinical_engine_t *engine)
{
  /* FIX: Gate rhythm flags until ≥5 consistent beats
   * (prevents 0x02 SINUS_BRADY flag from firing during startup) */
  if (engine->rr_count < 5) {
    engine->rhythm_flags &= ~(TARANG_RHYTHM_SINUS_TACH | TARANG_RHYTHM_SINUS_BRADY);
    return;
  }

  bool afib_active = (engine->rhythm_flags & TARANG_RHYTHM_AFIB) != 0;

  if (!afib_active && engine->current_hr > TARANG_TACHYCARDIA_BPM) {
    engine->rhythm_flags |= TARANG_RHYTHM_SINUS_TACH;
  } else {
    engine->rhythm_flags &= ~TARANG_RHYTHM_SINUS_TACH;
  }

  if (!afib_active && engine->current_hr < TARANG_BRADYCARDIA_BPM
      && engine->current_hr > 0) {
    engine->rhythm_flags |= TARANG_RHYTHM_SINUS_BRADY;
  } else {
    engine->rhythm_flags &= ~TARANG_RHYTHM_SINUS_BRADY;
  }
}

/*******************************************************************************
 * 9. HRV metrics — updated every 30 beats for periodic telemetry
 ******************************************************************************/
static void update_hrv(tarang_clinical_engine_t *engine)
{
  if (engine->rr_count < TARANG_RR_WINDOW_SIZE) return;

  engine->sdnn_ms = compute_sdnn(engine->rr_buffer, engine->rr_head,
                                  engine->rr_count, TARANG_RR_WINDOW_SIZE);
  engine->rmssd_ms = compute_rmssd(engine->rr_buffer, engine->rr_head,
                                    engine->rr_count, TARANG_RR_WINDOW_SIZE);
  engine->prr50_pct = compute_prr50(engine->rr_buffer, engine->rr_head,
                                     engine->rr_count, TARANG_RR_WINDOW_SIZE);
}

/*******************************************************************************
 * Public API
 ******************************************************************************/

void tarang_clinical_engine_init(tarang_clinical_engine_t *engine)
{
  memset(engine, 0, sizeof(tarang_clinical_engine_t));
  engine->last_beat_class = TARANG_BEAT_N;
  /* Initialize pattern buffer to 0xFF (invalid) */
  memset(engine->pattern_buffer, 0xFF, sizeof(engine->pattern_buffer));
}

void tarang_clinical_engine_process_beat(tarang_clinical_engine_t *engine,
                                          const tarang_beat_input_t *beat)
{
  /* Save previous rhythm_flags for change detection */
  engine->prev_rhythm_flags = engine->rhythm_flags;
  engine->significant_event = false;

  /* ── Push RR interval into ring buffer ──────────────────────────────── */
  if (beat->rr_interval_ms > 0) {
    rr_ring_push(engine->rr_buffer, &engine->rr_head, &engine->rr_count,
                 TARANG_RR_WINDOW_SIZE, beat->rr_interval_ms);
    engine->rr_valid_push_count++;  /* monotonic — never saturates */
  }

  /* ── Push beat class into pattern buffer ────────────────────────────── */
  pattern_ring_push(engine->pattern_buffer, &engine->pattern_head,
                    &engine->pattern_count, TARANG_PATTERN_WINDOW_SIZE,
                    beat->beat_class);

  /* ── Update running counters ────────────────────────────────────────── */
  engine->total_beats++;
  if (beat->beat_class == TARANG_BEAT_S) engine->pac_count++;
  if (beat->beat_class == TARANG_BEAT_V) engine->pvc_count++;

  /* ── Run all detection algorithms in dependency order ────────────── */

  /* 1. HR */
  update_hr(engine, beat);

  /* 3. Couplets / Triplets (must run before V-Run check) */
  check_consecutive_ectopics(engine, beat->beat_class);

  /* 4. Bigeminy / Trigeminy (must run before AFib to exclude V patterns) */
  check_rhythm_patterns(engine);

  /* 5. V-Run → VT */
  check_v_run(engine);

  /* 6. SVT-Run */
  check_svt_run(engine);

  /* 7. AFib (depends on bigeminy exclusion being current) */
  check_afib(engine);

  /* 8. Sinus Tach / Brady (gated on NOT AFIB) */
  check_sinus_rate(engine);

  /* 9. HRV metrics — update every 30 valid RR pushes (not every beat).
   * rr_count saturates at TARANG_RR_WINDOW_SIZE (30) once the ring fills,
   * so using it for the modulus would fire on every single beat. The
   * monotonic rr_valid_push_count keeps climbing and gives a true
   * periodic trigger. */
  if (engine->rr_count >= TARANG_RR_WINDOW_SIZE &&
      (engine->rr_valid_push_count % TARANG_RR_WINDOW_SIZE) == 0) {
    update_hrv(engine);
  }

  /* ── Detect rhythm_flags change ─────────────────────────────────────── */
  if (engine->rhythm_flags != engine->prev_rhythm_flags) {
    engine->rhythm_changed = true;
  }

  /* ── Update last beat class for next iteration ──────────────────────── */
  engine->last_beat_class = beat->beat_class;
}

void tarang_clinical_engine_build_packet(const tarang_clinical_engine_t *engine,
                                          const tarang_beat_input_t *beat,
                                          tarang_event_packet_t *pkt)
{
  if (pkt == NULL) return;
  if (beat != NULL && beat->timestamp_ms > 0) {
    pkt->timestamp_ms    = beat->timestamp_ms;
    pkt->beat_class      = beat->beat_class;
    pkt->confidence      = beat->confidence;
    pkt->rr_interval_ms  = beat->rr_interval_ms;
  } else {
    pkt->timestamp_ms    = tarang_now_ms();
    pkt->beat_class      = 0;
    pkt->confidence      = 255;
    pkt->rr_interval_ms  = 0;
  }
  pkt->rhythm_flags    = engine ? engine->rhythm_flags : 0;
  pkt->pac_burden_pct  = engine ? compute_burden(engine->pac_count, engine->total_beats) : 0;
  pkt->pvc_burden_pct  = engine ? compute_burden(engine->pvc_count, engine->total_beats) : 0;
  pkt->current_hr      = engine ? engine->current_hr : 0;
  pkt->sdnn_ms         = engine ? engine->sdnn_ms : 0;
  pkt->rmssd_ms        = engine ? engine->rmssd_ms : 0;
}

bool tarang_clinical_engine_rhythm_changed(tarang_clinical_engine_t *engine)
{
  bool changed = engine->rhythm_changed;
  engine->rhythm_changed = false;
  return changed;
}

bool tarang_clinical_engine_significant_event(tarang_clinical_engine_t *engine)
{
  bool event = engine->significant_event;
  engine->significant_event = false;
  return event;
}
