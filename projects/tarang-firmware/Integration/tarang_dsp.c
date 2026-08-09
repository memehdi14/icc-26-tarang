/***************************************************************************//**
 * @file tarang_dsp.c
 * @brief TARANG DSP module — streaming Pan-Tompkins R-peak detection.
 *
 * Direct C port of tarang_dsp_reference.py v16 (StreamingTarangDSP).
 * Each block is a single-sample step. No vectorized operations.
 *
 * Filter coefficients are pre-computed from scipy.signal.butter() and
 * hardcoded. To regenerate:
 *   from scipy.signal import butter
 *   butter(4, [0.5/125, 40/125], btype='band', output='sos')
 *   butter(2, 5/125, btype='high', output='sos')
 *   butter(2, 15/125, btype='low', output='sos')
 *
 * ZERO heap. All state is in tarang_dsp_state_t (stack or static).
 *
 * Target : EFR32MG26B510F3200IM48 (Series 2, Cortex-M33)
 ******************************************************************************/

#include "tarang_dsp.h"
#include <string.h>
#include <math.h>
#include <stdio.h>

/*******************************************************************************
 * Pre-computed Filter Coefficients
 *
 * Morphology bandpass: Butterworth order 4, 0.5–40 Hz @ 250 Hz
 *   scipy: butter(4, [0.5/125, 40/125], btype='band', output='sos')
 *   Yields 4 second-order sections [b0,b1,b2,1,a1,a2]
 *
 * QRS HP: Butterworth order 2, 5 Hz @ 250 Hz
 *   scipy: butter(2, 5/125, btype='high', output='sos')
 *   Yields 1 second-order section
 *
 * QRS LP: Butterworth order 2, 15 Hz @ 250 Hz
 *   scipy: butter(2, 15/125, btype='low', output='sos')
 *   Yields 1 second-order section
 ******************************************************************************/

/* Morphology bandpass 0.5–40Hz, order 4, fs=250Hz (4 SOS sections)
 * Computed: scipy.signal.butter(4, [0.5/125, 40/125], btype='band', output='sos') */
static const float MORPH_SOS[4][6] = {
  /*         b0              b1              b2              a0              a1              a2        */
  {  0.0219612634f,  0.0439225269f,  0.0219612634f,  1.0000000000f, -0.6215552807f,  0.1305843533f },
  {  1.0000000000f,  2.0000000000f,  1.0000000000f,  1.0000000000f, -0.8176588707f,  0.5194597166f },
  {  1.0000000000f, -2.0000000000f,  1.0000000000f,  1.0000000000f, -1.9765144890f,  0.9766768505f },
  {  1.0000000000f, -2.0000000000f,  1.0000000000f,  1.0000000000f, -1.9904258739f,  0.9905840603f },
};

/* QRS high-pass 5Hz, order 2, fs=250Hz (1 SOS section)
 * Computed: scipy.signal.butter(2, 5/125, btype='high', output='sos') */
static const float QRS_HP_SOS[1][6] = {
  {  0.9149691441f, -1.8299382882f,  0.9149691441f,  1.0000000000f, -1.8226949252f,  0.8371816513f },
};

/* QRS low-pass 15Hz, order 2, fs=250Hz (1 SOS section)
 * Computed: scipy.signal.butter(2, 15/125, btype='low', output='sos') */
static const float QRS_LP_SOS[1][6] = {
  {  0.0278597661f,  0.0557195322f,  0.0278597661f,  1.0000000000f, -1.4754804436f,  0.5869195081f },
};

/* Notch filter for 50Hz at 250Hz, r=0.95
 * b = [1, -2*cos(2π*50/250), 1], a = [1, -2*r*cos(2π*50/250), r²] */
static const float NOTCH_50_B[3] = { 1.0f, -0.6180339887f, 1.0f };
static const float NOTCH_50_A[3] = { 1.0f, -0.5871322893f, 0.9025f };

/*******************************************************************************
 * Private: Biquad step (transposed direct form II)
 *
 * y = b0*x + z1
 * z1' = b1*x + z2 - a1*y
 * z2' = b2*x      - a2*y
 ******************************************************************************/
static inline float biquad_step(dsp_biquad_t *bq, float x)
{
  float y = bq->b0 * x + bq->z1;
  bq->z1 = bq->b1 * x + bq->z2 - bq->a1 * y;
  bq->z2 = bq->b2 * x           - bq->a2 * y;
  return y;
}

/*******************************************************************************
 * Private: SOS cascade step (N biquads in series)
 ******************************************************************************/
static float sos_cascade_step(dsp_biquad_t *sections, int n_sections, float x)
{
  float y = x;
  for (int k = 0; k < n_sections; k++) {
    y = biquad_step(&sections[k], y);
  }
  return y;
}

/*******************************************************************************
 * Private: Notch filter step
 ******************************************************************************/
static float notch_step(dsp_notch_t *n, float x)
{
  if (!n->enabled) return x;
  float y = n->b0 * x + n->z1;
  n->z1 = n->b1 * x + n->z2 - n->a1 * y;
  n->z2 = n->b2 * x          - n->a2 * y;
  return y;
}

/*******************************************************************************
 * Private: Rolling z-score normalization step
 *
 * mu = S1 / C
 * var = max(S2/C - mu², 0)
 * z = (x - mu) / max(sqrt(var), ε)
 ******************************************************************************/
static float rolling_norm_step(dsp_rolling_norm_t *rn, float x)
{
  if (rn->count >= DSP_NORM_WINDOW) {
    float old = rn->ring[rn->idx];
    rn->S1 -= (double)old;
    rn->S2 -= (double)old * (double)old;
  }
  rn->S1 += (double)x;
  rn->S2 += (double)x * (double)x;
  rn->ring[rn->idx] = x;
  rn->idx = (rn->idx + 1) % DSP_NORM_WINDOW;
  if (rn->count < DSP_NORM_WINDOW) rn->count++;

  double mu = rn->S1 / rn->count;
  double var = rn->S2 / rn->count - mu * mu;
  if (var < 0.0) var = 0.0;
  double std = sqrt(var);
  if (std < 1e-8) std = 1e-8;

  return (float)((x - mu) / std);
}

/*******************************************************************************
 * Private: 5-tap causal derivative step
 *
 * y = (1/8T) * (x[n] + 2*x[n-1] - 2*x[n-3] - x[n-4])
 ******************************************************************************/
static float derivative_step(float *delay, float T, float x)
{
  float x1 = delay[0], x3 = delay[2], x4 = delay[3];
  float y = (1.0f / (8.0f * T)) * (x + 2.0f * x1 - 2.0f * x3 - x4);

  /* Shift delay line */
  delay[3] = delay[2];
  delay[2] = delay[1];
  delay[1] = delay[0];
  delay[0] = x;

  return y;
}

/*******************************************************************************
 * Private: MWI step (ring buffer + running sum, O(1) per sample)
 ******************************************************************************/
static float mwi_step(dsp_mwi_t *m, float x)
{
  if (m->count >= DSP_MWI_WINDOW) {
    m->S -= m->ring[m->idx];
  }
  m->S += x;
  m->ring[m->idx] = x;
  m->idx = (m->idx + 1) % DSP_MWI_WINDOW;
  if (m->count < DSP_MWI_WINDOW) m->count++;

  return m->S / (float)m->count;
}

/*******************************************************************************
 * Private: Read from morphology ring buffer at absolute index
 ******************************************************************************/
static float morph_ring_read(const tarang_dsp_state_t *state, int abs_idx)
{
  if (state->sample_idx < DSP_MORPH_BUFFER_SIZE) {
    /* Buffer not full yet */
    if (abs_idx < 0 || abs_idx >= state->sample_idx) return 0.0f;
    return state->morph_ring[abs_idx % DSP_MORPH_BUFFER_SIZE];
  }
  int offset = state->sample_idx - DSP_MORPH_BUFFER_SIZE;
  int rel = abs_idx - offset;
  if (rel < 0 || rel >= DSP_MORPH_BUFFER_SIZE) return 0.0f;
  return state->morph_ring[(offset + rel) % DSP_MORPH_BUFFER_SIZE];
}

/*******************************************************************************
 * Private: Add accepted RR to threshold state
 ******************************************************************************/
static void thresh_add_rr(dsp_adaptive_thresh_t *th, int rr_samples)
{
  if (rr_samples <= 0) return;
  if (th->rr_count < DSP_RR_HISTORY_SIZE) {
    th->rr_history[th->rr_count++] = rr_samples;
  } else {
    /* Shift left and append */
    for (int i = 0; i < DSP_RR_HISTORY_SIZE - 1; i++) {
      th->rr_history[i] = th->rr_history[i + 1];
    }
    th->rr_history[DSP_RR_HISTORY_SIZE - 1] = rr_samples;
  }
  /* Update mean */
  int sum = 0;
  for (int i = 0; i < th->rr_count; i++) {
    sum += th->rr_history[i];
  }
  th->recent_rr_mean = (float)sum / (float)th->rr_count;
}

/*******************************************************************************
 * Private: SPKI update with outlier clamp
 ******************************************************************************/
static void update_spki(dsp_adaptive_thresh_t *th, float peak_val)
{
  float spki_cap = (th->SPKI > 0.0f)
      ? th->spki_max_step_ratio * th->SPKI : peak_val;
  float capped = (spki_cap > 0.0f && peak_val > spki_cap) ? spki_cap : peak_val;
  th->SPKI = 0.125f * capped + 0.875f * th->SPKI;
  th->TH1 = th->NPKI + 0.25f * (th->SPKI - th->NPKI);
  th->TH2 = 0.5f * th->TH1;
}

/*******************************************************************************
 * Private: Accept an R-peak (common logic for primary + search-back)
 ******************************************************************************/
static void accept_peak(dsp_adaptive_thresh_t *th, int peak_idx,
                         float peak_val, float slope)
{
  update_spki(th, peak_val);
  th->refractory_remaining = DSP_REFRACTORY_SAMPLES;

  if (th->last_R_idx >= 0) {
    int rr = peak_idx - th->last_R_idx;
    if (rr > 0) thresh_add_rr(th, rr);
  }

  th->last_R_idx = peak_idx;
  th->last_R_slope = slope;
  th->n_candidates = 0;
}

/*******************************************************************************
 * Private: Adaptive threshold step — process one MWI sample
 *
 * Returns index of accepted R-peak, or -1 if none.
 * Port of adaptive_threshold_step() from Python reference (Phase 2 refactor).
 ******************************************************************************/
static int adaptive_thresh_step(dsp_adaptive_thresh_t *th,
                                 float mwi_val, float slope_est)
{
  int accepted = -1;
  int idx = th->current_idx;

  /* Decrement refractory */
  if (th->refractory_remaining > 0) th->refractory_remaining--;

  /* Local-max detection: prev_mwi was a peak if current < prev - hysteresis */
  float hysteresis = 0.01f * fabsf(th->prev_mwi);
  if (hysteresis < 1e-6f) hysteresis = 1e-6f;

  bool peak_detected = (th->prev_mwi_idx >= 0) &&
                        (mwi_val < th->prev_mwi - hysteresis);

  if (peak_detected) {
    float peak_val = th->prev_mwi;
    int   peak_idx = th->prev_mwi_idx;

    /* Buffer candidate if > TH2 (for search-back) */
    if (peak_val > th->TH2) {
      bool within_refr = (th->last_R_idx >= 0) &&
                          (peak_idx - th->last_R_idx < DSP_REFRACTORY_SAMPLES);
      if (!within_refr && th->n_candidates < DSP_CANDIDATE_BUFFER_SIZE) {
        th->candidates[th->n_candidates].idx = peak_idx;
        th->candidates[th->n_candidates].val = peak_val;
        th->n_candidates++;
      }
    }

    /* Trim old candidates */
    if (th->recent_rr_mean > 0.0f) {
      int max_age = (int)(2.0f * TARANG_SEARCHBACK_GAMMA * th->recent_rr_mean);
      int write = 0;
      for (int i = 0; i < th->n_candidates; i++) {
        if (idx - th->candidates[i].idx <= max_age) {
          th->candidates[write++] = th->candidates[i];
        }
      }
      th->n_candidates = write;
    }

    /* Search-back: too long since last R */
    int ref_idx = (th->last_R_idx >= 0) ? th->last_R_idx : 0;
    float eff_rr = (th->recent_rr_mean > 0.0f)
        ? th->recent_rr_mean
        : (float)(th->default_rr_samples > 0 ? th->default_rr_samples : 1);

    if ((float)(idx - ref_idx) > TARANG_SEARCHBACK_GAMMA * eff_rr &&
        th->refractory_remaining == 0 &&
        th->n_candidates > 0) {
      /* Find best candidate */
      int best_i = 0;
      for (int i = 1; i < th->n_candidates; i++) {
        if (th->candidates[i].val > th->candidates[best_i].val) best_i = i;
      }
      if (th->candidates[best_i].val > th->TH2) {
        accepted = th->candidates[best_i].idx;
        accept_peak(th, accepted, th->candidates[best_i].val, slope_est);
      }
    }

    /* Primary threshold check on PEAK value */
    if (accepted < 0 && peak_val > th->TH1 &&
        th->refractory_remaining == 0) {
      /* T-wave rejection */
      bool twave_ok = true;
      if (th->last_R_slope > 0.0f &&
          slope_est < 0.5f * th->last_R_slope) {
        if (th->last_R_idx >= 0) {
          int dt = peak_idx - th->last_R_idx;
          if (dt >= 50 && dt <= 100) twave_ok = false;
        }
      }

      if (twave_ok) {
        accepted = peak_idx;
        accept_peak(th, peak_idx, peak_val, slope_est);
      } else {
        /* T-wave: update noise */
        th->NPKI = 0.125f * peak_val + 0.875f * th->NPKI;
        th->TH1 = th->NPKI + 0.25f * (th->SPKI - th->NPKI);
        th->TH2 = 0.5f * th->TH1;
      }
    } else if (accepted < 0 && peak_val > th->TH2 && peak_val <= th->TH1) {
      /* Noise peak between TH2 and TH1 */
      th->NPKI = 0.125f * peak_val + 0.875f * th->NPKI;
      th->TH1 = th->NPKI + 0.25f * (th->SPKI - th->NPKI);
      th->TH2 = 0.5f * th->TH1;
    }
  }

  /* Timeout check: if no R-peak detected for 3 seconds (750 samples),
   * decay SPKI and NPKI by 50% to recover from threshold lock-in */
  int time_since_R = (th->last_R_idx >= 0) ? (idx - th->last_R_idx) : idx;
  if (time_since_R > TARANG_PEAK_TIMEOUT_SAMPLES) {
    th->SPKI *= 0.5f;
    th->NPKI *= 0.5f;
    if (th->SPKI < 0.01f) th->SPKI = 0.01f;
    th->TH1 = th->NPKI + 0.25f * (th->SPKI - th->NPKI);
    th->TH2 = 0.5f * th->TH1;
    th->last_R_idx = idx - (TARANG_PEAK_TIMEOUT_SAMPLES / 2);
  }

  /* Update state for next call */
  th->prev_mwi = mwi_val;
  th->prev_mwi_idx = idx;
  th->current_idx = idx + 1;

  return accepted;
}

/*******************************************************************************
 * Private: Recenter R-peak on morphology signal (±15 samples)
 *
 * Find the largest absolute-value peak in the z-scored morphology
 * signal within ±RECENTER range of the delay-corrected candidate.
 ******************************************************************************/
static int recenter_peak(const tarang_dsp_state_t *state, int candidate_idx)
{
  int corrected = candidate_idx - DSP_DETECTION_DELAY;
  int lo = corrected - DSP_RECENTER_RANGE;
  int hi = corrected + DSP_RECENTER_RANGE;
  if (lo < 0) lo = 0;

  float best_val = 0.0f;
  int   best_idx = corrected;

  for (int i = lo; i <= hi; i++) {
    float v = fabsf(morph_ring_read(state, i));
    if (v > best_val) {
      best_val = v;
      best_idx = i;
    }
  }
  return best_idx;
}

/*******************************************************************************
 * Private: Extract 130-sample beat window + compute 4 RR features
 ******************************************************************************/
static bool extract_beat(tarang_dsp_state_t *state, int refined_peak,
                          float mwi_peak_val, float spki_at_det,
                          tarang_beat_output_t *beat)
{
  int beat_start = refined_peak - TARANG_BEAT_PRE_R_SAMPLES;
  int beat_end   = refined_peak + TARANG_BEAT_POST_R_SAMPLES;

  if (beat_start < 0 || beat_end > state->sample_idx) {
    beat->valid = false;
    return false;
  }

  /* Extract waveform from morphology ring buffer */
  for (int i = 0; i < TARANG_BEAT_WINDOW_SIZE; i++) {
    beat->waveform[i] = morph_ring_read(state, beat_start + i);
  }

  /* Compute 4 causal RR features */
  if (state->rpeak_count == 0) {
    beat->rr_features[0] = 0.0f; /* rr_prev_ms */
    beat->rr_features[1] = 0.0f; /* rr_mean_5_ms */
    beat->rr_features[2] = 0.0f; /* rr_std_5_ms */
    beat->rr_features[3] = 0.0f; /* local_hr_bpm */
  } else {
    int last_r = state->rpeak_history[state->rpeak_count - 1];
    float rr_prev_ms = (float)(refined_peak - last_r) * 1000.0f
                     / (float)TARANG_ECG_SAMPLE_RATE_HZ;
    beat->rr_features[TARANG_RR_FEAT_RR_PREV] = rr_prev_ms;

    /* Collect recent intervals (including current) */
    float intervals[6];
    int n_int = 0;
    for (int i = 1; i < state->rpeak_count && n_int < 5; i++) {
      int r0 = state->rpeak_history[i - 1];
      int r1 = state->rpeak_history[i];
      intervals[n_int++] = (float)(r1 - r0) * 1000.0f
                          / (float)TARANG_ECG_SAMPLE_RATE_HZ;
    }
    intervals[n_int++] = rr_prev_ms;

    /* Use last 5 */
    int start = (n_int > 5) ? n_int - 5 : 0;
    int use = n_int - start;
    float sum = 0.0f;
    for (int i = start; i < n_int; i++) sum += intervals[i];
    float mean_ms = sum / (float)use;

    float sq_sum = 0.0f;
    for (int i = start; i < n_int; i++) {
      float d = intervals[i] - mean_ms;
      sq_sum += d * d;
    }
    float std_ms = (use > 1) ? sqrtf(sq_sum / (float)use) : 0.0f;

    beat->rr_features[TARANG_RR_FEAT_RR_MEAN_5] = mean_ms;
    beat->rr_features[TARANG_RR_FEAT_RR_STD_5]  = std_ms;
    beat->rr_features[TARANG_RR_FEAT_LOCAL_HR]   = (mean_ms > 0.01f)
        ? 60000.0f / mean_ms : 0.0f;
  }

  /* Update R-peak history */
  if (state->rpeak_count < DSP_RPEAK_HISTORY_SIZE) {
    state->rpeak_history[state->rpeak_count++] = refined_peak;
  } else {
    for (int i = 0; i < DSP_RPEAK_HISTORY_SIZE - 1; i++) {
      state->rpeak_history[i] = state->rpeak_history[i + 1];
    }
    state->rpeak_history[DSP_RPEAK_HISTORY_SIZE - 1] = refined_peak;
  }

  /* Signal quality: detector confidence */
  float det_conf = (spki_at_det > 0.0f)
      ? (mwi_peak_val / spki_at_det) : 0.0f;
  if (det_conf > 1.0f) det_conf = 1.0f;
  beat->signal_quality = (uint8_t)(det_conf * 255.0f);

  /* Low quality during startup (first 30s) */
  if (refined_peak < DSP_NORM_WINDOW) {
    if (beat->signal_quality > 128) beat->signal_quality = 128;
  }

  beat->r_peak_sample_idx = (uint32_t)refined_peak;
  beat->valid = true;
  return true;
}

/*******************************************************************************
 * Public API
 ******************************************************************************/

void tarang_dsp_init(tarang_dsp_state_t *state)
{
  memset(state, 0, sizeof(tarang_dsp_state_t));

  /* Block 1: Morphology bandpass — load pre-computed SOS coefficients */
  for (int k = 0; k < DSP_MORPH_SOS_SECTIONS; k++) {
    state->morph_sos[k].b0 = MORPH_SOS[k][0];
    state->morph_sos[k].b1 = MORPH_SOS[k][1];
    state->morph_sos[k].b2 = MORPH_SOS[k][2];
    state->morph_sos[k].a1 = MORPH_SOS[k][3 + 1]; /* skip a0=1.0 */
    state->morph_sos[k].a2 = MORPH_SOS[k][3 + 2];
    state->morph_sos[k].z1 = 0.0f;
    state->morph_sos[k].z2 = 0.0f;
  }

  /* Block 2: Notch (disabled by default — enable for 50/60Hz environments) */
  state->notch.b0 = NOTCH_50_B[0];
  state->notch.b1 = NOTCH_50_B[1];
  state->notch.b2 = NOTCH_50_B[2];
  state->notch.a1 = NOTCH_50_A[1];
  state->notch.a2 = NOTCH_50_A[2];
  state->notch.z1 = 0.0f;
  state->notch.z2 = 0.0f;
  state->notch.enabled = false;

  /* Block 4: QRS HP (5Hz) */
  state->qrs_hp[0].b0 = QRS_HP_SOS[0][0];
  state->qrs_hp[0].b1 = QRS_HP_SOS[0][1];
  state->qrs_hp[0].b2 = QRS_HP_SOS[0][2];
  state->qrs_hp[0].a1 = QRS_HP_SOS[0][4];
  state->qrs_hp[0].a2 = QRS_HP_SOS[0][5];
  state->qrs_hp[0].z1 = 0.0f;
  state->qrs_hp[0].z2 = 0.0f;

  /* Block 4: QRS LP (15Hz) */
  state->qrs_lp[0].b0 = QRS_LP_SOS[0][0];
  state->qrs_lp[0].b1 = QRS_LP_SOS[0][1];
  state->qrs_lp[0].b2 = QRS_LP_SOS[0][2];
  state->qrs_lp[0].a1 = QRS_LP_SOS[0][4];
  state->qrs_lp[0].a2 = QRS_LP_SOS[0][5];
  state->qrs_lp[0].z1 = 0.0f;
  state->qrs_lp[0].z2 = 0.0f;

  /* Block 5: Derivative */
  state->deriv_T = 1.0f / (float)TARANG_ECG_SAMPLE_RATE_HZ;

  /* Block 8: Adaptive threshold */
  state->thresh.SPKI = 0.0f;
  state->thresh.NPKI = 0.0f;
  state->thresh.TH1 = 0.0f;
  state->thresh.TH2 = 0.0f;
  state->thresh.refractory_remaining = 0;
  state->thresh.last_R_idx = -1;
  state->thresh.prev_mwi_idx = -1;
  state->thresh.spki_max_step_ratio = 3.0f;
  state->thresh.default_rr_samples = TARANG_ECG_SAMPLE_RATE_HZ; /* 1s = 60bpm */

  /* Warm-up: 2 seconds of signal for threshold initialization */
  state->warmup_samples = 2 * TARANG_ECG_SAMPLE_RATE_HZ;

  printf("[DSP] Initialized: fs=%dHz, MWI_N=%d, refractory=%d, "
         "norm_window=%d, detection_delay=%d\r\n",
         TARANG_ECG_SAMPLE_RATE_HZ, DSP_MWI_WINDOW, DSP_REFRACTORY_SAMPLES,
         DSP_NORM_WINDOW, DSP_DETECTION_DELAY);
}

bool tarang_dsp_process_sample(tarang_dsp_state_t *state,
                                uint32_t raw_adc,
                                tarang_beat_output_t *beat)
{
  beat->valid = false;

  /* ── Step 1: Sanitize raw ADC → float ───────────────────────────── */
  /* Remove DC midpoint based on ADC resolution (12-bit / 16-bit / 24-bit) */
  uint32_t raw_val = raw_adc & 0x00FFFFFFu;
  float x;
  if (raw_val <= 4095u) {
    x = (float)raw_val - 2048.0f;       /* 12-bit ADC (IADC standard) */
  } else if (raw_val <= 65535u) {
    x = (float)raw_val - 32768.0f;      /* 16-bit ADC */
  } else {
    x = (float)raw_val - 8388608.0f;    /* 24-bit ADC */
  }

  /* Catch NaN/Inf from potential bad ADC values */
  if (!isfinite(x)) x = 0.0f;

  /* ── Step 2: Morphology bandpass (0.5–40Hz, 4 SOS sections) ─────── */
  float y_filt = sos_cascade_step(state->morph_sos, DSP_MORPH_SOS_SECTIONS, x);

  /* ── Step 3: Optional notch ─────────────────────────────────────── */
  float y_post_notch = notch_step(&state->notch, y_filt);

  /* ── Step 4: Rolling z-score normalization ───────────────────────── */
  float y_norm = rolling_norm_step(&state->norm, y_post_notch);

  /* ── Store in morphology ring buffer ────────────────────────────── */
  state->morph_ring[state->morph_write_idx] = y_norm;
  state->morph_write_idx = (state->morph_write_idx + 1) % DSP_MORPH_BUFFER_SIZE;

  /* ── Step 5: QRS bandpass (5–15Hz) — HP then LP ─────────────────── */
  float y_qrs = sos_cascade_step(state->qrs_hp, 1, y_post_notch);
  y_qrs = sos_cascade_step(state->qrs_lp, 1, y_qrs);

  /* ── Step 6: Derivative ─────────────────────────────────────────── */
  float y_deriv = derivative_step(state->deriv_delay, state->deriv_T, y_qrs);

  /* ── Step 7: Squaring ───────────────────────────────────────────── */
  float y_sq = y_deriv * y_deriv;

  /* ── Step 8: MWI ────────────────────────────────────────────────── */
  float y_mwi = mwi_step(&state->mwi, y_sq);

  state->debug_sample.sample_idx = (uint32_t)state->sample_idx;
  state->debug_sample.raw_adc = raw_val;
  state->debug_sample.bandpassed = y_post_notch;
  state->debug_sample.zscored = y_norm;
  state->debug_sample.mwi = y_mwi;
  state->debug_sample.threshold_th1 = state->thresh.TH1;
  state->debug_sample.warmed_up = state->warmed_up;

  /* ── Warm-up phase: collect MWI statistics, don't detect ────────── */
  if (!state->warmed_up) {
    if (y_mwi > state->warmup_mwi_max) state->warmup_mwi_max = y_mwi;
    state->warmup_mwi_sum += y_mwi;
    state->warmup_mwi_count++;

    if (state->warmup_mwi_count >= state->warmup_samples) {
      /* Initialize SPKI/NPKI from warm-up statistics */
      float npki_init = state->warmup_mwi_sum / (float)state->warmup_mwi_count;
      float spki_init = state->warmup_mwi_max * 0.5f; /* robust 50% max estimate */

      if (npki_init < 1e-6f) npki_init = 1e-4f;
      /* Cap SPKI so single transient spikes during warm-up can't strand TH1 */
      if (spki_init > npki_init * 4.0f) {
        spki_init = npki_init * 3.0f;
      }
      if (spki_init <= npki_init) spki_init = npki_init * 2.0f;

      state->thresh.SPKI = spki_init;
      state->thresh.NPKI = npki_init;
      state->thresh.TH1 = npki_init + 0.25f * (spki_init - npki_init);
      state->thresh.TH2 = 0.5f * state->thresh.TH1;
      state->thresh.current_idx = state->sample_idx;
      state->thresh.prev_mwi = 0.0f;
      state->thresh.prev_mwi_idx = -1;

      state->warmed_up = true;
      state->debug_sample.warmed_up = true;

      printf("[DSP] Warm-up complete: SPKI=%d NPKI=%d TH1=%d (x1000)\r\n",
             (int)(spki_init * 1000.0f),
             (int)(npki_init * 1000.0f),
             (int)(state->thresh.TH1 * 1000.0f));
    } else {
      state->sample_idx++;
      return false;
    }
  }

  /* ── Step 9: Adaptive threshold — R-peak detection ──────────────── */
  float slope_est = fabsf(y_deriv);
  int accepted_idx = adaptive_thresh_step(&state->thresh, y_mwi, slope_est);
  state->debug_sample.threshold_th1 = state->thresh.TH1;

  /* ── Step 10-12: If peak detected, add to pending ───────────────── */
  if (accepted_idx >= 0) {
    /* Find an empty pending slot */
    for (int i = 0; i < DSP_MAX_PENDING; i++) {
      if (!state->pending[i].active) {
        state->pending[i].mwi_peak_idx = accepted_idx;
        state->pending[i].mwi_peak_val = state->thresh.SPKI; /* approximation */
        state->pending[i].spki_at_detection = state->thresh.SPKI;
        state->pending[i].active = true;
        break;
      }
    }
  }

  /* ── Check pending for beat extraction ──────────────────────────── */
  /* Wait POST_R + RECENTER_RANGE samples after MWI peak before extracting */
  int post_wait = TARANG_BEAT_POST_R_SAMPLES + DSP_RECENTER_RANGE;

  for (int i = 0; i < DSP_MAX_PENDING; i++) {
    if (state->pending[i].active &&
        state->sample_idx >= state->pending[i].mwi_peak_idx + post_wait) {

      /* Recenter on morphology signal */
      int refined = recenter_peak(state, state->pending[i].mwi_peak_idx);

      /* Extract beat window + RR features */
      if (extract_beat(state, refined,
                        state->pending[i].mwi_peak_val,
                        state->pending[i].spki_at_detection,
                        beat)) {
        state->pending[i].active = false;
        state->sample_idx++;
        return true; /* beat emitted */
      }

      state->pending[i].active = false; /* extraction failed, discard */
    }
  }

  state->sample_idx++;
  return false;
}
