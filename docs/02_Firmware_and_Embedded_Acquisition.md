# 02. Firmware & Embedded Hardware Acquisition

## 1. Hardware Overview & Microcontroller Platform

The Tarang Wearable Sensor Node is powered by the **Silicon Labs EFR32MG26 (BRD2608A / BRD2709A)**:
- **Processor:** 32-bit ARM Cortex-M33 running at 78 MHz with Floating Point Unit (FPU) and DSP extensions.
- **Memory:** 3200 KB Flash, 512 KB RAM (enabling local in-memory circular buffers and TFLite tensor arenas).
- **Peripherals Utilized:**
  - **IADC (Incremental ADC):** 16-bit high-resolution differential conversion for AD8232 ECG.
  - **LETIMER (Low Energy Timer):** Precision 250 Hz hardware trigger with zero CPU wakeups.
  - **LDMA (Linked Direct Memory Access):** Autonomous ping-pong DMA transfer from IADC FIFO directly into RAM ring buffers.
  - **I2C0 & I2C1:** Fast-mode 400 kHz bus communicating with MAX30102 (PPG) and MPU6050 (6-DOF IMU).
  - **RAIL / BLE 5.2 Stack:** Silicon Labs Gecko SDK Bluetooth controller.

---

## 2. Zero-CPU Hardware Acquisition Pipeline

Standard wearable architectures wake the CPU for every ADC sample via interrupts (250 Hz = interrupt every 4 ms), preventing the MCU from entering deep sleep modes and rapidly draining battery life. 

Tarang uses an autonomous hardware peripheral chain:

```
+------------------+         PRS (Peripheral Reflex System)
|  LETIMER0 (EM2)  | ------------------------------------+
|  (250 Hz Tick)   |                                     |
+------------------+                                     v
                                             +-----------------------+
                                             |     IADC0 Module      |
                                             | - Differential Sample |
                                             | - Hardware Decimation |
                                             +-----------+-----------+
                                                         | Single Conversion Done
                                                         v
                                             +-----------------------+
                                             |  LDMA Channel 0 & 1   |
                                             |  Ping-Pong Transfers  |
                                             +-----------+-----------+
                                                         |
                                 +-----------------------+-----------------------+
                                 |                                               |
                                 v                                               v
                     +-----------------------+                       +-----------------------+
                     |   RAM Ping Buffer     |                       |    RAM Pong Buffer    |
                     | (32 Samples / 128 ms) |                       | (32 Samples / 128 ms) |
                     +-----------+-----------+                       +-----------+-----------+
                                 |                                               |
                                 +-----------------------+-----------------------+
                                                         | DMA Half/Full Interrupt (EM2 -> EM0)
                                                         v
                                             +-----------------------+
                                             |  FreeRTOS Acquisition |
                                             |  Task Processes Frame |
                                             +-----------------------+
```

### 2.1 Benefits of Zero-CPU Pipeline:
1. **CPU Sleep Ratio:** The Cortex-M33 remains in **EM2 (Deep Sleep, < 3.5 µA)** for 96.4% of every 128 ms frame interval.
2. **Deterministic Sampling:** Hardware timer triggers prevent jitter caused by FreeRTOS task scheduling or BLE radio bursts.

---

## 3. FreeRTOS Multitasking Architecture

The firmware is structured into prioritized preemptive FreeRTOS tasks:

```
Priority  Task Name            Stack Size   Periodicity / Trigger
-----------------------------------------------------------------------------
High (5)  AcquisitionTask      2048 bytes   LDMA Transfer Complete (128 ms)
Med  (4)  DspTask              4096 bytes   Triggered by Acquisition queue
Med  (3)  InferenceTask        8192 bytes   Triggered on Pan-Tompkins R-Peak
Low  (2)  BleTransmitTask      3072 bytes   GATT TX Queue Available
Low  (1)  HousekeepingTask     1024 bytes   Periodic 1000 ms (Battery/Temp)
```

### 3.1 Task Responsibilities:

1. **`AcquisitionTask`:**
   - Swaps and acknowledges LDMA ping-pong buffers.
   - Reads 100 Hz MPU6050 accelerometer vectors and MAX30102 raw Red/IR FIFO samples via I2C.
   - Synchronizes ECG, PPG, and IMU sample timestamps into a unified sensor frame.

2. **`DspTask`:**
   - Executes causal IIR bandpass filtering (0.5 – 40 Hz) on raw ECG samples.
   - Feeds tri-axial acceleration into the **NLMS Adaptive Filter** to remove skin-electrode motion baseline wander.
   - Evaluates Pan-Tompkins derivative and moving-window integration to detect QRS complexes.

3. **`InferenceTask`:**
   - Buffers 2 pre-R-peak and 2 post-R-peak RR intervals (~1.7 s window).
   - Extracts 180-sample beat morphology centered on the detected R-peak.
   - Runs TFLite Micro Int8 inference via optimized CMSIS-NN kernels.

4. **`BleTransmitTask`:**
   - Serializes filtered waveforms and AI diagnosis into GATT notification packets and pushes to the Silicon Labs Bluetooth stack.

---

## 4. Architectural Trade-Off Analysis ("Why This vs. Why Not That")

### 4.1 MCU Selection: Silicon Labs EFR32MG26 vs. ESP32 vs. STM32WB55 vs. Nordic nRF52840

| Microcontroller | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **Silicon Labs EFR32MG26 (Chosen)** | Yes | **ADOPTED** | Industry-leading EM2 deep sleep power ($<3.5 \mu\text{A}$), Peripheral Reflex System (PRS) enabling true zero-CPU hardware interconnects, ARM Cortex-M33 with DSP/FPU, 512KB SRAM for multi-model TFLite arenas, and integrated BLE 5.2 radio. |
| **Espressif ESP32-WROOM** | Yes | **REJECTED** | Excessive active power draw ($50–150\text{ mA}$), noisy on-chip ADC with poor linearity ($< 9.5 \text{ ENOB}$), lack of hardware PRS peripheral linking, requiring constant CPU wakeups. |
| **STM32WB55 (Dual-Core M4/M0)** | Yes | **REJECTED** | Inter-core IPC mailbox overhead adds complexity to real-time DSP pipelines; smaller single-bank SRAM limits simultaneous dual-model Edge AI execution. |
| **Nordic nRF52840 (Cortex-M4)** | Yes | **REJECTED** | EFR32MG26 provides ARM Cortex-M33 (ARMv8-M architecture with TrustZone and improved DSP cycles), plus greater Flash/RAM headroom (3.2MB Flash vs 1MB). |

### 4.2 Acquisition Architecture: PRS + LDMA Ping-Pong vs. Periodic ISRs vs. Polling

| Acquisition Mechanism | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **PRS + LDMA Ping-Pong (Chosen)** | Yes | **ADOPTED** | Complete hardware autonomy: LETIMER triggers IADC conversion via PRS wire, LDMA moves sample to RAM without CPU involvement. CPU wakes up only once per 32 samples (128ms), achieving 96.4% EM2 sleep time. |
| **Timer-Interrupt-Driven ISR (250 Hz)** | Yes | **REJECTED** | Forces 250 context switches per second. Context saving/restoring burns significant battery power and introduces micro-jitter during BLE transmission events. |
| **Superloop Polling** | Yes | **REJECTED** | Keeps CPU in 100% active run mode (EM0), draining the patch battery in less than 6 hours. |

### 4.3 OS Architecture: FreeRTOS vs. Bare-Metal Super-Loop vs. Zephyr RTOS

| Operating System | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **FreeRTOS (Gecko SDK Native)** | Yes | **ADOPTED** | Deterministic preemptive scheduling guarantees high-priority DSP/acquisition is never blocked by slow I2C sensor reads or BLE radio stack negotiations. |
| **Bare-Metal Super-Loop** | Yes | **REJECTED** | Long-running Edge AI neural network inference (14ms) would block real-time BLE GATT packet transmissions and I2C FIFO servicing. |
| **Zephyr RTOS** | Yes | **REJECTED** | EFR32MG26 Silicon Labs Gecko SDK hardware driver maturity and RAIL radio optimizations are officially integrated and validated on FreeRTOS. |

### 4.4 Memory Management: Fixed Ring Buffers & Static Allocation vs. Dynamic `malloc()`

| Memory Strategy | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **Static Memory & Fixed Ring Buffers (Chosen)** | Yes | **ADOPTED** | 100% deterministic memory map. Zero heap fragmentation, zero risk of `malloc` NULL pointer panics during multi-day continuous physiological monitoring. |
| **Dynamic `malloc()` / `free()` Queues** | Yes | **REJECTED** | In embedded microcontrollers running for weeks, heap fragmentation inevitably leads to allocation failures, causing system resets and clinical monitoring lapses. |

---

## 5. Flash, Memory & Fault Resilience

- **Ring Buffer Protection:** Critical memory regions use atomic pointer exchanges and mutexes to avoid race conditions between DMA and FreeRTOS.
- **Lead-Off Detection:** Monitors AD8232 `LO+` and `LO-` GPIO lines. When an electrode detaches, the DSP pipeline flags `LEAD_OFF`, muting inference to prevent false arrhythmia triggers.
- **Watchdog Timer (WDOG):** Hardware watchdog reset with 2-second timeout guarantees automatic recovery in the event of unexpected bus stalls.
