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
  letimerInit.topValue = 131;   // ~250 Hz at LFRCO/32768
  letimerInit.ufoa0    = letimerUFOAPulse;

  LETIMER_Init(LETIMER0, &letimerInit);
  LETIMER_CompareSet(LETIMER0, 0, 131);

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

/***************************************************************************//**
 * ECG process action — check ping-pong halves.
 * Outputs compact telemetry stream for plotting without blocking CPU.
 ******************************************************************************/
void tarang_ecg_process(void)
{
  /*
   * ECG hardware pipeline is fully autonomous:
   *   LETIMER0 -> PRS ch2 -> IADC0 -> DMADRV ping-pong -> ecg_buffer RAM
   * Runs in background with 0% CPU intervention.
   */

  /* Clear half-ready flags */
  if (half0Ready) {
    half0Ready   = false;
    half0Pending = 0;
  }
  if (half1Ready) {
    half1Ready   = false;
    half1Pending = 0;
  }

  /* Gate on real DMA completions only */
  static uint32_t last_halves = 0;
  if (halves_completed == 0 || halves_completed == last_halves) {
    return;
  }
  if (halves_completed - last_halves < 5U) {
    return;
  }
  last_halves = halves_completed;

  /* Read newest sample from the freshest half */
  uint32_t base_idx = (halves_completed & 1U)
      ? ECG_HALF_SAMPLES   /* odd  -> half-1 just done */
      : 0U;                /* even -> half-0 just done */
  uint32_t newest_idx = base_idx + (ECG_HALF_SAMPLES - 1U);

  uint32_t raw_val = ecg_buffer[newest_idx] & 0x00FFFFFFu;

  printf("[ECG] raw=%lu\r\n", (unsigned long)raw_val);
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
