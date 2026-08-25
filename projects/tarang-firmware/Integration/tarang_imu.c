/***************************************************************************//**
 * @file tarang_imu.c
 * @brief TARANG IMU acquisition module — implementation.
 *
 * MPU6050 over I2C (sl_i2cspm_mikroe), interrupt-driven via PC00 GPIO with
 * 100 Hz timer polling fallback.
 *
 * Target : EFR32MG26B510F3200IM48 (Series 2, Cortex-M33)
 ******************************************************************************/

#include "tarang_imu.h"
#include "tarang_time.h"
#include "tarang_validation_stream.h"

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
 * MPU6050 Register Map
 ******************************************************************************/
#define MPU6050_DEFAULT_ADDR    0x68
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

/*******************************************************************************
 * Static variables
 ******************************************************************************/
static volatile uint8_t mpu_whoami = 0;
static volatile bool mpu_found = false;
static uint8_t mpu_address = MPU6050_DEFAULT_ADDR;

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

static volatile uint8_t int_pin_cfg_reg = 0;
static volatile bool int_pin_cfg_ok = false;

static volatile uint8_t int_enable_reg = 0;
static volatile bool int_enable_ok = false;
static volatile bool int_enable_write_ok = false;

static volatile uint8_t int_status_reg = 0;
static volatile uint32_t int_status_reads_ok = 0;
static volatile uint32_t int_status_reads_fail = 0;

static volatile bool read14_ok = false;
static volatile bool read14_fail = false;
static volatile uint32_t read_attempts = 0;
static volatile uint32_t read_success = 0;
static volatile uint32_t read_failures = 0;
static volatile uint32_t consecutive_read_failures = 0;

static volatile bool imu_data_ready = false;
static volatile uint32_t interrupt_count = 0;

static I2C_TransferReturn_TypeDef last_status_read_ret = i2cTransferDone;
static uint32_t status_read_ret_done = 0;
static uint32_t status_read_ret_nack = 0;
static uint32_t status_read_ret_buserr = 0;
static uint32_t status_read_ret_arblost = 0;
static uint32_t status_read_ret_usagefault = 0;
static uint32_t status_read_ret_other = 0;

static I2C_TransferReturn_TypeDef last_burst_read_ret = i2cTransferDone;
static uint32_t burst_read_ret_done = 0;
static uint32_t burst_read_ret_nack = 0;
static uint32_t burst_read_ret_buserr = 0;
static uint32_t burst_read_ret_arblost = 0;
static uint32_t burst_read_ret_usagefault = 0;
static uint32_t burst_read_ret_other = 0;

static bool int_status_read_ok = false;

static tarang_imu_sample_t imu_ring[TARANG_IMU_RING_SIZE];
static uint8_t imu_ring_head = 0u;
static uint8_t imu_ring_count = 0u;
static uint64_t latest_sample_us = 0u;

static bool gravity_initialized = false;
static int32_t gravity_x_q8 = 0;
static int32_t gravity_y_q8 = 0;
static int32_t gravity_z_q8 = 0;
static uint16_t motion_mg = 0u;

static uint32_t last_imu_poll_ms = 0u;

/*******************************************************************************
 * Private helpers
 ******************************************************************************/
#if TARANG_VALIDATION_STREAM_ACTIVE
#define TARANG_VALIDATION_IMU_BLOCK_SAMPLES 5u
#define TARANG_VALIDATION_IMU_SAMPLE_BYTES  14u

static uint8_t s_validation_imu_payload[
    9u + TARANG_VALIDATION_IMU_BLOCK_SAMPLES
       * TARANG_VALIDATION_IMU_SAMPLE_BYTES];
static uint8_t s_validation_imu_count = 0u;
static size_t s_validation_imu_length = 0u;

static void imu_emit_validation_sample(void)
{
  uint32_t now_ms = tarang_now_ms();
  if (s_validation_imu_count == 0u) {
    tarang_validation_put_u32(&s_validation_imu_payload[0], sample_count);
    tarang_validation_put_u32(&s_validation_imu_payload[4], now_ms);
    s_validation_imu_payload[8] = 0u;
    s_validation_imu_length = 9u;
  }

  uint8_t *sample = &s_validation_imu_payload[s_validation_imu_length];
  tarang_validation_put_u16(&sample[0], (uint16_t)accel_x);
  tarang_validation_put_u16(&sample[2], (uint16_t)accel_y);
  tarang_validation_put_u16(&sample[4], (uint16_t)accel_z);
  tarang_validation_put_u16(&sample[6], (uint16_t)gyro_x);
  tarang_validation_put_u16(&sample[8], (uint16_t)gyro_y);
  tarang_validation_put_u16(&sample[10], (uint16_t)gyro_z);
  tarang_validation_put_u16(&sample[12], motion_mg);

  s_validation_imu_length += TARANG_VALIDATION_IMU_SAMPLE_BYTES;
  s_validation_imu_count++;
  s_validation_imu_payload[8] = s_validation_imu_count;

  if (s_validation_imu_count >= TARANG_VALIDATION_IMU_BLOCK_SAMPLES) {
    tarang_validation_emit('I', s_validation_imu_payload, s_validation_imu_length);
    s_validation_imu_count = 0u;
    s_validation_imu_length = 0u;
  }
}
#else
static void imu_emit_validation_sample(void)
{
  uint32_t now_ms = tarang_now_ms();
  printf("@I,%lu,%lu,%d,%d,%d,%d,%d,%d,%u\r\n",
         (unsigned long)sample_count,
         (unsigned long)now_ms,
         accel_x, accel_y, accel_z,
         gyro_x, gyro_y, gyro_z,
         (unsigned int)motion_mg);
}
#endif

static uint32_t imu_isqrt32(uint32_t value)
{
  if (value == 0u) return 0u;
  uint32_t x = value;
  uint32_t y = (x + 1u) >> 1u;
  while (y < x) {
    x = y;
    y = (x + value / x) >> 1u;
  }
  return x;
}

static void imu_store_sample(void)
{
  uint64_t now_us = tarang_now_us();

  if (!gravity_initialized) {
    gravity_x_q8 = ((int32_t)accel_x) << 8;
    gravity_y_q8 = ((int32_t)accel_y) << 8;
    gravity_z_q8 = ((int32_t)accel_z) << 8;
    gravity_initialized = true;
  } else {
    gravity_x_q8 += ((((int32_t)accel_x) << 8) - gravity_x_q8) / 32;
    gravity_y_q8 += ((((int32_t)accel_y) << 8) - gravity_y_q8) / 32;
    gravity_z_q8 += ((((int32_t)accel_z) << 8) - gravity_z_q8) / 32;
  }

  int32_t hx = (int32_t)accel_x - (gravity_x_q8 >> 8);
  int32_t hy = (int32_t)accel_y - (gravity_y_q8 >> 8);
  int32_t hz = (int32_t)accel_z - (gravity_z_q8 >> 8);
  uint64_t mag_sq = (uint64_t)((int64_t)hx * hx)
                  + (uint64_t)((int64_t)hy * hy)
                  + (uint64_t)((int64_t)hz * hz);
  if (mag_sq > UINT32_MAX) mag_sq = UINT32_MAX;
  uint32_t mag_lsb = imu_isqrt32((uint32_t)mag_sq);
  uint32_t mag_mg = (mag_lsb * 1000u + 8192u) / 16384u;
  motion_mg = (uint16_t)(mag_mg > 65535u ? 65535u : mag_mg);

  tarang_imu_sample_t *slot = &imu_ring[imu_ring_head];
  slot->t_us = now_us;
  slot->ax = accel_x;
  slot->ay = accel_y;
  slot->az = accel_z;
  slot->gx = gyro_x;
  slot->gy = gyro_y;
  slot->gz = gyro_z;
  imu_ring_head = (uint8_t)((imu_ring_head + 1u) % TARANG_IMU_RING_SIZE);
  if (imu_ring_count < TARANG_IMU_RING_SIZE) imu_ring_count++;
  latest_sample_us = now_us;
}

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

  seq.addr = mpu_address << 1;
  seq.flags = I2C_FLAG_WRITE_READ;

  seq.buf[0].data = &reg;
  seq.buf[0].len  = 1;

  seq.buf[1].data = value;
  seq.buf[1].len  = 1;

  I2C_TransferReturn_TypeDef ret = I2CSPM_Transfer(sl_i2cspm_mikroe, &seq);
  return (ret == i2cTransferDone);
}

static bool MPU6050_WriteRegister(uint8_t reg, uint8_t value)
{
  uint8_t data[2];

  data[0] = reg;
  data[1] = value;

  I2C_TransferSeq_TypeDef seq;

  seq.addr = mpu_address << 1;
  seq.flags = I2C_FLAG_WRITE;

  seq.buf[0].data = data;
  seq.buf[0].len = 2;

  return (I2CSPM_Transfer(sl_i2cspm_mikroe, &seq) == i2cTransferDone);
}

static bool MPU6050_ReadIntStatusDiag(uint8_t *value)
{
  uint8_t reg = MPU6050_INT_STATUS;

  I2C_TransferSeq_TypeDef seq;

  seq.addr  = mpu_address << 1;
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

  seq.addr  = mpu_address << 1;
  seq.flags = I2C_FLAG_WRITE_READ;

  seq.buf[0].data = &reg;
  seq.buf[0].len  = 1;

  seq.buf[1].data = data;
  seq.buf[1].len  = 14;

  I2C_TransferReturn_TypeDef ret = I2CSPM_Transfer(sl_i2cspm_mikroe, &seq);
  mpu6050_record_burst_ret(ret);
  return (ret == i2cTransferDone);
}

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
  printf("[IMU] Starting MPU6050 initialization...\r\n");
  
  uint8_t whoami = 0;
  bool read_ok = false;

  /* Try primary address 0x68, then fallback to 0x69 if AD0 is high/floating */
  static const uint8_t addrs_to_try[] = { 0x68, 0x69 };
  uint8_t active_addr = MPU6050_DEFAULT_ADDR;

  for (int a = 0; a < 2 && !read_ok; a++) {
    active_addr = addrs_to_try[a];
    printf("[IMU] Trying address 0x%02X...\r\n", active_addr);

    for (int attempt = 1; attempt <= 3; attempt++) {
      printf("[IMU] WHO_AM_I attempt %d/3 @ 0x%02X...\r\n", attempt, active_addr);

      {
        I2C_TransferSeq_TypeDef seq;
        uint8_t reg = MPU6050_WHO_AM_I;
        seq.addr = active_addr << 1;
        seq.flags = I2C_FLAG_WRITE_READ;
        seq.buf[0].data = &reg;
        seq.buf[0].len  = 1;
        seq.buf[1].data = &whoami;
        seq.buf[1].len  = 1;
        I2C_TransferReturn_TypeDef ret = I2CSPM_Transfer(sl_i2cspm_mikroe, &seq);
        if (ret == i2cTransferDone) {
          read_ok = true;
          printf("[IMU] WHO_AM_I read OK: 0x%02X @ addr 0x%02X\r\n", whoami, active_addr);
          break;
        }
      }

      printf("[IMU] WHO_AM_I read failed @ 0x%02X\r\n", active_addr);
      if (attempt < 3) {
        printf("[IMU] Retrying after delay...\r\n");
        for (volatile uint32_t i = 0; i < 100 * 4000u; i++) { }  // 100ms delay
      }
    }
  }

  if (!read_ok) {
    printf("[IMU] Failed to read WHO_AM_I at 0x68 AND 0x69 after all attempts\r\n");
    return;
  }

  mpu_whoami = whoami;
  mpu_address = active_addr;

  if ((whoami == 0x68) || (whoami == 0x70))
  {
    mpu_found = true;

    /* Wake up device from sleep */
    if (MPU6050_WriteRegister(MPU6050_PWR_MGMT_1, 0x00))
    {
      if (MPU6050_ReadRegister(MPU6050_PWR_MGMT_1, (uint8_t *)&reg6b))
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
      MPU6050_ReadRegister(MPU6050_ACCEL_CONFIG, (uint8_t *)&accel_config_reg);
      if (accel_config_reg == 0x00)
      {
        accel_config_ok = true;
      }
    }

    /* Gyroscope +/-250 dps */
    if (MPU6050_WriteRegister(MPU6050_GYRO_CONFIG, 0x00))
    {
      MPU6050_ReadRegister(MPU6050_GYRO_CONFIG, (uint8_t *)&gyro_config_reg);
      if (gyro_config_reg == 0x00)
      {
        gyro_config_ok = true;
      }
    }

    /* DLPF configuration */
    if (MPU6050_WriteRegister(MPU6050_CONFIG, 0x03))
    {
      MPU6050_ReadRegister(MPU6050_CONFIG, (uint8_t *)&config_reg);
      if (config_reg == 0x03)
      {
        config_ok = true;
      }
    }

    /* 1kHz / (9 + 1) = 100 Hz */
    if (MPU6050_WriteRegister(MPU6050_SMPLRT_DIV, 9))
    {
      MPU6050_ReadRegister(MPU6050_SMPLRT_DIV, (uint8_t *)&smplrt_div_reg);
      if (smplrt_div_reg == 9)
      {
        sample_rate_ok = true;
      }
    }

    /* Interrupt pin configuration */
    if (MPU6050_WriteRegister(MPU6050_INT_PIN_CFG, 0x30))
    {
      MPU6050_ReadRegister(MPU6050_INT_PIN_CFG, (uint8_t *)&int_pin_cfg_reg);
      if (int_pin_cfg_reg == 0x30)
      {
        int_pin_cfg_ok = true;
      }
    }

    /* Enable DATA_RDY interrupt */
    if (MPU6050_WriteRegister(MPU6050_INT_ENABLE, 0x01))
    {
      int_enable_write_ok = true;
      MPU6050_ReadRegister(MPU6050_INT_ENABLE, (uint8_t *)&int_enable_reg);
      if (int_enable_reg == 0x01)
      {
        int_enable_ok = true;
      }
    }

    /* Clear any pending interrupt */
    if (MPU6050_ReadRegister(MPU6050_INT_STATUS, (uint8_t *)&int_status_reg))
    {
      int_status_reads_ok++;
    }
    else
    {
      int_status_reads_fail++;
    }

    /* ---------- GPIO Interrupt Setup ---------- */
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

    if (GPIO_PinInGet(MPU6050_INT_PORT, MPU6050_INT_PIN) != 0u) {
      imu_data_ready = true;
    }

    printf("[IMU] MPU6050 init complete. WHO_AM_I=0x%02X wakeup=%d accel=%d gyro=%d dlpf=%d sr=%d int=%d\r\n",
           mpu_whoami, wakeup_ok, accel_config_ok, gyro_config_ok,
           config_ok, sample_rate_ok, int_enable_ok);
  }
  else
  {
    printf("[IMU] WHO_AM_I mismatch: got 0x%02X (expected 0x68 or 0x70)\r\n", whoami);
  }
}

static void tarang_imu_recover_bus(void)
{
  /* Reset I2C0 peripheral so GPIO can take back pin routing */
  I2C_Reset(sl_i2cspm_mikroe);

  /* 9 SCL pulses to unwedge hung MPU6050 I2C state machine */
  GPIO_PinModeSet(gpioPortC, 5, gpioModeWiredAndPullUp, 1);
  GPIO_PinModeSet(gpioPortC, 7, gpioModeWiredAndPullUp, 1);

  for (int i = 0; i < 9; i++) {
    GPIO_PinOutClear(gpioPortC, 5);
    for (volatile uint32_t d = 0; d < 300u; d++) { }
    GPIO_PinOutSet(gpioPortC, 5);
    for (volatile uint32_t d = 0; d < 300u; d++) { }
  }
  GPIO_PinOutClear(gpioPortC, 7);
  for (volatile uint32_t d = 0; d < 300u; d++) { }
  GPIO_PinOutSet(gpioPortC, 5);
  for (volatile uint32_t d = 0; d < 300u; d++) { }
  GPIO_PinOutSet(gpioPortC, 7);
  for (volatile uint32_t d = 0; d < 300u; d++) { }

  sl_i2cspm_init_instances();
}

/*******************************************************************************
 * tarang_imu_process — interrupt-driven & polled IMU sample collection
 ******************************************************************************/
void tarang_imu_process(void)
{
  uint8_t raw[14];
  uint8_t int_status = 0;

  if (!imu_data_ready && (GPIO_PinInGet(MPU6050_INT_PORT, MPU6050_INT_PIN) == 0u))
  {
    uint32_t now_ms = tarang_now_ms();
    if ((now_ms - last_imu_poll_ms) >= 10u) /* 10ms = 100 Hz fallback */
    {
      last_imu_poll_ms = now_ms;
      imu_data_ready = true;
    }
    else
    {
      return;
    }
  }

  CORE_DECLARE_IRQ_STATE;

  CORE_ENTER_ATOMIC();
  imu_data_ready = false;
  CORE_EXIT_ATOMIC();

  read_attempts++;

  /* Step 1: Read INT_STATUS register to acknowledge and clear the interrupt pin */
  (void)MPU6050_ReadIntStatusDiag(&int_status);

  /* Step 2: Read 14-byte sensor burst */
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
    consecutive_read_failures = 0u;
    imu_store_sample();
    imu_emit_validation_sample();

#if TARANG_DEBUG_VERBOSE
    if ((sample_count % 100u) == 0u)
    {
      printf("[IMU] cnt=%lu ax=%d ay=%d az=%d gx=%d gy=%d gz=%d\r\n",
             (unsigned long)sample_count,
             accel_x, accel_y, accel_z,
             gyro_x, gyro_y, gyro_z);
    }
#endif
  }
  else
  {
    read14_ok = false;
    read14_fail = true;
    read_failures++;
    consecutive_read_failures++;
    if (consecutive_read_failures >= 3u) {
      tarang_imu_recover_bus();
      consecutive_read_failures = 0u;
    }
  }

  if (GPIO_PinInGet(MPU6050_INT_PORT, MPU6050_INT_PIN) != 0u) {
    imu_data_ready = true;
  }
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

bool tarang_imu_is_healthy(void)
{
  if (!mpu_found || sample_count == 0u || consecutive_read_failures >= 4u) {
    return false;
  }
  uint64_t now_us = tarang_now_us();
  return latest_sample_us > 0u && now_us >= latest_sample_us
      && (now_us - latest_sample_us) <= 500000u;
}

uint16_t tarang_imu_get_motion_mg(void)
{
  return motion_mg;
}

bool tarang_imu_get_latest_sample(tarang_imu_sample_t *sample)
{
  if (sample == NULL || imu_ring_count == 0u) return false;
  CORE_DECLARE_IRQ_STATE;
  CORE_ENTER_ATOMIC();
  uint8_t index = (uint8_t)((imu_ring_head + TARANG_IMU_RING_SIZE - 1u)
                            % TARANG_IMU_RING_SIZE);
  *sample = imu_ring[index];
  CORE_EXIT_ATOMIC();
  return true;
}

uint8_t tarang_imu_get_recent_samples(tarang_imu_sample_t *dest, uint8_t max_count)
{
  if (dest == NULL || max_count == 0u || imu_ring_count == 0u) return 0u;
  CORE_DECLARE_IRQ_STATE;
  CORE_ENTER_ATOMIC();
  uint8_t available = (imu_ring_count < max_count) ? imu_ring_count : max_count;
  for (uint8_t i = 0u; i < available; i++) {
    uint8_t index = (uint8_t)((imu_ring_head + TARANG_IMU_RING_SIZE - available + i)
                              % TARANG_IMU_RING_SIZE);
    dest[i] = imu_ring[index];
  }
  CORE_EXIT_ATOMIC();
  return available;
}

bool tarang_imu_get_sample_at_or_before(uint64_t timestamp_us,
                                        tarang_imu_sample_t *sample)
{
  if (sample == NULL || imu_ring_count == 0u) return false;
  CORE_DECLARE_IRQ_STATE;
  CORE_ENTER_ATOMIC();
  
  /* Search backwards from newest to oldest */
  for (uint8_t i = 0u; i < imu_ring_count; i++) {
    uint8_t index = (uint8_t)((imu_ring_head + TARANG_IMU_RING_SIZE - 1u - i)
                              % TARANG_IMU_RING_SIZE);
    if (imu_ring[index].t_us <= timestamp_us) {
      *sample = imu_ring[index];
      CORE_EXIT_ATOMIC();
      return true;
    }
  }
  
  /* Fallback: oldest available sample */
  uint8_t oldest = (uint8_t)((imu_ring_head + TARANG_IMU_RING_SIZE - imu_ring_count)
                             % TARANG_IMU_RING_SIZE);
  *sample = imu_ring[oldest];
  CORE_EXIT_ATOMIC();
  return true;
}

bool tarang_imu_get_interpolated_sample(uint64_t timestamp_us,
                                        tarang_imu_sample_t *sample)
{
  if (sample == NULL || imu_ring_count == 0u) return false;
  CORE_DECLARE_IRQ_STATE;
  CORE_ENTER_ATOMIC();

  if (imu_ring_count == 1u) {
    uint8_t index = (uint8_t)((imu_ring_head + TARANG_IMU_RING_SIZE - 1u)
                              % TARANG_IMU_RING_SIZE);
    *sample = imu_ring[index];
    CORE_EXIT_ATOMIC();
    return true;
  }

  /* Search for the bounding pair (s0.t_us <= timestamp_us <= s1.t_us) */
  for (uint8_t i = 0u; i < imu_ring_count - 1u; i++) {
    uint8_t idx1 = (uint8_t)((imu_ring_head + TARANG_IMU_RING_SIZE - 1u - i)
                             % TARANG_IMU_RING_SIZE);
    uint8_t idx0 = (uint8_t)((imu_ring_head + TARANG_IMU_RING_SIZE - 2u - i)
                             % TARANG_IMU_RING_SIZE);
    
    if (imu_ring[idx0].t_us <= timestamp_us && imu_ring[idx1].t_us >= timestamp_us) {
      uint64_t dt = imu_ring[idx1].t_us - imu_ring[idx0].t_us;
      if (dt == 0u) {
        *sample = imu_ring[idx0];
      } else {
        int64_t frac_q15 = ((int64_t)(timestamp_us - imu_ring[idx0].t_us) << 15) / (int64_t)dt;
        sample->t_us = timestamp_us;
        sample->ax = (int16_t)(imu_ring[idx0].ax + (((int64_t)(imu_ring[idx1].ax - imu_ring[idx0].ax) * frac_q15) >> 15));
        sample->ay = (int16_t)(imu_ring[idx0].ay + (((int64_t)(imu_ring[idx1].ay - imu_ring[idx0].ay) * frac_q15) >> 15));
        sample->az = (int16_t)(imu_ring[idx0].az + (((int64_t)(imu_ring[idx1].az - imu_ring[idx0].az) * frac_q15) >> 15));
        sample->gx = (int16_t)(imu_ring[idx0].gx + (((int64_t)(imu_ring[idx1].gx - imu_ring[idx0].gx) * frac_q15) >> 15));
        sample->gy = (int16_t)(imu_ring[idx0].gy + (((int64_t)(imu_ring[idx1].gy - imu_ring[idx0].gy) * frac_q15) >> 15));
        sample->gz = (int16_t)(imu_ring[idx0].gz + (((int64_t)(imu_ring[idx1].gz - imu_ring[idx0].gz) * frac_q15) >> 15));
      }
      CORE_EXIT_ATOMIC();
      return true;
    }
  }

  /* Fallback: return sample at or before */
  CORE_EXIT_ATOMIC();
  return tarang_imu_get_sample_at_or_before(timestamp_us, sample);
}
