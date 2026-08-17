/***************************************************************************//**
 * @file
 * @brief TARANG Integration — Orchestrator
 *
 * Thin orchestrator that initializes and processes all 3 sensor modules.
 * Each module is a direct extraction from its proven individual test project.
 *
 * Sensors:
 *   ECG  — LETIMER→PRS→IADC→DMADRV ping-pong (from ECG/july6)
 *   PPG  — MAX30102 I2C interrupt-driven      (from PPG/ppg)
 *   IMU  — MPU6050 I2C interrupt-driven        (from IMU/AMIMU)
 *
 * Target : EFR32MG26B510F3200IM48 (BRD2709A)
 *
 * ─── TEST MODE SELECTOR ─────────────────────────────────────────────────
 *
 * Set EXACTLY ONE of these to 1 before building to test that sensor alone.
 * Set ALL THREE to 1 for the full combined integration test.
 *
 *   TARANG_ENABLE_ECG   — ECG analog acquisition (IADC + DMADRV)
 *   TARANG_ENABLE_PPG   — PPG optical sensor     (MAX30102 I2C)
 *   TARANG_ENABLE_IMU   — IMU motion sensor      (MPU6050 I2C)
 *
 * Example: to test only ECG, set ECG=1, PPG=0, IMU=0 and rebuild.
 * ─────────────────────────────────────────────────────────────────────────
 ******************************************************************************/

#include "app.h"
#include "tarang_constants.h"
#include "tarang_pipeline.h"
#include "tarang_ecg.h"
#include "tarang_ppg.h"
#include "tarang_imu.h"
#include "tarang_ble.h"

#include <stdio.h>
#include <stdint.h>

#include "em_cmu.h"
#include "gpiointerrupt.h"
#include "sl_i2cspm_instances.h"

#if defined(SL_CATALOG_POWER_MANAGER_PRESENT)
#include "sl_power_manager.h"
#endif

/* Simple delay for sensor power-up stabilization */
static void delay_ms(uint32_t ms)
{
  for (volatile uint32_t i = 0; i < ms * 4000u; i++) { }
}

/*******************************************************************************
 * TEST MODE — Change these to select which sensors are active.
 * For individual testing, enable only one at a time.
 * For full integration, enable all three.
 ******************************************************************************/
#define TARANG_ENABLE_ECG   1
#define TARANG_ENABLE_PPG   1
#define TARANG_ENABLE_IMU   1
#define TARANG_ENABLE_BLE   1
#define TARANG_ENABLE_RAW_ECG_STREAM 1

#ifndef TARANG_RUN_BOOT_TESTS
#define TARANG_RUN_BOOT_TESTS 1
#endif

/***************************************************************************//**
 * Initialize application.
 ******************************************************************************/
void app_init(void)
{
#if TARANG_RUN_BOOT_TESTS
  /* === PHASE 1 & 2 VERIFICATION TEST AT BOOT === */
  extern void test_ml_model_multi_input(void);
  test_ml_model_multi_input();
  /* === END BOOT TEST === */
#endif

  /*
   * CRITICAL: Prevent the power manager from entering EM2/EM3.
   * EM2 shuts down I2C (kills PPG + IMU) and IADC/DMA (kills ECG).
   * EM1 keeps all peripherals alive while still saving power.
   */
#if defined(SL_CATALOG_POWER_MANAGER_PRESENT)
  sl_power_manager_add_em_requirement(SL_POWER_MANAGER_EM1);
#endif

  printf("\r\n");
  printf("==========================================\r\n");
  printf("  TARANG INTEGRATION v%s\r\n", TARANG_FW_VERSION_STRING);
  printf("  Target: EFR32MG26B510F3200IM48 (Series 2)\r\n");
  printf("  Active: %s%s%s%s\r\n",
         TARANG_ENABLE_ECG ? "ECG " : "",
         TARANG_ENABLE_PPG ? "PPG " : "",
         TARANG_ENABLE_IMU ? "IMU " : "",
         TARANG_ENABLE_RAW_ECG_STREAM ? "(RAW_STREAM) " : "");
  printf("==========================================\r\n");

  /*
   * GPIO clock + interrupt dispatcher — ONCE before any sensor init.
   * Both PPG (PC06) and IMU (PC00) use GPIOINT_CallbackRegister(),
   * which requires GPIOINT_Init() to have been called first.
   */
  CMU_ClockEnable(cmuClock_GPIO, true);
  GPIOINT_Init();

  /*
   * CRITICAL: Give I2C sensors time to power up after flash/reset.
   * MAX30102 and MPU6050 both need ~50-100ms for stable power-on.
   * Re-initialize I2CSPM to ensure clean bus state.
   */
  printf("[INIT] Waiting for sensor power-up (100ms)...\r\n");
  delay_ms(100);
  printf("[INIT] Re-initializing I2C bus...\r\n");
  sl_i2cspm_init_instances();
  delay_ms(50);

#if TARANG_ENABLE_ECG
  printf("[INIT] ECG: Starting LETIMER+PRS+IADC+DMADRV...\r\n");
  tarang_ecg_init();
  tarang_ecg_set_raw_streaming(TARANG_ENABLE_RAW_ECG_STREAM);
  printf("[INIT] ECG: Acquisition running at ~250 Hz (Raw stream: %s)\r\n",
         TARANG_ENABLE_RAW_ECG_STREAM ? "ENABLED" : "DISABLED");
  tarang_pipeline_init(tarang_pipeline_get_instance());
#else
  printf("[INIT] ECG: DISABLED\r\n");
#endif

#if TARANG_ENABLE_PPG
  printf("[INIT] PPG: Configuring MAX30102...\r\n");
  tarang_ppg_init(false);
  printf("[INIT] PPG: %s\r\n",
         tarang_ppg_is_found() ? "OK — interrupts armed at ~100 Hz" : "FAILED");
#else
  printf("[INIT] PPG: DISABLED\r\n");
#endif

#if TARANG_ENABLE_IMU
  printf("[INIT] IMU: Configuring MPU6050...\r\n");
  tarang_imu_init();
  printf("[INIT] IMU: %s\r\n",
         tarang_imu_is_found() ? "OK — DATA_RDY armed at ~100 Hz" : "NOT FOUND");
#else
  printf("[INIT] IMU: DISABLED\r\n");
#endif

#if TARANG_ENABLE_BLE
  printf("[INIT] BLE: Initializing Telemetry Service...\r\n");
  tarang_ble_init();
#endif

  printf("==========================================\r\n");
  printf("[INIT] Done. Diagnostics every ~2 sec.\r\n");
  printf("==========================================\r\n");
}

/***************************************************************************//**
 * App ticking function — called repeatedly from main() super loop.
 *
 * Each module checks its own interrupt flag and returns immediately
 * if nothing to do. No blocking, no sleep here — SDK power manager
 * handles EM2 entry between process actions.
 ******************************************************************************/
void app_process_action(void)
{
  /* ── Sensor processing ──────────────────────────────────────────────── */
#if TARANG_ENABLE_ECG
  tarang_ecg_process();
#endif
#if TARANG_ENABLE_PPG
  tarang_ppg_process();
#endif
#if TARANG_ENABLE_IMU
  tarang_imu_process();
#endif

  /* ── BLE Telemetry Dispatch ─────────────────────────────────────────── */
#if TARANG_ENABLE_BLE
  tarang_ble_process(tarang_pipeline_get_instance());
#endif

  uint32_t current_count = 0;
#if TARANG_ENABLE_ECG
  current_count = tarang_ecg_get_sample_count();
#elif TARANG_ENABLE_PPG
  current_count = tarang_ppg_get_sample_count();
#elif TARANG_ENABLE_IMU
  current_count = tarang_imu_get_sample_count();
#endif

  /* ── Non-blocking Coordinated I2C Bus Recovery ──────────────────────
   *
   * Fast, non-blocking sensor probe with exponential backoff.
   * If both I2C sensors are unavailable, run lightweight quick-pings (<0.2ms).
   * Only reconfigure a sensor if it actually ACKs on the bus.
   * ─────────────────────────────────────────────────────────────────── */
#if TARANG_ENABLE_PPG && TARANG_ENABLE_IMU
  static uint32_t last_bus_recovery_tick = 0;
  static uint32_t bus_recovery_interval = 1250u; /* Start at 5 sec (1250 samples @ 250 Hz) */
  static uint32_t consecutive_recovery_fails = 0;

  bool ppg_unavail = (tarang_ppg_get_health() == TARANG_SENSOR_UNAVAILABLE || !tarang_ppg_is_found());
  bool imu_unavail = (tarang_imu_get_health() == TARANG_SENSOR_UNAVAILABLE || !tarang_imu_is_found());

  if (ppg_unavail || imu_unavail) {
    if (current_count - last_bus_recovery_tick >= bus_recovery_interval) {
      last_bus_recovery_tick = current_count;

      /* Step 1: Lightweight non-blocking quick-ping (<0.2 ms execution time) */
      bool ppg_alive = ppg_unavail ? tarang_i2c_quick_ping(TARANG_MAX30102_I2C_ADDR) : true;
      bool imu_alive = imu_unavail ? tarang_i2c_quick_ping(TARANG_MPU6050_I2C_ADDR) : true;

      if (!ppg_alive && !imu_alive) {
        /* Both missing: run 9-pulse bus clear with interleaved ECG drain */
#if TARANG_ENABLE_ECG
        tarang_ecg_process(); /* Pre-drain */
#endif
        tarang_i2c_bus_clear();
#if TARANG_ENABLE_ECG
        tarang_ecg_process(); /* Post-drain */
#endif
        /* Exponential backoff: 5s -> 15s -> 30s -> 60s max */
        consecutive_recovery_fails++;
        if (consecutive_recovery_fails == 1)      bus_recovery_interval = 1250u;  /* 5s */
        else if (consecutive_recovery_fails == 2) bus_recovery_interval = 3750u;  /* 15s */
        else if (consecutive_recovery_fails == 3) bus_recovery_interval = 7500u;  /* 30s */
        else                                      bus_recovery_interval = 15000u; /* 60s max */
      } else {
        /* At least one sensor responded to quick-ping! Reset backoff & reconfigure */
        consecutive_recovery_fails = 0;
        bus_recovery_interval = 1250u;

        if (ppg_unavail && ppg_alive) {
#if TARANG_ENABLE_ECG
          tarang_ecg_process();
#endif
          printf("[APP] MAX30102 detected on I2C quick-ping. Reconfiguring...\r\n");
          tarang_ppg_init(true);
        }

        if (imu_unavail && imu_alive) {
#if TARANG_ENABLE_ECG
          tarang_ecg_process();
#endif
          printf("[APP] MPU6050 detected on I2C quick-ping. Reconfiguring...\r\n");
          tarang_imu_init_ex(true);
        }
#if TARANG_ENABLE_ECG
        tarang_ecg_process();
#endif
      }
    }
  } else {
    consecutive_recovery_fails = 0;
    bus_recovery_interval = 1250u;
  }
#endif

  /* ── Periodic diagnostics (every ~2 seconds) ────────────────────────
   *
   * Timebase selection:
   *   - If ECG enabled:  use ECG sample_count (250 Hz → 500 samples = 2 sec)
   *   - If PPG enabled:  use PPG sample_count (100 Hz → 200 samples = 2 sec)
   *   - If IMU enabled:  use IMU sample_count (100 Hz → 200 samples = 2 sec)
   * This ensures diagnostics print regardless of which sensors are active.
   * ─────────────────────────────────────────────────────────────────── */

  static uint32_t last_diag = 0;
  uint32_t diag_interval = 200;  /* default: 200 samples @ 100 Hz = 2 sec */

#if TARANG_ENABLE_ECG
  diag_interval = 500;   /* 500 samples @ 250 Hz = 2 sec */
#elif TARANG_ENABLE_PPG
  diag_interval = 200;   /* 200 samples @ 100 Hz = 2 sec */
#elif TARANG_ENABLE_IMU
  diag_interval = 200;   /* 200 samples @ 100 Hz = 2 sec */
#endif

  if (current_count - last_diag < diag_interval) {
    return;
  }
  last_diag = current_count;

  printf("\r\n========= TARANG LIVE READINGS =========\r\n");

  /* ── ECG readings ─────────────────────────────────────────────────── */
#if TARANG_ENABLE_ECG
  {
    uint32_t halves   = tarang_ecg_get_halves_completed();
    uint32_t samples  = tarang_ecg_get_sample_count();
    uint32_t overruns = tarang_ecg_get_overrun_count();
    uint32_t *buf     = tarang_ecg_get_buffer();

    /* Show most recent raw ADC — last slot of each half (DMA fills forward,
     * so the highest index in each half is the newest sample). */
    uint32_t raw0 = (buf != NULL) ? (buf[ECG_HALF_SAMPLES - 1]  & 0x00FFFFFFu) : 0;
    uint32_t raw1 = (buf != NULL) ? (buf[ECG_BUFFER_SIZE   - 1] & 0x00FFFFFFu) : 0;

    printf("  [ECG] halves=%lu  total_samples=%lu  overruns=%lu\r\n",
           (unsigned long)halves,
           (unsigned long)samples,
           (unsigned long)overruns);
    printf("  [ECG] latest_half0=%lu  latest_half1=%lu\r\n",
           (unsigned long)raw0,
           (unsigned long)raw1);

    if (overruns > 0) {
      printf("  [ECG] !! OVERRUN DETECTED — CPU not draining fast enough\r\n");
    }
    if (halves == 0 && samples > 100) {
      printf("  [ECG] !! WARNING — samples counting but no DMA halves completed\r\n");
    }
  }
#endif

  /* ── PPG readings ─────────────────────────────────────────────────── */
#if TARANG_ENABLE_PPG
  {
    uint32_t cnt   = tarang_ppg_get_sample_count();
    uint32_t red   = tarang_ppg_get_red();
    uint32_t ir    = tarang_ppg_get_ir();
    bool     found = tarang_ppg_is_found();

    printf("  [PPG] samples=%lu  RED=%lu  IR=%lu  sensor=%s\r\n",
           (unsigned long)cnt,
           (unsigned long)red,
           (unsigned long)ir,
           found ? "OK" : "FAIL");

    if (!found) {
      printf("  [PPG] !! MAX30102 NOT RESPONDING — check I2C wiring (PC05/PC07)\r\n");
    }
    if (found && red == 0 && ir == 0 && cnt > 50) {
      printf("  [PPG] !! Sensor found but readings are ZERO — check LED current config\r\n");
    }
  }
#endif

  /* ── IMU readings ─────────────────────────────────────────────────── */
#if TARANG_ENABLE_IMU
  {
    uint32_t cnt  = tarang_imu_get_sample_count();
    uint32_t ints = tarang_imu_get_interrupt_count();
    int16_t  ax   = tarang_imu_get_accel_x();
    int16_t  ay   = tarang_imu_get_accel_y();
    int16_t  az   = tarang_imu_get_accel_z();
    int16_t  gx   = tarang_imu_get_gyro_x();
    int16_t  gy   = tarang_imu_get_gyro_y();
    int16_t  gz   = tarang_imu_get_gyro_z();
    bool     found = tarang_imu_is_found();

    printf("  [IMU] samples=%lu  interrupts=%lu  sensor=%s\r\n",
           (unsigned long)cnt,
           (unsigned long)ints,
           found ? "OK" : "FAIL");
    printf("  [IMU] accel: ax=%d  ay=%d  az=%d\r\n", ax, ay, az);
    printf("  [IMU] gyro:  gx=%d  gy=%d  gz=%d\r\n", gx, gy, gz);

    if (!found) {
      printf("  [IMU] !! MPU6050 NOT RESPONDING — check I2C wiring + AD0→GND\r\n");
    }
    if (found && cnt == 0 && ints == 0) {
      printf("  [IMU] !! Sensor found but no DATA_RDY interrupts — check PC00 wiring\r\n");
    }
    if (found && ax == 0 && ay == 0 && az == 0) {
      printf("  [IMU] !! All accel axes ZERO — sensor may be in sleep mode\r\n");
    }
  }
#endif

  /* ── AI & Pipeline diagnostics ─────────────────────────────────────── */
  tarang_pipeline_t *pipeline = tarang_pipeline_get_instance();
  if (pipeline && pipeline->initialized) {
    printf("  [AI] tier0_evals=%lu  tier1_fires=%lu  tier2_fires=%lu\r\n",
           (unsigned long)pipeline->tier0_evals,
           (unsigned long)pipeline->tier1_fires,
           (unsigned long)pipeline->tier2_fires);
    printf("  [AI] class_n=%lu  class_s=%lu  class_v=%lu\r\n",
           (unsigned long)pipeline->class_n_count,
           (unsigned long)pipeline->class_s_count,
           (unsigned long)pipeline->class_v_count);
  }

  printf("========================================\r\n");
}
