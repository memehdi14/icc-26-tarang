/***************************************************************************//**
 * @file tarang_ppg.c
 * @brief TARANG PPG acquisition module — implementation.
 *
 * Acquisition began from Separate Testing/PPG/ppg/app.c. Integration adds
 * rolling pulse/SpO2 estimation, signal-quality gates, and motion rejection.
 *
 * MAX30102 over I2C (sl_i2cspm_mikroe), interrupt-driven via PC06 GPIO.
 * Optimized with A_FULL FIFO batching: drains up to 32 samples per wake,
 * reducing CPU interrupts from 100 Hz to ~5.8 Hz.
 *
 * Target : EFR32MG26B510F3200IM48 (Series 2, Cortex-M33)
 ******************************************************************************/

#include "tarang_ppg.h"

#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <math.h>
#include <string.h>

#include "tarang_constants.h"
#include "tarang_time.h"
#include "tarang_validation_stream.h"

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
#define MAX30102_INT_STATUS1_A_FULL     0x80u

#define MAX30102_MAX_DRAIN_PER_SERVICE  32u
#define MAX30102_RECOVERY_THRESHOLD     4u

#define PPG_METRIC_WINDOW_SAMPLES       400u  /* 4 seconds at 100 Hz */
#define PPG_METRIC_UPDATE_SAMPLES       100u  /* Recompute once per second */
#define PPG_FINGER_IR_MIN               10000.0f
#define PPG_SENSOR_DC_MAX               250000.0f
#define PPG_MIN_AC_RATIO                0.0005f
#define PPG_MOTION_REJECT_MG            120u
#define PPG_MIN_PULSE_BPM               40u
#define PPG_MAX_PULSE_BPM               200u

/*******************************************************************************
 * Hardware Pin Definition — MAX30102 INT connected to PC06
 ******************************************************************************/
#define MAX30102_INT_PORT    gpioPortC
#define MAX30102_INT_PIN     6u
#define MAX30102_INT_LINE    6u

/*******************************************************************************
 * Static variables
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
static volatile uint16_t latest_motion_mg = 0u;

static tarang_ppg_metrics_t latest_metrics;
static float ppg_ir_ac_window[PPG_METRIC_WINDOW_SAMPLES];
static uint32_t last_metric_sample_count = 0u;

static volatile I2C_TransferReturn_TypeDef last_ppg_i2c_ret = i2cTransferDone;

#if TARANG_VALIDATION_STREAM_ACTIVE
#define TARANG_VALIDATION_PPG_BLOCK_SAMPLES 10u
#define TARANG_VALIDATION_PPG_SAMPLE_BYTES  6u

static uint8_t s_validation_ppg_payload[
    9u + TARANG_VALIDATION_PPG_BLOCK_SAMPLES
       * TARANG_VALIDATION_PPG_SAMPLE_BYTES];
static uint8_t s_validation_ppg_count = 0u;
static size_t s_validation_ppg_length = 0u;

static void ppg_emit_validation_sample(uint32_t sample_index,
                                       uint32_t timestamp_ms,
                                       uint32_t red,
                                       uint32_t ir)
{
    if (s_validation_ppg_count == 0u) {
        tarang_validation_put_u32(&s_validation_ppg_payload[0], sample_index);
        tarang_validation_put_u32(&s_validation_ppg_payload[4], timestamp_ms);
        s_validation_ppg_payload[8] = 0u;
        s_validation_ppg_length = 9u;
    }

    uint8_t *sample = &s_validation_ppg_payload[s_validation_ppg_length];
    tarang_validation_put_u24(&sample[0], red);
    tarang_validation_put_u24(&sample[3], ir);
    s_validation_ppg_length += TARANG_VALIDATION_PPG_SAMPLE_BYTES;
    s_validation_ppg_count++;
    s_validation_ppg_payload[8] = s_validation_ppg_count;

    if (s_validation_ppg_count >= TARANG_VALIDATION_PPG_BLOCK_SAMPLES) {
        tarang_validation_emit('P', s_validation_ppg_payload,
                               s_validation_ppg_length);
        s_validation_ppg_count = 0u;
        s_validation_ppg_length = 0u;
    }
}
#endif

static bool max30102_read_reg(uint8_t reg, uint8_t *value);
static bool max30102_write_reg(uint8_t reg, uint8_t value);
static bool max30102_read_fifo_one(uint8_t *data);
static void ppg_update_metrics(void);

static uint32_t ppg_window_value(const uint32_t *buffer, uint32_t logical_index)
{
    uint32_t start = (ppg_index + PPG_BUFFER_SIZE - PPG_METRIC_WINDOW_SAMPLES)
                     % PPG_BUFFER_SIZE;
    return buffer[(start + logical_index) % PPG_BUFFER_SIZE];
}

static void ppg_update_metrics(void)
{
    if (ppg_sample_count < PPG_METRIC_WINDOW_SAMPLES) {
        return;
    }
    if ((ppg_sample_count - last_metric_sample_count) < PPG_METRIC_UPDATE_SAMPLES) {
        return;
    }
    last_metric_sample_count = ppg_sample_count;

    double red_sum = 0.0;
    double ir_sum = 0.0;
    for (uint32_t i = 0; i < PPG_METRIC_WINDOW_SAMPLES; i++) {
        red_sum += (double)ppg_window_value(ppg_red_buffer, i);
        ir_sum += (double)ppg_window_value(ppg_ir_buffer, i);
    }

    float red_dc = (float)(red_sum / (double)PPG_METRIC_WINDOW_SAMPLES);
    float ir_dc = (float)(ir_sum / (double)PPG_METRIC_WINDOW_SAMPLES);
    double red_energy = 0.0;
    double ir_energy = 0.0;

    for (uint32_t i = 0; i < PPG_METRIC_WINDOW_SAMPLES; i++) {
        float red_ac = (float)ppg_window_value(ppg_red_buffer, i) - red_dc;
        float ir_ac = (float)ppg_window_value(ppg_ir_buffer, i) - ir_dc;
        ppg_ir_ac_window[i] = ir_ac;
        red_energy += (double)red_ac * red_ac;
        ir_energy += (double)ir_ac * ir_ac;
    }

    float red_rms = sqrtf((float)(red_energy / PPG_METRIC_WINDOW_SAMPLES));
    float ir_rms = sqrtf((float)(ir_energy / PPG_METRIC_WINDOW_SAMPLES));
    float ir_ac_ratio = ir_dc > 1.0f ? ir_rms / ir_dc : 0.0f;

    memset(&latest_metrics, 0, sizeof(latest_metrics));
    latest_metrics.window_end_sample = ppg_sample_count;
    latest_metrics.finger_present =
        ir_dc >= PPG_FINGER_IR_MIN && ir_dc < PPG_SENSOR_DC_MAX
        && red_dc > 1000.0f && red_dc < PPG_SENSOR_DC_MAX;
    latest_metrics.motion_rejected = latest_motion_mg > PPG_MOTION_REJECT_MG;

    float pi_x100 = ir_ac_ratio * 10000.0f;
    if (pi_x100 > 65535.0f) pi_x100 = 65535.0f;
    latest_metrics.perfusion_index_x100 = (uint16_t)pi_x100;

    uint32_t zero_crossings = 0u;
    uint32_t peaks = 0u;
    for (uint32_t i = 1; i < PPG_METRIC_WINDOW_SAMPLES; i++) {
        if ((ppg_ir_ac_window[i - 1] < 0.0f && ppg_ir_ac_window[i] >= 0.0f)
            || (ppg_ir_ac_window[i - 1] > 0.0f && ppg_ir_ac_window[i] <= 0.0f)) {
            zero_crossings++;
        }
        if (i > 1 && i < (PPG_METRIC_WINDOW_SAMPLES - 1)) {
            if (ppg_ir_ac_window[i] > ppg_ir_ac_window[i - 1]
                && ppg_ir_ac_window[i] > ppg_ir_ac_window[i + 1]
                && ppg_ir_ac_window[i] > (ir_rms * 0.5f)) {
                peaks++;
            }
        }
    }

    float estimated_bpm = ((float)peaks / 4.0f) * 60.0f;
    if (estimated_bpm < (float)PPG_MIN_PULSE_BPM || estimated_bpm > (float)PPG_MAX_PULSE_BPM) {
        estimated_bpm = 0.0f;
    }
    latest_metrics.pulse_rate_bpm = (uint16_t)estimated_bpm;

    float r_ratio = (red_dc > 1.0f && ir_rms > 0.001f)
                    ? (red_rms / red_dc) / (ir_rms / ir_dc)
                    : 0.0f;
    latest_metrics.r_curve_x1000 = (uint32_t)(r_ratio * 1000.0f);

    float spo2 = 0.0f;
    if (r_ratio > 0.4f && r_ratio < 2.0f) {
        spo2 = 110.0f - (25.0f * r_ratio);
        if (spo2 > 100.0f) spo2 = 100.0f;
        if (spo2 < 70.0f) spo2 = 70.0f;
    }
    latest_metrics.spo2_pct = (uint8_t)spo2;

    float sqi = 0.0f;
    if (latest_metrics.finger_present && !latest_metrics.motion_rejected) {
        if (ir_ac_ratio >= PPG_MIN_AC_RATIO && peaks >= 3u && peaks <= 14u) {
            sqi = 220.0f;
        } else if (ir_ac_ratio >= PPG_MIN_AC_RATIO) {
            sqi = 140.0f;
        }
    }
    latest_metrics.signal_quality = (uint8_t)sqi;

    latest_metrics.valid = !latest_metrics.motion_rejected
                           && latest_metrics.finger_present
                           && latest_metrics.pulse_rate_bpm > 0u
                           && latest_metrics.spo2_pct >= 70u;

#if TARANG_DEBUG_VERBOSE
    printf("[PPG][METRIC] valid=%u finger=%u motion=%u SpO2=%u pulse=%u PIx100=%u SQI=%u R_x1000=%lu\r\n",
           latest_metrics.valid ? 1u : 0u,
           latest_metrics.finger_present ? 1u : 0u,
           latest_metrics.motion_rejected ? 1u : 0u,
           latest_metrics.spo2_pct,
           latest_metrics.pulse_rate_bpm,
           latest_metrics.perfusion_index_x100,
           latest_metrics.signal_quality,
           (unsigned long)latest_metrics.r_curve_x1000);
#endif
}

/*******************************************************************************
 * Interrupt handler callback (PC06 falling edge)
 ******************************************************************************/
static void max30102_int_callback(uint8_t intNo, void *ctx)
{
    (void)intNo;
    (void)ctx;
    interrupt_count++;
    ppg_data_ready = true;
}

/*******************************************************************************
 * Private: delay helper
 ******************************************************************************/
static void ppg_delay_ms(uint32_t ms)
{
    for (volatile uint32_t i = 0; i < ms * 4000u; i++) { }
}

/*******************************************************************************
 * Private: I2C bus recovery
 ******************************************************************************/
static void max30102_clear_bus(void)
{
    uint8_t scl_state = GPIO_PinInGet(gpioPortC, 5);
    uint8_t sda_state = GPIO_PinInGet(gpioPortC, 7);
    printf("[PPG] Before clear: SCL=%d SDA=%d\r\n", scl_state, sda_state);

    GPIO_PinModeSet(gpioPortC, 5, gpioModeWiredAndPullUp, 1);
    GPIO_PinModeSet(gpioPortC, 7, gpioModeWiredAndPullUp, 1);

    for (int i = 0; i < 9; i++) {
        GPIO_PinOutClear(gpioPortC, 5);
        ppg_delay_ms(1);
        GPIO_PinOutSet(gpioPortC, 5);
        ppg_delay_ms(1);
    }

    GPIO_PinOutClear(gpioPortC, 7);
    ppg_delay_ms(1);
    GPIO_PinOutSet(gpioPortC, 5);
    ppg_delay_ms(1);
    GPIO_PinOutSet(gpioPortC, 7);
    ppg_delay_ms(1);

    scl_state = GPIO_PinInGet(gpioPortC, 5);
    sda_state = GPIO_PinInGet(gpioPortC, 7);
    printf("[PPG] After clear: SCL=%d SDA=%d\r\n", scl_state, sda_state);
    ppg_delay_ms(10);
    printf("[PPG] I2C bus clear done (no peripheral re-init)\r\n");
}

static bool max30102_configure_sensor(void)
{
    bool ok = true;

    ok &= max30102_write_reg(MAX30102_MODE_CONFIG, MAX30102_MODE_RESET);
    ppg_delay_ms(50);

    ok &= max30102_write_reg(MAX30102_FIFO_WR_PTR,  0x00u);
    ok &= max30102_write_reg(MAX30102_OVF_COUNTER,  0x00u);
    ok &= max30102_write_reg(MAX30102_FIFO_RD_PTR,  0x00u);

    /* 1. FIFO_CONFIG (0x08): 0x1F -> sample_avg=1, FIFO_ROLLOVER_EN=1 (bit 4), A_FULL=15 */
    ok &= max30102_write_reg(MAX30102_FIFO_CONFIG_REG, 0x1Fu);

    /* 2. INT_ENABLE1 (0x02): 0x80 -> Enable ONLY A_FULL_EN (bit 7) for 17-sample FIFO batching */
    ok &= max30102_write_reg(MAX30102_INT_ENABLE1, 0x80u);
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
        printf("[PPG] RECOVERY FAILED ret=%d attempt=%lu\r\n",
               (int)last_ppg_i2c_ret,
               (unsigned long)recovery_attempts);
    }
}

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
    seq.buf[1].len  = 6u; /* 3 bytes RED + 3 bytes IR */

    ret = I2CSPM_Transfer(sl_i2cspm_mikroe, &seq);
    last_ppg_i2c_ret = ret;
    return (ret == i2cTransferDone);
}

/*******************************************************************************
 * Public: initialization
 ******************************************************************************/
void tarang_ppg_init(void)
{
    uint8_t part_id = 0u;
    uint8_t rev_id  = 0u;

    printf("[PPG] Initializing MAX30102 on sl_i2cspm_mikroe (I2C1)...\r\n");

    GPIO_PinModeSet(MAX30102_INT_PORT, MAX30102_INT_PIN, gpioModeInputPullFilter, 1);

    max30102_clear_bus();

    bool id_ok = max30102_read_reg(0xFFu, &part_id);
    (void)max30102_read_reg(0xFEu, &rev_id);

    if (id_ok && part_id == 0x15u) {
        printf("[PPG] MAX30102 detected (PartID=0x%02X RevID=0x%02X)\r\n", part_id, rev_id);
        max30102_found = true;
    } else {
        printf("[PPG] WARNING: PartID read returned 0x%02X (expected 0x15), ret=%d\r\n",
               part_id, (int)last_ppg_i2c_ret);
        max30102_found = id_ok;
    }

    if (!max30102_configure_sensor()) {
        printf("[PPG] ERROR: Sensor configuration failed\r\n");
        max30102_found = false;
        return;
    }

    ppg_data_ready = false;
    max30102_read_reg(MAX30102_INT_STATUS1, (uint8_t *)&int_status1);
    max30102_read_reg(MAX30102_INT_STATUS2, (uint8_t *)&int_status2);

    GPIOINT_Init();
    GPIOINT_CallbackRegister(MAX30102_INT_LINE, max30102_int_callback);
    GPIO_ExtIntConfig(MAX30102_INT_PORT, MAX30102_INT_PIN, MAX30102_INT_LINE,
                      false, true, true);

    if (GPIO_PinInGet(MAX30102_INT_PORT, MAX30102_INT_PIN) == 0u) {
        ppg_data_ready = true;
    }

    printf("[PPG] MAX30102 initialized successfully with A_FULL FIFO batching (drain=%u)\r\n",
           (unsigned)MAX30102_MAX_DRAIN_PER_SERVICE);
}

/*******************************************************************************
 * Public: process loop
 ******************************************************************************/
void tarang_ppg_process(void)
{
    uint8_t fifo_data[6];
    uint32_t drained = 0u;
    bool status_has_data = false;
    bool line_low = false;
    bool service_sensor = false;

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
    status_has_data = ((int_status1 & (MAX30102_INT_STATUS1_A_FULL | MAX30102_INT_STATUS1_PPG_RDY)) != 0u);
    line_low = (GPIO_PinInGet(MAX30102_INT_PORT, MAX30102_INT_PIN) == 0u);

    if (!(status_has_data || line_low)) {
        return;
    }

    /* FIFO batch calculation using write and read pointers */
    uint8_t wr_ptr = 0, rd_ptr = 0;
    max30102_read_reg(MAX30102_FIFO_WR_PTR, &wr_ptr);
    max30102_read_reg(MAX30102_FIFO_RD_PTR, &rd_ptr);
    uint32_t available = (wr_ptr >= rd_ptr) ? (uint32_t)(wr_ptr - rd_ptr) : (uint32_t)(wr_ptr + 32u - rd_ptr);
    if (available == 0 && (status_has_data || line_low)) {
        available = 32u; /* FIFO completely full */
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

#if TARANG_VALIDATION_STREAM_ACTIVE
        ppg_emit_validation_sample(ppg_sample_count, tarang_now_ms(),
                                   red_sample, ir_sample);
#endif
    }

    ppg_update_metrics();

    consecutive_i2c_failures = 0u;

    if (GPIO_PinInGet(MAX30102_INT_PORT, MAX30102_INT_PIN) == 0u) {
        ppg_data_ready = true;
    }

#if TARANG_DEBUG_VERBOSE
    if ((drained > 1u) || ((ppg_sample_count != 0u) && ((ppg_sample_count % 100u) == 0u))) {
        printf("[PPG] cnt=%lu int=%lu RED=%lu IR=%lu drained=%u\r\n",
               (unsigned long)ppg_sample_count,
               (unsigned long)interrupt_count,
               (unsigned long)red_sample,
               (unsigned long)ir_sample,
               (unsigned int)drained);
    }
#endif
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

bool tarang_ppg_is_finger_present(void)
{
    return latest_metrics.finger_present;
}

uint32_t tarang_ppg_get_consecutive_failures(void)
{
    return consecutive_i2c_failures;
}

void tarang_ppg_set_motion_level_mg(uint16_t motion_mg)
{
    latest_motion_mg = motion_mg;
}

bool tarang_ppg_get_metrics(tarang_ppg_metrics_t *metrics)
{
    if (metrics == NULL) return false;
    *metrics = latest_metrics;
    return latest_metrics.valid;
}
