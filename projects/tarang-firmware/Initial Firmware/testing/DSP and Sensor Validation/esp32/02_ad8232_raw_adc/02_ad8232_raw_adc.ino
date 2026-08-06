/***************************************************************************//**
 * @file 02_ad8232_raw_adc.ino
 * @brief Tarang bring-up Stage 3 — raw AD8232 analog read on GPIO34.
 *
 * Wiring (AD8232 -> ESP32):
 *   AD8232 OUTPUT -> GPIO34  (ADC1_CH6, input-only, safe for 3.3V analog)
 *   AD8232 LO+    -> GPIO35  (optional, lead-off +)
 *   AD8232 LO-    -> GPIO32  (optional, lead-off -)
 *   AD8232 SDN    -> 3V3     (or leave floating; module usually pulls high)
 *   AD8232 GND    -> GND
 *   AD8232 3.3V   -> 3V3
 *
 * Safety:
 *   - DO NOT connect electrodes to body yet. Leave AD8232 input open.
 *   - DO NOT power ESP32 from mains-charged laptop while electrodes are on body.
 *   - This stage is signal-chain validation only.
 *
 * Expected output:
 *   [Tarang] AD8232 raw ADC on GPIO34 (12-bit, 0..4095, ~0.805 mV/LSB)
 *   raw=2048  mv=0.0   <- mid-rail with open input (good)
 *   raw=4095  mv=2640  <- rail (input saturated high)
 *   raw=0     mv=-2652 <- rail (input saturated low)
 *
 * Failure modes:
 *   - raw stuck at 0 or 4095 -> AD8232 OUTPUT pin disconnected or module not powered
 *   - raw noisy >50 LSBs with no input -> SDN low (shutdown), or bad 3V3
 *   - raw always 2048 +/- 1 -> ADC working, AD8232 quiet (good for Stage 3)
 ******************************************************************************/
#include <Arduino.h>

#define ECG_ADC_PIN    34
#define ECG_LO_PLUS    35
#define ECG_LO_MINUS   32

void setup() {
  Serial.begin(115200);
  delay(300);
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);   // 0..3.3V full-scale (~0.805 mV/LSB)
  pinMode(ECG_ADC_PIN, INPUT);
  pinMode(ECG_LO_PLUS, INPUT);
  pinMode(ECG_LO_MINUS, INPUT);
  Serial.println(F("\n[Tarang] AD8232 raw ADC on GPIO34 (12-bit, 0..4095, ~0.805 mV/LSB)"));
  Serial.println(F("idx,raw,mv,lo+,lo-"));
}

void loop() {
  static uint32_t idx = 0;
  int raw = analogRead(ECG_ADC_PIN);
  int lop = digitalRead(ECG_LO_PLUS);
  int lom = digitalRead(ECG_LO_MINUS);
  float mv = (raw - 2048.0f) * (3300.0f / 4096.0f);
  Serial.printf("%lu,%d,%.1f,%d,%d\n",
                (unsigned long)idx++, raw, mv, lop, lom);
  delay(10);
}
