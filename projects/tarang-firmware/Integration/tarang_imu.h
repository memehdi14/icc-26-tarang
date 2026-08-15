/***************************************************************************//**
 * @file tarang_imu.h
 * @brief TARANG IMU acquisition module — public API.
 *
 * Extracted from Separate Testing/IMU/AMIMU/app.c (proven on hardware).
 * MPU6050 over I2C (sl_i2cspm_mikroe), interrupt-driven via PC00 GPIO.
 ******************************************************************************/
#ifndef TARANG_IMU_H
#define TARANG_IMU_H

#include <stdint.h>
#include <stdbool.h>
#include "tarang_sensor_health.h"

#ifdef __cplusplus
extern "C" {
#endif

/***************************************************************************//**
 * Initialize IMU sensor (MPU6050).
 * Configures: I2C registers, GPIO PC00 interrupt for DATA_RDY.
 *
 * @note Call GPIOINT_Init() and CMU_ClockEnable(cmuClock_GPIO) BEFORE this.
 ******************************************************************************/
void tarang_imu_init(void);

/***************************************************************************//**
 * IMU process action — call from app_process_action().
 * Reads 14-byte burst if DATA_RDY interrupt has fired.
 * Returns immediately if nothing pending.
 ******************************************************************************/
void tarang_imu_process(void);

/* ─── Status accessors ──────────────────────────────────────────────────── */
bool     tarang_imu_is_found(void);
int16_t  tarang_imu_get_accel_x(void);
int16_t  tarang_imu_get_accel_y(void);
int16_t  tarang_imu_get_accel_z(void);
int16_t  tarang_imu_get_gyro_x(void);
int16_t  tarang_imu_get_gyro_y(void);
int16_t  tarang_imu_get_gyro_z(void);
int16_t  tarang_imu_get_temp_raw(void);
uint32_t tarang_imu_get_sample_count(void);
uint32_t tarang_imu_get_interrupt_count(void);
tarang_sensor_health_t tarang_imu_get_health(void);
bool     tarang_imu_is_valid(void);

#ifdef __cplusplus
}
#endif

#endif /* TARANG_IMU_H */
