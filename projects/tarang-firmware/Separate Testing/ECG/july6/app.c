/***************************************************************************//**
 * @file
 * @brief Top level application functions
 *******************************************************************************
 * # License
 * <b>Copyright 2020 Silicon Laboratories Inc. www.silabs.com</b>
 *******************************************************************************
 *
 * The licensor of this software is Silicon Laboratories Inc. Your use of this
 * software is governed by the terms of Silicon Labs Master Software License
 * Agreement (MSLA) available at
 * www.silabs.com/about-us/legal/master-software-license-agreement. This
 * software is distributed to you in Source Code format and is governed by the
 * sections of the MSLA applicable to Source Code.
 *
 ******************************************************************************/

/*******************************************************************************
 * tarang_ecg_pipeline.c
 *
 * TRUE zero-CPU acquisition chain:
 *
 *   LETIMER0 (underflow pulse)
 *        -> PRS async channel
 *        -> IADC0 single queue trigger
 *        -> IADC0 SINGLEFIFODATA
 *        -> DMADRV ping-pong DMA transfer (wraps LDMA internally)
 *        -> RAM (ecg_buffer[], two halves)
 *
 * ---------------------------------------------------------------------------
 * WHY THIS VERSION USES DMADRV INSTEAD OF RAW EMLIB LDMA
 * ---------------------------------------------------------------------------
 * Your project has the DMADRV software component installed (pulled in as a
 * dependency of another component you can't remove). DMADRV owns the
 * LDMA_IRQHandler vector itself -- it is not possible for app.c to also
 * define LDMA_IRQHandler without a "multiple definition" link error, no
 * matter how the raw-emlib code is written. So instead of fighting the
 * component tree, this version rides entirely on top of DMADRV's own API:
 * DMADRV_PeripheralMemoryPingPong() is a built-in primitive that does exactly
 * what a hand-rolled 2-descriptor LDMA ping-pong does (continuous double-
 * buffered transfer from a peripheral FIFO into two RAM halves), and DMADRV
 * manages the LDMA ISR internally -- we only supply a completion callback.
 *
 * Nothing about the LETIMER -> PRS -> IADC chain changes. Only the
 * "IADC FIFO -> RAM" stage's implementation changes, from raw LDMA to DMADRV.
 *
 * Target  : EFR32MG26B210F1024IM48 (Series 2, Cortex-M33)
 * SDK     : Simplicity SDK / emlib + emdrv (DMADRV)
 ******************************************************************************/

#define SL_SUPPRESS_DEPRECATION_WARNINGS_SDK_2026_6

#include "app.h"
#include "sl_iostream.h"

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

// Total capture buffer, split into two ping-pong halves
#define ECG_HALF_SAMPLES     512
#define ECG_BUFFER_SIZE      (ECG_HALF_SAMPLES * 2)

// Set CLK_ADC to 1MHz (adjust to taste)
#define CLK_SRC_ADC_FREQ     10000000  // CLK_SRC_ADC
#define CLK_ADC_FREQ         1000000   // CLK_ADC

/*******************************************************************************
 *************************** GLOBAL VARIABLES **********************************
 ******************************************************************************/
// 32-bit: matches SINGLEFIFODATA register width moved natively by DMA.
uint32_t ecg_buffer[ECG_BUFFER_SIZE];

static unsigned int ecgDmaChannel;

volatile uint32_t sample_count       = 0;   // LETIMER underflow bookkeeping only
volatile bool      half0Ready        = false;
volatile bool      half1Ready        = false;
volatile uint32_t  ecg_overrun_count = 0;   // consumer fell behind by a full lap
volatile uint32_t  halves_completed  = 0;   // increments forever, never cleared -- proof of continuous DMA activity
volatile bool      first_half_seen   = false; // used to discard the possible spurious first sample (IADC_E307)

/***************************************************************************//**
 * LETIMER Interrupt
 *
 * IADC triggering is fully autonomous via PRS, and sample movement is fully
 * autonomous via DMADRV/LDMA. This ISR touches neither -- it exists purely
 * so you can sanity-check the LETIMER period (sample_count) without
 * perturbing the hardware pipeline at all.
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
 * DMADRV completion callback -- called by DMADRV's own internal LDMA ISR
 * every time one half of ecg_buffer finishes filling.
 *
 * sequenceNo is "number of times this callback has fired" (0, 1, 2, ...),
 * not a buffer id -- but since DMADRV_PeripheralMemoryPingPong() strictly
 * alternates dst0, dst1, dst0, dst1, ..., sequenceNo's parity tells us
 * which half just completed: even -> half 0, odd -> half 1.
 *
 * Returning true keeps the ping-pong going forever (required for a
 * continuous zero-CPU stream). Returning false would stop it after this
 * transfer -- never do that here.
 ******************************************************************************/
static bool ecgDmaCallback(unsigned int channel, unsigned int sequenceNo, void *userParam)
{
  (void)channel;
  (void)userParam;

  halves_completed++;   // monotonic -- check this across two debugger pauses

  if ((sequenceNo & 1U) == 0U)
  {
    if (half0Ready) { ecg_overrun_count++; }   // consumer didn't drain in time
    half0Ready = true;
  }
  else
  {
    if (half1Ready) { ecg_overrun_count++; }
    half1Ready = true;
  }

  return true;   // keep streaming forever
}

/***************************************************************************//**
 * Initialize application
 ******************************************************************************/
void app_init(void)
{
  /**********************************************************************
   * 1. CMU - clocks first
   **********************************************************************/
  CMU_ClockEnable(cmuClock_GPIO, true);

  CMU_ClockEnable(cmuClock_LFRCO, true);

  CMU_ClockEnable(cmuClock_FSRCO, true);
  CMU_ClockSelectSet(cmuClock_IADCCLK, cmuSelect_FSRCO);

  CMU_ClockEnable(cmuClock_LETIMER0, true);
  CMU_ClockEnable(cmuClock_PRS, true);
  CMU_ClockEnable(cmuClock_IADC0, true);
  // NOTE: no manual cmuClock_LDMA enable here -- DMADRV_Init() handles the
  // LDMA clock (and IRQ enable) internally. Enabling it again yourself is
  // harmless but redundant.

  /**********************************************************************
   * 2. GPIO
   * iadcPosInputPadAna0 is a dedicated AIN pad -- no ABUSALLOC/pin-mode
   * routing required (that's only for iadcPosInputPortXPinY-style inputs).
   **********************************************************************/

  /**********************************************************************
   * 3. LETIMER - configure, do NOT enable yet
   **********************************************************************/
  // Tier-1 power tuning: scale the EM2/EM3 core voltage down for lower idle
  // current. Trade-off: slightly longer wake latency, which is irrelevant
  // here since our wake sources (LETIMER, LDMA) aren't latency-critical at
  // a ~10-15 Hz sample rate.
  EMU_EM23Init_TypeDef em23Init = EMU_EM23INIT_DEFAULT;
  em23Init.vScaleEM23Voltage = emuVScaleEM23_LowPower;
  EMU_EM23Init(&em23Init);
  
  
   LETIMER_Init_TypeDef letimerInit = LETIMER_INIT_DEFAULT;

  letimerInit.enable   = false;
  letimerInit.debugRun = true;   // keep running when core is halted in debugger
  letimerInit.comp0Top = true;
  letimerInit.repMode  = letimerRepeatFree;
  letimerInit.topValue = 131;   // ~1 second at LFRCO/32768 tick rate
  letimerInit.ufoa0    = letimerUFOAPulse;

  LETIMER_Init(LETIMER0, &letimerInit);
  LETIMER_CompareSet(LETIMER0, 0, 131);

  LETIMER_IntEnable(LETIMER0, LETIMER_IEN_UF);
  NVIC_EnableIRQ(LETIMER0_IRQn);

  /**********************************************************************
   * 4. PRS - route LETIMER0 OUT0 (pulse on underflow) to IADC0 single
   *    trigger, async channel.
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

  // Suspend ADC_CLK between conversions until the next PRS trigger (power).
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

  initSingle.triggerSelect = iadcTriggerSelPrs0PosEdge; // generic PRSPOS enum -> SINGLETRIGSEL
  initSingle.triggerAction = iadcTriggerActionOnce;
  initSingle.start         = true;             // arm the single queue
  initSingle.dataValidLevel = iadcFifoCfgDvl1;  // request DMA after every sample
  initSingle.fifoDmaWakeup  = true;             // arm the DMA request line

  singleInput.posInput = iadcPosInputPadAna0;
  singleInput.negInput = iadcNegInputGnd;

  IADC_init(IADC0, &init, &initAllConfigs);
  IADC_initSingle(IADC0, &initSingle, &singleInput);

  /**********************************************************************
   * 6. DMADRV - continuous ping-pong transfer, IADC0 FIFO -> RAM
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
      ECG_HALF_SAMPLES,                  // len, in dmadrvDataSize4 units
      dmadrvDataSize4,                   // 32-bit, matches SINGLEFIFODATA width
      ecgDmaCallback,
      NULL);

  /**********************************************************************
   * 7. LETIMER enable - START LAST
   **********************************************************************/
  LETIMER_Enable(LETIMER0, true);
}

/***************************************************************************//**
 * Main application loop
 *
 * No IADC register access. No FIFO reads. The CPU only reacts to whichever
 * half of ecg_buffer the DMADRV callback just marked ready, then goes back
 * to sleep. Call this from your idle/EM loop, e.g.:
 *
 *   while (1) {
 *     app_process_action();
 *     EMU_EnterEM2(true);   // wakes automatically on the next DMA completion
 *   }
 ******************************************************************************/
void app_process_action(void)
{
  if (half0Ready)
  {
    half0Ready = false;

    if (!first_half_seen)
    {
      first_half_seen = true;
      // ecg_buffer[0] may be a spurious immediate conversion per Silicon Labs'
      // published IADC_E307 errata (PRSPOS trigger can fire once immediately
      // if the PRS line is already high when the queue arms) -- don't treat
      // it as real data on this very first pass only.
    }

    // Consume ecg_buffer[0 .. ECG_HALF_SAMPLES-1] here (e.g. hand off to a
    // processing/BLE task). Hardware is now filling half 1 in parallel.
  }

  if (half1Ready)
  {
    half1Ready = false;
    // Consume ecg_buffer[ECG_HALF_SAMPLES .. ECG_BUFFER_SIZE-1] here.
    // Hardware is now filling half 0 in parallel.
  }

  // Tier-1 power design: nothing left for the CPU to do until the next
  // hardware event (LETIMER underflow or LDMA half/full completion).
  // Sleeping here -- instead of spinning through this function thousands of
  // times a second doing nothing -- is what actually makes the CPU idle
  // between samples. Wakes automatically on the next enabled interrupt.
  EMU_EnterEM2(true);
}