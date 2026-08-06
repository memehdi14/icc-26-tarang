/***************************************************************************//**
 * @file 04_ecg_imu_combined.ino
 * @brief Tarang bring-up Stage 5 — combined ECG + MPU6050 serial CSV stream.
 *
 * This is the SIMPLIFIED single-task version. Use 05_ecg_imu_250_100hz_csv
 * for production-tight 250/100 Hz timing with master-tick scheduling.
 *
 * Wiring:
 *   AD8232 OUTPUT -> GPIO34
 *   AD8232 LO+    -> GPIO35   (optional)
 *   AD8232 LO-    -> GPIO32   (optional)
 *   AD8232 3.3V   -> 3V3
 *   AD8232 GND    -> GND
 *   AD8232 SDN    -> 3V3
 *   MPU6050 VCC   -> 3V3
 *   MPU6050 GND   -> GND
 *   MPU6050 SCL   -> GPIO22
 *   MPU6050 SDA   -> GPIO21
 *   MPU6050 AD0   -> GND
 *
 * Output (one CSV row per ECG sample, ~250 Hz):
 *   t_us,ecg_idx,imu_idx,ecg_raw,ecg_mv,ax,ay,az,imu_mag,lo+
 *
 * The IMU is read every 5th ECG sample and zero-order-held in between,
 * so consecutive ECG rows share the same imu_idx until the next IMU read.
 ******************************************************************************/
#include <Wire.h>
#include <Arduino.h>

#define MPU6050_ADDR        0x68
#define MPU6050_SMPLRT_DIV  0x19
#define MPU6050_CONFIG      0x1A
#define MPU6050_ACCEL_CFG   0x1C
#define MPU6050_ACCEL_XOUT_H 0x3B
#define MPU6050_PWR_MGMT_1  0x6B
#define MPU6050_WHO_AM_I    0x75

#define ECG_ADC_PIN    34
#define ECG_LO_PLUS    35
#define ECG_LO_MINUS   32

#define ECG_HZ         250
#define IMU_HZ         100
#define IMU_PERIOD_ECG_TICKS  (ECG_HZ / IMU_HZ)   // 2 -> wait, 250/100=2.5

// 250/100 != integer -> use 5 ECG ticks = 2 IMU reads pattern.
// We sample IMU every 2nd or 3rd ECG tick alternating -> avg 100 Hz.
// Simpler: read IMU every 2 ECG samples = 125 Hz (acceptable for bring-up).
// Stage 05 fixes this properly with a 500 Hz master tick.
#define IMU_READ_EVERY_N_ECG  2

void mpu6050_write(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission(true);
}

bool mpu6050_read_accel(int16_t *ax, int16_t *ay, int16_t *az) {
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(MPU6050_ACCEL_XOUT_H);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((uint8_t)MPU6050_ADDR, (uint8_t)6) != 6) return false;
  *ax = (int16_t)((Wire.read() << 8) | Wire.read());
  *ay = (int16_t)((Wire.read() << 8) | Wire.read());
  *az = (int16_t)((Wire.read() << 8) | Wire.read());
  return true;
}

void setup() {
  Serial.begin(921600);
  delay(200);
  Wire.begin(21, 22, 400000);
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
  pinMode(ECG_ADC_PIN, INPUT);
  pinMode(ECG_LO_PLUS, INPUT);
  pinMode(ECG_LO_MINUS, INPUT);

  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(MPU6050_WHO_AM_I);
  Wire.endTransmission(false);
  Wire.requestFrom((uint8_t)MPU6050_ADDR, (uint8_t)1);
  uint8_t who = Wire.read();
  Serial.printf("# MPU6050 WHO_AM_I = 0x%02X\n", who);

  mpu6050_write(MPU6050_PWR_MGMT_1, 0x00);
  delay(5);
  mpu6050_write(MPU6050_SMPLRT_DIV, 9);
  mpu6050_write(MPU6050_CONFIG, 0x01);
  mpu6050_write(MPU6050_ACCEL_CFG, 0x00);

  Serial.println(F("# Tarang combined ECG+IMU bring-up v4"));
  Serial.println(F("# ECG 250 Hz (GPIO34), IMU 125 Hz (held), serial 921600"));
  Serial.println(F("t_us,ecg_idx,imu_idx,ecg_raw,ecg_mv,ax,ay,az,imu_mag,lo+"));
}

void loop() {
  static uint32_t ecg_idx = 0;
  static uint32_t imu_idx = 0;
  static int16_t ax = 0, ay = 0, az = 0;
  static uint32_t last_us = 0;
  static uint32_t imu_last_read_ecg_idx = 0xFFFFFFFF;

  uint32_t now = micros();
  if (last_us == 0) last_us = now;

  // Read ECG every iteration (loop runs ~250 Hz via delayMicroseconds)
  int raw = analogRead(ECG_ADC_PIN);
  int lop = digitalRead(ECG_LO_PLUS);
  ecg_idx++;

  // Read IMU every N ECG samples
  if (ecg_idx - imu_last_read_ecg_idx >= IMU_READ_EVERY_N_ECG) {
    int16_t nx, ny, nz;
    if (mpu6050_read_accel(&nx, &ny, &nz)) {
      ax = nx; ay = ny; az = nz;
      imu_idx++;
      imu_last_read_ecg_idx = ecg_idx;
    }
  }

  // IMU magnitude (raw LSB)
  int32_t mx = (int32_t)ax, my = (int32_t)ay, mz = (int32_t)az;
  uint32_t mag = (uint32_t)sqrtf((float)(mx*mx + my*my + mz*mz));
  float ecg_mv = (raw - 2048.0f) * (3300.0f / 4096.0f);

  Serial.printf("%lu,%lu,%lu,%d,%.2f,%d,%d,%d,%lu,%d\n",
                (unsigned long)now,
                (unsigned long)ecg_idx,
                (unsigned long)imu_idx,
                raw, ecg_mv,
                ax, ay, az,
                (unsigned long)mag,
                lop);

  // Pace to 250 Hz
  uint32_t elapsed = micros() - now;
  int32_t wait = 4000 - (int32_t)elapsed;   // 4000 us = 250 Hz
  if (wait > 0) delayMicroseconds(wait);
  last_us = now;
}
