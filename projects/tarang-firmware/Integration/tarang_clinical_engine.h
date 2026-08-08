/***************************************************************************//**
 * @file tarang_clinical_engine.h
 * @brief TARANG Clinical Event Engine — public API.
 *
 * Tier 3: Deterministic rhythm analysis. Runs on EVERY beat regardless of
 * whether the CNN fired. No neural network, no heap, pure C ring-buffer
 * arithmetic.
 *
 * Detects:
 *   - AFib (RR-based: CoV, pRR50, RMSSD — published ≥95% sensitivity)
 *   - PVC/PAC burden (running percentage)
 *   - Couplets, Triplets (consecutive ectopics)
 *   - Bigeminy (N-V-N-V-N-V), Trigeminy (N-N-V-N-N-V)
 *   - V-Run (≥3 consecutive V) → VT (≥5 V + HR>100)
 *   - SVT-Run (≥3 consecutive S)
 *   - Sinus Tachycardia / Bradycardia
 *   - HRV metrics (SDNN, RMSSD, pRR50)
 *
 * References:
 *   - Tarang_Architecture_Resolution_FINAL.md (Tier 3 spec)
 *   - Tarang_Arrhythmia_Pipeline_Design.md (Phase C)
 *   - Lynn 1991, Tateno 2001, Linker 2003 (AFib RR-based detection)
 *
 * Target : EFR32MG26B510F3200IM48 (Series 2, Cortex-M33)
 ******************************************************************************/
#ifndef TARANG_CLINICAL_ENGINE_H
#define TARANG_CLINICAL_ENGINE_H

#include <stdint.h>
#include <stdbool.h>
#include "tarang_constants.h"

#ifdef __cplusplus
extern "C" {
#endif

/*******************************************************************************
 * Engine State (all static ring buffers, zero heap)
 ******************************************************************************/
typedef struct {
  /* 30-beat RR rolling window for AFib + HRV */
  uint16_t rr_buffer[TARANG_RR_WINDOW_SIZE];
  uint8_t  rr_head;
  uint8_t  rr_count;

  /* 8-beat pattern buffer for bigeminy/trigeminy */
  uint8_t  pattern_buffer[TARANG_PATTERN_WINDOW_SIZE];
  uint8_t  pattern_head;
  uint8_t  pattern_count;

  /* Running counters */
  uint32_t total_beats;
  uint32_t pac_count;           /* S-class beats */
  uint32_t pvc_count;           /* V-class beats */

  /* Consecutive ectopic tracking */
  uint8_t  consecutive_v;
  uint8_t  consecutive_s;
  uint8_t  max_consecutive_v;   /* longest V-run in session */

  /* AFib state */
  uint16_t afib_consecutive_beats;  /* how many consecutive beats meet criteria */

  /* Current computed values */
  uint8_t  current_hr;          /* BPM */
  uint8_t  rhythm_flags;        /* bitfield: TARANG_RHYTHM_* */
  uint8_t  prev_rhythm_flags;   /* for change detection */

  /* HRV metrics (updated every 30 beats) */
  uint16_t sdnn_ms;
  uint16_t rmssd_ms;
  uint8_t  prr50_pct;           /* pRR50 as percentage (0-100) */

  /* Last beat class for compensatory pause detection */
  uint8_t  last_beat_class;

  /* Flag: rhythm_flags changed since last query */
  bool     rhythm_changed;
  bool     significant_event;   /* couplet, triplet, V-run, VT */
} tarang_clinical_engine_t;

/*******************************************************************************
 * Public API
 ******************************************************************************/

/***************************************************************************//**
 * @brief Initialize the clinical engine. Zeroes all state.
 * @param[out] engine  Pointer to engine state struct.
 ******************************************************************************/
void tarang_clinical_engine_init(tarang_clinical_engine_t *engine);

/***************************************************************************//**
 * @brief Process one beat through the clinical engine.
 *
 * Call this on EVERY beat, regardless of CNN result. Updates rhythm_flags,
 * HRV metrics, pattern detection, and burden counters.
 *
 * @param[in,out] engine  Engine state.
 * @param[in]     beat    Beat input from DSP/ML pipeline.
 ******************************************************************************/
void tarang_clinical_engine_process_beat(tarang_clinical_engine_t *engine,
                                         const tarang_beat_input_t *beat);

/***************************************************************************//**
 * @brief Build a 16-byte BLE event packet from current engine state.
 *
 * @param[in]  engine  Engine state.
 * @param[in]  beat    The beat that triggered this packet.
 * @param[out] pkt     Filled event packet.
 ******************************************************************************/
void tarang_clinical_engine_build_packet(const tarang_clinical_engine_t *engine,
                                          const tarang_beat_input_t *beat,
                                          tarang_event_packet_t *pkt);

/***************************************************************************//**
 * @brief Check if rhythm_flags changed since last call to this function.
 *
 * Clears the internal flag after reading.
 *
 * @param[in,out] engine  Engine state.
 * @return true if rhythm_flags changed.
 ******************************************************************************/
bool tarang_clinical_engine_rhythm_changed(tarang_clinical_engine_t *engine);

/***************************************************************************//**
 * @brief Check if a significant event occurred (couplet, triplet, V-run, VT).
 *
 * Clears the internal flag after reading.
 *
 * @param[in,out] engine  Engine state.
 * @return true if a significant event was detected.
 ******************************************************************************/
bool tarang_clinical_engine_significant_event(tarang_clinical_engine_t *engine);

#ifdef __cplusplus
}
#endif

#endif /* TARANG_CLINICAL_ENGINE_H */
