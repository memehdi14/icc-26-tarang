/***************************************************************************//**
 * @file 00_serial_sanity.ino
 * @brief Tarang bring-up Stage 1 — minimal ESP32 alive check.
 *
 * Purpose:
 *   - Verify USB upload works.
 *   - Verify serial monitor works.
 *   - Verify baud rate matches (115200).
 *
 * Expected output (every 1 s):
 *   [Tarang] ESP32 alive  millis=1234
 *   [Tarang] ESP32 alive  millis=2234
 *   ...
 *
 * Failure modes:
 *   - No output at all           -> wrong port, bad cable, no driver
 *   - Garbled text               -> baud mismatch (set monitor to 115200)
 *   - Upload fails               -> wrong board selected; pick "ESP32 Dev Module"
 *   - "Connecting..." then fail  -> hold BOOT button on ESP32 during upload
 ******************************************************************************/
#include <Arduino.h>

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println(F("\n[Tarang] Stage 1 — ESP32 alive check"));
  Serial.println(F("[Tarang] Board: ESP32 DevKit V1 (bring-up only, not final firmware)"));
  Serial.println(F("[Tarang] Baud: 115200. Open serial monitor at 115200."));
}

void loop() {
  Serial.printf("[Tarang] ESP32 alive  millis=%lu\n",
                (unsigned long)millis());
  delay(1000);
}
