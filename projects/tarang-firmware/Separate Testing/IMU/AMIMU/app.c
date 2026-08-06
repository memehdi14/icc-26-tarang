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

/***************************************************************************//**
 * DIAGNOSTIC REVISION NOTE
 *
 * This revision does NOT assume a root cause. The previous two-transaction
 * structure (separate INT_STATUS read, then separate 14-byte burst read) is
 * UNCHANGED and remains the default. What changed:
 *
 *   1. I2CSPM_Transfer() return codes are now captured and classified per
 *      transaction (status read vs. burst read) instead of being collapsed
 *      into a single pass/fail bool. This tells you whether failures are
 *      i2cTransferNack, i2cTransferBusErr, i2cTransferArbLost,
 *      i2cTransferUsageFault, or something else -- which narrows down
 *      whether this is a bus electrical issue, a slave NACK, an arbitration
 *      problem, or a driver usage problem.
 *   2. An OPTIONAL combined 15-byte transaction (INT_STATUS + burst in one
 *      I2CSPM_Transfer call) is included but fully compiled out by default
 *      via a single #define. It is not assumed to be the fix -- it is
 *      there so you can A/B test with a one-line change once the
 *      diagnostics above tell you where the failure actually is.
 *   3. Nothing was added that depends on generated/autogen symbols,
 *      component-generated init structs, or custom bus recovery. No SDK
 *      component configuration, linker script, or startup file changes
 *      are required. The GPIOINT / DATA_RDY interrupt architecture is
 *      untouched.
 ******************************************************************************/

#include "app.h"

#include "sl_i2cspm.h"
#include "sl_i2cspm_instances.h"

#include <stdint.h>
#include <stdbool.h>

#include "em_gpio.h"
#include "em_cmu.h"
#include "em_core.h"
#include "gpiointerrupt.h"

/* ---------------------------------------------------------------------
 * Optional combined-transaction experiment (OFF by default).
 *
 * Set to 1 only after the diagnostics below have been inspected. This
 * does not change GPIO/interrupt architecture, only which I2CSPM_Transfer
 * call(s) are issued in app_process_action(). Fully compiled out when 0,
 * so leaving it at 0 introduces zero behavioral or build risk relative
 * to the currently-working project.
 * --------------------------------------------------------------------- */
#define MPU6050_USE_COMBINED_BURST 0

#define MPU6050_ADDR     0x68
#define MPU6050_WHO_AM_I 0x75
#define MPU6050_ACCEL_XOUT_H   0x3B

#define MPU6050_PWR_MGMT_1      0x6B

#define MPU6050_ACCEL_CONFIG 0x1C
#define MPU6050_GYRO_CONFIG 0x1B

#define MPU6050_CONFIG      0x1A
#define MPU6050_SMPLRT_DIV  0x19

#define MPU6050_INT_ENABLE  0x38
#define MPU6050_INT_STATUS  0x3A
#define MPU6050_INT_PIN_CFG 0x37

#define MPU6050_INT_PORT gpioPortC
#define MPU6050_INT_PIN  0u
#define MPU6050_INT_LINE 0u

#if MPU6050_USE_COMBINED_BURST
/* INT_STATUS (0x3A) immediately precedes ACCEL_XOUT_H (0x3B) in the
 * MPU6050 register map, so a 15-byte read starting at 0x3A returns
 * status + all sensor data in one transaction. Only used if the macro
 * above is enabled. */
#define MPU6050_COMBINED_LEN 15u
#endif

volatile uint8_t mpu_whoami = 0;
volatile bool mpu_found;

volatile int16_t accel_x = 0;
volatile int16_t accel_y = 0;
volatile int16_t accel_z = 0;

volatile int16_t gyro_x = 0;
volatile int16_t gyro_y = 0;
volatile int16_t gyro_z = 0;

volatile int16_t temp_raw = 0;

volatile uint32_t sample_count = 0;

volatile uint8_t reg6b = 0;
volatile bool wakeup_ok = false;

volatile uint8_t accel_config_reg = 0;
volatile bool accel_config_ok = false;

volatile uint8_t gyro_config_reg = 0;
volatile bool gyro_config_ok = false;

volatile uint8_t config_reg = 0;
volatile uint8_t smplrt_div_reg = 0;

volatile bool config_ok = false;
volatile bool sample_rate_ok = false;

volatile uint8_t int_enable_reg = 0;
volatile bool int_enable_ok = false;

volatile bool int_enable_write_ok = false;

volatile uint8_t int_status_reg = 0;
volatile bool int_status_read_ok = false;

volatile bool imu_data_ready = false;
volatile uint32_t interrupt_count = 0;

volatile uint32_t read_attempts = 0;
volatile uint32_t read_success = 0;
volatile uint32_t read_failures = 0;

volatile uint8_t int_pin_cfg_reg = 0;
volatile bool int_pin_cfg_ok = false;

volatile uint32_t int_status_reads_ok = 0;
volatile uint32_t int_status_reads_fail = 0;

volatile bool read14_ok = false;
volatile bool read14_fail = false;

/* ---------------------------------------------------------------------
 * Diagnostics: per-transaction I2CSPM_Transfer() return code capture.
 *
 * I2C_TransferReturn_TypeDef (defined in em_i2c.h, pulled in via
 * sl_i2cspm.h which the file already includes) is a standard EMLIB enum:
 *   i2cTransferInProgress, i2cTransferDone, i2cTransferNack,
 *   i2cTransferBusErr, i2cTransferArbLost, i2cTransferUsageFault,
 *   i2cTransferSwFault
 *
 * No new headers or SDK components are required to use it.
 * --------------------------------------------------------------------- */

/* Last raw return code from each transaction type -- inspect live in a
 * watch window without needing to halt on a specific line. */
volatile I2C_TransferReturn_TypeDef last_status_read_ret = i2cTransferDone;
volatile I2C_TransferReturn_TypeDef last_burst_read_ret  = i2cTransferDone;

/* Classified counters, kept separate per transaction so you can see
 * directly which of the two transactions is failing and how. */
volatile uint32_t status_read_ret_done        = 0;
volatile uint32_t status_read_ret_nack        = 0;
volatile uint32_t status_read_ret_buserr      = 0;
volatile uint32_t status_read_ret_arblost     = 0;
volatile uint32_t status_read_ret_usagefault  = 0;
volatile uint32_t status_read_ret_other       = 0;

volatile uint32_t burst_read_ret_done       = 0;
volatile uint32_t burst_read_ret_nack       = 0;
volatile uint32_t burst_read_ret_buserr     = 0;
volatile uint32_t burst_read_ret_arblost    = 0;
volatile uint32_t burst_read_ret_usagefault = 0;
volatile uint32_t burst_read_ret_other      = 0;

/*
 * Classifies an I2C_TransferReturn_TypeDef into the counter set for a
 * given transaction category. Pure bookkeeping -- does not alter control
 * flow, does not retry, does not touch the bus.
 */
static void mpu6050_record_status_ret(I2C_TransferReturn_TypeDef ret)
{
  last_status_read_ret = ret;

  switch (ret)
  {
    case i2cTransferDone:        status_read_ret_done++;       break;
    case i2cTransferNack:        status_read_ret_nack++;       break;
    case i2cTransferBusErr:      status_read_ret_buserr++;     break;
    case i2cTransferArbLost:     status_read_ret_arblost++;    break;
    case i2cTransferUsageFault:  status_read_ret_usagefault++; break;
    default:                     status_read_ret_other++;      break;
  }
}

static void mpu6050_record_burst_ret(I2C_TransferReturn_TypeDef ret)
{
  last_burst_read_ret = ret;

  switch (ret)
  {
    case i2cTransferDone:        burst_read_ret_done++;       break;
    case i2cTransferNack:        burst_read_ret_nack++;       break;
    case i2cTransferBusErr:      burst_read_ret_buserr++;     break;
    case i2cTransferArbLost:     burst_read_ret_arblost++;    break;
    case i2cTransferUsageFault:  burst_read_ret_usagefault++; break;
    default:                     burst_read_ret_other++;      break;
  }
}

static bool MPU6050_ReadRegister(uint8_t reg, uint8_t *value)
{
  I2C_TransferSeq_TypeDef seq;

  seq.addr = MPU6050_ADDR << 1;
  seq.flags = I2C_FLAG_WRITE_READ;

  seq.buf[0].data = &reg;
  seq.buf[0].len  = 1;

  seq.buf[1].data = value;
  seq.buf[1].len  = 1;

  I2C_TransferReturn_TypeDef ret;

  ret = I2CSPM_Transfer(sl_i2cspm_mikroe, &seq);

  return (ret == i2cTransferDone);
}

static bool MPU6050_WriteRegister(uint8_t reg, uint8_t value)
{
  uint8_t data[2];

  data[0] = reg;
  data[1] = value;

  I2C_TransferSeq_TypeDef seq;

  seq.addr = MPU6050_ADDR << 1;
  seq.flags = I2C_FLAG_WRITE;

  seq.buf[0].data = data;
  seq.buf[0].len = 2;

  return (I2CSPM_Transfer(sl_i2cspm_mikroe, &seq)
          == i2cTransferDone);
}

/*
 * INT_STATUS read used in the sample hot path. Functionally identical to
 * the original MPU6050_ReadRegister(MPU6050_INT_STATUS, ...) call, but
 * additionally captures and classifies the raw I2CSPM_Transfer() return
 * code so failures on THIS specific transaction are distinguishable from
 * failures on the burst read below.
 */
static bool MPU6050_ReadIntStatusDiag(uint8_t *value)
{
  uint8_t reg = MPU6050_INT_STATUS;

  I2C_TransferSeq_TypeDef seq;

  seq.addr  = MPU6050_ADDR << 1;
  seq.flags = I2C_FLAG_WRITE_READ;

  seq.buf[0].data = &reg;
  seq.buf[0].len  = 1;

  seq.buf[1].data = value;
  seq.buf[1].len  = 1;

  I2C_TransferReturn_TypeDef ret = I2CSPM_Transfer(sl_i2cspm_mikroe, &seq);

  mpu6050_record_status_ret(ret);

  return (ret == i2cTransferDone);
}

/*
 * 14-byte burst read starting at ACCEL_XOUT_H. Structurally identical to
 * the original MPU6050_Read14Bytes(), but now captures and classifies the
 * raw I2CSPM_Transfer() return code for this specific transaction.
 */
static bool MPU6050_Read14BytesDiag(uint8_t *data)
{
  uint8_t reg = MPU6050_ACCEL_XOUT_H;

  I2C_TransferSeq_TypeDef seq;

  seq.addr  = MPU6050_ADDR << 1;
  seq.flags = I2C_FLAG_WRITE_READ;

  seq.buf[0].data = &reg;
  seq.buf[0].len  = 1;

  seq.buf[1].data = data;
  seq.buf[1].len  = 14;

  I2C_TransferReturn_TypeDef ret = I2CSPM_Transfer(sl_i2cspm_mikroe, &seq);

  mpu6050_record_burst_ret(ret);

  return (ret == i2cTransferDone);
}

#if MPU6050_USE_COMBINED_BURST
/*
 * OPTIONAL: single 15-byte transaction (INT_STATUS + full sensor burst).
 * Only compiled in if MPU6050_USE_COMBINED_BURST is set to 1 above.
 * Classified into the same "burst" counters, since it subsumes both
 * reads into one transfer.
 */
static bool MPU6050_ReadStatusAndBurstCombined(uint8_t *data)
{
  uint8_t reg = MPU6050_INT_STATUS;

  I2C_TransferSeq_TypeDef seq;

  seq.addr  = MPU6050_ADDR << 1;
  seq.flags = I2C_FLAG_WRITE_READ;

  seq.buf[0].data = &reg;
  seq.buf[0].len  = 1;

  seq.buf[1].data = data;
  seq.buf[1].len  = MPU6050_COMBINED_LEN;

  I2C_TransferReturn_TypeDef ret = I2CSPM_Transfer(sl_i2cspm_mikroe, &seq);

  mpu6050_record_burst_ret(ret);

  return (ret == i2cTransferDone);
}
#endif /* MPU6050_USE_COMBINED_BURST */

static void mpu6050_gpio_callback(uint8_t pin)
{
  (void)pin;

  interrupt_count++;
  imu_data_ready = true;
}

void app_init(void)
{
  uint8_t whoami = 0;

  if (MPU6050_ReadRegister(MPU6050_WHO_AM_I, &whoami))
  {
    mpu_whoami = whoami;

    if ((whoami == 0x68) || (whoami == 0x70))
    {
      mpu_found = true;

      /* Wake MPU6050 */
      if (MPU6050_WriteRegister(MPU6050_PWR_MGMT_1, 0x00))
      {
        if (MPU6050_ReadRegister(MPU6050_PWR_MGMT_1,
                                 (uint8_t *)&reg6b))
        {
          if (reg6b == 0x00)
          {
            wakeup_ok = true;
          }
        }
      }

      /* Accelerometer +/-2g */
      if (MPU6050_WriteRegister(MPU6050_ACCEL_CONFIG, 0x00))
      {
        MPU6050_ReadRegister(MPU6050_ACCEL_CONFIG,
                             (uint8_t *)&accel_config_reg);

        if (accel_config_reg == 0x00)
        {
          accel_config_ok = true;
        }
      }

      /* Gyroscope +/-250 dps */
      if (MPU6050_WriteRegister(MPU6050_GYRO_CONFIG, 0x00))
      {
        MPU6050_ReadRegister(MPU6050_GYRO_CONFIG,
                             (uint8_t *)&gyro_config_reg);

        if (gyro_config_reg == 0x00)
        {
          gyro_config_ok = true;
        }
      }

      /* DLPF configuration */
      if (MPU6050_WriteRegister(MPU6050_CONFIG, 0x03))
      {
        MPU6050_ReadRegister(MPU6050_CONFIG,
                             (uint8_t *)&config_reg);

        if (config_reg == 0x03)
        {
          config_ok = true;
        }
      }

      /* 1kHz / (9 + 1) = 100 Hz */
      if (MPU6050_WriteRegister(MPU6050_SMPLRT_DIV, 9))
      {
        MPU6050_ReadRegister(MPU6050_SMPLRT_DIV,
                             (uint8_t *)&smplrt_div_reg);

        if (smplrt_div_reg == 9)
        {
          sample_rate_ok = true;
        }
      }

      /* Interrupt pin configuration */
      if (MPU6050_WriteRegister(MPU6050_INT_PIN_CFG, 0x00))
      {
        MPU6050_ReadRegister(MPU6050_INT_PIN_CFG,
                             (uint8_t *)&int_pin_cfg_reg);

        if (int_pin_cfg_reg == 0x00)
        {
          int_pin_cfg_ok = true;
        }
      }

      /* Enable DATA_RDY interrupt */
      if (MPU6050_WriteRegister(MPU6050_INT_ENABLE, 0x01))
      {
        int_enable_write_ok = true;

        MPU6050_ReadRegister(MPU6050_INT_ENABLE,
                             (uint8_t *)&int_enable_reg);

        if (int_enable_reg == 0x01)
        {
          int_enable_ok = true;
        }
      }

      /* Clear any pending interrupt */
      if (MPU6050_ReadRegister(MPU6050_INT_STATUS,
                         (uint8_t *)&int_status_reg))
               {
                   int_status_reads_ok++;
              }
      else
          {
              int_status_reads_fail++;
       }

      /* ---------- GPIO Interrupt Setup (unchanged) ---------- */

      CMU_ClockEnable(cmuClock_GPIO, true);

      GPIO_PinModeSet(MPU6050_INT_PORT,
                      MPU6050_INT_PIN,
                      gpioModeInputPull,
                      0);

      GPIOINT_Init();

      GPIOINT_CallbackRegister(MPU6050_INT_PIN,
                               mpu6050_gpio_callback);

      GPIO_ExtIntConfig(MPU6050_INT_PORT,
                        MPU6050_INT_PIN,
                        MPU6050_INT_LINE,
                        true,   /* rising edge */
                        false,  /* falling edge */
                        true);  /* enable */
    }
  }
}

void app_process_action(void)
{
  uint8_t raw[14];

  /*
   * Interrupt-driven architecture.
   * Return immediately unless MPU6050 asserted DATA_RDY.
   * UNCHANGED from original.
   */
  if (!imu_data_ready)
  {
    return;
  }

  /*
   * Atomic flag clear.
   * Same pattern used in validated MAX30102 firmware.
   * UNCHANGED from original.
   */
  CORE_DECLARE_IRQ_STATE;

  CORE_ENTER_ATOMIC();
  imu_data_ready = false;
  CORE_EXIT_ATOMIC();

  read_attempts++;

#if MPU6050_USE_COMBINED_BURST
  /* Optional experiment path -- off by default. */
  {
    uint8_t combined[MPU6050_COMBINED_LEN];

    if (MPU6050_ReadStatusAndBurstCombined(combined))
    {
      int_status_reg = combined[0];
      read14_ok = true;
      read14_fail = false;

      accel_x = (int16_t)((combined[1]  << 8) | combined[2]);
      accel_y = (int16_t)((combined[3]  << 8) | combined[4]);
      accel_z = (int16_t)((combined[5]  << 8) | combined[6]);

      temp_raw = (int16_t)((combined[7] << 8) | combined[8]);

      gyro_x = (int16_t)((combined[9]  << 8) | combined[10]);
      gyro_y = (int16_t)((combined[11] << 8) | combined[12]);
      gyro_z = (int16_t)((combined[13] << 8) | combined[14]);

      sample_count++;
      read_success++;
    }
    else
    {
      read14_fail = true;
      read_failures++;
    }
  }
#else
  /*
   * DEFAULT PATH -- structurally identical to the original firmware:
   * a separate INT_STATUS read followed by a separate 14-byte burst
   * read. The only change is that each call now records its raw
   * I2CSPM_Transfer() return code via the *_Diag() wrappers above,
   * so the classified counters tell you definitively which of the two
   * transactions is failing and with what error code.
   */

  /*
   * Read INT_STATUS.
   * This acknowledges the MPU6050 interrupt source.
   */
  int_status_read_ok = MPU6050_ReadIntStatusDiag((uint8_t *)&int_status_reg);

  /*
   * Read one complete IMU sample.
   */
  if (MPU6050_Read14BytesDiag(raw))
  {
    read14_ok = true;
    read14_fail = false;
    read_success++;

    accel_x = (int16_t)((raw[0] << 8) | raw[1]);
    accel_y = (int16_t)((raw[2] << 8) | raw[3]);
    accel_z = (int16_t)((raw[4] << 8) | raw[5]);

    temp_raw = (int16_t)((raw[6] << 8) | raw[7]);

    gyro_x = (int16_t)((raw[8]  << 8) | raw[9]);
    gyro_y = (int16_t)((raw[10] << 8) | raw[11]);
    gyro_z = (int16_t)((raw[12] << 8) | raw[13]);

    sample_count++;
  }
  else
  {
    read14_ok = false;
    read14_fail = true;
    read_failures++;
  }
#endif /* MPU6050_USE_COMBINED_BURST */
}