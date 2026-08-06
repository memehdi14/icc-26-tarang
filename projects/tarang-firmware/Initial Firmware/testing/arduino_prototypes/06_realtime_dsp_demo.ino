/***************************************************************************//**
 * @file 06_realtime_dsp_demo.ino
 * @brief Tarang bring-up Stage 12 — lightweight real-time DSP on ESP32.
 *
 * This is NOT the full Pan-Tompkins. It is a lightweight adaptive-threshold
 * peak detector that runs comfortably on ESP32 alongside ECG + IMU sampling.
 *
 * Pipeline (per ECG sample, 250 Hz):
 *   1. ADC read (GPIO34)
 *   2. DC removal (single-pole IIR, alpha=0.99)
 *   3. Simple bandpass (sum of LP and HP first-order — cheap approximation)
 *   4. Squared moving-window energy (~80 ms window = 20 samples)
 *   5. Adaptive threshold (peak hold with decay)
 *   6. Refractory period (250 ms = 62 samples)
 *   7. On detection: increment beat counter, update BPM EMA
 *
 * Per IMU sample (100 Hz):
 *   - Compute |a| in raw LSB
 *   - Subtract 1g baseline (16384)
 *   - Motion flag if |deviation| > 300 LSB
 *
 * Serial output (one row per ECG sample @ 250 Hz, baud 921600):
 *   t_us, ecg_raw, ecg_filt, imu_mag, motion_flag, beat_flag, bpm
 *
 * This is a bring-up demo. Final Tarang firmware uses LETIMER+IADC+LDMA on
 * EFR32MG26 and a 32-tap Q15 NLMS — this sketch validates the DSP LOGIC
 * on cheaper hardware, NOT the production timing/architecture.
 ******************************************************************************/
#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <esp_wifi.h>

// ===== Pin assignments =====
#define ECG_ADC_PIN     34
#define ECG_LO_PLUS     35
#define ECG_LO_MINUS    32

// ===== MPU6050 =====
#define MPU6050_ADDR         0x68
#define MPU6050_SMPLRT_DIV   0x19
#define MPU6050_CONFIG       0x1A
#define MPU6050_ACCEL_CFG    0x1C
#define MPU6050_ACCEL_XOUT_H 0x3B
#define MPU6050_PWR_MGMT_1   0x6B
#define MPU6050_WHO_AM_I     0x75

// ===== Timing =====
#define MASTER_PERIOD_MS  2     // 500 Hz master tick
#define ECG_DECIM   2           // 500/2 = 250 Hz ECG
#define IMU_DECIM   5           // 500/5 = 100 Hz IMU

// ===== DSP state =====
#define DC_ALPHA          0.995f
#define MWI_WINDOW        20    // 20 samples @ 250 Hz = 80 ms
#define REFRACTORY_SAMPLES 62   // 62 samples @ 250 Hz = 248 ms
#define PEAK_DECAY_ALPHA  0.995f
#define PEAK_TRACK_ALPHA  0.125f
#define INIT_THRESHOLD    50.0f

// ===== Globals (static, no malloc) =====
static float dc_state = 0.0f;
static float mwi_buf[MWI_WINDOW];
static int   mwi_idx = 0;
static float mwi_sum = 0.0f;
static float threshold = INIT_THRESHOLD;
static int   last_beat_idx = -REFRACTORY_SAMPLES;
static int   beat_count = 0;
static float bpm_ema = 0.0f;
static uint32_t last_beat_micros = 0;

// IMU held values
static int16_t imu_ax = 0, imu_ay = 0, imu_az = 0;
static bool imu_valid = false;
static bool motion_flag = false;

// ===== I2C helpers =====
static void mpu6050_write(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(reg); Wire.write(val);
  Wire.endTransmission(true);
}

static bool mpu6050_read_accel(int16_t *ax, int16_t *ay, int16_t *az) {
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(MPU6050_ACCEL_XOUT_H);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((uint8_t)MPU6050_ADDR, (uint8_t)6) != 6) return false;
  *ax = (int16_t)((Wire.read() << 8) | Wire.read());
  *ay = (int16_t)((Wire.read() << 8) | Wire.read());
  *az = (int16_t)((Wire.read() << 8) | Wire.read());
  return true;
}

// ===== DSP: single-pole DC removal =====
static inline float dc_remove(float x, float *state) {
  float y = x - *state;
  *state = *state + DC_ALPHA * y;
  // Equivalent: y[n] = x[n] - x[n-1] + alpha*y[n-1]
  // (slight variant — this one tracks mean)
  return y;
}

// Note: we skip an explicit bandpass function. The cascade of
//   DC-removal (HP ~0.5 Hz)  +  derivative + square + MWI(80ms)
// acts as a band-pass-like QRS enhancer that is cheap enough to run on
// ESP32 in real time at 250 Hz alongside I2C IMU reads.

// ===== Sampler task =====
static void IRAM_ATTR samplerTask(void *arg) {
  (void)arg;
  const TickType_t period = pdMS_TO_TICKS(MASTER_PERIOD_MS);
  TickType_t last = xTaskGetTickCount();
  uint32_t tick = 0;
  uint32_t ecg_idx = 0;
  char line[160];

  for (;;) {
    vTaskDelayUntil(&last, period);
    tick++;
    uint32_t now_us = micros();

    // IMU read every 5th tick (100 Hz)
    if (tick % IMU_DECIM == 0) {
      int16_t nx, ny, nz;
      if (mpu6050_read_accel(&nx, &ny, &nz)) {
        imu_ax = nx; imu_ay = ny; imu_az = nz;
        imu_valid = true;
      }
    }

    // ECG every 2nd tick (250 Hz)
    if (tick % ECG_DECIM == 0) {
      int raw = analogRead(ECG_ADC_PIN);
      float x_mv = (raw - 2048.0f) * (3300.0f / 4096.0f);

      // DC removal
      dc_state = DC_ALPHA * dc_state + (1.0f - DC_ALPHA) * x_mv;
      float ecg_dc = x_mv - dc_state;

      // Derivative (simple 1-sample diff)
      static float prev = 0.0f;
      float deriv = ecg_dc - prev;
      prev = ecg_dc;

      // Square
      float sq = deriv * deriv;

      // Moving-window integration (80 ms)
      mwi_sum -= mwi_buf[mwi_idx];
      mwi_buf[mwi_idx] = sq;
      mwi_sum += sq;
      mwi_idx = (mwi_idx + 1) % MWI_WINDOW;
      float mwi = mwi_sum / MWI_WINDOW;

      // IMU magnitude
      int32_t mx = imu_ax, my = imu_ay, mz = imu_az;
      float mag = imu_valid ? sqrtf((float)(mx*mx + my*my + mz*mz)) : 0.0f;
      float dev = mag - 16384.0f;
      motion_flag = (fabsf(dev) > 300.0f);

      // Adaptive threshold + refractory
      bool beat = false;
      if (ecg_idx - last_beat_idx >= REFRACTORY_SAMPLES) {
        if (mwi > threshold) {
          beat = true;
          last_beat_idx = ecg_idx;
          beat_count++;
          // Track threshold upward
          threshold = (1.0f - PEAK_TRACK_ALPHA) * threshold
                      + PEAK_TRACK_ALPHA * (mwi * 1.5f);
          // BPM EMA
          if (last_beat_micros != 0) {
            float dt_s = (now_us - last_beat_micros) / 1e6f;
            if (dt_s > 0.3f && dt_s < 3.0f) {
              float inst_bpm = 60.0f / dt_s;
              bpm_ema = (bpm_ema == 0.0f) ? inst_bpm
                                          : (0.8f * bpm_ema + 0.2f * inst_bpm);
            }
          }
          last_beat_micros = now_us;
        }
      }
      // Decay threshold
      threshold *= PEAK_DECAY_ALPHA;
      if (threshold < INIT_THRESHOLD) threshold = INIT_THRESHOLD;

      // Emit CSV row
      int n = snprintf(line, sizeof(line),
        "%lu,%d,%.2f,%.2f,%d,%d,%.1f",
        (unsigned long)now_us,
        raw, ecg_dc, mwi,
        (int)(mag),
        beat ? 1 : 0,
        bpm_ema);
      if (n > 0) Serial.println(line);

      ecg_idx++;
    }
  }
}

void setup() {
  Serial.begin(921600);
  delay(200);

  WiFi.mode(WIFI_OFF);
  btStop();

  Wire.begin(21, 22, 400000);
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
  pinMode(ECG_ADC_PIN, INPUT);

  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(MPU6050_WHO_AM_I);
  Wire.endTransmission(false);
  Wire.requestFrom((uint8_t)MPU6050_ADDR, (uint8_t)1);
  uint8_t who = Wire.read();
  Serial.printf("# MPU6050 WHO_AM_I = 0x%02X\n", who);
  if (who == 0x68 || who == 0x70) {
    mpu6050_write(MPU6050_PWR_MGMT_1, 0x00); delay(5);
    mpu6050_write(MPU6050_SMPLRT_DIV, 9);
    mpu6050_write(MPU6050_CONFIG, 0x01);
    mpu6050_write(MPU6050_ACCEL_CFG, 0x00);
  }

  // Init buffers
  for (int i = 0; i < MWI_WINDOW; i++) mwi_buf[i] = 0.0f;

  Serial.println(F("# Tarang 06: real-time lightweight DSP demo"));
  Serial.println(F("# DSP: DC-remove -> deriv -> square -> MWI(80ms) -> adaptive thr -> refractory"));
  Serial.println(F("# NOT full Pan-Tompkins. NOT clinically validated. Bring-up only."));
  Serial.println(F("t_us,ecg_raw,ecg_dc,mwi,imu_mag,beat_flag,bpm"));

  xTaskCreatePinnedToCore(samplerTask, "sampler", 8192, NULL, 2, NULL, 1);
}

void loop() {
  vTaskDelay(pdMS_TO_TICKS(1000));
}
