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
#include "sl_iostream.h"

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

#define MAX30102_PART_ID_REG       0xFF

#define MAX30102_INT_ENABLE1_PPG_RDY    0x40u
#define MAX30102_INT_ENABLE1_A_FULL     0x80u

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
static volatile uint32_t fifo_overflow_total = 0u;

static volatile uint8_t  fifo_wr_ptr      = 0u;
static volatile uint8_t  fifo_rd_ptr      = 0u;
static volatile uint8_t  fifo_ovf         = 0u;
static volatile uint32_t red_sample       = 0u;
static volatile uint32_t ir_sample        = 0u;
static volatile uint8_t  int_status1      = 0u;
static volatile uint8_t  int_status2      = 0u;

static volatile bool     max30102_found   = false;

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

    bool ok = true;

    /* ── Step 1: Configure MAX30102 sensor registers ─────────────────── */

    ok &= max30102_write_reg(MAX30102_FIFO_WR_PTR,  0x00u);
    ok &= max30102_write_reg(MAX30102_OVF_COUNTER,  0x00u);
    ok &= max30102_write_reg(MAX30102_FIFO_RD_PTR,  0x00u);

    ok &= max30102_write_reg(MAX30102_FIFO_CONFIG_REG, 0x0Fu);

    ok &= max30102_write_reg(MAX30102_INT_ENABLE1, MAX30102_INT_ENABLE1_PPG_RDY);
    ok &= max30102_write_reg(MAX30102_INT_ENABLE2, 0x00u);

    ok &= max30102_write_reg(MAX30102_MODE_CONFIG, 0x03u);

    ok &= max30102_write_reg(MAX30102_SPO2_CONFIG, 0x27u);

    ok &= max30102_write_reg(MAX30102_LED1_PA,         0x24u);
    ok &= max30102_write_reg(MAX30102_LED2_PA,         0x24u);
    ok &= max30102_write_reg(MAX30102_MULTI_LED_CTRL1, 0x21u);
    ok &= max30102_write_reg(MAX30102_MULTI_LED_CTRL2, 0x00u);

    if (!ok) {
        write_failures++;
        printf("[PPG] SENSOR CONFIG FAILED\r\n");
        return;
    }

    printf("[PPG] Sensor config OK\r\n");

    /* Clear pending interrupt status */
    max30102_read_reg(MAX30102_INT_STATUS1, (uint8_t *)&int_status1);
    max30102_read_reg(MAX30102_INT_STATUS2, (uint8_t *)&int_status2);
    printf("[PPG] INT_STATUS1=0x%02X INT_STATUS2=0x%02X (cleared)\r\n",
           int_status1, int_status2);

    /* ── Step 2: Configure PC06 as interrupt input ───────────────────── */

    GPIO_PinModeSet(MAX30102_INT_PORT,
                    MAX30102_INT_PIN,
                    gpioModeInputPull,
                    1u);              /* 1 = pull-UP (idle HIGH) */

    /* ── Step 3: Register GPIO callback ──────────────────────────────── */
    /* NOTE: GPIOINT_Init() is called once by app.c before sensor inits */

    GPIOINT_CallbackRegister(MAX30102_INT_PIN, max30102_gpio_callback);

    /* ── Step 4: Configure the external interrupt for PC06 ───────────── */

    GPIO_ExtIntConfig(MAX30102_INT_PORT,
                      MAX30102_INT_PIN,
                      MAX30102_INT_LINE,
                      false,   /* no rising edge  */
                      true,    /* YES falling edge */
                      true);   /* enable now       */

    max30102_found = true;

    printf("[PPG] PC06 interrupt armed. Falling edge -> PPG_RDY @ 100Hz\r\n");
    printf("[PPG] Init complete. Waiting for samples...\r\n");
}

/*******************************************************************************
 * tarang_ppg_process — interrupt-driven PPG sample collection
 ******************************************************************************/
void tarang_ppg_process(void)
{
    uint8_t fifo_data[6];

    if (!ppg_data_ready) {
        return;
    }

    CORE_DECLARE_IRQ_STATE;
    CORE_ENTER_ATOMIC();
    ppg_data_ready = false;
    CORE_EXIT_ATOMIC();

    read_attempts++;

    /* Read and clear MAX30102 interrupt status */
    max30102_read_reg(MAX30102_INT_STATUS1, (uint8_t *)&int_status1);
    max30102_read_reg(MAX30102_INT_STATUS2, (uint8_t *)&int_status2);

    /* Read FIFO pointers and overflow counter */
    bool ok1 = max30102_read_reg(MAX30102_FIFO_WR_PTR,
                                  (uint8_t *)&fifo_wr_ptr);
    bool ok2 = max30102_read_reg(MAX30102_FIFO_RD_PTR,
                                  (uint8_t *)&fifo_rd_ptr);
    bool ok3 = max30102_read_reg(MAX30102_OVF_COUNTER,
                                  (uint8_t *)&fifo_ovf);

    /* Read one sample from FIFO (6 bytes = RED + IR) */
    bool ok4 = max30102_read_fifo_one(fifo_data);

    if (ok1 && ok2 && ok3 && ok4) {
        read_success++;
        fifo_poll_count++;
        max30102_found = true;

        if (fifo_ovf != 0u) {
            fifo_overflow_total += fifo_ovf;
            printf("[PPG] FIFO OVERFLOW: %u samples lost (total=%lu)\r\n",
                   (unsigned int)fifo_ovf,
                   (unsigned long)fifo_overflow_total);
        }

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

        /* Mask to 18-bit ADC resolution */
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

bool tarang_ppg_is_found(void)
{
    return max30102_found;
}
