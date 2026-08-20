/***************************************************************************//**
 * @file tarang_ecg.c
 * @brief TARANG ECG Acquisition — LETIMER→PRS→IADC0→LDMA Ping-Pong
 *
 * Acquisition began from Separate Testing/ECG/july6/app.c.
 *
 * Hardware chain:
 *   LETIMER0 underflow (250 Hz, compare=130 on LFRCO 32768 Hz)
 *     → PRS CH0
 *       → IADC0 Single Trigger (AIN0 / iadcPosInputPadAna0)
 *         → LDMA ping-pong into ecg_buffer[128]
 *           (two 64-sample halves, interrupt on each half = ~3.9 Hz)
 *
 * Target : EFR32MG26B510F3200IM48 (BRD2709A)
 ******************************************************************************/

#include "tarang_ecg.h"
#include "tarang_constants.h"
#include "tarang_pipeline.h"
#include "tarang_time.h"

#include <stdio.h>
#include <string.h>

#include "em_cmu.h"
#include "em_emu.h"
#include "em_gpio.h"
#include "em_letimer.h"
#include "em_iadc.h"
#include "em_prs.h"
#include "em_ldma.h"
#include "em_core.h"
#include "sl_dma_manager.h"

/*******************************************************************************
 * Hardware Configuration Constants
 ******************************************************************************/
#define CLK_SRC_ADC_FREQ          20000000  // FSRCO default ~20 MHz
#define CLK_ADC_FREQ              10000000  // 10 MHz ADC clock
#define PRS_CHANNEL               0

/*******************************************************************************
 * Ping-Pong Buffers & Descriptors
 ******************************************************************************/
static uint32_t           ecg_buffer[ECG_BUFFER_SIZE];
static uint8_t            ecg_dma_channel   = 0;
static LDMA_Descriptor_t  ecg_dma_desc[2];

/* Diagnostics */
static volatile uint32_t  sample_count      = 0;
static volatile bool      half0Ready        = false;
static volatile bool      half1Ready        = false;
static volatile uint32_t  ecg_overrun_count = 0;
static volatile uint32_t  halves_completed  = 0;
static volatile uint32_t  half0Pending      = 0;
static volatile uint32_t  half1Pending      = 0;
static volatile uint64_t  half0CompletedUs  = 0;
static volatile uint64_t  half1CompletedUs  = 0;

/***************************************************************************//**
 * DMA Channel IRQ Handler — called by sl_dma_manager on LDMA interrupt.
 ******************************************************************************/
static void ecg_dma_irq_handler(void)
{
  halves_completed++;
  sample_count += ECG_HALF_SAMPLES;

  /* Even halves completed (0, 2, 4...) -> desc[0] filled half 0 */
  if ((halves_completed & 1U) == 1U)
  {
    if (half0Pending > 0U) { ecg_overrun_count++; }
    half0CompletedUs = tarang_now_us();
    half0Ready = true;
    half0Pending++;
  }
  /* Odd halves completed (1, 3, 5...) -> desc[1] filled half 1 */
  else
  {
    if (half1Pending > 0U) { ecg_overrun_count++; }
    half1CompletedUs = tarang_now_us();
    half1Ready = true;
    half1Pending++;
  }
}

/***************************************************************************//**
 * Initialize ECG acquisition chain.
 ******************************************************************************/
void tarang_ecg_init(void)
{
  /**********************************************************************
   * 1. CMU - clocks
   **********************************************************************/
  CMU_ClockEnable(cmuClock_LFRCO, true);

  CMU_ClockEnable(cmuClock_FSRCO, true);
  CMU_ClockSelectSet(cmuClock_IADCCLK, cmuSelect_FSRCO);

  CMU_ClockEnable(cmuClock_LETIMER0, true);
  CMU_ClockEnable(cmuClock_PRS, true);
  CMU_ClockEnable(cmuClock_IADC0, true);

  /**********************************************************************
   * 2. GPIO — iadcPosInputPadAna0 is a dedicated AIN pad
   **********************************************************************/

  /**********************************************************************
   * 3. LETIMER - configure, do NOT enable yet
   **********************************************************************/
  EMU_EM23Init_TypeDef em23Init = EMU_EM23INIT_DEFAULT;
  em23Init.vScaleEM23Voltage = emuVScaleEM23_LowPower;
  EMU_EM23Init(&em23Init);

  LETIMER_Init_TypeDef letimerInit = LETIMER_INIT_DEFAULT;

  letimerInit.enable   = false;
  letimerInit.debugRun = true;
  letimerInit.comp0Top = true;
  letimerInit.repMode  = letimerRepeatFree;
  letimerInit.topValue = 130;   // 250.137 Hz at LFRCO (32768 / (130 + 1))
  letimerInit.ufoa0    = letimerUFOAPulse;

  LETIMER_Init(LETIMER0, &letimerInit);
  LETIMER_CompareSet(LETIMER0, 0, 130);

  /*
   * Zero-CPU Optimization: LETIMER triggers IADC autonomously via PRS.
   * Disabling per-sample CPU interrupts eliminates 130 wakeups/second;
   * sample_count is now updated in ecg_dma_irq_handler.
   */
  LETIMER_IntClear(LETIMER0, _LETIMER_IF_MASK);

  /**********************************************************************
   * 4. PRS - route LETIMER0 OUT0 → IADC0 single trigger
   **********************************************************************/
  PRS_SourceAsyncSignalSet(
      PRS_CHANNEL,
      PRS_ASYNC_CH_CTRL_SOURCESEL_LETIMER0,
      PRS_LETIMER0_CH0);

  PRS_ConnectConsumer(
      PRS_CHANNEL,
      prsTypeAsync,
      prsConsumerIADC0_SINGLETRIGGER);

  /**********************************************************************
   * 5. IADC
   **********************************************************************/
  IADC_Init_t init                 = IADC_INIT_DEFAULT;
  IADC_AllConfigs_t initAllConfigs = IADC_ALLCONFIGS_DEFAULT;
  IADC_InitSingle_t initSingle     = IADC_INITSINGLE_DEFAULT;
  IADC_SingleInput_t singleInput   = IADC_SINGLEINPUT_DEFAULT;

  init.warmup = iadcWarmupNormal;
  init.iadcClkSuspend1 = true;

  init.srcClkPrescale = IADC_calcSrcClkPrescale(IADC0, CLK_SRC_ADC_FREQ, 0);

  initAllConfigs.configs[0].reference = iadcCfgReferenceVddx;
  initAllConfigs.configs[0].vRef       = 3300;

  initAllConfigs.configs[0].adcClkPrescale =
      IADC_calcAdcClkPrescale(IADC0,
                               CLK_ADC_FREQ,
                               0,
                               iadcCfgModeNormal,
                               init.srcClkPrescale);

  initSingle.triggerSelect = iadcTriggerSelPrs0PosEdge;
  initSingle.triggerAction = iadcTriggerActionOnce;
  initSingle.start         = true;
  initSingle.dataValidLevel = iadcFifoCfgDvl1;
  initSingle.fifoDmaWakeup  = true;

  singleInput.posInput = iadcPosInputPadAna0;
  singleInput.negInput = iadcNegInputGnd;

  IADC_init(IADC0, &init, &initAllConfigs);
  IADC_initSingle(IADC0, &initSingle, &singleInput);

  /**********************************************************************
   * 6. Direct Hardware LDMA Ping-Pong Transfer: IADC0 FIFO → RAM
   **********************************************************************/
  sl_status_t st_alloc = sl_dma_manager_allocate_channel(NULL, &ecg_dma_channel);
  printf("[ECG-DIAG] sl_dma_manager_allocate_channel st=0x%04lX, ch=%u\r\n",
         (unsigned long)st_alloc, (unsigned)ecg_dma_channel);

  sl_status_t st_cb = sl_dma_manager_register_channel_irq_callback(NULL, ecg_dma_channel, ecg_dma_irq_handler);
  printf("[ECG-DIAG] sl_dma_manager_register_callback st=0x%04lX\r\n", (unsigned long)st_cb);

  // Descriptor 0: First half (samples 0 .. ECG_HALF_SAMPLES-1) -> Links to desc[1]
  ecg_dma_desc[0] = (LDMA_Descriptor_t) LDMA_DESCRIPTOR_LINKREL_P2M_WORD(
      &(IADC0->SINGLEFIFODATA),
      &ecg_buffer[0],
      ECG_HALF_SAMPLES,
      1);
  ecg_dma_desc[0].xfer.doneIfs = 1; // Assert interrupt on half-complete

  // Descriptor 1: Second half (samples ECG_HALF_SAMPLES .. ECG_BUFFER_SIZE-1) -> Links to desc[0]
  ecg_dma_desc[1] = (LDMA_Descriptor_t) LDMA_DESCRIPTOR_LINKREL_P2M_WORD(
      &(IADC0->SINGLEFIFODATA),
      &ecg_buffer[ECG_HALF_SAMPLES],
      ECG_HALF_SAMPLES,
      -1);
  ecg_dma_desc[1].xfer.doneIfs = 1; // Assert interrupt on half-complete

  LDMA_TransferCfg_t transferCfg;
  memset(&transferCfg, 0, sizeof(transferCfg));
  transferCfg.ldmaReqSel = ldmaPeripheralSignal_IADC0_IADC_SINGLE;

  LDMA_StartTransfer(ecg_dma_channel, &transferCfg, &ecg_dma_desc[0]);

  printf("[ECG-DIAG] Direct LDMA Ping-Pong Started on ch=%u\r\n", (unsigned)ecg_dma_channel);

  /**********************************************************************
   * 7. LETIMER enable - START LAST
   **********************************************************************/
  LETIMER_Enable(LETIMER0, true);

  /* Diagnostic register read immediately following initialization */
  printf("[ECG-DIAG] IADC0->STATUS = 0x%08lX\r\n", (unsigned long)IADC0->STATUS);
  printf("[ECG-DIAG] IADC0->SINGLEFIFOCFG = 0x%08lX\r\n", (unsigned long)IADC0->SINGLEFIFOCFG);
}

static bool s_raw_streaming_enabled = false;

void tarang_ecg_set_raw_streaming(bool enable)
{
  s_raw_streaming_enabled = enable;
}

bool tarang_ecg_get_raw_streaming(void)
{
  return s_raw_streaming_enabled;
}

static void process_ecg_half(tarang_pipeline_t *pipeline,
                             uint32_t first,
                             uint32_t end,
                             uint64_t completed_us)
{
  if (!pipeline) return;

  uint64_t interval_us = (uint64_t)(1000000.0 / (double)TARANG_ECG_SAMPLE_RATE_HZ);
  uint32_t count = end - first;
  uint64_t base_us = (completed_us > (interval_us * count))
                     ? (completed_us - (interval_us * count))
                     : completed_us;

  for (uint32_t i = first; i < end; i++) {
    uint32_t offset = i - first;
    uint32_t sample_ts_ms = (uint32_t)((base_us + (offset * interval_us)) / 1000ULL);
    uint32_t raw_val = ecg_buffer[i] & 0x0FFFu;
    tarang_pipeline_process_ecg_sample(pipeline, raw_val, sample_ts_ms);
    if (s_raw_streaming_enabled) {
      printf("[ECG] raw=%lu\r\n", (unsigned long)raw_val);
    }
  }
}

/***************************************************************************//**
 * ECG process action — drain completed DMA half-buffers.
 ******************************************************************************/
void tarang_ecg_process(void)
{
  bool drain_h0 = false;
  bool drain_h1 = false;
  uint64_t h0_completed_us = 0u;
  uint64_t h1_completed_us = 0u;

  /* Atomically snapshot and clear flags to avoid race with DMA ISR */
  CORE_DECLARE_IRQ_STATE;
  CORE_ENTER_ATOMIC();
  if (half0Ready) {
    half0Ready   = false;
    half0Pending = 0;
    drain_h0     = true;
    h0_completed_us = half0CompletedUs;
  }
  if (half1Ready) {
    half1Ready   = false;
    half1Pending = 0;
    drain_h1     = true;
    h1_completed_us = half1CompletedUs;
  }
  CORE_EXIT_ATOMIC();

  tarang_pipeline_t *pipeline = tarang_pipeline_get_instance();

  if (drain_h0 && drain_h1) {
    if (h0_completed_us <= h1_completed_us) {
      process_ecg_half(pipeline, 0u, ECG_HALF_SAMPLES, h0_completed_us);
      process_ecg_half(pipeline, ECG_HALF_SAMPLES, ECG_BUFFER_SIZE,
                       h1_completed_us);
    } else {
      process_ecg_half(pipeline, ECG_HALF_SAMPLES, ECG_BUFFER_SIZE,
                       h1_completed_us);
      process_ecg_half(pipeline, 0u, ECG_HALF_SAMPLES, h0_completed_us);
    }
  } else if (drain_h0) {
    process_ecg_half(pipeline, 0u, ECG_HALF_SAMPLES, h0_completed_us);
  } else if (drain_h1) {
    process_ecg_half(pipeline, ECG_HALF_SAMPLES, ECG_BUFFER_SIZE,
                     h1_completed_us);
  }
}

/*******************************************************************************
 * Public accessors
 ******************************************************************************/
uint32_t *tarang_ecg_get_buffer(void)
{
  return ecg_buffer;
}

uint32_t tarang_ecg_get_sample_count(void)
{
  return sample_count;
}

uint32_t tarang_ecg_get_overrun_count(void)
{
  return ecg_overrun_count;
}
