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
 * Firmware Version Identifiers
 ******************************************************************************/
#define TARANG_FW_VERSION_MAJOR         1
#define TARANG_FW_VERSION_MINOR         0
#define TARANG_FW_VERSION_PATCH         0
#define TARANG_FW_VERSION_STRING        "1.0.0"

/*******************************************************************************
 * Integration Feature Selection
 *
 * Keep these switches shared. Acquisition runs in app.c while BLE health and
 * telemetry decisions run in tarang_ble.c; translation-unit-local definitions
 * can otherwise make the two sides report different hardware states.
 ******************************************************************************/
#define TARANG_ENABLE_ECG               1
#define TARANG_ENABLE_PPG               1
#define TARANG_ENABLE_IMU               1
#define TARANG_ENABLE_BLE               1
#define TARANG_ENABLE_NLMS              1
#define TARANG_NLMS_APPLY_TO_DSP        1
#define TARANG_ENABLE_AI_CIRCUIT_BREAKER 1  /* Re-enable only after overload validation. */
#define TARANG_ENABLE_RAW_ECG_STREAM    0
#ifndef TARANG_ENABLE_VALIDATION_STREAM
#define TARANG_ENABLE_VALIDATION_STREAM 1  /* Compact stream fits the stable 115200-baud VCOM. */
#endif
#define TARANG_ANY_SENSOR_ENABLED \
  (TARANG_ENABLE_ECG || TARANG_ENABLE_PPG || TARANG_ENABLE_IMU)

/*******************************************************************************
 * Debug UART Logging Flags (Solution D: gate verbose prints to eliminate UART blocking)
 ******************************************************************************/
#ifndef TARANG_DEBUG_VERBOSE
#define TARANG_DEBUG_VERBOSE            0       /* 1=Verbose per-sample logs, 0=Demo-safe lean output */
#endif

#ifndef TARANG_DEBUG_RAW_ECG
#define TARANG_DEBUG_RAW_ECG            0       /* 1=Print raw ADC every 5th buffer, 0=Quiet */
#endif

/*******************************************************************************
 * ECG Acquisition Parameters (ADR-002)
 ******************************************************************************/
#define TARANG_ECG_SAMPLE_RATE_HZ       250
/* NOT CURRENTLY USED — reserved for future batch processing; pipeline currently processes single samples */
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
/* NOT CURRENTLY USED — actual warmup governed by warmup_samples (8 * 250) in tarang_dsp.c:565 */
#define TARANG_SPKI_STARTUP_DELAY_SEC   3       /* seconds before threshold locks */
#define TARANG_SPKI_STARTUP_SAMPLES     (TARANG_SPKI_STARTUP_DELAY_SEC * TARANG_ECG_SAMPLE_RATE_HZ)
/* NOT CURRENTLY USED — reserved for future adaptive ceiling tuning */
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
 * Tier-0 Trigger Heuristic Thresholds (frozen)
 ******************************************************************************/
#define TARANG_PREMATURITY_RATIO_NUM    85      /* rr_interval / rr_mean_5 < 0.85 (85/100) */
#define TARANG_PREMATURITY_RATIO_DENOM  100
#define TARANG_COMPENSATORY_PAUSE_NUM   3       /* rr_interval > 1.5 * mean (3/2) */
#define TARANG_COMPENSATORY_PAUSE_DENOM 2
#define TARANG_CIRCUIT_BREAKER_MAX_SUSP_PCT 20

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
#define TARANG_AFIB_COV_THRESHOLD_PCT   12u     /* CoV > 12% */
#define TARANG_AFIB_PRR50_THRESHOLD     0.10f
#define TARANG_AFIB_PRR50_THRESHOLD_PCT 10u     /* pRR50 > 10% */
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
 * BLE Device Health Telemetry Packet (Low-rate 1Hz channel, 16 bytes packed)
 ******************************************************************************/
typedef struct __attribute__((packed)) {
  uint32_t uptime_s;            /* 4 bytes — device uptime in seconds */
  uint8_t  ecg_lead_off;        /* 1 byte  — 0=attached, 1=detached/saturated */
  uint8_t  ecg_sqi;             /* 1 byte  — 0-255 signal quality */
  uint8_t  ppg_finger_present;  /* 1 byte  — 0=absent, 1=present */
  uint8_t  imu_ok;              /* 1 byte  — 0=offline, 1=healthy */
  uint8_t  i2c_failure_count;   /* 1 byte  — consecutive I2C failures (clamped to 255) */
  uint8_t  dsp_overflow_count;  /* 1 byte  — DSP pending queue overflows */
  uint8_t  ecg_overrun_count;   /* 1 byte  — DMA overrun count */
  int8_t   ble_rssi;            /* 1 byte  — RSSI in dBm or 127 if unavailable */
  uint8_t  battery_pct;         /* 1 byte  — 255 = unavailable / no sensor */
  uint8_t  status_flags;        /* 1 byte  — reserved status bitfield */
  uint16_t fw_version_packed;   /* 2 bytes — (major << 8) | minor */
} tarang_health_packet_t;       /* 16 bytes total */

/*******************************************************************************
 * Reserved Device Status Flags
 *
 * The current generated GATT database does not expose a device-health
 * characteristic. Keep these values reserved until that characteristic is
 * added through Simplicity Studio; do not alias them onto an analytics UUID.
 ******************************************************************************/
#define TARANG_STATUS_CHARGING          0x01u   /* Bit 0: 1=External power connected, 0=Battery */
#define TARANG_STATUS_LOW_POWER_MODE    0x02u   /* Bit 1: 1=EM2 power-saving active, 0=EM0/EM1 */
#define TARANG_STATUS_LOG_BUFFER_FULL   0x04u   /* Bit 2: 1=Local circular storage log full */
#define TARANG_STATUS_AI_TIER_ACTIVE    0x08u   /* Bit 3: 1=INT8 AI Cascade engaged on last beat */
#define TARANG_STATUS_CALIBRATED        0x10u   /* Bit 4: 1=Baseline ECG/PPG calibration locked */
#define TARANG_STATUS_LEAD_FAULT_LO_POS 0x20u   /* Bit 5: 1=AD8232 LO+ pin asserted */
#define TARANG_STATUS_LEAD_FAULT_LO_NEG 0x40u   /* Bit 6: 1=AD8232 LO- pin asserted */
#define TARANG_STATUS_RESERVED_BIT7     0x80u   /* Bit 7: Reserved */

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

/** IMU ring buffer size: 64 entries at 100 Hz = 640 ms alignment history. */
#define TARANG_IMU_RING_SIZE            64

/** PPG ring buffer size — 16 entries at 100Hz = 160ms history */
#define TARANG_PPG_RING_SIZE            16

#ifdef __cplusplus
}
#endif

#endif /* TARANG_CONSTANTS_H */
