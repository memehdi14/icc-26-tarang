/***************************************************************************//**
 * @file 04_max30102_plotter.ino
 * @brief Tarang bring-up — MAX30102 raw IR/RED read, Serial Plotter view.
 *
 * Library required: SparkFun MAX3010x (Install via Library Manager)
 *
 * Wiring (MAX30102 -> ESP32):
 *   VIN -> 3V3
 *   GND -> GND
 *   SDA -> GPIO21
 *   SCL -> GPIO22
 *
 * Usage:
 *   Tools -> Serial Plotter, baud = 115200
 *
 * Expected:
 *   - On first power-up / EN press: brief spike/glitch for ~100ms, then settles.
 *     This is normal LED + ADC startup transient, not a fault.
 *   - Finger OFF sensor: IR and RED both low, mostly flat with noise.
 *   - Finger ON sensor: IR jumps up significantly (tens of thousands),
 *     RED follows a similar but usually lower trend. You should see a
 *     visible pulsatile waveform (heartbeat) once finger is steady.
 *
 * Failure modes:
 *   - "MAX30102 not found" -> check wiring, check I2C scanner shows 0x57
 *   - Both IR/RED stuck at 0 -> sensor not initialized, check power
 *   - Values pinned at max/overflow -> too much ambient light, shield sensor
 ******************************************************************************/
#include <Wire.h>
#include "MAX30105.h"

MAX30105 particleSensor;

void setup() {
  Serial.begin(115200);
  delay(1000);

  Wire.begin(21, 22, 400000);

  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30102 not found -- check wiring (0x57 on I2C scanner).");
    while (1) delay(1000);
  }

  // Sensor config: LED brightness, sample avg, mode, sample rate, pulse width, ADC range
  byte ledBrightness = 60;   // 0-255
  byte sampleAverage  = 4;   // 1,2,4,8,16,32
  byte ledMode        = 2;   // 2 = Red + IR
  int sampleRate      = 100; // Hz
  int pulseWidth      = 411; // us
  int adcRange        = 4096;

  particleSensor.setup(ledBrightness, sampleAverage, ledMode,
                        sampleRate, pulseWidth, adcRange);

  delay(500); // let startup transient (the EN-press spike) settle before plotting
}

void loop() {
  long irValue  = particleSensor.getIR();
  long redValue = particleSensor.getRed();

  Serial.printf("IR:%ld,RED:%ld\n", irValue, redValue);

  delay(10); // ~100Hz
}