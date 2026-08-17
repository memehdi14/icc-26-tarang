/***************************************************************************//**
 * @file tarang_dsp.h
 * @brief TARANG DSP module — streaming Pan-Tompkins R-peak detection.
 *
 * Direct C port of tarang_dsp_reference.py (v16, StreamingTarangDSP).
 * Every block is a single-sample step function. No vectorized sibling.
 *
 * Processing chain (per sample):
 *   1. Sanitize raw ADC → float
 *   2. Morphology bandpass (0.5–40Hz, Butterworth order 4, SOS cascade)
 *   3. Optional notch (50/60Hz, second-order IIR)
 *   4. Rolling z-score normalization (30s window)
 *   5. QRS bandpass (5–15Hz, Butterworth order 2)
 *   6. 5-tap causal derivative
 *   7. Squaring
 *   8. Moving-window integration (N=38 samples, ~152ms)
 *   9. Adaptive threshold + refractory + search-back + T-wave rejection
 *  10. Detection delay correction (−29 samples)
 *  11. Recenter on morphology signal (±15 samples)
 *  12. Extract 130-sample beat window + 4 RR features
 *
 * ZERO heap. All buffers are static arrays inside tarang_dsp_state_t.
 *
 * Target : EFR32MG26B510F3200IM48 (Series 2, Cortex-M33)
 ******************************************************************************/
#ifndef TARANG_DSP_H
#define TARANG_DSP_H

#include <stdint.h>
#include <stdbool.h>
#include "tarang_constants.h"

#ifdef __cplusplus
extern "C" {
#endif

/*******************************************************************************
 * Configuration Constants
 ******************************************************************************/
#define DSP_MORPH_SOS_SECTIONS      4   /* order 4 bandpass = 4 SOS sections */
#define DSP_QRS_SOS_SECTIONS        2   /* order 2 HP + LP = 1+1 sections */
#define DSP_DERIV_TAPS              4   /* 5-tap causal derivative delay line */
#define DSP_MORPH_BUFFER_SIZE       256 /* ring buffer for morphology signal */
#define DSP_MWI_WINDOW              38  /* ~152ms at 250Hz */
#define DSP_NORM_WINDOW             7500 /* 30s × 250Hz */
#define DSP_REFRACTORY_SAMPLES      50  /* 200ms at 250Hz */
#define DSP_DETECTION_DELAY         29  /* cumulative group delay correction */
#define DSP_RECENTER_RANGE          15  /* ±15 samples */
#define DSP_RR_HISTORY_SIZE         8   /* last 8 RR for search-back */
#define DSP_CANDIDATE_BUFFER_SIZE   16  /* pending candidates for search-back */
#define DSP_RPEAK_HISTORY_SIZE      8   /* last 8 R-peaks for RR features */

/*******************************************************************************
 * Beat Output (passed to pipeline)
 ******************************************************************************/
typedef struct {
  float    waveform[TARANG_BEAT_WINDOW_SIZE]; /* 130 z-scored samples */
  float    rr_features[TARANG_RR_FEATURE_COUNT]; /* 4 causal RR features */
  uint32_t r_peak_sample_idx;   /* absolute sample index */
  uint8_t  signal_quality;      /* 0-255 */
  bool     valid;               /* false = extraction failed */
} tarang_beat_output_t;

typedef struct {
  uint32_t sample_idx;
  uint32_t raw_adc;
  float    bandpassed;
  float    zscored;
  float    mwi;
  float    threshold_th1;
  bool     warmed_up;
} tarang_dsp_debug_sample_t;

/*******************************************************************************
 * SOS Biquad State
 ******************************************************************************/
typedef struct {
  float b0, b1, b2;
  float a1, a2;     /* a0 is always 1.0 */
  float z1, z2;     /* delay state (transposed direct form II) */
} dsp_biquad_t;

/*******************************************************************************
 * Notch Filter State
 ******************************************************************************/
typedef struct {
  float b0, b1, b2;
  float a1, a2;
  float z1, z2;
  bool  enabled;
} dsp_notch_t;

/*******************************************************************************
 * Rolling Z-Score Normalization State
 ******************************************************************************/
typedef struct {
  float  ring[DSP_NORM_WINDOW];
  double S1;            /* running sum */
  double S2;            /* running sum of squares */
  int    count;         /* valid count (0..DSP_NORM_WINDOW) */
  int    idx;           /* write index */
} dsp_rolling_norm_t;

/*******************************************************************************
 * MWI State (ring buffer + running sum)
 ******************************************************************************/
typedef struct {
  float ring[DSP_MWI_WINDOW];
  float S;              /* running sum */
  int   count;
  int   idx;
} dsp_mwi_t;

/*******************************************************************************
 * Adaptive Threshold State
 ******************************************************************************/
typedef struct {
  int   idx;
  float val;
} dsp_candidate_t;

typedef struct {
  float SPKI, NPKI, TH1, TH2;
  int   refractory_remaining;
  int   last_R_idx;
  float last_R_slope;
  int   current_idx;

  /* RR history for search-back */
  int   rr_history[DSP_RR_HISTORY_SIZE];
  int   rr_count;
  float recent_rr_mean;

  /* Search-back candidate buffer */
  dsp_candidate_t candidates[DSP_CANDIDATE_BUFFER_SIZE];
  int   n_candidates;

  /* Local-max detection (Phase 2 refactor) */
  float prev_mwi;
  int   prev_mwi_idx;

  /* SPKI clamp */
  float spki_max_step_ratio;

  /* Default RR for bootstrap */
  int   default_rr_samples;
} dsp_adaptive_thresh_t;

/*******************************************************************************
 * Pending Beat (waiting for POST_R samples after detection)
 ******************************************************************************/
typedef struct {
  int   mwi_peak_idx;
  float mwi_peak_val;
  float spki_at_detection;
  bool  active;
} dsp_pending_beat_t;

#define DSP_MAX_PENDING   4

/*******************************************************************************
 * Master DSP State
 ******************************************************************************/
typedef struct {
  /* Block 1: Morphology bandpass (0.5-40Hz, order 4) */
  dsp_biquad_t morph_sos[DSP_MORPH_SOS_SECTIONS];

  /* Block 2: Optional notch */
  dsp_notch_t notch;

  /* Block 3: Rolling z-score */
  dsp_rolling_norm_t norm;

  /* Block 4: QRS bandpass (5-15Hz) — separate HP + LP */
  dsp_biquad_t qrs_hp[1];    /* order 2 HP = 1 SOS section */
  dsp_biquad_t qrs_lp[1];    /* order 2 LP = 1 SOS section */

  /* Block 5: Derivative delay line */
  float deriv_delay[DSP_DERIV_TAPS]; /* x[n-1]..x[n-4] */
  float deriv_T;

  /* Block 7: MWI */
  dsp_mwi_t mwi;

  /* Block 8: Adaptive threshold */
  dsp_adaptive_thresh_t thresh;

  /* Morphology ring buffer (z-scored signal for beat extraction) */
  float morph_ring[DSP_MORPH_BUFFER_SIZE];
  int   morph_write_idx;

  /* Pending beats */
  dsp_pending_beat_t pending[DSP_MAX_PENDING];

  /* R-peak history for RR features */
  int   rpeak_history[DSP_RPEAK_HISTORY_SIZE];
  int   rpeak_count;

  /* Global sample counter */
  int   sample_idx;

  /* Warm-up */
  bool  warmed_up;
  int   warmup_samples;
  float warmup_mwi_max;
  float warmup_mwi_sum;
  int   warmup_mwi_count;

  /* Pending beat overflow diagnostic counter */
  uint32_t pending_overflow_count;

  /* Latest intermediate values for validation telemetry. */
  tarang_dsp_debug_sample_t debug_sample;
} tarang_dsp_state_t;

/*******************************************************************************
 * Public API
 ******************************************************************************/

/***************************************************************************//**
 * @brief Get total number of pending beat buffer overflows.
 * @param[in] state  DSP state struct.
 * @return Count of dropped beats due to full pending queue.
 ******************************************************************************/
uint32_t tarang_dsp_get_pending_overflow_count(const tarang_dsp_state_t *state);

/***************************************************************************//**
 * @brief Initialize DSP state. Designs all filters, zeroes all state.
 * @param[out] state  DSP state struct.
 ******************************************************************************/
void tarang_dsp_init(tarang_dsp_state_t *state);

/***************************************************************************//**
 * @brief Process one raw ECG sample through the full DSP chain.
 *
 * Call at 250Hz. Returns a beat output if an R-peak was detected and
 * the beat window is ready for extraction.
 *
 * @param[in,out] state   DSP state.
 * @param[in]     raw_adc Raw 24-bit ADC value from IADC.
 * @param[out]    beat    Beat output (valid only if return is true).
 * @return true if a beat was emitted this sample.
 ******************************************************************************/
bool tarang_dsp_process_sample(tarang_dsp_state_t *state,
                                uint32_t raw_adc,
                                tarang_beat_output_t *beat);

#ifdef __cplusplus
}
#endif

#endif /* TARANG_DSP_H */
