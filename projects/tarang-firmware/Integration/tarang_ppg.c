/***************************************************************************//**
 * @file tarang_ppg.c
 * @brief TARANG PPG acquisition module — implementation.
 *
 * Direct extraction from Separate Testing/PPG/ppg/app.c.
 * UNCHANGED sensor logic. Only renamed app_init→tarang_ppg_init,
 * app_process_action→tarang_ppg_process, removed GPIOINT_Init()
 * (called once by orchestrator).
 *
 * MAX30102 over I2C (sl_i2cspm_mikroe), interrupt-driven via PC06 GPIO.
 * PPG_RDY interrupt fires at 100Hz, one sample read per interrupt.
 *
 * Target : EFR32MG26B510F3200IM48 (Series 2, Cortex-M33)
 ******************************************************************************/

#include "tarang_ppg.h"

#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>

#include "sl_i2cspm.h"
#include "sl_i2cspm_instances.h"

#include "em_gpio.h"
#include "em_cmu.h"
#include "em_core.h"
#include "gpiointerrupt.h"

/*******************************************************************************
 * MAX30102 Register Map
 ******************************************************************************/
#define MAX30102_ADDR              0x57

#define MAX30102_INT_STATUS1       0x00
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

#define MAX30102_MODE_SPO2         0x03u
#define MAX30102_MODE_RESET        0x40u

#define MAX30102_INT_ENABLE1_PPG_RDY    0x40u
#define MAX30102_INT_ENABLE1_A_FULL     0x80u

#define MAX30102_INT_STATUS1_PPG_RDY    0x40u

#define MAX30102_MAX_DRAIN_PER_SERVICE  8u
#define MAX30102_RECOVERY_THRESHOLD     4u
#define MAX30102_MAX_RECOVERY_ATTEMPTS  5u   /* stop trying after this many */

/*******************************************************************************
 * Hardware Pin Definition — MAX30102 INT connected to PC06
 ******************************************************************************/
#define MAX30102_INT_PORT    gpioPortC
#define MAX30102_INT_PIN     6u
#define MAX30102_INT_LINE    6u

/*******************************************************************************
 * Static variables (were globals in the test project)
 ******************************************************************************/
static uint32_t ppg_red_buffer[PPG_BUFFER_SIZE];
static uint32_t ppg_ir_buffer[PPG_BUFFER_SIZE];

static volatile uint32_t ppg_index        = 0u;
static volatile uint32_t ppg_sample_count = 0u;

static volatile bool     ppg_data_ready   = false;
static volatile uint32_t interrupt_count  = 0u;

/* Diagnostics */
static volatile uint32_t read_attempts    = 0u;
static volatile uint32_t read_success     = 0u;
static volatile uint32_t read_failures    = 0u;
static volatile uint32_t write_failures   = 0u;
static volatile uint32_t fifo_poll_count  = 0u;
static volatile uint32_t sample_reads     = 0u;

static volatile uint32_t red_sample       = 0u;
static volatile uint32_t ir_sample        = 0u;
static volatile uint8_t  int_status1      = 0u;
static volatile uint8_t  int_status2      = 0u;

static volatile bool     max30102_found   = false;
static volatile uint32_t consecutive_i2c_failures = 0u;
static volatile uint32_t recovery_attempts = 0u;
static volatile bool     ppg_disabled      = false;  /* set true after max recovery attempts */

static volatile I2C_TransferReturn_TypeDef last_ppg_i2c_ret = i2cTransferDone;

static bool max30102_read_reg(uint8_t reg, uint8_t *value);
static bool max30102_write_reg(uint8_t reg, uint8_t value);
static bool max30102_read_fifo_one(uint8_t *data);

/* Simple busy-wait delay */
static void ppg_delay_ms(uint32_t ms)
{
    for (volatile uint32_t i = 0; i < ms * 4000u; i++) { }
}

/* 9-pulse I2C bus clear procedure to release any stuck I2C slave holding SDA low */
static void i2c_bus_clear(void)
{
    printf("[PPG] I2C bus clear: checking SDA/SCL state...\r\n");
    
    CMU_ClockEnable(cmuClock_GPIO, true);

    // Read initial state
    uint8_t scl_state = GPIO_PinInGet(gpioPortC, 5);
    uint8_t sda_state = GPIO_PinInGet(gpioPortC, 7);
    printf("[PPG] Before clear: SCL=%d SDA=%d\r\n", scl_state, sda_state);

    // PC05 = SCL, PC07 = SDA
    GPIO_PinModeSet(gpioPortC, 5, gpioModeWiredAndPullUp, 1);
    GPIO_PinModeSet(gpioPortC, 7, gpioModeWiredAndPullUp, 1);

    for (int i = 0; i < 9; i++) {
        GPIO_PinOutClear(gpioPortC, 5);
        ppg_delay_ms(1);
        GPIO_PinOutSet(gpioPortC, 5);
        ppg_delay_ms(1);
    }

    // Generate STOP
    GPIO_PinOutClear(gpioPortC, 7);
    ppg_delay_ms(1);
    GPIO_PinOutSet(gpioPortC, 5);
    ppg_delay_ms(1);
    GPIO_PinOutSet(gpioPortC, 7);
    ppg_delay_ms(1);

    // Check final state
    scl_state = GPIO_PinInGet(gpioPortC, 5);
    sda_state = GPIO_PinInGet(gpioPortC, 7);
    printf("[PPG] After clear: SCL=%d SDA=%d\r\n", scl_state, sda_state);

    // Re-init I2CSPM peripheral
    sl_i2cspm_init_instances();
    ppg_delay_ms(10);
    printf("[PPG] I2CSPM re-initialized\r\n");
}

static bool max30102_configure_sensor(void)
{
    bool ok = true;

    // Reset register first
    ok &= max30102_write_reg(MAX30102_MODE_CONFIG, MAX30102_MODE_RESET);
    ppg_delay_ms(50);

    // Clear FIFO pointers
    ok &= max30102_write_reg(MAX30102_FIFO_WR_PTR,  0x00u);
    ok &= max30102_write_reg(MAX30102_OVF_COUNTER,  0x00u);
    ok &= max30102_write_reg(MAX30102_FIFO_RD_PTR,  0x00u);

    /* 1. FIFO_CONFIG (0x08): 0x1F -> sample_avg=1, FIFO_ROLLOVER_EN=1 (bit 4), A_FULL=15
     * CRITICAL: Bit 4 (FIFO_ROLLOVER_EN) MUST be 1, otherwise when FIFO fills
     * to 32 samples, the sensor stops taking data and interrupts permanently halt! */
    ok &= max30102_write_reg(MAX30102_FIFO_CONFIG_REG, 0x1Fu);

    /* 2. INT_ENABLE1 (0x02): 0xC0 -> Enable both A_FULL_EN (bit 7) and PPG_RDY_EN (bit 6) */
    ok &= max30102_write_reg(MAX30102_INT_ENABLE1, 0xC0u);
    ok &= max30102_write_reg(MAX30102_INT_ENABLE2, 0x00u);

    /* 3. MODE_CONFIG (0x09): 0x03 -> SpO2 mode (Red + IR sampling) */
    ok &= max30102_write_reg(MAX30102_MODE_CONFIG, MAX30102_MODE_SPO2);

    /* 4. SPO2_CONFIG (0x0A): 0x27 -> ADC range 4096nA, 100 SPS, 411us pulse width */
    ok &= max30102_write_reg(MAX30102_SPO2_CONFIG, 0x27u);

    /* 5. LED Current (0x0C, 0x0D): 0x24 (~7.2mA) for both RED and IR LEDs */
    ok &= max30102_write_reg(MAX30102_LED1_PA, 0x24u);
    ok &= max30102_write_reg(MAX30102_LED2_PA, 0x24u);

    return ok;
}

static void max30102_recover(void)
{
    recovery_attempts++;

    /* ── SAFETY CAP: If sensor is physically gone, stop trying ────────── */
    if (recovery_attempts >= MAX30102_MAX_RECOVERY_ATTEMPTS) {
        ppg_disabled = true;
        max30102_found = false;
        consecutive_i2c_failures = 0u;
        printf("[PPG] *** PERMANENTLY DISABLED after %lu failed recoveries ***\r\n",
               (unsigned long)recovery_attempts);
        printf("[PPG] *** ECG + IMU + Pipeline continue normally ***\r\n");
        return;
    }

    /*
     * NOTE: Do NOT call sl_i2cspm_init_instances() here at runtime.
     * It reinitializes the entire I2C peripheral, which would corrupt
     * any ongoing IMU transaction on the shared bus.
     * Instead, just try to reconfigure the MAX30102 sensor.
     */

    if (max30102_configure_sensor()) {
        consecutive_i2c_failures = 0u;
        max30102_found = true;
        ppg_data_ready = false;
        max30102_read_reg(MAX30102_INT_STATUS1, (uint8_t *)&int_status1);
        max30102_read_reg(MAX30102_INT_STATUS2, (uint8_t *)&int_status2);

        if (GPIO_PinInGet(MAX30102_INT_PORT, MAX30102_INT_PIN) == 0u) {
            ppg_data_ready = true;
        }

        printf("[PPG] RECOVERED after %lu failures (attempt=%lu)\r\n",
               (unsigned long)MAX30102_RECOVERY_THRESHOLD,
               (unsigned long)recovery_attempts);
    } else {
        max30102_found = false;
        printf("[PPG] RECOVERY FAILED ret=%d attempt=%lu/%lu\r\n",
               (int)last_ppg_i2c_ret,
               (unsigned long)recovery_attempts,
               (unsigned long)MAX30102_MAX_RECOVERY_ATTEMPTS);
    }
}

/*******************************************************************************
 * Private: I2C read/write helpers (proven working from test project)
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
    last_ppg_i2c_ret = ret;
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
    last_ppg_i2c_ret = ret;
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
    last_ppg_i2c_ret = ret;
    return (ret == i2cTransferDone);
}

/*******************************************************************************
 * GPIO Interrupt Callback — registered for pin 6 (PC06)
 ******************************************************************************/
static void max30102_gpio_callback(uint8_t pin)
{
    (void)pin;
    interrupt_count++;
    ppg_data_ready = true;
}

/*******************************************************************************
 * tarang_ppg_init
 ******************************************************************************/
void tarang_ppg_init(void)
{
    printf("\r\n");
    printf("====================================\r\n");
    printf("MAX30102 INTERRUPT-DRIVEN TARANG PPG\r\n");
    printf("====================================\r\n");

    /* ── Step 0: Clear I2C bus (in case slave was holding SDA low) ────── */
    i2c_bus_clear();

    /* ── Step 1: Configure MAX30102 sensor registers with retry ──────── */
    bool config_ok = false;
    for (int attempt = 1; attempt <= 3; attempt++) {
        printf("[PPG] Config attempt %d/3...\r\n", attempt);
        
        if (max30102_configure_sensor()) {
            config_ok = true;
            printf("[PPG] Sensor config OK\r\n");
            break;
        }
        
        write_failures++;
        printf("[PPG] Config failed (i2c_ret=%d)\r\n", (int)last_ppg_i2c_ret);
        
        if (attempt < 3) {
            printf("[PPG] Retrying after delay...\r\n");
            ppg_delay_ms(100);
            i2c_bus_clear();  // Try clearing bus again
        }
    }

    if (!config_ok) {
        printf("[PPG] SENSOR CONFIG FAILED after 3 attempts\r\n");
        return;
    }

    uint8_t rb_int1 = 0, rb_mode = 0;
    max30102_read_reg(MAX30102_INT_ENABLE1, &rb_int1);
    max30102_read_reg(MAX30102_MODE_CONFIG, &rb_mode);
    printf("[PPG] readback: INT_ENABLE1=0x%02X MODE_CONFIG=0x%02X ok=%d\r\n",
           rb_int1, rb_mode, (int)config_ok);

    /* Clear pending interrupt status after sensor config, before GPIO service. */
    max30102_read_reg(MAX30102_INT_STATUS1, (uint8_t *)&int_status1);
    max30102_read_reg(MAX30102_INT_STATUS2, (uint8_t *)&int_status2);
    printf("[PPG] INT_STATUS1=0x%02X INT_STATUS2=0x%02X (cleared)\r\n",
           int_status1, int_status2);

    /* ── Step 2: Configure PC06 as interrupt input ───────────────────── */

    CMU_ClockEnable(cmuClock_GPIO, true);

    GPIO_PinModeSet(MAX30102_INT_PORT,
                    MAX30102_INT_PIN,
                    gpioModeInputPull,
                    1u);              /* 1 = pull-UP (idle HIGH) */

    /* ── Step 3: Register GPIO callback & arm external interrupt ─────── */
    GPIOINT_CallbackRegister(MAX30102_INT_PIN, max30102_gpio_callback);

    GPIO_ExtIntConfig(MAX30102_INT_PORT,
                      MAX30102_INT_PIN,
                      MAX30102_INT_LINE,
                      false,   /* no rising edge  */
                      true,    /* YES falling edge */
                      true);   /* enable now       */

    /* Prime ppg_data_ready if INT pin is already held low by MAX30102 */
    if (GPIO_PinInGet(MAX30102_INT_PORT, MAX30102_INT_PIN) == 0u) {
        ppg_data_ready = true;
    }

    max30102_found = true;

    printf("[PPG] PC06 interrupt armed. Falling edge -> PPG_RDY @ 100Hz\r\n");
    printf("[PPG] Init complete. Waiting for samples...\r\n");
}

/*******************************************************************************
 * tarang_ppg_process — interrupt-driven PPG sample collection
 ******************************************************************************/
void tarang_ppg_process(void)
{
    /* If sensor was permanently disabled after too many failures, skip entirely */
    if (ppg_disabled) {
        return;
    }

    uint8_t fifo_data[6];
    bool service_sensor = false;
    uint8_t drained = 0u;
    bool line_low = false;
    bool status_has_data = false;

    CORE_DECLARE_IRQ_STATE;
    CORE_ENTER_ATOMIC();
    if (ppg_data_ready) {
        ppg_data_ready = false;
        service_sensor = true;
    }
    CORE_EXIT_ATOMIC();

    if (!service_sensor) {
        return;
    }

    read_attempts++;

    /* Read and clear MAX30102 interrupt status */
    bool ok1 = max30102_read_reg(MAX30102_INT_STATUS1, (uint8_t *)&int_status1);
    bool ok2 = max30102_read_reg(MAX30102_INT_STATUS2, (uint8_t *)&int_status2);

    if (!(ok1 && ok2)) {
        read_failures++;
        consecutive_i2c_failures++;
        printf("[PPG] I2C FAIL status1=%d status2=%d ret=%d fail=%lu\r\n",
               ok1, ok2, (int)last_ppg_i2c_ret,
               (unsigned long)consecutive_i2c_failures);

        if (consecutive_i2c_failures >= MAX30102_RECOVERY_THRESHOLD) {
            max30102_recover();
        }
        return;
    }

    consecutive_i2c_failures = 0u;
    max30102_found = true;
    fifo_poll_count++;
    status_has_data = ((int_status1 & MAX30102_INT_STATUS1_PPG_RDY) != 0u);
    line_low = (GPIO_PinInGet(MAX30102_INT_PORT, MAX30102_INT_PIN) == 0u);

    if (!(status_has_data || line_low)) {
        return;
    }

    /* FIX: Calculate available samples using WR/RD pointers instead of GPIO pin */
    uint8_t wr_ptr = 0, rd_ptr = 0;
    max30102_read_reg(MAX30102_FIFO_WR_PTR, &wr_ptr);
    max30102_read_reg(MAX30102_FIFO_RD_PTR, &rd_ptr);
    uint8_t available = (wr_ptr - rd_ptr) & 0x1F;
    if (available == 0 && status_has_data) {
        available = 1; /* Fallback: if interrupt fired, assume at least 1 */
    }

    while ((drained < MAX30102_MAX_DRAIN_PER_SERVICE) && (drained < available)) {
        bool ok4 = max30102_read_fifo_one(fifo_data);
        if (!ok4) {
            read_failures++;
            consecutive_i2c_failures++;
            printf("[PPG] I2C FAIL fifo=%d drained=%u ret=%d fail=%lu\r\n",
                   ok4,
                   (unsigned int)drained,
                   (int)last_ppg_i2c_ret,
                   (unsigned long)consecutive_i2c_failures);

            if (consecutive_i2c_failures >= MAX30102_RECOVERY_THRESHOLD) {
                max30102_recover();
            }
            return;
        }

        /* Unpack 3-byte big-endian RED sample */
        red_sample = ((uint32_t)fifo_data[0] << 16u)
                   | ((uint32_t)fifo_data[1] <<  8u)
                   |  (uint32_t)fifo_data[2];

        /* Unpack 3-byte big-endian IR sample */
        ir_sample  = ((uint32_t)fifo_data[3] << 16u)
                   | ((uint32_t)fifo_data[4] <<  8u)
                   |  (uint32_t)fifo_data[5];

        red_sample &= 0x0003FFFFu;
        ir_sample  &= 0x0003FFFFu;

        sample_reads++;
        read_success++;

        ppg_red_buffer[ppg_index] = red_sample;
        ppg_ir_buffer[ppg_index]  = ir_sample;

        ppg_index++;
        if (ppg_index >= PPG_BUFFER_SIZE) {
            ppg_index = 0u;
        }

        ppg_sample_count++;
        drained++;
        status_has_data = false;
    }

    consecutive_i2c_failures = 0u;

    /* Re-prime — if the pin is still LOW after our read, the sensor
     * already has another sample queued (or INT line was held low).
     * Edge-triggered IRQ won't fire again on its own since there's
     * no new falling edge. */
    if (GPIO_PinInGet(MAX30102_INT_PORT, MAX30102_INT_PIN) == 0u) {
        ppg_data_ready = true;
    }

    if ((drained > 1u) || ((ppg_sample_count != 0u) && ((ppg_sample_count % 100u) == 0u))) {
        printf("[PPG] cnt=%lu int=%lu RED=%lu IR=%lu drained=%u\r\n",
               (unsigned long)ppg_sample_count,
               (unsigned long)interrupt_count,
               (unsigned long)red_sample,
               (unsigned long)ir_sample,
               (unsigned int)drained);
    }
}

/*******************************************************************************
 * Public accessors
 ******************************************************************************/
uint32_t tarang_ppg_get_red(void)
{
    return red_sample;
}

uint32_t tarang_ppg_get_ir(void)
{
    return ir_sample;
}

uint32_t tarang_ppg_get_sample_count(void)
{
    return ppg_sample_count;
}

uint32_t tarang_ppg_get_interrupt_count(void)
{
    return interrupt_count;
}

bool tarang_ppg_is_found(void)
{
    return max30102_found;
}
