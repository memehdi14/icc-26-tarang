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
#include "tarang_ecg.h"
#include "tarang_ppg.h"
#include "tarang_imu.h"
#include "tarang_pipeline.h"
#include "tarang_time.h"

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

/* ── TARANG DSP/ML/Clinical Pipeline (static — ~32KB in .bss) ────────── */
static tarang_pipeline_t s_pipeline;

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

/***************************************************************************//**
 * Initialize application.
 ******************************************************************************/
void app_init(void)
{
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
  printf("  TARANG INTEGRATION v2.0 (DSP+ML)\r\n");
  printf("  Active: %s%s%s\r\n",
         TARANG_ENABLE_ECG ? "ECG " : "",
         TARANG_ENABLE_PPG ? "PPG " : "",
         TARANG_ENABLE_IMU ? "IMU " : "");
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

  printf("[INIT] Re-initializing I2C bus...\r\n");
  sl_i2cspm_init_instances();
  printf("[INIT] I2C bus ready.\r\n");
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
  printf("[INIT] ECG: Acquisition running at ~250 Hz\r\n");
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

  /* ── Initialize DSP → ML → Clinical Pipeline ────────────────────────── */
  printf("[INIT] Pipeline: Initializing DSP + ML + Clinical Engine...\r\n");
  tarang_pipeline_init(&s_pipeline);
  printf("[INIT] Pipeline: Ready. Feed ECG samples via process_ecg_sample().\r\n");
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
  /* CRITICAL: Read DMA half-ready flags BEFORE ecg_process() clears them.
   * ecg_process() sets halfXReady = false internally, so if we check
   * after, we'd always see false and never feed samples to the pipeline. */
  bool h0 = tarang_ecg_half0_ready();
  bool h1 = tarang_ecg_half1_ready();

  tarang_ecg_process();

  /* ── Feed completed ECG DMA half-buffers into the DSP→ML pipeline ─── */
  {
    uint32_t *ecg_buf = tarang_ecg_get_buffer();
    if (ecg_buf != NULL) {
      /* Half 0 completed (DMA wrote 64 samples at index 0..63) */
      if (h0) {
        uint32_t now = tarang_now_ms();
        for (int i = 0; i < ECG_HALF_SAMPLES; i++) {
          tarang_pipeline_process_ecg_sample(&s_pipeline, ecg_buf[i], now);
        }
      }
      /* Half 1 completed (DMA wrote 64 samples at index 64..127) */
      if (h1) {
        uint32_t now = tarang_now_ms();
        for (int i = 0; i < ECG_HALF_SAMPLES; i++) {
          tarang_pipeline_process_ecg_sample(&s_pipeline,
                                              ecg_buf[ECG_HALF_SAMPLES + i], now);
        }
      }
    }
  }
#endif
#if TARANG_ENABLE_PPG
  tarang_ppg_process();
#endif
#if TARANG_ENABLE_IMU
  tarang_imu_process();
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
  uint32_t current_count = 0;
  uint32_t diag_interval = 200;  /* default: 200 samples @ 100 Hz = 2 sec */

#if TARANG_ENABLE_ECG
  current_count = tarang_ecg_get_sample_count();
  diag_interval = 500;   /* 500 samples @ 250 Hz = 2 sec */
#elif TARANG_ENABLE_PPG
  current_count = tarang_ppg_get_sample_count();
  diag_interval = 200;   /* 200 samples @ 100 Hz = 2 sec */
#elif TARANG_ENABLE_IMU
  current_count = tarang_imu_get_sample_count();
  diag_interval = 200;   /* 200 samples @ 100 Hz = 2 sec */
#endif

  if (current_count - last_diag < diag_interval) {
    /* Fallback: if no samples collected at all, print a warning periodically
     * so we know the firmware is alive but the sensor isn't producing data. */
    static uint32_t stall_counter = 0;
    if (current_count == 0 && (++stall_counter % 400u) == 0) {
      printf("\r\n[WARN] No samples collected. Sensor may not be generating interrupts.\r\n");
#if TARANG_ENABLE_PPG
      printf("[WARN] PPG found=%d  samples=%lu  pin_PC06=%u  int_count=%lu\r\n",
             (int)tarang_ppg_is_found(),
             (unsigned long)tarang_ppg_get_sample_count(),
             (unsigned)GPIO_PinInGet(gpioPortC, 6),
             (unsigned long)tarang_ppg_get_interrupt_count());
#endif
#if TARANG_ENABLE_IMU
      printf("[WARN] IMU found=%d  samples=%lu  int_count=%lu\r\n",
             (int)tarang_imu_is_found(),
             (unsigned long)tarang_imu_get_sample_count(),
             (unsigned long)tarang_imu_get_interrupt_count());
#endif
    }
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

    /* Show most recent raw ADC from each half-buffer slot 0 */
    uint32_t raw0 = (buf != NULL) ? (buf[0] & 0x00FFFFFFu) : 0;
    uint32_t raw1 = (buf != NULL) ? (buf[ECG_HALF_SAMPLES] & 0x00FFFFFFu) : 0;

    printf("  [ECG] halves=%lu  total_samples=%lu  overruns=%lu\r\n",
           (unsigned long)halves,
           (unsigned long)samples,
           (unsigned long)overruns);
    printf("  [ECG] raw_half0[0]=%lu  raw_half1[0]=%lu\r\n",
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

  printf("========================================\r\n");

  /* ── Pipeline diagnostics ────────────────────────────────────────── */
  {
    const tarang_diagnostics_t *d = tarang_pipeline_get_diag(&s_pipeline);
    printf("  [PIPELINE] beats: total=%lu  suspicious=%lu  gate_passed=%lu\r\n",
           (unsigned long)s_pipeline.total_beats,
           (unsigned long)s_pipeline.suspicious_beats,
           (unsigned long)s_pipeline.gate_passed_beats);
    printf("  [PIPELINE] AI: triggers=%lu  time=%lu us  BLE_pkts=%lu\r\n",
           (unsigned long)d->ai_trigger_count,
           (unsigned long)d->ai_time_us,
           (unsigned long)d->ble_packet_count);
    if (s_pipeline.engine.total_beats > 0) {
      uint32_t total = s_pipeline.engine.total_beats;
      uint32_t pac_pct = s_pipeline.engine.pac_count * 100u / total;
      uint32_t pvc_pct = s_pipeline.engine.pvc_count * 100u / total;
      printf("  [PIPELINE] HR=%u bpm  rhythm=0x%02X  PAC=%u%%  PVC=%u%%\r\n",
             (unsigned)s_pipeline.engine.current_hr,
             (unsigned)s_pipeline.engine.rhythm_flags,
             (unsigned)pac_pct,
             (unsigned)pvc_pct);
    }
  }
  printf("========================================\r\n");
}
