/***************************************************************************//**
 * @file tarang_ble.h
 * @brief TARANG Bluetooth Low Energy (BLE) Telemetry Module Header.
 *
 * TARANG Mode A (Event-Driven) BLE Telemetry:
 *   - Service A: Vitals (Periodic 2-5s notify: HR, SpO2, Timestamp)
 *   - Service B: Analytics (Periodic 5-min notify: Burden, HRV, AI Duty Cycle, EM2 Sleep)
 *   - Service C: ClinicalEvent (Event-driven notify: Rhythm, Meta, Snippet Chunks, Annotations, Ticker)
 *
 * Target : EFR32MG26B510F3200IM48 (Series 2, Cortex-M33)
 ******************************************************************************/
#ifndef TARANG_BLE_H
#define TARANG_BLE_H

#include <stdbool.h>
#include <stdint.h>
#include "tarang_constants.h"
#include "tarang_pipeline.h"

#ifdef __cplusplus
extern "C" {
#endif

/*******************************************************************************
 * Mode A BLE Packet Structures (Packed, byte-exact)
 ******************************************************************************/

/** Service A: Vitals Packet (Periodic 2-5s) */
typedef struct __attribute__((packed)) {
  uint16_t heart_rate_bpm;      /* 2B: BPM (fused ECG+PPG 8-beat rolling mean) */
  uint8_t  spo2_pct;            /* 1B: % (MAX30102) */
  uint32_t timestamp_ms;        /* 4B: Epoch / uptime tick for last update */
} tarang_ble_vitals_packet_t;

/** Service B: 5-Min Analytics Rollup Packet (Periodic 5-min) */
typedef struct __attribute__((packed)) {
  uint8_t  pvc_burden_pct;      /* 1B: 0-100% */
  uint8_t  pac_burden_pct;      /* 1B: 0-100% */
  uint16_t sdnn_ms;             /* 2B: ms */
  uint16_t rmssd_ms;            /* 2B: ms */
  uint8_t  prr50_pct;           /* 1B: % (0-100) */
  uint8_t  ai_duty_cycle_pct10; /* 1B: Duty cycle % fixed-point x10 (e.g. 15 = 1.5%) */
  uint8_t  em2_sleep_pct;       /* 1B: EM2 Sleep % (0-100) */
} tarang_ble_analytics_packet_t;

/** Service C: Clinical Event Meta Packet */
typedef struct __attribute__((packed)) {
  uint16_t event_id;            /* 2B: Monotonic event counter */
  uint8_t  event_type;          /* 1B: Rhythm / arrhythmia enum */
  uint8_t  confidence;          /* 1B: 0-255 */
  uint32_t timestamp_ms;        /* 4B: Timestamp of anomaly onset */
} tarang_ble_event_meta_t;

/** Service C: Glitch Ticker Event Packet */
typedef struct __attribute__((packed)) {
  uint16_t pattern_type;        /* 2B: 1=Couplet, 2=Triplet, 3=Bigeminy, 4=Trigeminy, 5=V-Run, 6=SVT-Run */
  uint32_t timestamp_ms;        /* 4B: Event timestamp */
} tarang_ble_glitch_ticker_t;

/** Service C: Beat Annotation entry */
typedef struct __attribute__((packed)) {
  uint16_t offset_ms;           /* 2B: Offset in ms from snippet start (0..4000) */
  uint8_t  label;               /* 1B: 'N' (0), 'S' (1), 'V' (2), 'Q' (3) */
  uint8_t  confidence;          /* 1B: 0-255 */
} tarang_ble_beat_annotation_t;

/** Snippet chunk packet layout (up to 240 bytes payload per indication) */
#define TARANG_SNIPPET_CHUNK_MAX_SAMPLES 110  /* 110 int16 samples = 220B + 4B header */
typedef struct __attribute__((packed)) {
  uint16_t sequence_id;         /* 2B: Chunk index (0, 1, 2...) */
  uint16_t total_chunks;        /* 2B: Total chunks in this 4s transfer */
  int16_t  samples[TARANG_SNIPPET_CHUNK_MAX_SAMPLES]; /* 250Hz * 4s = 1000 samples (~10 chunks) */
} tarang_ble_snippet_chunk_t;

/*******************************************************************************
 * Public API
 ******************************************************************************/

/***************************************************************************//**
 * @brief Initialize BLE module and prepare advertising / state.
 ******************************************************************************/
void tarang_ble_init(void);

/***************************************************************************//**
 * @brief Check if BLE client is currently connected.
 ******************************************************************************/
bool tarang_ble_is_connected(void);

/***************************************************************************//**
 * @brief Check if BLE notifications/indications are enabled.
 ******************************************************************************/
bool tarang_ble_is_notifications_enabled(void);

/***************************************************************************//**
 * @brief Dispatch Mode A BLE periodic and event-driven data.
 *
 * @param[in,out] pipeline  Pointer to the pipeline instance.
 ******************************************************************************/
void tarang_ble_process(tarang_pipeline_t *pipeline);

/***************************************************************************//**
 * @brief Send Mode A Service A Vitals notification (Heart Rate + SpO2 + Timestamp).
 ******************************************************************************/
bool tarang_ble_send_vitals(uint16_t hr_bpm, uint8_t spo2_pct, uint32_t ts_ms);

/***************************************************************************//**
 * @brief Send Mode A Service B 5-Min Analytics rollup notification.
 ******************************************************************************/
bool tarang_ble_send_analytics(const tarang_ble_analytics_packet_t *analytics);

/***************************************************************************//**
 * @brief Trigger Mode A Service C Clinical Event push (meta + snippet + annotations).
 ******************************************************************************/
bool tarang_ble_trigger_clinical_event(
    uint8_t rhythm_status,
    uint16_t pattern_type,
    uint8_t confidence,
    uint32_t ts_ms,
    const int16_t *ecg_4s_samples,
    uint16_t sample_count,
    const tarang_ble_beat_annotation_t *annotations,
    uint8_t annotation_count);

/***************************************************************************//**
 * @brief Build legacy health packet for diagnostics compatibility.
 ******************************************************************************/
void tarang_ble_build_health_packet(tarang_pipeline_t *pipeline, tarang_health_packet_t *pkt);

#ifdef __cplusplus
}
#endif

#endif /* TARANG_BLE_H */
