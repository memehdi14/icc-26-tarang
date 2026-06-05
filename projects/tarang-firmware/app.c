/****************************************************************************//**
 * @file    app.c
 * @brief   TARANG Clinical IoT Wearable — Core Firmware + BLE Layer
 *
 * Target:  EFR32MG26B210F1024IM48 (Series 2, Cortex-M33)
 * SDK:     Simplicity SDK (SiSDK) / emlib — NOT sl_hal (Series 3)
 * System:  LETIMER → PRS → IADC → LDMA (EM2) + framed IMU/PPG in EM0 window
 *
 * Authors: Team Ocelleon — IoT Challenge 2026
 *
 * Firmware layer : Kedar  (LETIMER, PRS, IADC, LDMA, IMU, PPG, pipeline)
 * BLE layer      : Kartik (advertising, connection, GATT, anomaly TX)
 *
 * CHANGE LOG (BLE patch — feature/ble-anomaly-notification):
 *   1. Added tarang_ble_conn_handle / tarang_ble_anomaly_notifications_enabled
 *      to track connection state for safe notification dispatch.
 *   2. Connection handle stored on sl_bt_evt_connection_opened_id.
 *   3. Both cleared on sl_bt_evt_connection_closed_id.
 *   4. CCCD tracking: anomaly CCCD enable/disable sets the flag.
 *   5. Fixed ce_len_max: 0 → 0xFFFF on connection open (BLE spec compliance).
 *   6. Implemented tarang_ble_submit_anomaly() with actual
 *      sl_bt_gatt_server_send_notification() using gattdb_anomaly_data (h=30).
 *   7. Kedar's firmware layer is 100% unchanged.
 *******************************************************************************/

#include "app.h"
#include "tarang_pipeline.h"
#include "gatt_db.h"          /* gattdb_anomaly_data, TARANG_ANOMALY_PKT_LEN */
#include "em_device.h"
#include "em_chip.h"
#include "em_cmu.h"
#include "em_emu.h"
#include "em_gpio.h"
#include "em_letimer.h"
#include "em_prs.h"
#include "em_iadc.h"
#include "em_ldma.h"
#include "em_i2c.h"
#include "em_usart.h"
#include "em_wdog.h"
#include "sl_core.h"
#include "sl_bt_api.h"
#include "app_assert.h"
#include <stdint.h>
#include <stdbool.h>
#include <string.h>

/* ─── Timing / geometry (LDMA descriptor contract) ─────────────────────── */
#define TARANG_ECG_SAMPLE_RATE_HZ    250u
#define TARANG_IMU_SAMPLE_RATE_HZ    100u
#define ECG_BUFFER_SIZE              TARANG_ECG_SAMPLES_PER_FRAME
#define IMU_BUFFER_SIZE              TARANG_IMU_SPI_FRAME_BYTES
#define LETIMER_TOP_VALUE            130u
#define LDMA_CH_ECG                  0u
#define LDMA_CH_IMU_RX               1u
#define LDMA_CH_IMU_TX               2u
#define ANOMALY_CONFIDENCE_THRESHOLD 0.85f
#define PPG_BUFFER_SIZE              TARANG_PPG_SAMPLES_PER_FRAME

#define TARANG_FRAME_PERIOD_US       ((ECG_BUFFER_SIZE * 1000000u) / TARANG_ECG_SAMPLE_RATE_HZ)
#define TARANG_LDMA_SPIN_LIMIT         2000000u
#define TARANG_I2C_SPIN_LIMIT          500000u

#define TARANG_IMU_REG_WHO_AM_I        0x75u
#define TARANG_IMU_REG_BURST           0x3Bu
#define TARANG_IMU_WHO_AM_I_EXPECT     0x68u
#define TARANG_MAX30102_ADDR           0x57u
#define TARANG_MAX30102_FIFO_DATA      0x07u

#define TARANG_MAX30102_FIFO_STATUS    0x00u
#define TARANG_MAX30102_LED1_PA        0x0Cu
#define TARANG_MAX30102_LED2_PA        0x0Du

#define TARANG_SPI_CS_PORT             gpioPortA
#define TARANG_SPI_CS_PIN              3u

/* PATCH 1: 16-bit link-relative P2M descriptor (not in em_ldma.h for Series 2) */
#define LDMA_DESCRIPTOR_LINKREL_P2M_HALFWORD(src, dest, count, linkOffset) \
  {                                                                        \
    .xfer =                                                                \
    {                                                                      \
      .structType   = ldmaCtrlStructTypeXfer,                              \
      .structReq    = 0,                                                   \
      .xferCnt      = (uint32_t)((count) - 1u),                            \
      .byteSwap     = 0,                                                   \
      .blockSize    = ldmaCtrlBlockSizeUnit1,                              \
      .doneIfs      = 1,                                                   \
      .reqMode      = ldmaCtrlReqModeBlock,                                \
      .decLoopCnt   = 0,                                                   \
      .ignoreSrec   = 0,                                                   \
      .srcInc       = ldmaCtrlSrcIncNone,                                  \
      .size         = ldmaCtrlSizeHalf,                                    \
      .dstInc       = ldmaCtrlDstIncOne,                                   \
      .srcAddrMode  = ldmaCtrlSrcAddrModeAbs,                              \
      .dstAddrMode  = ldmaCtrlDstAddrModeAbs,                              \
      .srcAddr      = (uint32_t)(src),                                     \
      .dstAddr      = (uint32_t)(dest),                                    \
      .linkMode     = ldmaLinkModeRel,                                     \
      .link         = 1,                                                   \
      .linkAddr     = (int32_t)((linkOffset) * LDMA_DESCRIPTOR_NON_EXTEND_SIZE_WORD) \
    }                                                                      \
  }

#ifndef cmuClock_LFAST
#define cmuClock_LFAST  cmuClock_EM23GRPACLK
#endif
#ifndef prsSignalLETIMER0_UNDERFLOW
#define prsSignalLETIMER0_UNDERFLOW  prsSignalLETIMER0_CH0
#endif

/* ─── Unified double-buffered frame pool (zero-copy LDMA targets) ────────── */
static sensor_frame_matrix_t Tarang_Pool[2] __attribute__((aligned(4)));

/* ─── LDMA descriptor chains (ECG ping-pong; IMU one-shot templates) ─────── */
static LDMA_Descriptor_t ecg_ldma_chain[2]    __attribute__((aligned(4)));
static LDMA_Descriptor_t imu_rx_ldma_chain[2] __attribute__((aligned(4)));
static LDMA_Descriptor_t imu_tx_ldma_chain[2] __attribute__((aligned(4)));

/* Framed SPI TX: byte0 = READ(0x3B), remainder = 0xFF clock fill */
static uint8_t imu_spi_tx_frame[IMU_BUFFER_SIZE] __attribute__((aligned(4)));

/* ─── Runtime pipeline control ───────────────────────────────────────────── */
static volatile uint8_t  ecg_active_pool_index           = 0u;
static volatile uint8_t  tarang_pending_pool_index        = 0xFFu;
static volatile uint32_t tarang_events_pending            = 0u;
static volatile uint32_t tarang_frame_sequence            = 0u;
static volatile uint32_t tarang_last_processed_sequence   = 0xFFFFFFFFu;
static volatile uint8_t  tarang_ownership_token_ctr       = 1u;
static volatile bool     tarang_acquisition_paused        = false;

static bool tarang_hf_boosted     = false;
static bool tarang_imu_present    = false;
static I2C_Init_TypeDef tarang_i2c_saved;
static tarang_diagnostics_t tarang_diag;

/* ─── BLE connection state (Kartik) ────────────────────────────────────────
 *
 * tarang_ble_conn_handle:
 *   Stores the connection handle from sl_bt_evt_connection_opened_id.
 *   Required by sl_bt_gatt_server_send_notification().
 *   Reset to SL_BT_INVALID_CONNECTION_HANDLE on disconnect.
 *
 * tarang_ble_anomaly_notifications_enabled:
 *   Set true only when the gateway writes CCCD = 0x0001 on gattdb_anomaly_data.
 *   Prevents sending notifications before the gateway has subscribed, which
 *   would return SL_STATUS_INVALID_STATE from the BLE stack.
 *
 * tarang_advertising_set_handle:
 *   Allocated by sl_bt_advertiser_create_set() on boot.
 *   Kept at 0xFF until assigned (SiLabs convention).
 * ──────────────────────────────────────────────────────────────────────── */
#define SL_BT_INVALID_CONNECTION_HANDLE  0xFFu

static uint8_t tarang_advertising_set_handle         = 0xFFu;
static uint8_t tarang_ble_conn_handle                 = SL_BT_INVALID_CONNECTION_HANDLE;
static bool    tarang_ble_anomaly_notifications_enabled = false;

/* ─── Forward declarations ─────────────────────────────────────────────── */
static void tarang_event_post(tarang_event_mask_t evt);
static void tarang_event_dispatch(void);
static void tarang_clock_boost_hf(void);
static void tarang_clock_revert_lp(void);
static void tarang_timestamp_capture(synchronization_metadata_t *sync);
static bool tarang_pool_transition(uint8_t idx, buffer_state_t expect,
                                   buffer_state_t next);
static void tarang_pipeline_fault(tarang_fault_flag_t fault, uint8_t pool_idx);
static void tarang_watchdog_init(void);
static void tarang_watchdog_feed(void);
static bool imu_validate_whoami(void);
static bool imu_framed_ldma_acquire(uint8_t *dst);
static bool ppg_burst_read_fifo(uint32_t *ppg_dst);
static void i2c_recover_bus(void);
static void tarang_acquisition_on_ecg_block(uint8_t pool_idx);
static void tarang_process_frame(sensor_frame_matrix_t *frame);
static void tarang_configure_ecg_ldma(void);
static void tarang_configure_imu_ldma_templates(void);
static void tarang_acquisition_pause(void);
static void tarang_acquisition_resume_if_idle(void);
static bool tarang_sequence_validate(uint32_t sequence);


/* ═══════════════════════════════════════════════════════════════════════════
 * LDMA_IRQHandler — minimal: ownership + events only (no sensor processing)
 * Owner: Kedar — DO NOT MODIFY
 * ═══════════════════════════════════════════════════════════════════════════ */
void LDMA_IRQHandler(void)
{
    uint32_t flags = LDMA_IntGet();
    LDMA_IntClear(flags);

    if (flags & (1u << LDMA_CH_ECG)) {
        uint8_t completed = ecg_active_pool_index;
        sensor_frame_matrix_t *frame = &Tarang_Pool[completed];

        if (frame->meta.state != BUFFER_STATE_DMA_OWNED) {
            tarang_pipeline_fault(TARANG_FAULT_OWNERSHIP, completed);
        } else if (!tarang_pool_transition(completed,
                                           BUFFER_STATE_DMA_OWNED,
                                           BUFFER_STATE_READY_FOR_AI)) {
            tarang_pipeline_fault(TARANG_FAULT_DMA_OVERRUN, completed);
        } else {
            tarang_timestamp_capture(&frame->meta.sync);
            frame->meta.sync_flags |= TARANG_SYNC_ECG_VALID;
            tarang_pending_pool_index = completed;
            tarang_event_post(TARANG_EVT_ACQ_FRAME);
        }

        ecg_active_pool_index ^= 1u;
        uint8_t filling = ecg_active_pool_index;

        if (Tarang_Pool[filling].meta.state != BUFFER_STATE_FREE) {
            tarang_pipeline_fault(TARANG_FAULT_DMA_OVERRUN, filling);
            tarang_diag.dropped_frames++;
            tarang_diag.missed_processing++;
            tarang_acquisition_pause();
        } else {
            (void)tarang_pool_transition(filling,
                                         BUFFER_STATE_FREE,
                                         BUFFER_STATE_DMA_OWNED);
        }
    }

    if (flags & (1u << LDMA_CH_IMU_RX)) {
        GPIO_PinOutSet(TARANG_SPI_CS_PORT, TARANG_SPI_CS_PIN);
    }
}


/* ═══════════════════════════════════════════════════════════════════════════
 * app_init
 * Owner: Kedar — DO NOT MODIFY (BLE state vars initialised at declaration)
 * ═══════════════════════════════════════════════════════════════════════════ */
void app_init(void)
{
    memset(&tarang_diag, 0, sizeof(tarang_diag));
    memset(Tarang_Pool, 0, sizeof(Tarang_Pool));

    Tarang_Pool[0].meta.pool_index = 0u;
    Tarang_Pool[0].meta.state      = BUFFER_STATE_DMA_OWNED;
    Tarang_Pool[1].meta.pool_index = 1u;
    Tarang_Pool[1].meta.state      = BUFFER_STATE_FREE;

    imu_spi_tx_frame[0] = (uint8_t)(TARANG_IMU_REG_BURST | 0x80u);
    memset(&imu_spi_tx_frame[1], 0xFF, IMU_BUFFER_SIZE - 1u);

    CHIP_Init();

    CMU_OscillatorEnable(cmuOsc_LFXO, true, true);
    CMU_ClockSelectSet(cmuClock_LFAST, cmuSelect_LFXO);

    CMU_OscillatorEnable(cmuOsc_HFXO, true, true);
    CMU_ClockSelectSet(cmuClock_SYSCLK, cmuSelect_HFXO);
    tarang_hf_boosted = true;

    CMU_ClockEnable(cmuClock_GPIO,     true);
    CMU_ClockEnable(cmuClock_PRS,      true);
    CMU_ClockEnable(cmuClock_LETIMER0, true);
    CMU_ClockEnable(cmuClock_IADC0,    true);
    CMU_ClockEnable(cmuClock_LDMA,     true);
    CMU_ClockEnable(cmuClock_LDMAXBAR, true);
    CMU_ClockEnable(cmuClock_I2C0,     true);
    CMU_ClockEnable(cmuClock_USART0,   true);

    GPIO_PinModeSet(gpioPortA, 5u, gpioModeDisabled,  0u);
    GPIO_PinModeSet(gpioPortA, 6u, gpioModeDisabled,  0u);
    GPIO_PinModeSet(gpioPortC, 2u, gpioModeWiredAnd,  1u);
    GPIO_PinModeSet(gpioPortC, 3u, gpioModeWiredAnd,  1u);
    GPIO_PinModeSet(gpioPortA, 0u, gpioModePushPull,  1u);
    GPIO_PinModeSet(gpioPortA, 1u, gpioModePushPull,  1u);
    GPIO_PinModeSet(gpioPortA, 2u, gpioModeInput,     0u);
    GPIO_PinModeSet(gpioPortA, 3u, gpioModePushPull,  1u);
    GPIO_PinOutSet(TARANG_SPI_CS_PORT, TARANG_SPI_CS_PIN);

    GPIO->I2CROUTE[0].SDAROUTE = (gpioPortC << _GPIO_I2C_SDAROUTE_PORT_SHIFT)
                                | (2u << _GPIO_I2C_SDAROUTE_PIN_SHIFT);
    GPIO->I2CROUTE[0].SCLROUTE = (gpioPortC << _GPIO_I2C_SCLROUTE_PORT_SHIFT)
                                | (3u << _GPIO_I2C_SCLROUTE_PIN_SHIFT);
    GPIO->I2CROUTE[0].ROUTEEN  = GPIO_I2C_ROUTEEN_SDAPEN | GPIO_I2C_ROUTEEN_SCLPEN;

    GPIO->USARTROUTE[0].TXROUTE  = (gpioPortA << _GPIO_USART_TXROUTE_PORT_SHIFT)
                                  | (1u << _GPIO_USART_TXROUTE_PIN_SHIFT);
    GPIO->USARTROUTE[0].RXROUTE  = (gpioPortA << _GPIO_USART_RXROUTE_PORT_SHIFT)
                                  | (2u << _GPIO_USART_RXROUTE_PIN_SHIFT);
    GPIO->USARTROUTE[0].CLKROUTE = (gpioPortA << _GPIO_USART_CLKROUTE_PORT_SHIFT)
                                  | (0u << _GPIO_USART_CLKROUTE_PIN_SHIFT);
    GPIO->USARTROUTE[0].ROUTEEN  = GPIO_USART_ROUTEEN_TXPEN
                                  | GPIO_USART_ROUTEEN_RXPEN
                                  | GPIO_USART_ROUTEEN_CLKPEN;

    LETIMER_Init_TypeDef letimerInit = LETIMER_INIT_DEFAULT;
    letimerInit.enable   = false;
    letimerInit.comp0Top = true;
    letimerInit.repMode  = letimerRepeatFree;
    letimerInit.ufoa0    = letimerUFOAPulse;
    letimerInit.out0Pol  = 0u;
    LETIMER_Init(LETIMER0, &letimerInit);
    LETIMER_CompareSet(LETIMER0, 0u, LETIMER_TOP_VALUE);

    PRS_ConnectSignal(0u, prsTypeAsync, prsSignalLETIMER0_UNDERFLOW);
    PRS_ConnectConsumer(0u, prsTypeAsync, prsConsumerIADC0_SINGLETRIGGER);

    IADC_Init_t        initIADC        = IADC_INIT_DEFAULT;
    IADC_AllConfigs_t  initAllConfigs  = IADC_ALLCONFIGS_DEFAULT;
    IADC_InitSingle_t  initSingle      = IADC_INITSINGLE_DEFAULT;
    IADC_SingleInput_t initSingleInput = IADC_SINGLEINPUT_DEFAULT;

    initIADC.warmup = iadcWarmupNormal;
    initAllConfigs.configs[0].reference    = iadcCfgReferenceInt1V2;
    initAllConfigs.configs[0].vRef         = 1210u;
    initAllConfigs.configs[0].osrHighSpeed = iadcCfgOsrHighSpeed2x;
    initAllConfigs.configs[0].adcClkPrescale =
        IADC_calcAdcClkPrescale(IADC0, 1000000uL, 0u,
                                iadcCfgModeNormal, initIADC.timebase);
    initSingle.triggerSelect  = iadcTriggerSelPrs0PosEdge;
    initSingle.dataValidLevel = iadcFifoCfgDvl1;
    initSingle.fifoDmaWakeup  = true;
    initSingle.singleTailgate = false;
    initSingleInput.posInput  = iadcPosInputPortAPin5;
    initSingleInput.negInput  = iadcNegInputPortAPin6;

    IADC_init(IADC0, &initIADC, &initAllConfigs);
    IADC_initSingle(IADC0, &initSingle, &initSingleInput);
    IADC_clearInt(IADC0, _IADC_IF_MASK);

    I2C_Init_TypeDef i2cInit = I2C_INIT_DEFAULT;
    i2cInit.enable  = true;
    i2cInit.master  = true;
    i2cInit.refFreq = 0u;
    i2cInit.freq    = I2C_FREQ_FAST_MAX;
    i2cInit.clhr    = i2cClockHLRFast;
    I2C_Init(I2C0, &i2cInit);
    tarang_i2c_saved = i2cInit;

    USART_InitSync_TypeDef spiInit = USART_INITSYNC_DEFAULT;
    spiInit.enable      = usartEnable;
    spiInit.refFreq     = 0u;
    spiInit.baudrate    = 8000000uL;
    spiInit.databits    = usartDatabits8;
    spiInit.master      = true;
    spiInit.msbf        = true;
    spiInit.clockMode   = usartClockMode3;
    spiInit.prsRxEnable = false;
    spiInit.autoTx      = false;
    USART_InitSync(USART0, &spiInit);

    tarang_watchdog_init();
    tarang_imu_present = imu_validate_whoami();
    if (!tarang_imu_present) {
        tarang_pipeline_fault(TARANG_FAULT_IMU_WHOAMI, 0xFFu);
    }

    LDMA_Init_t ldmaInit = LDMA_INIT_DEFAULT;
    LDMA_Init(&ldmaInit);
    tarang_configure_ecg_ldma();
    tarang_configure_imu_ldma_templates();

    LDMA_TransferCfg_t ecgCfg =
        LDMA_TRANSFER_CFG_PERIPHERAL(ldmaPeripheralSignal_IADC0_IADC_SINGLE);
    LDMA_StartTransfer(LDMA_CH_ECG, &ecgCfg, &ecg_ldma_chain[0]);

    NVIC_ClearPendingIRQ(LDMA_IRQn);
    NVIC_SetPriority(LDMA_IRQn, 2u);
    NVIC_EnableIRQ(LDMA_IRQn);

    LETIMER_Enable(LETIMER0, true);

    tarang_clock_revert_lp();
}


/* ═══════════════════════════════════════════════════════════════════════════
 * app_process_action — EM2 first, then deferred event engine in EM0 window
 * Owner: Kedar — DO NOT MODIFY
 * ═══════════════════════════════════════════════════════════════════════════ */
void app_process_action(void)
{
    tarang_clock_revert_lp();
    EMU_EnterEM2(true);
    tarang_clock_boost_hf();
    tarang_watchdog_feed();
    tarang_event_dispatch();
    tarang_watchdog_feed();
}


/* ═══════════════════════════════════════════════════════════════════════════
 * sl_bt_on_event — BLE stack event handler
 * Owner: Kartik
 *
 * CHANGES vs repo baseline:
 *   - connection_opened: saved conn handle; fixed ce_len_max 0 → 0xFFFF
 *   - connection_closed: cleared conn handle and CCCD flag
 *   - characteristic_status: tracked CCCD per gattdb_anomaly_data handle
 * ═══════════════════════════════════════════════════════════════════════════ */
void sl_bt_on_event(sl_bt_msg_t *evt)
{
    sl_status_t sc;

    switch (SL_BT_MSG_ID(evt->header)) {

    /* ── Boot: allocate advertising set and start connectable advertising ── */
    case sl_bt_evt_system_boot_id:
        sc = sl_bt_advertiser_create_set(&tarang_advertising_set_handle);
        app_assert_status(sc);

        sc = sl_bt_legacy_advertiser_generate_data(
                tarang_advertising_set_handle,
                sl_bt_advertiser_general_discoverable);
        app_assert_status(sc);

        /* 100 ms advertising interval (160 * 0.625 ms) */
        sc = sl_bt_advertiser_set_timing(
                tarang_advertising_set_handle,
                160,   /* min interval */
                160,   /* max interval */
                0,     /* duration: advertise indefinitely */
                0);    /* max events: unlimited */
        app_assert_status(sc);

        sc = sl_bt_legacy_advertiser_start(
                tarang_advertising_set_handle,
                sl_bt_legacy_advertiser_connectable);
        app_assert_status(sc);
        break;

    /* ── Connection opened: save handle, request connection parameters ───── */
    case sl_bt_evt_connection_opened_id:
        /*
         * BLE PATCH: store connection handle for notification dispatch.
         * Without this, tarang_ble_submit_anomaly() cannot call
         * sl_bt_gatt_server_send_notification() — it requires a valid handle.
         */
        tarang_ble_conn_handle = evt->data.evt_connection_opened.connection;

        /*
         * Request aggressive connection interval for low-latency telemetry:
         *   min CI = 16 * 1.25 ms = 20 ms
         *   max CI = 32 * 1.25 ms = 40 ms
         *   slave latency = 0 (no skipped events — essential for anomaly TX)
         *   supervision timeout = 100 * 10 ms = 1000 ms
         *   ce_len min/max = 0 / 0xFFFF (let the stack schedule freely)
         *
         * BLE PATCH FIX: ce_len_max was 0 in both the repo and Kartik's
         * skeleton. 0 forces zero-length connection events, starving the
         * stack. Set to 0xFFFF to let the controller decide.
         */
        sc = sl_bt_connection_set_parameters(
                evt->data.evt_connection_opened.connection,
                16,       /* min CI */
                32,       /* max CI */
                0,        /* slave latency */
                100,      /* supervision timeout (×10 ms = 1000 ms) */
                0,        /* ce_len min */
                0xFFFF);  /* ce_len max — FIXED from 0 */
        app_assert_status(sc);
        break;

    /* ── Connection closed: clear state, restart advertising ─────────────── */
    case sl_bt_evt_connection_closed_id:
        /*
         * BLE PATCH: clear both connection state variables so that any
         * in-flight anomaly packet from tarang_process_frame() is safely
         * dropped rather than sent to an invalid handle.
         */
        tarang_ble_conn_handle                  = SL_BT_INVALID_CONNECTION_HANDLE;
        tarang_ble_anomaly_notifications_enabled = false;

        sc = sl_bt_legacy_advertiser_generate_data(
                tarang_advertising_set_handle,
                sl_bt_advertiser_general_discoverable);
        app_assert_status(sc);

        sc = sl_bt_legacy_advertiser_start(
                tarang_advertising_set_handle,
                sl_bt_legacy_advertiser_connectable);
        app_assert_status(sc);
        break;

    /* ── CCCD write: track anomaly notification subscription ─────────────── */
    case sl_bt_evt_gatt_server_characteristic_status_id:
        /*
         * BLE PATCH: only act on CCCD writes (client_config flag), and only
         * on gattdb_anomaly_data (handle 30). Ignore CCCD writes on other
         * characteristics (e.g. gattdb_telemetry_data) to avoid false enables.
         */
        if (evt->data.evt_gatt_server_characteristic_status.status_flags
                == sl_bt_gatt_server_client_config) {

            if (evt->data.evt_gatt_server_characteristic_status.characteristic
                    == gattdb_anomaly_data) {

                if (evt->data.evt_gatt_server_characteristic_status.client_config_flags
                        == sl_bt_gatt_notification) {
                    /*
                     * Gateway subscribed to anomaly notifications.
                     * Re-negotiate CI now that data path is active.
                     */
                    tarang_ble_anomaly_notifications_enabled = true;

                    sc = sl_bt_connection_set_parameters(
                            evt->data.evt_gatt_server_characteristic_status.connection,
                            16,
                            32,
                            0,
                            100,
                            0,
                            0xFFFF);
                    app_assert_status(sc);

                } else if (evt->data.evt_gatt_server_characteristic_status.client_config_flags
                               == sl_bt_gatt_disable) {
                    /* Gateway unsubscribed — disable notification guard */
                    tarang_ble_anomaly_notifications_enabled = false;
                }
            }
        }
        break;

    default:
        break;
    }
}


/* ═══════════════════════════════════════════════════════════════════════════
 * tarang_ble_submit_anomaly — called from tarang_process_frame() in Kedar's
 * firmware pipeline when an anomaly exceeds ANOMALY_CONFIDENCE_THRESHOLD.
 *
 * Owner: Kartik (BLE TX path)
 * Integration point: called by Kedar's tarang_process_frame()
 *
 * Wire format (20 bytes, little-endian, see gatt_db.h):
 *   [0..3]  uint32_t  frame_sequence
 *   [4..7]  float     confidence_afib    (IEEE-754, little-endian)
 *   [8..11] float     confidence_pvc     (IEEE-754, little-endian)
 *   [12]    uint8_t   anomaly_type_flags (bit0=AFib, bit1=PVC)
 *   [13..19] uint8_t  reserved = 0x00
 *
 * Safety guards (in order):
 *   1. Null pointer check
 *   2. anomaly_detected flag (caller's gate — already checked in process_frame)
 *   3. Connection handle valid (not 0xFF — i.e. a central is connected)
 *   4. CCCD enabled (gateway has subscribed — prevents SL_STATUS_INVALID_STATE)
 * ═══════════════════════════════════════════════════════════════════════════ */
void tarang_ble_submit_anomaly(const tarang_ble_anomaly_t *pkt)
{
    if (pkt == NULL) {
        return;
    }
    if (!pkt->anomaly_detected) {
        return;
    }
    if (tarang_ble_conn_handle == SL_BT_INVALID_CONNECTION_HANDLE) {
        return;  /* No central connected — drop silently, firmware continues */
    }
    if (!tarang_ble_anomaly_notifications_enabled) {
        return;  /* Central hasn't subscribed yet — drop silently */
    }

    /*
     * Boost HF clock for BLE radio TX window.
     * tarang_ble_on_radio_wake() calls tarang_clock_boost_hf() which enables
     * HFXO and switches SYSCLK — required before any sl_bt_* API call that
     * triggers a radio operation.
     */
    tarang_ble_on_radio_wake();

    /*
     * Build the 20-byte anomaly notification packet.
     * memcpy is used for float fields to avoid strict-aliasing UB.
     */
    uint8_t payload[TARANG_ANOMALY_PKT_LEN];
    memset(payload, 0, sizeof(payload));

    /* [0..3] frame_sequence — little-endian uint32 */
    payload[0] = (uint8_t)( pkt->frame_sequence        & 0xFFu);
    payload[1] = (uint8_t)((pkt->frame_sequence >>  8) & 0xFFu);
    payload[2] = (uint8_t)((pkt->frame_sequence >> 16) & 0xFFu);
    payload[3] = (uint8_t)((pkt->frame_sequence >> 24) & 0xFFu);

    /* [4..7] confidence_afib — IEEE-754 float, copy as raw bytes */
    memcpy(&payload[4], &pkt->confidence_afib, sizeof(float));

    /* [8..11] confidence_pvc */
    memcpy(&payload[8], &pkt->confidence_pvc, sizeof(float));

    /* [12] anomaly_type_flags */
    uint8_t flags = 0u;
    if (pkt->confidence_afib >= ANOMALY_CONFIDENCE_THRESHOLD) {
        flags |= TARANG_ANOMALY_FLAG_AFIB;
    }
    if (pkt->confidence_pvc >= ANOMALY_CONFIDENCE_THRESHOLD) {
        flags |= TARANG_ANOMALY_FLAG_PVC;
    }
    payload[12] = flags;

    /* [13..19] reserved — already zeroed by memset */

    /*
     * Transmit the notification.
     * sl_bt_gatt_server_send_notification() arguments:
     *   connection   — handle saved on sl_bt_evt_connection_opened_id
     *   characteristic — gattdb_anomaly_data (handle 30, from gatt_db.h)
     *   value_len    — TARANG_ANOMALY_PKT_LEN (20)
     *   value        — payload buffer
     *
     * Return value is intentionally not assert'd here: a transient error
     * (e.g. TX buffer full) must not halt the firmware pipeline. The anomaly
     * event is logged in diagnostics instead.
     */
    sl_status_t sc = sl_bt_gatt_server_send_notification(
                         tarang_ble_conn_handle,
                         gattdb_anomaly_data,
                         sizeof(payload),
                         payload);

    if (sc != SL_STATUS_OK) {
        tarang_diag.sync_faults++;  /* Reuse existing counter — non-fatal */
    }

    tarang_ble_on_radio_sleep();
}


/* ═══════════════════════════════════════════════════════════════════════════
 * BLE radio power hooks — called by tarang_ble_submit_anomaly()
 * Owner: Kedar (clock management) — DO NOT MODIFY
 * ═══════════════════════════════════════════════════════════════════════════ */
void tarang_ble_on_radio_wake(void)
{
    tarang_clock_boost_hf();
}

void tarang_ble_on_radio_sleep(void)
{
    tarang_clock_revert_lp();
}


/* ═══════════════════════════════════════════════════════════════════════════
 * DSP / IMU / AI stubs — replace with NLMS / TFLM implementations
 * Owner: Kedar — DO NOT MODIFY structure; fill implementations in-place
 * ═══════════════════════════════════════════════════════════════════════════ */
void tarang_dsp_process(const tarang_dsp_input_t *in, tarang_dsp_output_t *out)
{
    if ((in == NULL) || (out == NULL)) {
        return;
    }
    (void)in;
    memset(out, 0, sizeof(*out));
    out->confidence_normal = 1.0f;
}

void tarang_imu_process(const tarang_imu_input_t *in, tarang_imu_output_t *out)
{
    if ((in == NULL) || (out == NULL)) {
        return;
    }
    (void)in;
    memset(out, 0, sizeof(*out));
}

void tarang_ai_process(const tarang_ai_input_t *in)
{
    if ((in == NULL) || (in->frame == NULL)) {
        return;
    }
    (void)in;
}

void tarang_ble_submit_telemetry(const tarang_ble_telemetry_t *pkt)
{
    if (pkt == NULL) {
        return;
    }
    tarang_ble_on_radio_wake();
    (void)pkt;
    tarang_ble_on_radio_sleep();
}


/* ═══════════════════════════════════════════════════════════════════════════
 * Public diagnostics / utility API
 * Owner: Kedar — DO NOT MODIFY
 * ═══════════════════════════════════════════════════════════════════════════ */
const tarang_diagnostics_t *tarang_diag_get(void)
{
    return &tarang_diag;
}

uint32_t tarang_time_us_from_sequence(uint32_t sequence)
{
    return sequence * TARANG_FRAME_PERIOD_US;
}

bool tarang_frame_try_acquire_processing(sensor_frame_matrix_t **frame_out,
                                         uint8_t *token_out)
{
    if ((frame_out == NULL) || (token_out == NULL)) {
        return false;
    }

    for (uint8_t i = 0u; i < 2u; i++) {
        CORE_DECLARE_IRQ_STATE;
        bool ok = false;
        CORE_ENTER_ATOMIC();
        if (Tarang_Pool[i].meta.state == BUFFER_STATE_READY_FOR_AI) {
            Tarang_Pool[i].meta.state = BUFFER_STATE_PROCESSING;
            Tarang_Pool[i].meta.ownership_token = tarang_ownership_token_ctr++;
            *token_out = Tarang_Pool[i].meta.ownership_token;
            *frame_out = &Tarang_Pool[i];
            ok = true;
        }
        CORE_EXIT_ATOMIC();
        if (ok) {
            return true;
        }
    }
    return false;
}

void tarang_frame_release_processing(uint8_t token)
{
    for (uint8_t i = 0u; i < 2u; i++) {
        CORE_DECLARE_IRQ_STATE;
        CORE_ENTER_ATOMIC();
        if ((Tarang_Pool[i].meta.state == BUFFER_STATE_PROCESSING)
            && (Tarang_Pool[i].meta.ownership_token == token)) {
            Tarang_Pool[i].meta.state     = BUFFER_STATE_FREE;
            Tarang_Pool[i].meta.sync_flags  = 0u;
            Tarang_Pool[i].meta.fault_flags = 0u;
            tarang_acquisition_resume_if_idle();
        }
        CORE_EXIT_ATOMIC();
    }
}

void tarang_ppg_apply_led_scale(uint8_t ir_current, uint8_t red_current)
{
    uint8_t reg;
    uint8_t val;

    reg = TARANG_MAX30102_LED1_PA;
    val = ir_current;
    I2C_TransferSeq_TypeDef seq_ir;
    seq_ir.addr        = (uint16_t)(TARANG_MAX30102_ADDR << 1u);
    seq_ir.flags       = I2C_FLAG_WRITE;
    seq_ir.buf[0].data = &reg;
    seq_ir.buf[0].len  = 1u;
    seq_ir.buf[1].data = &val;
    seq_ir.buf[1].len  = 1u;
    (void)I2C_TransferInit(I2C0, &seq_ir);
    while (I2C_Transfer(I2C0) == i2cTransferInProgress) {}

    reg = TARANG_MAX30102_LED2_PA;
    val = red_current;
    I2C_TransferSeq_TypeDef seq_red;
    seq_red.addr        = (uint16_t)(TARANG_MAX30102_ADDR << 1u);
    seq_red.flags       = I2C_FLAG_WRITE;
    seq_red.buf[0].data = &reg;
    seq_red.buf[0].len  = 1u;
    seq_red.buf[1].data = &val;
    seq_red.buf[1].len  = 1u;
    (void)I2C_TransferInit(I2C0, &seq_red);
    while (I2C_Transfer(I2C0) == i2cTransferInProgress) {}
}

void tarang_motion_quality_score(const tarang_imu_output_t *imu,
                                 tarang_motion_quality_t *quality)
{
    if ((imu == NULL) || (quality == NULL)) {
        return;
    }
    quality->motion_magnitude = imu->motion_magnitude;
    quality->is_in_motion     = imu->is_in_motion;
    quality->imu_quality      = imu->is_in_motion ? 500u : 1000u;
}


/* ═══════════════════════════════════════════════════════════════════════════
 * Private firmware implementation — Owner: Kedar — DO NOT MODIFY
 * ═══════════════════════════════════════════════════════════════════════════ */

static void tarang_event_post(tarang_event_mask_t evt)
{
    CORE_DECLARE_IRQ_STATE;
    CORE_ENTER_ATOMIC();
    tarang_events_pending |= (uint32_t)evt;
    CORE_EXIT_ATOMIC();
}

static void tarang_event_dispatch(void)
{
    uint32_t events;
    CORE_DECLARE_IRQ_STATE;

    CORE_ENTER_ATOMIC();
    events = tarang_events_pending;
    tarang_events_pending = 0u;
    CORE_EXIT_ATOMIC();

    if (events & (uint32_t)TARANG_EVT_ACQ_FRAME) {
        uint8_t idx = tarang_pending_pool_index;
        if (idx < 2u) {
            tarang_acquisition_on_ecg_block(idx);
            tarang_event_post(TARANG_EVT_PROCESS);
        }
    }

    if (events & (uint32_t)TARANG_EVT_PROCESS) {
        sensor_frame_matrix_t *frame = NULL;
        uint8_t token = 0u;
        while (tarang_frame_try_acquire_processing(&frame, &token)) {
            tarang_process_frame(frame);
            tarang_frame_release_processing(token);
        }
    }

    if (events & (uint32_t)TARANG_EVT_BLE) {
        /*
         * BLE event window — HF clock is already boosted by app_process_action.
         * tarang_ble_submit_anomaly() manages its own radio wake/sleep;
         * nothing additional needed here.
         */
        tarang_clock_boost_hf();
        tarang_clock_revert_lp();
    }

    if (events & (uint32_t)TARANG_EVT_FAULT) {
        tarang_watchdog_feed();
    }
}

static void tarang_clock_boost_hf(void)
{
    if (tarang_hf_boosted) {
        return;
    }
    CMU_OscillatorEnable(cmuOsc_HFXO, true, true);
    CMU_ClockSelectSet(cmuClock_SYSCLK, cmuSelect_HFXO);
    CMU_ClockEnable(cmuClock_I2C0,   true);
    CMU_ClockEnable(cmuClock_USART0, true);
    tarang_hf_boosted = true;
}

static void tarang_clock_revert_lp(void)
{
    if (!tarang_hf_boosted) {
        return;
    }
    CMU_ClockEnable(cmuClock_I2C0,   false);
    CMU_ClockEnable(cmuClock_USART0, false);
    CMU_ClockSelectSet(cmuClock_SYSCLK, cmuSelect_FSRCO);
    CMU_OscillatorEnable(cmuOsc_HFXO, false, false);
    tarang_hf_boosted = false;
}

static void tarang_acquisition_pause(void)
{
    CORE_DECLARE_IRQ_STATE;
    CORE_ENTER_ATOMIC();
    if (!tarang_acquisition_paused) {
        LETIMER_Enable(LETIMER0, false);
        tarang_acquisition_paused = true;
    }
    CORE_EXIT_ATOMIC();
}

static void tarang_acquisition_resume_if_idle(void)
{
    bool resume = true;
    for (uint8_t i = 0u; i < 2u; i++) {
        if (Tarang_Pool[i].meta.state != BUFFER_STATE_FREE) {
            resume = false;
            break;
        }
    }
    if (!resume) {
        return;
    }

    CORE_DECLARE_IRQ_STATE;
    CORE_ENTER_ATOMIC();
    if (tarang_acquisition_paused) {
        ecg_active_pool_index        = 0u;
        Tarang_Pool[0].meta.state    = BUFFER_STATE_DMA_OWNED;
        Tarang_Pool[1].meta.state    = BUFFER_STATE_FREE;
        LETIMER_Enable(LETIMER0, true);
        tarang_acquisition_paused    = false;
    }
    CORE_EXIT_ATOMIC();
}

static bool tarang_sequence_validate(uint32_t sequence)
{
    if (tarang_last_processed_sequence == 0xFFFFFFFFu) {
        tarang_last_processed_sequence = sequence;
        return true;
    }
    if (sequence != (tarang_last_processed_sequence + 1u)) {
        tarang_diag.sequence_gaps++;
        tarang_last_processed_sequence = sequence;
        return false;
    }
    tarang_last_processed_sequence = sequence;
    return true;
}

static void tarang_timestamp_capture(synchronization_metadata_t *sync)
{
    if (sync == NULL) {
        return;
    }
    CORE_DECLARE_IRQ_STATE;
    CORE_ENTER_ATOMIC();
    sync->letimer_ticks  = LETIMER_CounterGet(LETIMER0);
    sync->frame_sequence = tarang_frame_sequence++;
    CORE_EXIT_ATOMIC();
    sync->sample_time_us = tarang_time_us_from_sequence(sync->frame_sequence);
}

static bool tarang_pool_transition(uint8_t idx, buffer_state_t expect,
                                   buffer_state_t next)
{
    if (idx >= 2u) {
        return false;
    }
    bool ok = false;
    CORE_DECLARE_IRQ_STATE;
    CORE_ENTER_ATOMIC();
    if (Tarang_Pool[idx].meta.state == expect) {
        Tarang_Pool[idx].meta.state = next;
        ok = true;
    }
    CORE_EXIT_ATOMIC();
    return ok;
}

static void tarang_pipeline_fault(tarang_fault_flag_t fault, uint8_t pool_idx)
{
    if (fault == TARANG_FAULT_DMA_OVERRUN) {
        tarang_diag.dma_overruns++;
    } else if (fault == TARANG_FAULT_STALE_FRAME) {
        tarang_diag.stale_frames++;
    } else if (fault == TARANG_FAULT_OWNERSHIP) {
        tarang_diag.ownership_violations++;
    } else if (fault == TARANG_FAULT_IMU_TIMEOUT) {
        tarang_diag.imu_timeouts++;
    } else if (fault == TARANG_FAULT_PPG_TIMEOUT) {
        tarang_diag.ppg_timeouts++;
    }

    if (pool_idx < 2u) {
        CORE_DECLARE_IRQ_STATE;
        CORE_ENTER_ATOMIC();
        Tarang_Pool[pool_idx].meta.fault_flags |= (uint32_t)fault;
        CORE_EXIT_ATOMIC();
    }

    tarang_diag.sync_faults++;
    tarang_event_post(TARANG_EVT_FAULT);
}

static void tarang_watchdog_init(void)
{
#if defined(WDOG0)
    WDOG_Init_TypeDef wdogInit = WDOG_INIT_DEFAULT;
    wdogInit.enable = true;
    wdogInit.em2Run = false;
    WDOGn_Init(WDOG0, &wdogInit);
#endif
}

static void tarang_watchdog_feed(void)
{
#if defined(WDOG0)
    WDOGn_Feed(WDOG0);
    tarang_diag.wdog_feeds++;
#endif
}

static bool imu_validate_whoami(void)
{
    uint8_t tx = (uint8_t)(TARANG_IMU_REG_WHO_AM_I | 0x80u);
    uint8_t id = 0u;

    GPIO_PinOutClear(TARANG_SPI_CS_PORT, TARANG_SPI_CS_PIN);
    (void)USART_SpiTransfer(USART0, tx);
    id = (uint8_t)USART_SpiTransfer(USART0, 0xFFu);
    GPIO_PinOutSet(TARANG_SPI_CS_PORT, TARANG_SPI_CS_PIN);

    return (id == TARANG_IMU_WHO_AM_I_EXPECT);
}

static void tarang_configure_ecg_ldma(void)
{
    ecg_ldma_chain[0] = (LDMA_Descriptor_t)
        LDMA_DESCRIPTOR_LINKREL_P2M_HALFWORD(
            &(IADC0->SINGLEFIFODATA),
            Tarang_Pool[0].data.ecg,
            ECG_BUFFER_SIZE,
            +1);

    ecg_ldma_chain[1] = (LDMA_Descriptor_t)
        LDMA_DESCRIPTOR_LINKREL_P2M_HALFWORD(
            &(IADC0->SINGLEFIFODATA),
            Tarang_Pool[1].data.ecg,
            ECG_BUFFER_SIZE,
            -1);
}

static void tarang_configure_imu_ldma_templates(void)
{
    imu_tx_ldma_chain[0] = (LDMA_Descriptor_t)
        LDMA_DESCRIPTOR_SINGLE_M2P_BYTE(
            imu_spi_tx_frame,
            &(USART0->TXDATA),
            IMU_BUFFER_SIZE);
    imu_tx_ldma_chain[0].xfer.doneIfs   = 0u;
    imu_tx_ldma_chain[0].xfer.blockSize = ldmaCtrlBlockSizeUnit1;

    imu_rx_ldma_chain[0] = (LDMA_Descriptor_t)
        LDMA_DESCRIPTOR_SINGLE_P2M_BYTE(
            &(USART0->RXDATA),
            Tarang_Pool[0].data.imu_spi,
            IMU_BUFFER_SIZE);
    imu_rx_ldma_chain[0].xfer.doneIfs   = 1u;
    imu_rx_ldma_chain[0].xfer.blockSize = ldmaCtrlBlockSizeUnit1;
}

static bool imu_framed_ldma_acquire(uint8_t *dst)
{
    if ((dst == NULL) || !tarang_imu_present) {
        return false;
    }

    imu_rx_ldma_chain[0] = (LDMA_Descriptor_t)
        LDMA_DESCRIPTOR_SINGLE_P2M_BYTE(
            &(USART0->RXDATA),
            dst,
            IMU_BUFFER_SIZE);
    imu_rx_ldma_chain[0].xfer.doneIfs   = 1u;
    imu_rx_ldma_chain[0].xfer.blockSize = ldmaCtrlBlockSizeUnit1;

    LDMA_TransferCfg_t imuRxCfg =
        LDMA_TRANSFER_CFG_PERIPHERAL(ldmaPeripheralSignal_USART0_RXDATAV);
    LDMA_TransferCfg_t imuTxCfg =
        LDMA_TRANSFER_CFG_PERIPHERAL(ldmaPeripheralSignal_USART0_TXBL);

    GPIO_PinOutClear(TARANG_SPI_CS_PORT, TARANG_SPI_CS_PIN);

    LDMA_StartTransfer(LDMA_CH_IMU_TX, &imuTxCfg, &imu_tx_ldma_chain[0]);
    LDMA_StartTransfer(LDMA_CH_IMU_RX, &imuRxCfg, &imu_rx_ldma_chain[0]);

    uint32_t spin = 0u;
    while (!LDMA_TransferDone(LDMA_CH_IMU_RX)) {
        if (++spin > TARANG_LDMA_SPIN_LIMIT) {
            GPIO_PinOutSet(TARANG_SPI_CS_PORT, TARANG_SPI_CS_PIN);
            tarang_pipeline_fault(TARANG_FAULT_IMU_TIMEOUT, 0xFFu);
            tarang_diag.spi_recoveries++;
            return false;
        }
        tarang_watchdog_feed();
    }

    GPIO_PinOutSet(TARANG_SPI_CS_PORT, TARANG_SPI_CS_PIN);
    return true;
}

static bool ppg_burst_read_fifo(uint32_t *ppg_dst)
{
    if (ppg_dst == NULL) {
        return false;
    }

    uint8_t status_reg = TARANG_MAX30102_FIFO_STATUS;
    uint8_t status_val = 0u;
    I2C_TransferSeq_TypeDef status_seq;
    status_seq.addr        = (uint16_t)(TARANG_MAX30102_ADDR << 1u);
    status_seq.flags       = I2C_FLAG_WRITE_READ;
    status_seq.buf[0].data = &status_reg;
    status_seq.buf[0].len  = 1u;
    status_seq.buf[1].data = &status_val;
    status_seq.buf[1].len  = 1u;
    I2C_TransferReturn_TypeDef st = I2C_TransferInit(I2C0, &status_seq);
    while (st == i2cTransferInProgress) {
        st = I2C_Transfer(I2C0);
    }
    if ((st == i2cTransferDone) && (status_val & 0x20u)) {
        tarang_pipeline_fault(TARANG_FAULT_PPG_TIMEOUT, 0xFFu);
    }

    uint8_t rx_buf[96];
    uint8_t reg_addr = TARANG_MAX30102_FIFO_DATA;

    I2C_TransferSeq_TypeDef seq;
    seq.addr        = (uint16_t)(TARANG_MAX30102_ADDR << 1u);
    seq.flags       = I2C_FLAG_WRITE_READ;
    seq.buf[0].data = &reg_addr;
    seq.buf[0].len  = 1u;
    seq.buf[1].data = rx_buf;
    seq.buf[1].len  = sizeof(rx_buf);

    I2C_TransferReturn_TypeDef result = I2C_TransferInit(I2C0, &seq);
    uint32_t spin = 0u;
    while (result == i2cTransferInProgress) {
        result = I2C_Transfer(I2C0);
        if (++spin > TARANG_I2C_SPIN_LIMIT) {
            i2c_recover_bus();
            tarang_pipeline_fault(TARANG_FAULT_PPG_TIMEOUT, 0xFFu);
            return false;
        }
        tarang_watchdog_feed();
    }

    if (result != i2cTransferDone) {
        i2c_recover_bus();
        tarang_pipeline_fault(TARANG_FAULT_I2C_STUCK, 0xFFu);
        return false;
    }

    for (uint8_t i = 0u; i < PPG_BUFFER_SIZE; i++) {
        ppg_dst[i] = ((uint32_t)rx_buf[i * 3u]          << 16u)
                   | ((uint32_t)rx_buf[i * 3u + 1u]     <<  8u)
                   |  (uint32_t)rx_buf[i * 3u + 2u];
    }
    return true;
}

static void i2c_recover_bus(void)
{
    tarang_diag.i2c_recoveries++;

    I2C_Enable(I2C0, false);
    GPIO_PinModeSet(gpioPortC, 3u, gpioModeWiredAnd, 1u);
    for (uint8_t i = 0u; i < 9u; i++) {
        GPIO_PinOutClear(gpioPortC, 3u);
        for (volatile uint32_t d = 0u; d < 100u; d++) {}
        GPIO_PinOutSet(gpioPortC, 3u);
        for (volatile uint32_t d = 0u; d < 100u; d++) {}
    }
    I2C_Enable(I2C0, true);
    I2C_Init(I2C0, &tarang_i2c_saved);
}

static void tarang_acquisition_on_ecg_block(uint8_t pool_idx)
{
    if (pool_idx >= 2u) {
        return;
    }

    CORE_DECLARE_IRQ_STATE;
    CORE_ENTER_ATOMIC();
    tarang_pending_pool_index = 0xFFu;
    CORE_EXIT_ATOMIC();

    sensor_frame_matrix_t *frame = &Tarang_Pool[pool_idx];

    if (frame->meta.state != BUFFER_STATE_READY_FOR_AI) {
        tarang_pipeline_fault(TARANG_FAULT_STALE_FRAME, pool_idx);
        return;
    }

    (void)tarang_sequence_validate(frame->meta.sync.frame_sequence);

    if (tarang_imu_present) {
        if (imu_framed_ldma_acquire(frame->data.imu_spi)) {
            frame->meta.sync_flags  |= TARANG_SYNC_IMU_VALID;
            frame->meta.imu_quality  = 1000u;
        }
    }

    if (ppg_burst_read_fifo(frame->data.ppg)) {
        frame->meta.sync_flags  |= TARANG_SYNC_PPG_VALID;
        frame->meta.ppg_quality  = 1000u;
    }

    frame->meta.ecg_quality  = 1000u;
    frame->meta.sync_flags  |= TARANG_SYNC_COMMITTED;
}

static void tarang_process_frame(sensor_frame_matrix_t *frame)
{
    if (frame == NULL) {
        return;
    }

    tarang_dsp_input_t  dsp_in;
    tarang_dsp_output_t dsp_out;
    tarang_imu_input_t  imu_in;
    tarang_imu_output_t imu_out;

    dsp_in.ecg          = frame->data.ecg;
    dsp_in.ppg          = frame->data.ppg;
    dsp_in.sequence     = frame->meta.sync.frame_sequence;
    dsp_in.timestamp_us = frame->meta.sync.sample_time_us;
    tarang_dsp_process(&dsp_in, &dsp_out);

    if (frame->meta.sync_flags & TARANG_SYNC_IMU_VALID) {
        imu_in.imu_spi  = frame->data.imu_spi;
        imu_in.sequence = frame->meta.sync.frame_sequence;
        tarang_imu_process(&imu_in, &imu_out);
        (void)imu_out;
    }

    /*
     * Anomaly gate: if either classifier fires above threshold, build the
     * packet and hand it to the BLE layer via tarang_ble_submit_anomaly().
     * That function owns all connection/CCCD guards — this caller does not
     * need to check BLE state.
     */
    if ((dsp_out.confidence_afib >= ANOMALY_CONFIDENCE_THRESHOLD)
        || (dsp_out.confidence_pvc >= ANOMALY_CONFIDENCE_THRESHOLD)) {

        tarang_ble_anomaly_t pkt;
        pkt.frame_sequence   = frame->meta.sync.frame_sequence;
        pkt.confidence_afib  = dsp_out.confidence_afib;
        pkt.confidence_pvc   = dsp_out.confidence_pvc;
        pkt.anomaly_detected = true;
        tarang_ble_submit_anomaly(&pkt);
        tarang_event_post(TARANG_EVT_BLE);
    }

    tarang_ai_input_t ai_in;
    ai_in.frame           = frame;
    ai_in.ownership_token = frame->meta.ownership_token;
    tarang_ai_process(&ai_in);
}