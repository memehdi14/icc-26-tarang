/*
  MAX30102 PPG Sensor on ESP32 - Heart Rate + SpO2 + Live Graph
  SDA -> GPIO 21
  SCL -> GPIO 22
  VIN -> 3.3V, GND -> GND

  Requires: SparkFun MAX3010x Pulse and Proximity Sensor Library
  (Library Manager -> search "SparkFun MAX3010x")
  This library ships with spo2_algorithm.h used below.

  HOW TO SEE THE GRAPH:
  Arduino IDE -> Tools -> Serial Plotter (NOT Serial Monitor)
  Set baud rate to 115200 in the dropdown at the bottom of the plotter window.
  You'll see live traces for IR, BPM, and SpO2.

  HOW TO SEE TEXT VALUES:
  Arduino IDE -> Tools -> Serial Monitor, also at 115200.
  (You can only have one of Plotter/Monitor open at a time in most IDE versions)
*/

#include <Wire.h>
#include "MAX30105.h"
#include "spo2_algorithm.h"

MAX30105 particleSensor;

#define BUFFER_SIZE 100 // ~4 seconds of data at 25 samples/sec

uint32_t irBuffer[BUFFER_SIZE];
uint32_t redBuffer[BUFFER_SIZE];

int32_t bufferLength = BUFFER_SIZE;
int32_t spo2;
int8_t validSPO2;
int32_t heartRate;
int8_t validHeartRate;

void setup() {
  Serial.begin(115200);
  delay(1000);

  Wire.begin(21, 22);

  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30102 not found. Check wiring/power.");
    while (1);
  }

  Serial.println("Place your finger on the sensor. Warming up...");

  byte ledBrightness = 60;
  byte sampleAverage = 4;
  byte ledMode = 2;      // Red + IR (needed for SpO2)
  byte sampleRate = 100; // matches ~25 effective samples/sec after averaging
  int pulseWidth = 411;
  int adcRange = 4096;

  particleSensor.setup(ledBrightness, sampleAverage, ledMode, sampleRate, pulseWidth, adcRange);

  // Fill the initial buffer
  for (byte i = 0; i < bufferLength; i++) {
    while (particleSensor.available() == false)
      particleSensor.check();

    redBuffer[i] = particleSensor.getRed();
    irBuffer[i] = particleSensor.getIR();
    particleSensor.nextSample();
  }

  maxim_heart_rate_and_oxygen_saturation(irBuffer, bufferLength, redBuffer,
                                          &spo2, &validSPO2, &heartRate, &validHeartRate);
}

void loop() {
  // Shift buffer left by 25 samples, discard oldest 25
  for (byte i = 25; i < BUFFER_SIZE; i++) {
    redBuffer[i - 25] = redBuffer[i];
    irBuffer[i - 25] = irBuffer[i];
  }

  // Take 25 fresh samples to refill the tail
  for (byte i = 75; i < BUFFER_SIZE; i++) {
    while (particleSensor.available() == false)
      particleSensor.check();

    redBuffer[i] = particleSensor.getRed();
    irBuffer[i] = particleSensor.getIR();
    particleSensor.nextSample();
  }

  maxim_heart_rate_and_oxygen_saturation(irBuffer, bufferLength, redBuffer,
                                          &spo2, &validSPO2, &heartRate, &validHeartRate);

  long latestIR = irBuffer[BUFFER_SIZE - 1];
  bool fingerDetected = (latestIR > 50000);

  // ---- Text output for Serial Monitor ----
  Serial.print("IR="); Serial.print(latestIR);
  Serial.print(" | HR=");
  Serial.print(validHeartRate ? heartRate : 0);
  Serial.print(validHeartRate ? " (valid)" : " (--)");
  Serial.print(" | SpO2=");
  Serial.print(validSPO2 ? spo2 : 0);
  Serial.print(validSPO2 ? "% (valid)" : "% (--)");
  if (!fingerDetected) Serial.print("  <-- No finger detected");
  Serial.println();

  // ---- Numeric output for Serial Plotter (labeled traces) ----
  Serial.print("IR:"); Serial.print(latestIR / 100); // scaled down so it fits on same graph
  Serial.print("\tBPM:"); Serial.print(validHeartRate ? heartRate : 0);
  Serial.print("\tSpO2:"); Serial.println(validSPO2 ? spo2 : 0);
}
