# Why TARANG Power Optimization Is Deferred

Status: Accepted for the functional-validation build

Date: 2026-08-19

## Decision

Keep the following acquisition rates during the end-to-end integration and initial human validation phase:

| Signal | Validation rate | Reason |
| --- | ---: | --- |
| ECG | 250 Hz | Preserves the sampling rate used by the DSP, beat window, RR timing, and AI preprocessing contract. |
| MAX30102 PPG | 100 Hz | Preserves RED/IR pulse morphology for SpO2, pulse-rate, perfusion, and signal-quality calculations. |
| MPU6050 IMU | 100 Hz | Preserves motion-reference bandwidth and timing for IMU-assisted NLMS cancellation. |

Do not reduce the IMU to 20 Hz, disable per-sample PPG servicing, or otherwise change sensor timing until the complete data path has passed functional and signal-quality validation.

Power optimization remains required, but it is a separate phase after correctness is demonstrated.

## Why 20 Hz IMU Is Not Selected Now

The AI does not consume IMU samples directly. It consumes a 130-sample ECG beat window after filtering and normalization. The IMU matters because it supplies the reference used to estimate motion contamination in the ECG before beat detection and AI inference.

A 20 Hz IMU stream has a Nyquist limit of 10 Hz. Any motion content above 10 Hz is lost before firmware receives it. Interpolating 20 Hz samples onto the 250 Hz ECG timeline changes the number of samples but cannot reconstruct the missing motion information.

That creates four immediate risks:

1. Fast electrode movement may be present in ECG but absent from the NLMS reference.
2. The adaptive filter may converge slowly or estimate the wrong artifact.
3. Residual motion may create false R peaks, missed R peaks, or distorted beat windows.
4. AI receives a waveform distribution that differs unpredictably from both its training data and the unfiltered firmware path.

Keeping IMU at 100 Hz gives 50 Hz reference bandwidth and five times finer alignment with the 250 Hz ECG stream. Firmware can perform causal interpolation from 100 Hz to 250 Hz while retaining the original measurements and timestamps.

## Why PPG Remains at 100 Hz

MAX30102 RED and IR samples are used over a rolling time window, not as isolated values. The intended PPG path calculates:

- DC RED and IR levels.
- AC pulse energy for both wavelengths.
- Ratio of ratios for estimated SpO2.
- PPG pulse rate.
- Perfusion index.
- Finger presence and signal quality.
- Motion rejection using the synchronized IMU state.

Reducing the PPG rate while these calculations are still being implemented changes peak shape, window statistics, and pulse timing. That adds another variable to validation and makes failures harder to localize.

The current 100 Hz rate is retained. Invalid or motion-corrupted windows must produce an unavailable result rather than a plausible constant.

## Why FIFO Batching Is Deferred

FIFO batching can reduce MCU wakeups without reducing the physical sensor sample rate, and it remains the preferred later optimization. It is deferred because it changes interrupt behavior, FIFO pointer handling, latency, and overflow recovery at the same time that SpO2 and NLMS are being connected.

Applying batching now would make these failures difficult to distinguish:

- Sensor acquisition failure.
- FIFO pointer or rollover error.
- Timestamp reconstruction error.
- DSP algorithm error.
- BLE or dashboard transport error.

The initial validation build favors direct, observable acquisition. Once the metrics match captured reference data, batching can be introduced behind a feature switch and compared against the same test recordings.

## Why ECG Wakeup Changes Are Deferred

The ECG chain already uses LETIMER, PRS, IADC, and LDMA for autonomous acquisition. Removing the LETIMER bookkeeping interrupt and counting samples in the DMA half-completion callback is logically sound and should not alter ADC data.

It is still deferred from the correctness pass because the current priority is proving that:

`ECG DAQ -> NLMS -> DSP -> beat extraction -> AI -> clinical engine -> BLE -> Pi -> backend -> dashboard`

produces the expected samples and events. Wakeup changes will be applied after golden-vector and hardware traces make it possible to prove bit-for-bit acquisition equivalence.

## Risks of Optimizing Too Early

### Signal-distribution risk

The Gate and SV models were trained for a specific ECG preprocessing path. Changing sensor rates and enabling adaptive cancellation simultaneously can shift beat amplitude, noise texture, and timing. A model may still run successfully while producing worse classifications.

### False-cleaning risk

NLMS can remove useful ECG morphology when the motion reference is poorly synchronized or correlated with the cardiac signal. The implementation therefore keeps a raw path, a cleaned path, an automatic bypass, and suppression diagnostics.

### Clinical-display risk

A believable but invalid value is more dangerous than an unavailable value. SpO2, heart rate, and anomaly waveforms must be tagged invalid until their source window passes quality checks.

### Debugging risk

Combining power, acquisition, DSP, AI, BLE, and UI changes in one test removes the ability to identify which layer introduced a regression.

## Functional-Validation Configuration

The pre-validation build uses:

- ECG at 250 Hz.
- PPG at 100 Hz.
- IMU at 100 Hz.
- Raw ECG retained internally.
- NLMS cleaned ECG generated with timestamp-aligned IMU references.
- Automatic NLMS bypass when IMU is stale, motion is absent, ECG is saturated, or filter diagnostics are unsafe.
- Cleaned ECG used for anomaly snapshots and, after an explicit compile-time selection, DSP/AI input.
- Real PPG values only after a complete valid window.
- No hardcoded 75 bpm or 98% SpO2 presented as measurements.

## Required Validation Before Power Work

1. Confirm ECG DMA continuity and zero overruns for the complete test duration.
2. Compare raw and cleaned ECG R-peak timing and morphology.
3. Confirm NLMS does not reduce QRS amplitude beyond the agreed tolerance.
4. Compare Gate and SV outputs with NLMS bypassed and active.
5. Compare PPG pulse rate with ECG heart rate during stationary periods.
6. Compare SpO2 with a reference pulse oximeter and reject low-quality windows.
7. Confirm every clinical event arrives with all 1000 cleaned ECG samples and real beat annotations.
8. Confirm Pi reconnect, rebond, backend restart, and interrupted BLE transfer behavior.

## Later Power Phase

After the validation gates pass, optimize one change at a time:

1. Remove the ECG LETIMER CPU bookkeeping interrupt and prove identical sample counts through DMA callbacks.
2. Batch MAX30102 FIFO reads while retaining 100 Hz physical sampling.
3. Batch MPU6050 FIFO reads while retaining 100 Hz physical sampling.
4. Remove unnecessary periodic application timers.
5. Gate verbose UART output.
6. Measure EM0/EM1/EM2 residency with Silicon Labs Energy Profiler rather than relying only on application timing estimates.
7. Re-run signal and AI regression tests after every power change.

Only after those measurements should lower physical sampling rates be considered. A 20 Hz IMU mode may be suitable for idle motion detection, but it should not replace the 100 Hz reference while NLMS is actively cleaning ECG.

## Conclusion

Power optimization is postponed, not rejected. The immediate objective is a trustworthy and observable data path. Maintaining ECG 250 Hz, PPG 100 Hz, and IMU 100 Hz removes avoidable uncertainty and gives the NLMS, PPG metrics, AI cascade, and anomaly waveform the best chance of working correctly during the limited validation window.
