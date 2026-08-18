/***************************************************************************//**
 * @file
 * @brief TARANG Integration — Orchestrator
 *
 * Thin orchestrator that initializes and processes all 3 sensor modules
 * plus the DSP → AI → Clinical Engine → BLE telemetry pipeline.
 *
 * Sensors:
 *   ECG  — LETIMER→PRS→IADC→DMADRV ping-pong (from ECG/july6)
 *   PPG  — MAX30102 I2C interrupt-driven      (from PPG/ppg)
 *   IMU  — MPU6050 I2C interrupt-driven        (from IMU/AMIMU)
 *
 * Pipeline (4-tier AI cascade):
 *   Tier 0: DSP heuristics (always-on, Pan-Tompkins R-peak detection)
 *   Tier 1: Gate CNN (~40KB, ~12ms on MVP) — only if suspicious
 *   Tier 2: SV Head CNN (~32KB, ~10ms on MVP) — only if Gate flags abnormal
 *   Tier 3: Clinical Event Engine (every beat)
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
 *   TARANG_ENABLE_BLE   — BLE telemetry service
 *   TARANG_ENABLE_RAW_ECG_STREAM — Output raw ADC via VCOM at 250 Hz
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
#include "em_gpio.h"
#include "gpiointerrupt.h"
#include "sl_i2cspm.h"
#include "sl_i2cspm_instances.h"
#include "sl_sleeptimer.h"

#if defined(SL_CATALOG_POWER_MANAGER_PRESENT)
#include "sl_power_manager.h"
#endif

/* Sleeptimer handle for periodic 10ms wakeup */
static sl_sleeptimer_timer_handle_t wakeup_timer;
static void wakeup_callback(sl_sleeptimer_timer_handle_t *handle, void *data)
{
  (void)handle;
  (void)data;
  /* Empty — the sole purpose is to wake the CPU from EM1 every 10ms
   * so the super loop runs and processes any pending sensor data. */
}

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
#define TARANG_RUN_BOOT_TESTS 0   /* Set to 1 to run AI/ML boot test — adds ~100ms startup delay */
#endif

/***************************************************************************//**
 * Initialize application.
 ******************************************************************************/
void app_init(void)
{
  /*
   * CRITICAL: Prevent the power manager from entering EM2/EM3.
   * EM2 shuts down I2C (kills PPG + IMU) and IADC/DMA (kills ECG).
   * EM1 keeps all peripherals alive while still saving power.
   * Must be set BEFORE any peripheral usage (including boot tests).
   */
#if defined(SL_CATALOG_POWER_MANAGER_PRESENT)
  sl_power_manager_add_em_requirement(SL_POWER_MANAGER_EM1);
#endif

#if TARANG_RUN_BOOT_TESTS
  /* === PHASE 1 & 2 VERIFICATION TEST AT BOOT === */
  extern void test_ml_model_multi_input(void);
  test_ml_model_multi_input();
  /* === END BOOT TEST === */
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
   * GPIO clock — ensure enabled before sensor init.
   * NOTE: GPIOINT_Init() is already called by autogen sl_driver_init()
   * in sl_event_handler.c, so we do NOT call it again here.
   */
  CMU_ClockEnable(cmuClock_GPIO, true);

  /*
   * CRITICAL: Give I2C sensors time to power up after flash/reset.
   * MAX30102 and MPU6050 both need ~50-100ms for stable power-on.
   */
  printf("[INIT] Waiting for sensor power-up (100ms)...\r\n");
  delay_ms(100);

  /*
   * I2C BUS RECOVERY: If the MPU6050/MAX30102 was mid-transaction when
   * the debugger halted or the MCU reset, the slave may be holding SDA low.
   * Toggle SCL 9 times + generate a STOP to release the bus.
   * This MUST happen BEFORE sl_i2cspm_init_instances().
   */
  printf("[INIT] I2C bus recovery (9 SCL pulses)...\r\n");
  {
    /* PC05 = SCL, PC07 = SDA (I2C1 mikroe) */
    GPIO_PinModeSet(gpioPortC, 5, gpioModeWiredAndPullUp, 1);
    GPIO_PinModeSet(gpioPortC, 7, gpioModeWiredAndPullUp, 1);

    for (int i = 0; i < 9; i++) {
      GPIO_PinOutClear(gpioPortC, 5);  /* SCL low */
      delay_ms(1);
      GPIO_PinOutSet(gpioPortC, 5);    /* SCL high */
      delay_ms(1);
    }
    /* Generate STOP: SDA low→high while SCL high */
    GPIO_PinOutClear(gpioPortC, 7);    /* SDA low */
    delay_ms(1);
    GPIO_PinOutSet(gpioPortC, 5);      /* SCL high */
    delay_ms(1);
    GPIO_PinOutSet(gpioPortC, 7);      /* SDA high → STOP */
    delay_ms(1);

    printf("[INIT] Bus state: SCL=%u SDA=%u\r\n",
           (unsigned)GPIO_PinInGet(gpioPortC, 5),
           (unsigned)GPIO_PinInGet(gpioPortC, 7));
  }

  /* NOTE: sl_i2cspm_init_instances() is already called by autogen
   * sl_driver_init() in sl_event_handler.c. No re-init needed. */
  printf("[INIT] I2C bus ready (autogen init).\r\n");
  delay_ms(50);

  /* ── I2C Bus Scan — probe known sensor addresses ───────────────────── */
  {
    printf("[INIT] I2C scan: probing known addresses...\r\n");
    uint8_t addrs[] = { 0x57, 0x68 };  /* MAX30102, MPU6050 */
    const char *names[] = { "MAX30102 (PPG)", "MPU6050  (IMU)" };

    for (int i = 0; i < 2; i++) {
      I2C_TransferSeq_TypeDef seq;
      uint8_t dummy = 0;
      seq.addr  = addrs[i] << 1;
      seq.flags = I2C_FLAG_WRITE_READ;
      uint8_t reg = 0x00;
      seq.buf[0].data = &reg;
      seq.buf[0].len  = 1;
      seq.buf[1].data = &dummy;
      seq.buf[1].len  = 1;

      I2C_TransferReturn_TypeDef ret = I2CSPM_Transfer(sl_i2cspm_mikroe, &seq);
      printf("[INIT]   0x%02X %s -> %s (ret=%d)\r\n",
             addrs[i], names[i],
             (ret == i2cTransferDone) ? "ACK (found)" : "NACK (missing)",
             (int)ret);
    }
  }

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
  tarang_ppg_init();
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

  /*
   * Start a 10ms periodic wakeup timer. This wakes the CPU from EM1
   * every 10ms so the super loop can check sensor data_ready flags.
   * GPIO sensor interrupts ALSO wake the CPU — this timer is a
   * guaranteed fallback that ensures the system never sleeps forever.
   */
  uint32_t ticks = sl_sleeptimer_ms_to_tick(10);
  sl_sleeptimer_start_periodic_timer(&wakeup_timer,
                                     ticks,
                                     wakeup_callback,
                                     NULL, 0, 0);
  printf("[INIT] 10ms wakeup timer started.\r\n");
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

  /* ── I2C Bus Recovery ────────────────────────────────────────────────
   *
   * NOTE: Disabled — PR #24 PPG/IMU drivers don't have
   * tarang_ppg_get_health() / tarang_i2c_quick_ping() / tarang_i2c_bus_clear()
   * / tarang_imu_init_ex(). Recovery will be re-enabled when PPG/IMU
   * drivers are upgraded with health tracking APIs.
   * ─────────────────────────────────────────────────────────────────── */

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
