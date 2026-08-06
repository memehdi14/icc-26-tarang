/***************************************************************************//**
 * @file tarang_imu.c
 * @brief TARANG IMU acquisition module — implementation.
 *
 * Direct extraction from Separate Testing/IMU/AMIMU/app.c.
 * UNCHANGED sensor logic. Only renamed app_init→tarang_imu_init,
 * app_process_action→tarang_imu_process, removed GPIOINT_Init()
 * (called once by orchestrator).
 *
 * MPU6050 over I2C (sl_i2cspm_mikroe), interrupt-driven via PC00 GPIO.
 * DATA_RDY interrupt at 100Hz, 14-byte burst read per interrupt.
 *
 * Target : EFR32MG26B510F3200IM48 (Series 2, Cortex-M33)
 ******************************************************************************/

#include "tarang_imu.h"

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
 * Optional combined-transaction experiment (OFF by default)
 ******************************************************************************/
#define MPU6050_USE_COMBINED_BURST 0

/*******************************************************************************
 * MPU6050 Register Map
 ******************************************************************************/
#define MPU6050_ADDR            0x68
#define MPU6050_WHO_AM_I        0x75
#define MPU6050_ACCEL_XOUT_H    0x3B

#define MPU6050_PWR_MGMT_1      0x6B

#define MPU6050_ACCEL_CONFIG    0x1C
#define MPU6050_GYRO_CONFIG     0x1B

#define MPU6050_CONFIG          0x1A
#define MPU6050_SMPLRT_DIV      0x19

#define MPU6050_INT_ENABLE      0x38
#define MPU6050_INT_STATUS      0x3A
#define MPU6050_INT_PIN_CFG     0x37

/*******************************************************************************
 * Hardware Pin Definition — MPU6050 INT connected to PC00
 ******************************************************************************/
#define MPU6050_INT_PORT gpioPortC
#define MPU6050_INT_PIN  0u
#define MPU6050_INT_LINE 0u

#if MPU6050_USE_COMBINED_BURST
#define MPU6050_COMBINED_LEN 15u
#endif

/*******************************************************************************
 * Static variables (were globals in the test project)
 ******************************************************************************/
static volatile uint8_t mpu_whoami = 0;
static volatile bool mpu_found = false;

static volatile int16_t accel_x = 0;
static volatile int16_t accel_y = 0;
static volatile int16_t accel_z = 0;

static volatile int16_t gyro_x = 0;
static volatile int16_t gyro_y = 0;
static volatile int16_t gyro_z = 0;

static volatile int16_t temp_raw = 0;

static volatile uint32_t sample_count = 0;

static volatile uint8_t reg6b = 0;
static volatile bool wakeup_ok = false;

static volatile uint8_t accel_config_reg = 0;
static volatile bool accel_config_ok = false;

static volatile uint8_t gyro_config_reg = 0;
static volatile bool gyro_config_ok = false;

static volatile uint8_t config_reg = 0;
static volatile uint8_t smplrt_div_reg = 0;

static volatile bool config_ok = false;
static volatile bool sample_rate_ok = false;

static volatile uint8_t int_enable_reg = 0;
static volatile bool int_enable_ok = false;

static volatile bool int_enable_write_ok = false;

static volatile uint8_t int_status_reg = 0;
static volatile bool int_status_read_ok = false;

static volatile bool imu_data_ready = false;
static volatile uint32_t interrupt_count = 0;

static volatile uint32_t read_attempts = 0;
static volatile uint32_t read_success = 0;
static volatile uint32_t read_failures = 0;

static volatile uint8_t int_pin_cfg_reg = 0;
static volatile bool int_pin_cfg_ok = false;

static volatile uint32_t int_status_reads_ok = 0;
static volatile uint32_t int_status_reads_fail = 0;

static volatile bool read14_ok = false;
static volatile bool read14_fail = false;

/* Diagnostics: per-transaction I2CSPM_Transfer() return code capture */
static volatile I2C_TransferReturn_TypeDef last_status_read_ret = i2cTransferDone;
static volatile I2C_TransferReturn_TypeDef last_burst_read_ret  = i2cTransferDone;

static volatile uint32_t status_read_ret_done        = 0;
static volatile uint32_t status_read_ret_nack        = 0;
static volatile uint32_t status_read_ret_buserr      = 0;
static volatile uint32_t status_read_ret_arblost     = 0;
static volatile uint32_t status_read_ret_usagefault  = 0;
static volatile uint32_t status_read_ret_other       = 0;

static volatile uint32_t burst_read_ret_done       = 0;
static volatile uint32_t burst_read_ret_nack       = 0;
static volatile uint32_t burst_read_ret_buserr     = 0;
static volatile uint32_t burst_read_ret_arblost    = 0;
static volatile uint32_t burst_read_ret_usagefault = 0;
static volatile uint32_t burst_read_ret_other      = 0;

/*******************************************************************************
 * Private: I2C helpers and diagnostics
 ******************************************************************************/
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

/*******************************************************************************
 * GPIO Interrupt Callback — registered for pin 0 (PC00)
 ******************************************************************************/
static void mpu6050_gpio_callback(uint8_t pin)
{
  (void)pin;

  interrupt_count++;
  imu_data_ready = true;
}

/*******************************************************************************
 * tarang_imu_init
 ******************************************************************************/
void tarang_imu_init(void)
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

      /* ---------- GPIO Interrupt Setup ---------- */
      /* NOTE: GPIOINT_Init() is called once by app.c before sensor inits */

      GPIO_PinModeSet(MPU6050_INT_PORT,
                      MPU6050_INT_PIN,
                      gpioModeInputPull,
                      0);

      GPIOINT_CallbackRegister(MPU6050_INT_PIN,
                               mpu6050_gpio_callback);

      GPIO_ExtIntConfig(MPU6050_INT_PORT,
                        MPU6050_INT_PIN,
                        MPU6050_INT_LINE,
                        true,   /* rising edge */
                        false,  /* falling edge */
                        true);  /* enable */

      printf("[IMU] MPU6050 init complete. WHO_AM_I=0x%02X\r\n", mpu_whoami);
    }
    else
    {
      printf("[IMU] WHO_AM_I mismatch: got 0x%02X\r\n", whoami);
    }
  }
  else
  {
    printf("[IMU] I2C read WHO_AM_I failed\r\n");
  }
}

/*******************************************************************************
 * tarang_imu_process — interrupt-driven IMU sample collection
 ******************************************************************************/
void tarang_imu_process(void)
{
  uint8_t raw[14];

  if (!imu_data_ready)
  {
    return;
  }

  CORE_DECLARE_IRQ_STATE;

  CORE_ENTER_ATOMIC();
  imu_data_ready = false;
  CORE_EXIT_ATOMIC();

  read_attempts++;

#if MPU6050_USE_COMBINED_BURST
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
  /* DEFAULT PATH: separate INT_STATUS read + 14-byte burst read */

  int_status_read_ok = MPU6050_ReadIntStatusDiag((uint8_t *)&int_status_reg);

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

    /* Print every 100 samples (every 1 second at 100Hz) */
    if ((sample_count % 100u) == 0u)
    {
      printf("[IMU] cnt=%lu ax=%d ay=%d az=%d gx=%d gy=%d gz=%d\r\n",
             (unsigned long)sample_count,
             accel_x, accel_y, accel_z,
             gyro_x, gyro_y, gyro_z);
    }
  }
  else
  {
    read14_ok = false;
    read14_fail = true;
    read_failures++;
  }
#endif /* MPU6050_USE_COMBINED_BURST */
}

/*******************************************************************************
 * Public accessors
 ******************************************************************************/
bool tarang_imu_is_found(void)
{
  return mpu_found;
}

int16_t tarang_imu_get_accel_x(void)
{
  return accel_x;
}

int16_t tarang_imu_get_accel_y(void)
{
  return accel_y;
}

int16_t tarang_imu_get_accel_z(void)
{
  return accel_z;
}

int16_t tarang_imu_get_gyro_x(void)
{
  return gyro_x;
}

int16_t tarang_imu_get_gyro_y(void)
{
  return gyro_y;
}

int16_t tarang_imu_get_gyro_z(void)
{
  return gyro_z;
}

int16_t tarang_imu_get_temp_raw(void)
{
  return temp_raw;
}

uint32_t tarang_imu_get_sample_count(void)
{
  return sample_count;
}

uint32_t tarang_imu_get_interrupt_count(void)
{
  return interrupt_count;
}
