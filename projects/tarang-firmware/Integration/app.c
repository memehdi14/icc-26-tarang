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
 * Configure the shared TARANG_ENABLE_* switches in tarang_constants.h.
 * Set exactly one sensor to 1 for an isolated test, or all three to 1 for the
 * full combined integration test.
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
#include "tarang_time.h"
#include "tarang_validation_stream.h"

#include <stdio.h>
#include <stdint.h>

#include "em_cmu.h"
#include "em_emu.h"
#include "em_gpio.h"
#include "gpiointerrupt.h"
#include "sl_i2cspm.h"
#include "sl_i2cspm_instances.h"
#include "sl_sleeptimer.h"

#if defined(SL_CATALOG_POWER_MANAGER_PRESENT)
#include "sl_power_manager.h"
#endif

#if defined(SL_CATALOG_BLUETOOTH_PRESENT)
#include "sl_bt_api.h"
#endif

#if TARANG_ANY_SENSOR_ENABLED
/* Sleeptimer handle for periodic 10ms sensor processing. */
static sl_sleeptimer_timer_handle_t wakeup_timer;
static void wakeup_callback(sl_sleeptimer_timer_handle_t *handle, void *data)
{
  (void)handle;
  (void)data;
  /* Wake the CPU every 10ms so the super loop runs and processes
   * any pending sensor or BLE telemetry actions. */
}
#endif

#if TARANG_ENABLE_PPG || TARANG_ENABLE_IMU
/* Simple delay for sensor power-up stabilization */
static void delay_ms(uint32_t ms)
{
  for (volatile uint32_t i = 0; i < ms * 4000u; i++) { }
}
#endif

#ifndef TARANG_RUN_BOOT_TESTS
#define TARANG_RUN_BOOT_TESTS 0   /* Set to 1 to run AI/ML boot test — adds ~100ms startup delay */
#endif

/***************************************************************************//**
 * Initialize application.
 ******************************************************************************/
void app_init(void)
{
  /*
   * NOTE: Permanent EM1 lock is intentionally DISABLED to allow the system
   * to enter EM2 deep sleep. The Silicon Labs Bluetooth Link Layer requires
   * EM2 to properly clock and schedule radio advertising and connection events
   * with the RTCC/BURTC low-frequency crystal oscillators.
   */

  /*
   * Log and clear the reset cause FIRST, before anything else can touch
   * the EMU cause register. This is the diagnostic for the battery
   * disconnect-loop investigation: if a BOD flag shows up here on every
   * boot during a battery-powered session, that confirms brownout during
   * the BLE event burst rather than some other reset path.
   *
   * The raw hex value alone is enough to diagnose against the reference
   * manual's RSTCAUSE bit table even if none of the named macros below
   * happen to match this SDK version. Each named flag is printed only if
   * its macro exists, so a missing macro can never break the build --
   * each check is a standalone guarded block, not one printf depending on
   * several macros at once.
   *
   * Reads/clears the register directly (EMU->RSTCAUSE / EMU->CMD) instead
   * of going through emlib wrapper functions -- the wrapper function names
   * (EMU_ResetCauseGet/Clear, or RMU_ on older families) vary across SDK
   * versions and device families, but the EMU peripheral struct itself is
   * defined by the CMSIS device header that's already pulled in by the
   * other emlib includes below, so this is the more portable form.
   */
  {
    uint32_t reset_cause = EMU->RSTCAUSE;
#ifdef EMU_CMD_RSTCAUSECLR
    EMU->CMD = EMU_CMD_RSTCAUSECLR;
#endif
    printf("[BOOT] RSTCAUSE=0x%08lX\r\n", (unsigned long)reset_cause);
#ifdef EMU_RSTCAUSE_POR
    if (reset_cause & EMU_RSTCAUSE_POR)      printf("[BOOT]   POR\r\n");
#endif
#ifdef EMU_RSTCAUSE_PIN
    if (reset_cause & EMU_RSTCAUSE_PIN)      printf("[BOOT]   PIN\r\n");
#endif
#ifdef EMU_RSTCAUSE_EM4
    if (reset_cause & EMU_RSTCAUSE_EM4)      printf("[BOOT]   EM4WU\r\n");
#endif
#ifdef EMU_RSTCAUSE_WDOG0
    if (reset_cause & EMU_RSTCAUSE_WDOG0)    printf("[BOOT]   WATCHDOG\r\n");
#endif
#ifdef EMU_RSTCAUSE_SYSREQ
    if (reset_cause & EMU_RSTCAUSE_SYSREQ)   printf("[BOOT]   SYSREQ\r\n");
#endif
#ifdef EMU_RSTCAUSE_AVDDBOD
    if (reset_cause & EMU_RSTCAUSE_AVDDBOD)  printf("[BOOT]   AVDDBOD (brownout)\r\n");
#endif
#ifdef EMU_RSTCAUSE_DVDDBOD
    if (reset_cause & EMU_RSTCAUSE_DVDDBOD)  printf("[BOOT]   DVDDBOD (brownout)\r\n");
#endif
#ifdef EMU_RSTCAUSE_DECBOD
    if (reset_cause & EMU_RSTCAUSE_DECBOD)   printf("[BOOT]   DECBOD (brownout)\r\n");
#endif
#ifdef EMU_RSTCAUSE_VREGIN
    if (reset_cause & EMU_RSTCAUSE_VREGIN)   printf("[BOOT]   VREGIN BOD (brownout)\r\n");
#endif
  }

#if TARANG_RUN_BOOT_TESTS
  /* === PHASE 1 & 2 VERIFICATION TEST AT BOOT === */
  extern void test_ml_model_multi_input(void);
  test_ml_model_multi_input();
  /* === END BOOT TEST === */
#endif

  printf("\r\n");
  printf("==========================================\r\n");

#if TARANG_ENABLE_VALIDATION_STREAM
#if TARANG_VALIDATION_STREAM_ACTIVE
  printf("[VALIDATION] Compact full-rate VCOM stream enabled at %u baud.\r\n",
         (unsigned)SL_IOSTREAM_EUSART_VCOM_BAUDRATE);
  printf("@V,%u,%u,%u,%u\r\n",
         TARANG_VALIDATION_STREAM_VERSION,
         TARANG_ECG_SAMPLE_RATE_HZ,
         TARANG_PPG_SAMPLE_RATE_HZ,
         TARANG_IMU_SAMPLE_RATE_HZ);
#else
  printf("[VALIDATION] Stream disabled: set VCOM baud to %u in Simplicity Studio.\r\n",
         (unsigned)TARANG_VALIDATION_STREAM_REQUIRED_BAUD);
#endif
#endif
  printf("  TARANG INTEGRATION v%s\r\n", TARANG_FW_VERSION_STRING);
  printf("  Target: EFR32MG26B510F3200IM48 (Series 2)\r\n");
  printf("  Active: %s%s%s%s\r\n",
         TARANG_ENABLE_ECG ? "ECG " : "",
         TARANG_ENABLE_PPG ? "PPG " : "",
         TARANG_ENABLE_IMU ? "IMU " : "",
         TARANG_ENABLE_RAW_ECG_STREAM ? "(RAW_STREAM) " : "");
  printf("==========================================\r\n");

#if TARANG_ANY_SENSOR_ENABLED
  /* GPIOINT_Init() is already called by autogen sl_driver_init(). */
  CMU_ClockEnable(cmuClock_GPIO, true);
#endif

#if TARANG_ENABLE_PPG || TARANG_ENABLE_IMU
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

  /* Re-initialize I2CSPM peripheral routing after manual pin manipulation */
  sl_i2cspm_init_instances();
  printf("[INIT] I2C bus ready (sl_i2cspm_init_instances).\r\n");
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
#else
  printf("[INIT] Sensor bus setup skipped (BLE-only mode).\r\n");
#endif

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

#if TARANG_ANY_SENSOR_ENABLED
  /* Sensor builds need a periodic fallback in addition to GPIO interrupts. */
  uint32_t ticks = sl_sleeptimer_ms_to_tick(10);
  sl_status_t timer_status = sl_sleeptimer_start_periodic_timer(
      &wakeup_timer, ticks, wakeup_callback, NULL, 0, 0);
  printf("[INIT] 10ms wakeup timer: 0x%08lX\r\n",
         (unsigned long)timer_status);
#else
  printf("[INIT] BLE reference runtime active (no application wake timer).\r\n");
#endif
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
#if TARANG_ENABLE_IMU
  tarang_imu_process();
#endif
#if TARANG_ENABLE_PPG
#if TARANG_ENABLE_IMU
  tarang_ppg_set_motion_level_mg(tarang_imu_get_motion_mg());
#else
  tarang_ppg_set_motion_level_mg(0u);
#endif
  tarang_ppg_process();
#endif
#if TARANG_ENABLE_ECG
  tarang_ecg_process();
  tarang_pipeline_run_deferred(tarang_pipeline_get_instance());
#endif

  /* ── BLE Telemetry Dispatch (Unconditional) ─────────────────────────── */
#if TARANG_ENABLE_BLE
  tarang_ble_process(tarang_pipeline_get_instance());
#endif

  /* ── Periodic diagnostics (every ~2 seconds) ────────────────────────
   *
   * Timebase: uses tarang_now_ms() so diagnostics print reliably even
   * if physical sensors are disabled.
   * ─────────────────────────────────────────────────────────────────── */
  static uint32_t last_diag_ms = 0;
  uint32_t now_ms = tarang_now_ms();
  if (now_ms - last_diag_ms < 2000u) {
    return;
  }
  last_diag_ms = now_ms;

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

#if TARANG_VALIDATION_STREAM_ACTIVE
    tarang_ppg_metrics_t metrics = {0};
    (void)tarang_ppg_get_metrics(&metrics);
    printf("@M,%lu,%lu,%u,%u,%u,%u,%u,%u,%u\r\n",
           (unsigned long)now_ms,
           (unsigned long)metrics.window_end_sample,
           metrics.spo2_pct,
           metrics.pulse_rate_bpm,
           metrics.signal_quality,
           metrics.perfusion_index_x100,
           metrics.finger_present ? 1u : 0u,
           metrics.motion_rejected ? 1u : 0u,
           metrics.valid ? 1u : 0u);
#endif
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
    const tarang_nlms_state_t *nlms =
        tarang_pipeline_get_nlms_state(pipeline);
    printf("  [NLMS] state=%s motion=%u mg suppression=%u.%u%% resets=%lu\r\n",
           tarang_nlms_bypass_reason_string(nlms->bypass_reason),
           nlms->motion_mg,
           nlms->suppression_pct_x10 / 10u,
           nlms->suppression_pct_x10 % 10u,
           (unsigned long)nlms->safety_reset_count);

#if TARANG_VALIDATION_STREAM_ACTIVE
    printf("@D,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%u,%u,%u,%lu,%lu,%lu\r\n",
           (unsigned long)now_ms,
           (unsigned long)tarang_ecg_get_sample_count(),
           (unsigned long)tarang_ecg_get_overrun_count(),
           (unsigned long)tarang_ppg_get_sample_count(),
           (unsigned long)tarang_imu_get_sample_count(),
           (unsigned long)pipeline->tier0_evals,
           (unsigned long)pipeline->tier1_fires,
           (unsigned long)pipeline->tier2_fires,
           (unsigned long)pipeline->class_n_count,
           (unsigned long)pipeline->class_s_count,
           (unsigned long)pipeline->class_v_count,
           (unsigned)nlms->bypass_reason,
           nlms->motion_mg,
           nlms->suppression_pct_x10,
           (unsigned long)nlms->safety_reset_count,
           (unsigned long)pipeline->diag.dropped_frames,
           (unsigned long)tarang_dsp_get_pending_overflow_count(&pipeline->dsp));
#endif
  }

#if TARANG_ENABLE_BLE
  tarang_ble_print_status();
#endif

  printf("========================================\r\n");
}

/***************************************************************************//**
 * Bluetooth stack event callback.
 *
 * Implemented directly in app.c to guarantee strong linkage over the weak
 * default in autogen/sl_bluetooth.c.
 ******************************************************************************/
#if defined(SL_CATALOG_BLUETOOTH_PRESENT)
void sl_bt_on_event(sl_bt_msg_t *evt)
{
  tarang_ble_on_event(evt);
}
#endif