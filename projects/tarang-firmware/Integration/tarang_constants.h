/***************************************************************************//**
 * @file tarang_constants.h
 * @brief TARANG frozen parameters, shared types, and diagnostic counters.
 *
 * All frozen DSP/ML parameters live here. Do NOT retune these without
 * re-running the 75-record validation and updating golden vectors.
 *
 * References:
 *   - DSP KB v16, Section 3.3 (frozen parameters)
 *   - Architecture Resolution FINAL (window sizes, RR feature order)
 *   - ADR-002 (ECG frame = 256 samples)
 *   - ADR-005 (event-gated AI)
 *
 * Target : EFR32MG26B510F3200IM48 (Series 2, Cortex-M33)
 ******************************************************************************/
#ifndef TARANG_CONSTANTS_H
#define TARANG_CONSTANTS_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*******************************************************************************
 * ECG Acquisition Parameters (ADR-002)
 ******************************************************************************/
#define TARANG_ECG_SAMPLE_RATE_HZ       250
#define TARANG_ECG_FRAME_SIZE           256     /* 1.024s per frame */
#define TARANG_ECG_SAMPLE_PERIOD_US     4000    /* 1e6 / 250 */

/*******************************************************************************
 * IMU Acquisition Parameters
 ******************************************************************************/
#define TARANG_IMU_SAMPLE_RATE_HZ       100
#define TARANG_IMU_SAMPLE_PERIOD_US     10000   /* 1e6 / 100 */

/*******************************************************************************
 * PPG Acquisition Parameters
 ******************************************************************************/
#define TARANG_PPG_SAMPLE_RATE_HZ       100
#define TARANG_PPG_SAMPLE_PERIOD_US     10000   /* 1e6 / 100 */

/*******************************************************************************
 * DSP Frozen Parameters (Section 3.3 — use these exact values, don't retune)
 ******************************************************************************/

/* ML beat window: 130 samples (65 pre-R + 65 post-R, R at index 65)
 * This supersedes any reference to 256-sample beat windows. */
#define TARANG_BEAT_WINDOW_SIZE         130
#define TARANG_BEAT_PRE_R_SAMPLES       65
#define TARANG_BEAT_POST_R_SAMPLES      65

/* Morphology bandpass: 0.5–40 Hz, Butterworth order 4 */
#define TARANG_MORPH_BP_LOW_HZ          0.5f
#define TARANG_MORPH_BP_HIGH_HZ         40.0f
#define TARANG_MORPH_BP_ORDER           4

/* QRS detection bandpass: 5–15 Hz, Butterworth order 2 */
#define TARANG_QRS_BP_LOW_HZ            5.0f
#define TARANG_QRS_BP_HIGH_HZ           15.0f
#define TARANG_QRS_BP_ORDER             2

/* Moving Window Integrator */
#define TARANG_MWI_WINDOW_SIZE          38      /* ~152ms at 250Hz */

/* Pan-Tompkins refractory period */
#define TARANG_REFRACTORY_SAMPLES       50      /* 200ms at 250Hz */

/* Candidate recenter search range */
#define TARANG_RECENTER_RANGE           15      /* ±15 samples */

/* Detection delay correction */
#define TARANG_DETECTION_DELAY          29      /* samples */

/* Rolling z-score normalization window */
#define TARANG_ZSCORE_WINDOW_SEC        30      /* seconds */
#define TARANG_ZSCORE_WINDOW_SAMPLES    (TARANG_ZSCORE_WINDOW_SEC * TARANG_ECG_SAMPLE_RATE_HZ)

/* SPKI lock-in fix parameters */
#define TARANG_SPKI_STARTUP_DELAY_SEC   3       /* seconds before threshold locks */
#define TARANG_SPKI_STARTUP_SAMPLES     (TARANG_SPKI_STARTUP_DELAY_SEC * TARANG_ECG_SAMPLE_RATE_HZ)
#define TARANG_SPKI_CEILING_MULT        5.0f    /* 5 × (median + 3×MAD) */
#define TARANG_PEAK_TIMEOUT_SAMPLES     750     /* 3 seconds, force TH1 reset */

/* Search-back gamma */
#define TARANG_SEARCHBACK_GAMMA         1.66f

/*******************************************************************************
 * RR Feature Order (frozen, 4 features — supersedes older "7 features")
 ******************************************************************************/
#define TARANG_RR_FEATURE_COUNT         4
/* Order: [rr_prev_ms, rr_mean_5_ms, rr_std_5_ms, local_hr_bpm] */
#define TARANG_RR_FEAT_RR_PREV          0
#define TARANG_RR_FEAT_RR_MEAN_5        1
#define TARANG_RR_FEAT_RR_STD_5         2
#define TARANG_RR_FEAT_LOCAL_HR         3

/*******************************************************************************
 * ML Thresholds (ADR-005, event-gated)
 ******************************************************************************/
/* LOCKED thresholds from validation Step 4
 * Run ID: 20260716_002728_72352b61 (thresholds.h) */
#define TARANG_GATE_THRESHOLD           0.2500f  /* P(abnormal) > 0.25 → Tier 2 */
#define TARANG_V_THRESHOLD              0.6000f  /* P(V) > 0.60 → V class (PVC) */
#define TARANG_S_THRESHOLD              0.3500f  /* P(S) > 0.35 → S class (PAC) */

/*******************************************************************************
 * Beat Classification Labels
 ******************************************************************************/
#define TARANG_BEAT_N                   0       /* Normal */
#define TARANG_BEAT_S                   1       /* Supraventricular (PAC) */
#define TARANG_BEAT_V                   2       /* Ventricular (PVC) */
#define TARANG_BEAT_Q                   3       /* Unclassifiable / poor quality */

/*******************************************************************************
 * Clinical Event Engine Parameters
 ******************************************************************************/
#define TARANG_RR_WINDOW_SIZE           30      /* 30-beat rolling window */
#define TARANG_PATTERN_WINDOW_SIZE      8       /* 8-beat pattern buffer */
#define TARANG_HR_WINDOW_SIZE           8       /* last 8 RR for HR calc */

/* AFib thresholds (published, validated on MIT-BIH AFDB) */
#define TARANG_AFIB_COV_THRESHOLD       0.12f
#define TARANG_AFIB_PRR50_THRESHOLD     0.10f
#define TARANG_AFIB_RMSSD_THRESHOLD_MS  30.0f
#define TARANG_AFIB_MIN_RR_MS           600     /* exclude extreme brady */
#define TARANG_AFIB_MAX_RR_MS           1000    /* exclude extreme tachy */

/* HR thresholds */
#define TARANG_TACHYCARDIA_BPM          100
#define TARANG_BRADYCARDIA_BPM          60

/* VT detection */
#define TARANG_VT_MIN_CONSECUTIVE_V     5
#define TARANG_VT_MIN_HR                100

/* Signal quality gate */
#define TARANG_SQI_MIN                  128     /* 0-255 scale */

/*******************************************************************************
 * Rhythm Flags Bitfield (BLE event packet, Section 6.5)
 ******************************************************************************/
#define TARANG_RHYTHM_NORMAL            0x00
#define TARANG_RHYTHM_AFIB              0x01
#define TARANG_RHYTHM_SINUS_TACH        0x02
#define TARANG_RHYTHM_SINUS_BRADY       0x04
#define TARANG_RHYTHM_BIGEMINY          0x08
#define TARANG_RHYTHM_TRIGEMINY         0x10
#define TARANG_RHYTHM_V_RUN             0x20
#define TARANG_RHYTHM_SVT_RUN           0x40
#define TARANG_RHYTHM_VT_SUSPECTED      0x80    /* CRITICAL — life-threatening */

/*******************************************************************************
 * BLE Event Packet (Section 6.5 — exact struct, 16 bytes packed)
 ******************************************************************************/
typedef struct __attribute__((packed)) {
  uint32_t timestamp_ms;        /* 4 bytes */
  uint8_t  beat_class;          /* 1 byte  — N=0, S=1, V=2, Q=3 */
  uint8_t  confidence;          /* 1 byte  — 0-255 */
  uint16_t rr_interval_ms;      /* 2 bytes */
  uint8_t  rhythm_flags;        /* 1 byte  — bitfield above */
  uint8_t  pac_burden_pct;      /* 1 byte */
  uint8_t  pvc_burden_pct;      /* 1 byte */
  uint8_t  current_hr;          /* 1 byte */
  uint16_t sdnn_ms;             /* 2 bytes */
  uint16_t rmssd_ms;            /* 2 bytes */
} tarang_event_packet_t;        /* 16 bytes total */

/*******************************************************************************
 * Beat Input (DSP/ML → Clinical Engine interface)
 ******************************************************************************/
typedef struct {
  uint32_t timestamp_ms;
  uint8_t  beat_class;          /* TARANG_BEAT_N / S / V / Q */
  uint8_t  confidence;          /* 0-255 */
  uint16_t rr_interval_ms;
  uint8_t  signal_quality;      /* 0=bad, 255=excellent */
} tarang_beat_input_t;

/*******************************************************************************
 * Firmware Diagnostic Counters (Section 6.9 — add now, not later)
 ******************************************************************************/
typedef struct {
  uint32_t frames_processed;
  uint32_t dsp_time_us;
  uint32_t nlms_time_us;
  uint32_t rpeak_time_us;
  uint32_t ai_trigger_count;
  uint32_t ai_time_us;
  uint32_t ble_packet_count;
  uint32_t sleep_time_us;
  uint32_t dropped_frames;
  uint32_t dma_overruns;
  uint32_t watchdog_feeds;
  uint32_t sequence_gaps;
} tarang_diagnostics_t;

/*******************************************************************************
 * Timestamped Ring Buffer Sample Types (Phase 1.5)
 ******************************************************************************/

/** IMU timestamped sample for causal nearest-past lookup */
typedef struct {
  uint64_t t_us;
  int16_t  ax, ay, az;
  int16_t  gx, gy, gz;
} tarang_imu_sample_t;

/** PPG timestamped sample for validation cross-check */
typedef struct {
  uint64_t t_us;
  uint32_t red;
  uint32_t ir;
} tarang_ppg_sample_t;

/** IMU ring buffer size — 16 entries at 100Hz = 160ms history */
#define TARANG_IMU_RING_SIZE            16

/** PPG ring buffer size — 16 entries at 100Hz = 160ms history */
#define TARANG_PPG_RING_SIZE            16

#ifdef __cplusplus
}
#endif

#endif /* TARANG_CONSTANTS_H */
