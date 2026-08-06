/***************************************************************************//**
 * @file 05_ecg_imu_250_100hz_csv.ino
 * @brief Tarang bring-up Stage 5 (PRODUCTION-LIKE) — exact 250 Hz ECG + 100 Hz
 *        IMU via a single 500 Hz master tick. CSV over 921600 baud serial.
 *
 * Design:
 *   - FreeRTOS task "sampler" pinned to core 1, priority 2 (above Arduino loop).
 *   - vTaskDelayUntil(pdMS_TO_TICKS(2)) gives a 500 Hz wakeup grid (2 ms).
 *   - tick % 2 == 0  -> read ECG (250 Hz, even ticks)
 *   - tick % 5 == 0  -> read MPU6050 (100 Hz, every 5th tick)
 *   - Both grids are phase-locked: every 10 ms both fire on the same tick.
 *   - Each ECG sample emits one CSV row with the latest held IMU values.
 *
 * Output columns (header row first):
 *   t_us,ecg_idx,imu_idx,ecg_raw,ecg_mv,ax,ay,az,imu_mag,lo+
 *
 * Wiring:
 *   AD8232 OUTPUT -> GPIO34   AD8232 LO+ -> GPIO35   AD8232 LO- -> GPIO32
 *   AD8232 3.3V   -> 3V3      AD8232 GND -> GND      AD8232 SDN -> 3V3
 *   MPU6050 VCC   -> 3V3      MPU6050 GND -> GND
 *   MPU6050 SCL   -> GPIO22   MPU6050 SDA -> GPIO21  MPU6050 AD0 -> GND
 *
 * On Raspberry Pi:
 *   python3 01_serial_logger.py /dev/ttyUSB0 921600
 *
 * Expected (Stage 8 sampling-rate check):
 *   mean_rate = 250.00 +/- 0.05 Hz
 *   jitter_p2p < 2 ms
 *   IMU imu_idx increments exactly once per 2.5 ECG samples on average.
 *
 * Failure modes:
 *   - rate drift >1 Hz       -> other tasks stealing CPU; raise sampler priority.
 *   - IMU imu_idx not advancing -> I2C read failing; check wiring.
 *   - Serial buffer overrun  -> lower baud is NOT the fix; raise to 921600 or
 *                               split emit into a separate task with ring buf.
 *   - Wi-Fi/BLE active       -> KILLS timing. Ensure WiFi.mode(WIFI_OFF) (done).
 ******************************************************************************/
#include <Wire.h>
#include <Arduino.h>
#include <WiFi.h>
#include <esp_wifi.h>

#define MPU6050_ADDR         0x68
#define MPU6050_SMPLRT_DIV   0x19
#define MPU6050_CONFIG       0x1A
#define MPU6050_ACCEL_CFG    0x1C
#define MPU6050_ACCEL_XOUT_H 0x3B
#define MPU6050_PWR_MGMT_1   0x6B
#define MPU6050_WHO_AM_I     0x75

#define ECG_ADC_PIN    34
#define ECG_LO_PLUS    35
#define ECG_LO_MINUS   32

// 500 Hz master grid -> ECG 250 Hz (decim 2), IMU 100 Hz (decim 5)
#define MASTER_PERIOD_MS  2
#define ECG_DECIM   2
#define IMU_DECIM   5

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

static void IRAM_ATTR samplerTask(void *arg) {
  (void)arg;
  const TickType_t period = pdMS_TO_TICKS(MASTER_PERIOD_MS);
  TickType_t last = xTaskGetTickCount();
  uint32_t tick = 0;
  uint32_t ecg_idx = 0;
  uint32_t imu_idx = 0;
  int16_t ax = 0, ay = 0, az = 0;     // held values
  bool imu_valid = false;
  char line[160];

  for (;;) {
    vTaskDelayUntil(&last, period);
    tick++;
    uint32_t now_us = micros();

    // IMU read every 5th tick (100 Hz)
    if (tick % IMU_DECIM == 0) {
      int16_t nx, ny, nz;
      if (mpu6050_read_accel(&nx, &ny, &nz)) {
        ax = nx; ay = ny; az = nz;
        imu_idx++;
        imu_valid = true;
      }
    }

    // ECG read every 2nd tick (250 Hz) — emit CSV row
    if (tick % ECG_DECIM == 0) {
      int raw = analogRead(ECG_ADC_PIN);
      int lop = digitalRead(ECG_LO_PLUS);
      ecg_idx++;

      int32_t mx = (int32_t)ax, my = (int32_t)ay, mz = (int32_t)az;
      uint32_t mag = imu_valid
                     ? (uint32_t)sqrtf((float)(mx*mx + my*my + mz*mz))
                     : 0u;
      float ecg_mv = (raw - 2048.0f) * (3300.0f / 4096.0f);

      int n = snprintf(line, sizeof(line),
        "%lu,%lu,%lu,%d,%.2f,%d,%d,%d,%lu,%d",
        (unsigned long)now_us,
        (unsigned long)ecg_idx,
        (unsigned long)imu_idx,
        raw, ecg_mv,
        ax, ay, az,
        (unsigned long)mag,
        lop);
      if (n > 0) {
        Serial.println(line);
      }
    }
  }
}

void setup() {
  Serial.begin(921600);
  delay(200);

  // CRITICAL: kill WiFi/BLE so they don't steal CPU from sampler task
  WiFi.mode(WIFI_OFF);
  btStop();

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
  Serial.printf("# MPU6050 WHO_AM_I = 0x%02X (expect 0x68)\n", who);

  if (who == 0x68 || who == 0x70) {
    mpu6050_write(MPU6050_PWR_MGMT_1, 0x00);
    delay(5);
    mpu6050_write(MPU6050_SMPLRT_DIV, 9);
    mpu6050_write(MPU6050_CONFIG, 0x01);
    mpu6050_write(MPU6050_ACCEL_CFG, 0x00);
  } else {
    Serial.println(F("# [!] MPU6050 NOT detected — continuing with IMU=0"));
  }

  Serial.println(F("# Tarang 05: ECG 250 Hz + IMU 100 Hz, master 500 Hz, core 1"));
  Serial.println(F("t_us,ecg_idx,imu_idx,ecg_raw,ecg_mv,ax,ay,az,imu_mag,lo+"));

  xTaskCreatePinnedToCore(samplerTask, "sampler", 8192, NULL, 2, NULL, 1);
}

void loop() {
  // Arduino loop idle — everything happens in samplerTask
  vTaskDelay(pdMS_TO_TICKS(1000));
}
