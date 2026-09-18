# 04. Edge AI & Machine Learning Development Journey

## 1. Problem Formulation & Clinical Context

Real-time automated arrhythmia detection on wearable battery-powered hardware requires classifying heartbeats under the **AAMI EC57** international standard:
- **$N$ (Normal Sinus):** Normal beats and bundle branch blocks.
- **$S$ (Supraventricular Ectopic Beat / SVEB):** Atrial premature beats (PACs), aberrantly conducted beats.
- **$V$ (Ventricular Ectopic Beat / VEB):** Premature Ventricular Contractions (PVCs), ventricular escape beats.
- **$F$ (Fusion Beats):** Hybrid ventricular and normal depolarization.
- **$Q$ (Unknown / Paced / Artifact):** Unclassifiable or noisy frames.

The core embedded challenge: Deploying real-time neural inference within **< 30 KB static RAM**, under **< 15 ms inference latency**, on an ARM Cortex-M33 microcontroller running at 78 MHz while ensuring ultra-high sensitivity ($> 90\%$) for life-threatening ventricular ectopy ($V$).

---

## 2. Chronological ML Development Journey (`projects/tarang-ml`)

The `projects/tarang-ml` repository contains 40+ Jupyter experiments documenting the systematic progression from proof-of-concept to production embedded deployment:

```
[Phase 1: Baselines & Mismatches (v1 - v4)]
   ├── 1D-CNN baseline trained on MIT-BIH (360 Hz).
   └── Discovered hardware sampling mismatch (360 Hz dataset vs 250 Hz hardware ADC) -> Solved via anti-aliased polyphase rational resampling (250/360).
         │
         v
[Phase 2: Single-Model Class Imbalance (v5 - v7)]
   ├── PhysioNet Challenge 2017 single-lead dataset exploration.
   └── Single 5-class monolithic network suffered severe majority-class bias ($N > 85\%$), yielding poor $S$ and $V$ recall (< 70%).
         │
         v
[Phase 3: Hierarchical Cascade & Dual-Head (v8.1 - v8.7)]
   ├── Decomposed problem: Stage 1 (Gate: Normal vs Abnormal) -> Stage 2 (Morphology: $S$ vs $V$).
   ├── Added rhythm features (RR intervals) to complement 1D morphology.
   └── Explored dual-head shared backbones and routing networks.
         │
         v
[Phase 4: Noise Robustness & PTB-XL Cross-Val (v9.1 - v9.5)]
   ├── Addressed label noise in PhysioNet annotations via confidence-weighted loss.
   ├── 3-phase training curriculum: Baseline -> Hard-Negative Mining -> Calibration.
   └── Validated generalization on PTB-XL and INCART.
         │
         v
[Phase 5: Lead-I Native Adaptation & Morphology Audit (v10 - v12)]
   ├── v10: External synthetic morphology augmentation evaluated and REJECTED (caused severe hallucination on real hardware).
   └── v11-v12: Native Lead-I projection from 12-lead INCART database to match AD8232 chest electrode vector.
         │
         v
[Phase 6: Production Embedded Deployment (v13 - v15)]
   ├── Two-stage cascade: Gate Model (40.5 KB Flash) + SV Classifier (32.0 KB Flash).
   ├── 130-sample ECG window (520 ms) + 4 RR features (scaled via static rr_scaler.h).
   ├── Int8 Post-Training Quantization (PTQ) with representative calibration.
   └── Locked threshold deployment (`GATE_THR=0.25`, `V_THR=0.60`, `S_THR=0.35`) exported to C++ byte arrays.
```

---

## 3. Dataset Engineering & Input Feature Pipeline

### 3.1 Databases Utilized
1. **St. Petersburg INCART 12-Lead Arrhythmia Database:** 75 annotated 30-minute recordings (257,000 beats). Lead-I was extracted to exactly mirror the single-lead AD8232 wearable vector.
2. **PhysioNet / Computing in Cardiology Challenge 2017:** 8,528 single-lead short ECG recordings for motion noise and AFib rhythm benchmarking.
3. **MIT-BIH Arrhythmia Database & AFDB:** Benchmark reference for cross-database validation.

### 3.2 Beat Segmentation Window (130 Samples @ 250 Hz)
- Centered on detected R-peaks: **$-65$ to $+65$ samples** (total **130 samples / 520 ms window**, with the R-peak aligned at index 65).
- Captures the complete QRS complex, preceding PR segment, and following ST segment/T-wave.
- Standardized via rolling z-score normalization on-device:
  $$x_{\text{norm}}(i) = \frac{x(i) - \mu_{\text{window}}}{\sigma_{\text{window}} + \epsilon}$$

### 3.3 Engineered Rhythm Features ($4 \times \text{float}$)
Morphology alone cannot distinguish Supraventricular Ectopy ($S$) from Normal ($N$) because PACs traverse the normal His-Purkinje conduction system, creating identical narrow QRS complexes. They can only be distinguished by timing:
1. `rr_prev_ms`: Time delta from previous R-peak to current R-peak (identifies prematurity).
2. `rr_mean_5_ms`: Rolling 5-beat mean RR interval (establishes patient baseline heart rate).
3. `rr_std_5_ms`: Rolling 5-beat standard deviation (captures rhythm irregularity).
4. `local_hr_bpm`: Instantaneous local heart rate derived from the current RR interval.

*Note on feature scaling:* In firmware, features are normalized using static mean/scale factors embedded in `rr_scaler.h`, avoiding dynamic allocations:
$$\text{feat}_{\text{scaled}} = (\text{feat} - \text{mean}) \times \text{scale}$$

---

## 4. Final Cascade Architecture & Production Parameters

```
[130 Raw ECG Samples + 4 Scaled RR Features]
                 │
                 ▼
+─────────────────────────────────────────────────────────────+
│ STAGE 1: GATE MODEL (gate_model_data.cc - 40,576 Bytes Flash)│
│ Input: [1, 130] ECG (int8) + [1, 4] RR (int8)               │
│ 1D-Conv(32, k=7) ──► BatchNorm ──► ReLU ──► MaxPool(2)      │
│ 1D-Conv(64, k=5) ──► BatchNorm ──► ReLU ──► GlobalAvgPool   │
│ Concat with 4 RR Features ──► Dense(32) ──► Dense(1, Sigmoid)│
│ Tensor Arena RAM: 8,192 Bytes                               │
+─────────────────────────────────────────────────────────────+
                 │
        Is P(Abnormal) >= TARANG_GATE_THRESHOLD (0.25)?
        ┌────────────────────────┴────────────────────────┐
        │ NO (< 0.25)                                     │ YES (>= 0.25)
        ▼                                                 ▼
[NORMAL SINUS BEAT (N)]         +─────────────────────────────────────────────────────────────+
(SV-Head skipped; saves power!) │ STAGE 2: SV HEAD MODEL (sv_model_data.cc - 32,064 Bytes Flash)│
                                │ Input: [1, 130] ECG (int8) + [1, 4] RR (int8)               │
                                │ 1D-Conv(32, k=5) ──► ReLU ──► MaxPool(2)                    │
                                │ 1D-Conv(64, k=3) ──► ReLU ──► GlobalAvgPool                 │
                                │ Concat with 4 RR ──► Dense(32) ──► 2 Sigmoids [P(V), P(S)] │
                                │ Tensor Arena RAM: 12,288 Bytes                              │
                                +─────────────────────────────────────────────────────────────+
                                                          │
                               ┌──────────────────────────┴──────────────────────────┐
                               ▼                                                     ▼
                      If P(V) >= 0.60                                       Else If P(S) >= 0.35
                               ▼                                                     ▼
                     [VENTRICULAR BEAT (V)]                               [SUPRAVENTRICULAR BEAT (S)]
                      (Premature Ventricular Contraction)                  (Premature Atrial Contraction)
                               │                                                     │
                               └──────────────────────────┬──────────────────────────┘
                                                          ▼ Neither threshold met
                                                [NORMAL SINUS BEAT (N)]
                                                (Gate false-positive resolved)
```

---

## 5. Mathematical Derivation: AI Duty Cycle & Deep Sleep (EM2)

Judges and clinicians frequently ask: **"Where does the 0.8% AI Duty Cycle and 99.0% EM2 Deep Sleep figure come from?"**

### 5.1 Inference Execution Profile (Measured on Cortex-M33 @ 78 MHz)
- **Stage 1 (Gate Model):** $t_{\text{gate}} \approx 7.2\text{ ms}$
- **Stage 2 (SV Head Model):** $t_{\text{sv}} \approx 6.1\text{ ms}$

### 5.2 Duty Cycle Calculation
In a standard patient at resting heart rate (60–75 BPM), one cardiac cycle occurs every $T_{\text{cardiac}} \approx 800 - 1000\text{ ms}$.
- Over $90\%$ of heartbeats are normal sinus rhythm.
- For $>90\%$ of beats, **only the Stage 1 Gate runs** ($7.2\text{ ms}$). Stage 2 is skipped completely.
- Active AI inference duty cycle:
  $$\text{Duty Cycle}_{\text{nominal}} = \frac{t_{\text{gate}}}{T_{\text{cardiac}}} = \frac{7.2\text{ ms}}{1000\text{ ms}} = 0.72\% \approx 0.8\%$$
- When an abnormal beat is encountered:
  $$\text{Duty Cycle}_{\text{abnormal}} = \frac{t_{\text{gate}} + t_{\text{sv}}}{T_{\text{cardiac}}} = \frac{7.2\text{ ms} + 6.1\text{ ms}}{1000\text{ ms}} = 1.33\%$$
- Since abnormal beats represent $< 5\%$ of typical daily monitoring, the weighted average active AI load remains **$0.75\% – 0.85\%$**.

### 5.3 Deep Sleep (EM2) Residency
Because raw ECG sampling is handled autonomously by **LETIMER + PRS + LDMA** without waking the CPU:
- The Cortex-M33 core remains in **EM2 Deep Sleep ($< 3.5\text{ }\mu\text{A}$)** during signal acquisition and inter-beat intervals.
- The CPU wakes only for brief DSP filtering ($< 0.5\text{ ms}$) and R-peak AI inference ($7.2\text{ ms}$).
- Theoretical EM2 sleep residency:
  $$\text{EM2 Residency} = 100\% - \text{Active Duty} \approx 100\% - 0.8\% = 99.2\% \implies \mathbf{99.0\%}$$
- In firmware (`tarang_ble.c`), this is tracked cumulatively in microseconds:
  $$\text{duty\_x10} = \frac{\text{ai\_time\_us} \times 1000}{\text{uptime\_us}}$$
  $$\text{em2\_sleep\_pct} = 100 - \lfloor \frac{\text{duty\_x10}}{10} \rfloor$$
- Telemetry updates this metric every **60 seconds (1 minute)** via Mode A characteristic `gattdb_analytics_ai_duty_cycle`.

---

## 6. Architectural Trade-Off Analysis ("Why This vs. Why Not That")

### 6.1 Architecture: Two-Stage Cascade vs. Single End-to-End Multiclass vs. Recurrent Networks

| Architecture Strategy | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **Two-Stage Cascade (Gate + SV) (Chosen)** | Yes | **ADOPTED** | Decouples the routine detection of normal beats ($>90\%$) from subtle morphological discrimination between $S$ and $V$. Saves $>90\%$ AI energy because Stage 2 only triggers when Stage 1 flags an abnormality. |
| **Single 5-Class 1D-CNN (v5–v7)** | Yes | **REJECTED** | Suffers severe majority-class collapse ($N > 85\%$). Training loss is dominated by normal beats, causing the network to suppress rare ventricular triggers ($V$ recall $< 72\%$). |
| **Recurrent Neural Networks (LSTM / GRU) & Transformers** | Yes | **REJECTED** | Recurrent matrix operations consume $> 120\text{ KB}$ runtime RAM and require sequential step evaluations that exceed the 20ms latency deadline on Cortex-M33. |
| **Classical Handcrafted Features + XGBoost** | Yes | **REJECTED** | Handcrafted fiducial markers (Q-onset, S-offset, ST segment) fail catastrophically during motion noise or baseline wander. 1D-CNN learns robust hierarchical morphological representations. |

### 6.2 Feature Input: 130 Beat Samples + 4 RR Features vs. Raw Waveform Only vs. Multi-Second Slices

| Feature Representation | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **130 Beat Samples + 4 RR Metrics (Chosen)** | Yes | **ADOPTED** | Supraventricular ectopy ($S$) has nearly identical QRS shape to normal beats ($N$); it can ONLY be reliably distinguished by premature timing (`rr_prev_ms` shortening) and compensatory pause. Combining morphology + timing resolved this. |
| **Pure 1D Morphology Only (No RR)** | Yes | **REJECTED** | Model completely failed to detect Premature Atrial Contractions ($S\text{ F1} < 0.05$) because QRS morphology alone cannot indicate premature timing. |
| **Fixed 3-Second Raw ECG Slices** | Yes | **REJECTED** | Variable heart rates (40–180 BPM) cause 3s windows to contain anywhere between 2 to 9 beats, creating inconsistent spatial alignment and requiring $4\times$ larger model parameters. |

### 6.3 Data Augmentation Decision: Why Synthetic Morphology (v10) Was REJECTED

| Experiment | Evaluated? | Decision | Finding & Hard Engineering Rationale |
| :--- | :--- | :--- | :--- |
| **v10 Synthetic Morphology Augmentation** | Yes | **REJECTED** | Synthetic GAN / affine morphology warping was tested to artificially inflate $S$ and $V$ beat counts. While training accuracy appeared higher on paper, cross-validation on real hardware showed **severe hallucination**: normal sinus beats with mild baseline curvature were falsely classified as Ventricular Ectopy ($V$). Discarded in favor of clean Lead-I INCART real-patient data. |

### 6.4 Embedded Quantization: Int8 PTQ vs. Float32 vs. QAT

| Quantization Method | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **Int8 Post-Training Quantization (PTQ) (Chosen)** | Yes | **ADOPTED** | Reduces model flash footprint by $75\%$ ($160\text{ KB} \rightarrow 40.5\text{ KB}$) and leverages ARM CMSIS-NN SIMD integer multiplication instructions (`__SMLAD`), speeding up inference by $3.8\times$ with $< 0.8\%$ F1 loss. |
| **Float32 Unquantized** | Yes | **REJECTED** | Requires $> 160\text{ KB}$ Flash per model and relies on software floating-point emulation or FPU cycles, doubling inference energy draw. |
| **Quantization-Aware Training (QAT)** | Yes | **REJECTED** | Added substantial training hyperparameter complexity with no statistically significant accuracy gain over representative PTQ calibration. |

### 6.5 Runtime AI Safeguards: Why AI Circuit Breaker is Monitor-Only (`TARANG_ENABLE_AI_CIRCUIT_BREAKER = 0`)

| Policy Mode | Behavior at >20% Suspicious Rate | Patient Safety Impact | Engineering Decision |
| :--- | :--- | :--- | :--- |
| **Active Bypass (`1`)** | Shuts down CNN inference; force-labels all subsequent beats as Normal ($N$). | **CRITICAL RISK:** During runs of Ventricular Tachycardia (VT) or rapid PVC bursts, the beat rate easily exceeds the 20% threshold. The circuit breaker would trip and mask the lethal arrhythmia as normal sinus rhythm! | **REJECTED** |
| **Monitor-Only (`0`)** *(Chosen)* | Evaluates and logs the suspicious beat rate window, but continues running Tier-1 & Tier-2 CNN inference for all qualifying beats. | **SAFE & RESILIENT:** High abnormal burden continues to be analyzed by the neural network, guaranteeing that genuine life-threatening ventricular ectopy is captured and alerted. | **ADOPTED** |

---

## 7. Performance Metrics & Embedded Benchmarks

### 7.1 Validation Metrics (INCART Lead-I Test Set)
- **Normal ($N$) F1-Score:** `0.912`
- **Ventricular Ectopy ($V$) Recall (Sensitivity):** `0.918` *(Prioritized for patient safety)*
- **Ventricular Ectopy ($V$) F1-Score:** `0.567`
- **Supraventricular ($S$) F1-Score:** `0.199` *(Reported transparently due to morphological similarity to normal beats in single-lead recordings)*
- **Macro F1-Score:** `0.559` (Overall across all ectopic classes)
- **Cross-Database Macro F1 (INCART + MIT-BIH):** `0.713`

### 7.2 Embedded Microcontroller Benchmarks (Cortex-M33 @ 78 MHz)
- **Gate Model Flash Footprint:** 40,576 bytes (`gate_model_data.cc`)
- **SV Classifier Flash Footprint:** 32,064 bytes (`sv_model_data.cc`)
- **Total Static Tensor Arenas:** 20.4 KB RAM (Gate: 8 KB, SV: 12 KB, static allocation, zero heap fragmentation)
- **Execution Times:**
  - Stage 1 Gate Inference: **7.2 ms**
  - Stage 2 SV Inference: **6.1 ms**
  - Full Worst-Case Latency: **< 14.5 ms** (well within the 250 Hz beat processing deadline)
