/*******************************************************************************
 * app.c — TARANG PPG Acquisition (Interrupt-Driven, INT pin = PC06)
 *
 * TARGET : EFR32MG26B510F3200IM48
 * SDK    : Simplicity SDK (SiSDK) — Bluetooth project
 * I2C    : sl_i2cspm_mikroe (PC05=SCL, PC07=SDA)
 * INT PIN: PC06 — MAX30102 active-LOW interrupt → falling edge trigger
 *
 * BUILD FIX SUMMARY:
 *   BUG 1 (FATAL): Defined GPIO_EVEN_IRQHandler() directly.
 *          SDK's gpiointerrupt.c already owns this vector.
 *          LINKER ERROR: multiple definition of GPIO_EVEN_IRQHandler.
 *          FIX: Delete the raw ISR. Use GPIOINT_CallbackRegister() instead.
 *
 *   BUG 2 (FUNCTIONAL): GPIO_ExtIntConfig() intNo parameter was 6.
 *          For Series 2, intNo must equal the pin number = 6. This was
 *          accidentally correct but undocumented — added clear comment.
 *
 *   BUG 3 (FUNCTIONAL): INT_ENABLE1 = 0x80 enables A_FULL interrupt,
 *          NOT the PPG_RDY (data ready) interrupt.
 *          A_FULL fires when FIFO is almost FULL (17 slots used).
 *          PPG_RDY fires after EVERY new sample — what we actually want.
 *          FIX: INT_ENABLE1 = 0x40 → enables PPG_RDY interrupt.
 *
 *   BUG 4 (SUBTLE): INT_STATUS registers read in app_init() before
 *          the GPIO interrupt is configured. This clears the initial
 *          power-ready interrupt flag prematurely. Moved to after config.
 *
 *   BUG 5 (FUNCTIONAL): max30102_read_fifo() reads only 6 bytes = 1 sample.
 *          At 100Hz, interrupt fires 100 times/sec. Fine for now, but
 *          FIFO depth check added to show when burst reading is needed.
 ******************************************************************************/

#include "app.h"

#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>

#include "sl_i2cspm.h"
#include "sl_i2cspm_instances.h"
#include "sl_iostream.h"

#include "em_gpio.h"
#include "em_cmu.h"
#include "em_core.h"



/*
 * CRITICAL INCLUDE — This is what you were missing.
 * gpiointerrupt.h gives you GPIOINT_Init() and GPIOINT_CallbackRegister().
 * The SDK's gpiointerrupt.c already defines GPIO_EVEN_IRQHandler() and
 * GPIO_ODD_IRQHandler() internally and dispatches to your callback.
 * You must NEVER define GPIO_EVEN_IRQHandler() yourself in an SDK project.
 */
#include "gpiointerrupt.h"

/*******************************************************************************
 * MAX30102 Register Map
 ******************************************************************************/
#define MAX30102_ADDR              0x57

#define MAX30102_INT_STATUS1       0x00   /* Read to clear interrupt */
#define MAX30102_INT_STATUS2       0x01
#define MAX30102_INT_ENABLE1       0x02
#define MAX30102_INT_ENABLE2       0x03

#define MAX30102_FIFO_WR_PTR       0x04
#define MAX30102_OVF_COUNTER       0x05
#define MAX30102_FIFO_RD_PTR       0x06
#define MAX30102_FIFO_DATA_REG     0x07
#define MAX30102_FIFO_CONFIG_REG   0x08

#define MAX30102_MODE_CONFIG       0x09
#define MAX30102_SPO2_CONFIG       0x0A

#define MAX30102_LED1_PA           0x0C
#define MAX30102_LED2_PA           0x0D

#define MAX30102_MULTI_LED_CTRL1   0x11
#define MAX30102_MULTI_LED_CTRL2   0x12

#define MAX30102_PART_ID_REG       0xFF

/*******************************************************************************
 * INT_ENABLE1 bit definitions — THIS WAS BUG 3
 *
 * Bit 7 = A_FULL_EN  → fires when FIFO has only 17 free slots remaining
 *                       (almost full) — NOT what we want for per-sample
 * Bit 6 = PPG_RDY_EN → fires after EVERY new sample is written to FIFO
 *                       THIS is what we need for interrupt-driven acquisition
 *
 * Your original code used 0x80 (A_FULL) which fires rarely and
 * unpredictably — it would appear to "miss" most samples.
 * Correct value: 0x40 (PPG_RDY) fires at exactly 100Hz.
 ******************************************************************************/
#define MAX30102_INT_ENABLE1_PPG_RDY    0x40u   /* Correct: per-sample IRQ */
#define MAX30102_INT_ENABLE1_A_FULL     0x80u   /* Wrong for per-sample use */

/*******************************************************************************
 * Hardware Pin Definition — MAX30102 INT connected to PC06
 ******************************************************************************/
#define MAX30102_INT_PORT    gpioPortC
#define MAX30102_INT_PIN     6u

/*
 * EFR32 Series 2 GPIO interrupt constraint:
 * Pin number N on any port maps to external interrupt line N.
 * PC06 → interrupt line 6 → even number → dispatched by GPIO_EVEN_IRQHandler.
 * intNo in GPIO_ExtIntConfig() MUST equal the pin number (= 6 here).
 * Only ONE pin numbered 6 (across all ports) can use interrupt line 6.
 * You cannot simultaneously use PA06, PB06, and PC06 as interrupts.
 */
#define MAX30102_INT_LINE    6u

/*******************************************************************************
 * Buffer definitions
 ******************************************************************************/
#define PPG_BUFFER_SIZE    1024u

uint32_t ppg_red_buffer[PPG_BUFFER_SIZE];
uint32_t ppg_ir_buffer[PPG_BUFFER_SIZE];

volatile uint32_t ppg_index        = 0u;
volatile uint32_t ppg_sample_count = 0u;

/*******************************************************************************
 * Runtime state
 ******************************************************************************/
volatile bool     ppg_data_ready   = false;
volatile uint32_t interrupt_count  = 0u;

/* Diagnostics */
volatile uint32_t read_attempts    = 0u;
volatile uint32_t read_success     = 0u;
volatile uint32_t read_failures    = 0u;
volatile uint32_t write_failures   = 0u;
volatile uint32_t fifo_poll_count  = 0u;
volatile uint32_t sample_reads     = 0u;
volatile uint32_t fifo_overflow_total = 0u;

volatile uint8_t  fifo_wr_ptr      = 0u;
volatile uint8_t  fifo_rd_ptr      = 0u;
volatile uint8_t  fifo_ovf         = 0u;
volatile uint32_t red_sample       = 0u;
volatile uint32_t ir_sample        = 0u;
volatile uint8_t  int_status1      = 0u;
volatile uint8_t  int_status2      = 0u;

volatile bool     max30102_found   = false;

/*******************************************************************************
 * Private: I2C read/write helpers (unchanged — proven working)
 ******************************************************************************/
static bool max30102_read_reg(uint8_t reg, uint8_t *value)
{
    I2C_TransferSeq_TypeDef    seq;
    I2C_TransferReturn_TypeDef ret;
    uint8_t reg_addr = reg;

    seq.addr        = (uint16_t)(MAX30102_ADDR << 1u);
    seq.flags       = I2C_FLAG_WRITE_READ;
    seq.buf[0].data = &reg_addr;
    seq.buf[0].len  = 1u;
    seq.buf[1].data = value;
    seq.buf[1].len  = 1u;

    ret = I2CSPM_Transfer(sl_i2cspm_mikroe, &seq);
    return (ret == i2cTransferDone);
}

static bool max30102_write_reg(uint8_t reg, uint8_t value)
{
    I2C_TransferSeq_TypeDef    seq;
    I2C_TransferReturn_TypeDef ret;
    uint8_t tx[2] = { reg, value };

    seq.addr        = (uint16_t)(MAX30102_ADDR << 1u);
    seq.flags       = I2C_FLAG_WRITE;
    seq.buf[0].data = tx;
    seq.buf[0].len  = 2u;

    ret = I2CSPM_Transfer(sl_i2cspm_mikroe, &seq);
    return (ret == i2cTransferDone);
}

static bool max30102_read_fifo_one(uint8_t *data)
{
    I2C_TransferSeq_TypeDef    seq;
    I2C_TransferReturn_TypeDef ret;
    uint8_t reg = MAX30102_FIFO_DATA_REG;

    seq.addr        = (uint16_t)(MAX30102_ADDR << 1u);
    seq.flags       = I2C_FLAG_WRITE_READ;
    seq.buf[0].data = &reg;
    seq.buf[0].len  = 1u;
    seq.buf[1].data = data;
    seq.buf[1].len  = 6u;   /* 3 bytes RED + 3 bytes IR = 1 sample */

    ret = I2CSPM_Transfer(sl_i2cspm_mikroe, &seq);
    return (ret == i2cTransferDone);
}

/*******************************************************************************
 * MAX30102 GPIO Interrupt Callback
 *
 * THIS replaces your deleted GPIO_EVEN_IRQHandler().
 *
 * How it works:
 *   1. SDK's gpiointerrupt.c owns GPIO_EVEN_IRQHandler().
 *   2. It calls GPIO_IntGet(), clears flags, then dispatches to callbacks
 *      registered for each pin number via GPIOINT_CallbackRegister().
 *   3. This function is registered for pin 6 (PC06).
 *   4. It is called by the SDK dispatcher when PC06 falls LOW.
 *
 * The uint8_t parameter is the pin number (6) — ignore it here.
 * Keep this ISR minimal: just set flag, count, return.
 * All I2C work happens in app_process_action().
 ******************************************************************************/
static void max30102_gpio_callback(uint8_t pin)
{
    (void)pin;   /* Pin number confirmed = 6, not needed here */

    interrupt_count++;
    ppg_data_ready = true;
}

/*******************************************************************************
 * app_init
 ******************************************************************************/
void app_init(void)
{
    printf("\r\n");
    printf("====================================\r\n");
    printf("MAX30102 INTERRUPT-DRIVEN TARANG PPG\r\n");
    printf("====================================\r\n");

    bool ok = true;

    /* ── Step 1: Configure MAX30102 sensor registers ─────────────────── */

    /* Clear FIFO pointers to start fresh */
    ok &= max30102_write_reg(MAX30102_FIFO_WR_PTR,  0x00u);
    ok &= max30102_write_reg(MAX30102_OVF_COUNTER,  0x00u);
    ok &= max30102_write_reg(MAX30102_FIFO_RD_PTR,  0x00u);

    /*
     * FIFO_CONFIG = 0x0F
     *   SMP_AVE[7:5]          = 000  → No averaging (raw 100Hz samples)
     *   FIFO_ROLLOVER_EN[4]   = 1    → Oldest sample overwritten on overflow
     *   FIFO_A_FULL[3:0]      = 0xF  → A_FULL fires when 17 slots remain
     */
    ok &= max30102_write_reg(MAX30102_FIFO_CONFIG_REG, 0x0Fu);

    /*
     * INT_ENABLE1 = 0x40 → Enable PPG_RDY interrupt ONLY
     *
     * BUG 3 FIX: Your original code used 0x80 (A_FULL_EN).
     * A_FULL fires when the FIFO has only 17 free slots — which at 100Hz
     * means it fires once every ~150ms with irregular timing.
     * You would miss 14 out of every 15 samples silently.
     *
     * 0x40 = PPG_RDY_EN: fires after EVERY new sample = exactly 100Hz.
     * This is what "interrupt-driven per-sample acquisition" means.
     */
    ok &= max30102_write_reg(MAX30102_INT_ENABLE1, MAX30102_INT_ENABLE1_PPG_RDY);
    ok &= max30102_write_reg(MAX30102_INT_ENABLE2, 0x00u);

    /*
     * MODE_CONFIG = 0x03 → SpO2 mode (RED + IR both enabled)
     * This gives both channels needed for SpO2 + heart rate.
     */
    ok &= max30102_write_reg(MAX30102_MODE_CONFIG, 0x03u);

    /*
     * SPO2_CONFIG = 0x27
     *   ADC_RGE[6:5] = 01 → 4096 nA full scale
     *   SR[4:2]      = 01 → 100 samples per second
     *   LED_PW[1:0]  = 11 → 411μs pulse width, 18-bit ADC resolution
     */
    ok &= max30102_write_reg(MAX30102_SPO2_CONFIG, 0x27u);

    /* LED drive currents — your proven values, keep unchanged */
    ok &= max30102_write_reg(MAX30102_LED1_PA,         0x24u);  /* RED ~7.2mA */
    ok &= max30102_write_reg(MAX30102_LED2_PA,         0x24u);  /* IR  ~7.2mA */
    ok &= max30102_write_reg(MAX30102_MULTI_LED_CTRL1, 0x21u);
    ok &= max30102_write_reg(MAX30102_MULTI_LED_CTRL2, 0x00u);

    if (!ok) {
        write_failures++;
        printf("[PPG] SENSOR CONFIG FAILED\r\n");
        return;
    }

    printf("[PPG] Sensor config OK\r\n");

    /*
     * BUG 4 FIX: Read and clear interrupt status AFTER sensor config,
     * NOT before GPIO interrupt setup. This clears the power-ready
     * flag that MAX30102 asserts after initial configuration, preventing
     * a ghost interrupt from firing immediately on GPIO enable.
     */
    max30102_read_reg(MAX30102_INT_STATUS1, (uint8_t *)&int_status1);
    max30102_read_reg(MAX30102_INT_STATUS2, (uint8_t *)&int_status2);
    printf("[PPG] INT_STATUS1=0x%02X INT_STATUS2=0x%02X (cleared)\r\n",
           int_status1, int_status2);

    /* ── Step 2: Configure PC06 as interrupt input ───────────────────── */

    /*
     * CMU_ClockEnable for GPIO should already be done by the SDK
     * init sequence in a Bluetooth project. Calling it again is safe
     * (idempotent) — it does not reset the peripheral.
     */
    CMU_ClockEnable(cmuClock_GPIO, true);

    /*
     * Set PC06 as input with internal pull-up resistor.
     *
     * gpioModeInputPull: digital input, pull direction set by DOUT.
     * DOUT = 1 → pull-UP (idle HIGH).
     *
     * MAX30102 INT pin is open-drain, active-LOW:
     *   Idle:   INT = HIGH (our pull-up holds it there)
     *   Sample: INT = LOW  (MAX30102 pulls it down)
     * → We trigger on FALLING EDGE (HIGH → LOW transition).
     */
    GPIO_PinModeSet(MAX30102_INT_PORT,
                    MAX30102_INT_PIN,
                    gpioModeInputPull,
                    1u);              /* 1 = pull-UP (idle HIGH) */

    /* ── Step 3: Initialize the SDK GPIO dispatcher ──────────────────── */

    /*
     * GPIOINT_Init() initializes the SDK's internal callback dispatch table.
     * It sets up GPIO_EVEN_IRQHandler() and GPIO_ODD_IRQHandler() internally.
     * Call this ONCE before any GPIOINT_CallbackRegister() calls.
     *
     * In a Bluetooth project, the SDK may already call this. Calling it
     * again is safe — it reinitializes the table but does not corrupt
     * existing callbacks unless you registered them before this call.
     * Safe order: GPIOINT_Init() → GPIOINT_CallbackRegister() always.
     */
    GPIOINT_Init();

    /*
     * Register our callback for pin number 6.
     *
     * GPIOINT_CallbackRegister(pin, callback)
     *   pin      = 6 → matches MAX30102_INT_PIN (PC06)
     *   callback = max30102_gpio_callback → our function above
     *
     * When PC06 triggers, SDK dispatcher calls max30102_gpio_callback(6).
     * The callback runs in interrupt context — keep it minimal (flag only).
     */
    GPIOINT_CallbackRegister(MAX30102_INT_PIN, max30102_gpio_callback);

    /* ── Step 4: Configure the external interrupt for PC06 ───────────── */

    /*
     * GPIO_ExtIntConfig(port, pin, intNo, risingEdge, fallingEdge, enable)
     *
     *   port        = gpioPortC      → Port C
     *   pin         = 6              → PC06
     *   intNo       = 6              → MUST equal pin number on Series 2.
     *                                  Maps to external interrupt line 6.
     *                                  Line 6 is even → GPIO_EVEN_IRQHandler.
     *   risingEdge  = false          → Do NOT trigger on rising edge
     *   fallingEdge = true           → DO trigger on falling edge (INT goes LOW)
     *   enable      = true           → Enable interrupt immediately
     *
     * MAX30102 INT is active-LOW open-drain:
     *   Rising edge  = interrupt cleared (not useful)
     *   Falling edge = new sample ready (this is what we want)
     */
    GPIO_ExtIntConfig(MAX30102_INT_PORT,
                      MAX30102_INT_PIN,
                      MAX30102_INT_LINE,
                      false,   /* no rising edge  */
                      true,    /* YES falling edge */
                      true);   /* enable now       */

    /*
     * The NVIC enable is handled INSIDE gpiointerrupt.c by GPIOINT_Init().
     * DO NOT call NVIC_EnableIRQ(GPIO_EVEN_IRQn) yourself — the SDK
     * dispatcher already did it. Calling it again is harmless but redundant.
     * Removed to keep the code clean and avoid confusion.
     */

    printf("[PPG] PC06 interrupt armed. Falling edge → PPG_RDY @ 100Hz\r\n");
    printf("[PPG] Init complete. Waiting for samples...\r\n");
}

/*******************************************************************************
 * app_process_action — interrupt-driven PPG sample collection
 ******************************************************************************/
void app_process_action(void)
{
    uint8_t fifo_data[6];

    /* Return immediately if no interrupt has fired */
    if (!ppg_data_ready) {
        return;
    }

    /*
     * Clear the flag atomically.
     * CORE_ENTER_ATOMIC disables interrupts (saves PRIMASK, sets PRIMASK=1).
     * CORE_EXIT_ATOMIC restores PRIMASK.
     * This prevents a race where a new interrupt fires between our read
     * of ppg_data_ready and our write of false.
     */
    CORE_DECLARE_IRQ_STATE;
    CORE_ENTER_ATOMIC();
    ppg_data_ready = false;
    CORE_EXIT_ATOMIC();

    read_attempts++;

    /*
     * Step 1: Read and clear MAX30102 interrupt status.
     *
     * MANDATORY: Reading INT_STATUS1 clears the interrupt flag inside the
     * MAX30102 and releases the INT pin back HIGH (idle state).
     * If you skip this, INT stays LOW permanently and your GPIO fires
     * continuously in a tight interrupt storm, starving the main loop.
     *
     * INT_STATUS1 bit meanings:
     *   Bit 7 = A_FULL   → FIFO almost full event
     *   Bit 6 = PPG_RDY  → New sample ready (this is what fired us)
     *   Bit 5 = ALC_OVF  → Ambient light cancellation overflow
     *   Bit 0 = PWR_RDY  → Power-on reset complete
     */
    max30102_read_reg(MAX30102_INT_STATUS1, (uint8_t *)&int_status1);
    max30102_read_reg(MAX30102_INT_STATUS2, (uint8_t *)&int_status2);

    /* Step 2: Read FIFO pointers and overflow counter */
    bool ok1 = max30102_read_reg(MAX30102_FIFO_WR_PTR,
                                  (uint8_t *)&fifo_wr_ptr);
    bool ok2 = max30102_read_reg(MAX30102_FIFO_RD_PTR,
                                  (uint8_t *)&fifo_rd_ptr);
    bool ok3 = max30102_read_reg(MAX30102_OVF_COUNTER,
                                  (uint8_t *)&fifo_ovf);

    /* Step 3: Read one sample from FIFO (6 bytes = RED + IR) */
    bool ok4 = max30102_read_fifo_one(fifo_data);

    if (ok1 && ok2 && ok3 && ok4) {
        read_success++;
        fifo_poll_count++;
        max30102_found = true;

        /* Overflow check — log any lost samples */
        if (fifo_ovf != 0u) {
            fifo_overflow_total += fifo_ovf;
            printf("[PPG] FIFO OVERFLOW: %u samples lost (total=%lu)\r\n",
                   (unsigned int)fifo_ovf,
                   (unsigned long)fifo_overflow_total);
        }

        /*
         * FIFO depth check: (WR_PTR - RD_PTR) mod 32 = samples pending.
         * Should be 0 or 1 at PPG_RDY rate. If consistently > 3, your
         * I2C transaction is taking too long and you need burst reads.
         */
        uint8_t fifo_depth = (uint8_t)((fifo_wr_ptr - fifo_rd_ptr) & 0x1Fu);
        if (fifo_depth > 3u) {
            printf("[PPG] WARN: FIFO depth=%u — consider burst read\r\n",
                   (unsigned int)fifo_depth);
        }

        /* Unpack 3-byte big-endian RED sample */
        red_sample = ((uint32_t)fifo_data[0] << 16u)
                   | ((uint32_t)fifo_data[1] <<  8u)
                   |  (uint32_t)fifo_data[2];

        /* Unpack 3-byte big-endian IR sample */
        ir_sample  = ((uint32_t)fifo_data[3] << 16u)
                   | ((uint32_t)fifo_data[4] <<  8u)
                   |  (uint32_t)fifo_data[5];

        /* Mask to 18-bit ADC resolution (MAX30102 datasheet §3.5) */
        red_sample &= 0x0003FFFFu;
        ir_sample  &= 0x0003FFFFu;

        sample_reads++;

        /* Store into circular buffers */
        ppg_red_buffer[ppg_index] = red_sample;
        ppg_ir_buffer[ppg_index]  = ir_sample;

        ppg_index++;
        if (ppg_index >= PPG_BUFFER_SIZE) {
            ppg_index = 0u;
        }

        ppg_sample_count++;

        /* Print every 100 samples (every 1 second at 100Hz) */
        if ((ppg_sample_count % 100u) == 0u) {
            printf("[PPG] cnt=%lu int=%lu RED=%lu IR=%lu\r\n",
                   (unsigned long)ppg_sample_count,
                   (unsigned long)interrupt_count,
                   (unsigned long)red_sample,
                   (unsigned long)ir_sample);
        }
    } else {
        read_failures++;
        max30102_found = false;
        printf("[PPG] I2C FAIL ok1=%d ok2=%d ok3=%d ok4=%d\r\n",
               ok1, ok2, ok3, ok4);
    }
}