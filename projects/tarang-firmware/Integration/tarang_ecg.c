/***************************************************************************//**
 * @file tarang_ecg.c
 * @brief TARANG ECG acquisition module — implementation.
 *
 * Direct extraction from Separate Testing/ECG/july6/app.c.
 * UNCHANGED sensor logic. Only renamed app_init→tarang_ecg_init,
 * app_process_action→tarang_ecg_process, removed EMU_EnterEM2.
 *
 * Chain: LETIMER0 (underflow pulse)
 *        → PRS async channel 2
 *        → IADC0 single queue trigger
 *        → DMADRV ping-pong DMA transfer
 *        → RAM (ecg_buffer[], two halves)
 *
 * Target : EFR32MG26B510F3200IM48 (Series 2, Cortex-M33)
 * SDK    : Simplicity SDK / emlib + emdrv (DMADRV)
 ******************************************************************************/

#define SL_SUPPRESS_DEPRECATION_WARNINGS_SDK_2026_6

#include "tarang_ecg.h"
#include "tarang_pipeline.h"
#include "tarang_time.h"

#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>

#include "em_cmu.h"
#include "em_iadc.h"
#include "em_letimer.h"
#include "em_prs.h"
#include "em_gpio.h"
#include "em_emu.h"
#include "em_core.h"
#include "dmadrv.h"

/*******************************************************************************
 ******************************* DEFINES **************************************
 ******************************************************************************/
#define PRS_CHANNEL          2       // async PRS channel: LETIMER0 -> IADC0

// Set CLK_ADC to 1MHz (adjust to taste)
#define CLK_SRC_ADC_FREQ     10000000  // CLK_SRC_ADC
#define CLK_ADC_FREQ         1000000   // CLK_ADC

/*******************************************************************************
 *************************** STATIC VARIABLES **********************************
 ******************************************************************************/
// 32-bit: matches SINGLEFIFODATA register width moved natively by DMA.
static uint32_t ecg_buffer[ECG_BUFFER_SIZE];

static unsigned int ecgDmaChannel;

static volatile uint32_t sample_count       = 0;
static volatile bool      half0Ready        = false;
static volatile bool      half1Ready        = false;
static volatile uint32_t  ecg_overrun_count = 0;
static volatile uint32_t  halves_completed  = 0;
/* first_half_seen removed — was declared but never used */
static volatile uint32_t  half0Pending      = 0;
static volatile uint32_t  half1Pending      = 0;

/***************************************************************************//**
 * LETIMER Interrupt — sample_count bookkeeping only.
 * IADC triggering and sample movement are fully autonomous.
 ******************************************************************************/
void LETIMER0_IRQHandler(void)
{
  uint32_t flags = LETIMER_IntGet(LETIMER0);
  LETIMER_IntClear(LETIMER0, flags);

  if (flags & LETIMER_IF_UF)
  {
    sample_count++;
  }
}

/***************************************************************************//**
 * DMADRV completion callback — called every time one half of ecg_buffer
 * finishes filling. Even sequenceNo → half 0, odd → half 1.
 * Returning true keeps the ping-pong going forever.
 ******************************************************************************/
static bool ecgDmaCallback(unsigned int channel, unsigned int sequenceNo, void *userParam)
{
  (void)channel;
  (void)userParam;

  halves_completed++;

  if ((sequenceNo & 1U) == 0U)
  {
    if (half0Pending > 0U) { ecg_overrun_count++; }
    half0Ready = true;
    half0Pending++;
  }
  else
  {
    if (half1Pending > 0U) { ecg_overrun_count++; }
    half1Ready = true;
    half1Pending++;
  }

  return true;   // keep streaming forever
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
   * 2. GPIO — iadcPosInputPadAna0 is a dedicated AIN pad, no routing
   *    needed.
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

  LETIMER_IntEnable(LETIMER0, LETIMER_IEN_UF);
  NVIC_EnableIRQ(LETIMER0_IRQn);

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
   * 6. DMADRV - continuous ping-pong transfer, IADC0 FIFO → RAM
   **********************************************************************/
  DMADRV_Init();
  DMADRV_AllocateChannel(&ecgDmaChannel, NULL);

  DMADRV_PeripheralMemoryPingPong(
      ecgDmaChannel,
      dmadrvPeripheralSignal_IADC0_IADC_SINGLE,
      &ecg_buffer[0],                    // dst0 -- first half
      &ecg_buffer[ECG_HALF_SAMPLES],     // dst1 -- second half
      (void *)&(IADC0->SINGLEFIFODATA),  // src  -- IADC single FIFO
      true,                              // dstInc: increment through each half
      ECG_HALF_SAMPLES,                  // len
      dmadrvDataSize4,                   // 32-bit
      ecgDmaCallback,
      NULL);

  /**********************************************************************
   * 7. LETIMER enable - START LAST
   **********************************************************************/
  LETIMER_Enable(LETIMER0, true);
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

/***************************************************************************//**
 * ECG process action — check ping-pong halves.
 * Outputs compact telemetry stream for plotting without blocking CPU.
 ******************************************************************************/
void tarang_ecg_process(void)
{
  bool drain_h0 = false;
  bool drain_h1 = false;

  CORE_DECLARE_IRQ_STATE;
  CORE_ENTER_ATOMIC();
  if (half0Ready) {
    half0Ready   = false;
    half0Pending = 0;
    drain_h0     = true;
  }
  if (half1Ready) {
    half1Ready   = false;
    half1Pending = 0;
    drain_h1     = true;
  }
  CORE_EXIT_ATOMIC();

  tarang_pipeline_t *pipeline = tarang_pipeline_get_instance();
  uint32_t now_ms = tarang_now_ms();

  if (drain_h0 && pipeline) {
    for (uint32_t i = 0; i < ECG_HALF_SAMPLES; i++) {
      uint32_t raw_val = ecg_buffer[i] & 0x00FFFFFFu;
      tarang_pipeline_process_ecg_sample(pipeline, raw_val, now_ms);
      if (s_raw_streaming_enabled) {
        printf("[ECG] raw=%lu\r\n", (unsigned long)raw_val);
      }
    }
  }

  if (drain_h1 && pipeline) {
    for (uint32_t i = ECG_HALF_SAMPLES; i < ECG_BUFFER_SIZE; i++) {
      uint32_t raw_val = ecg_buffer[i] & 0x00FFFFFFu;
      tarang_pipeline_process_ecg_sample(pipeline, raw_val, now_ms);
      if (s_raw_streaming_enabled) {
        printf("[ECG] raw=%lu\r\n", (unsigned long)raw_val);
      }
    }
  }
}

/*******************************************************************************
 * Public accessors
 ******************************************************************************/
uint32_t *tarang_ecg_get_buffer(void)
{
  return ecg_buffer;
}

bool tarang_ecg_half0_ready(void)
{
  return half0Ready;
}

bool tarang_ecg_half1_ready(void)
{
  return half1Ready;
}

uint32_t tarang_ecg_get_sample_count(void)
{
  return sample_count;
}

uint32_t tarang_ecg_get_overrun_count(void)
{
  return ecg_overrun_count;
}

uint32_t tarang_ecg_get_halves_completed(void)
{
  return halves_completed;
}

tarang_sensor_health_t tarang_ecg_get_health(void)
{
  return (sample_count > 0) ? TARANG_SENSOR_OK : TARANG_SENSOR_STARTING;
}

bool tarang_ecg_is_valid(void)
{
  return (sample_count > 0);
}

bool tarang_ecg_is_lead_off(void)
{
#if TARANG_ECG_LO_PINS_WIRED
  /* Read physical LO+ and LO- pins from AD8232 */
  bool lo_plus = (GPIO_PinInGet(TARANG_ECG_LO_PLUS_PORT, TARANG_ECG_LO_PLUS_PIN) != 0);
  bool lo_minus = (GPIO_PinInGet(TARANG_ECG_LO_MINUS_PORT, TARANG_ECG_LO_MINUS_PIN) != 0);
  return lo_plus || lo_minus;
#else
  /* Evaluated in pipeline via ADC rail saturation (< 50 or > 4045 on 12-bit) / SQI < 30 */
  return false;
#endif
}
