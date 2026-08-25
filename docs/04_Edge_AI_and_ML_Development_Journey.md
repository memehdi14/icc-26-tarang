# 04. Edge AI & Machine Learning Development Journey

## 1. Problem Formulation & Clinical Context

Real-time automated arrhythmia detection on wearable battery-powered hardware requires classifying heartbeats under the **AAMI EC57** international standard:
- **$N$ (Normal Sinus):** Normal beats and bundle branch blocks.
- **$S$ (Supraventricular Ectopic Beat / SVEB):** Atrial premature beats, aberrantly conducted beats.
- **$V$ (Ventricular Ectopic Beat / VEB):** Premature Ventricular Contractions (PVCs), ventricular escape beats.
- **$F$ (Fusion Beats):** Hybrid ventricular and normal depolarization.
- **$Q$ (Unknown / Paced / Artifact):** Unclassifiable or noisy frames.

The key engineering challenge: Deploying real-time neural inference within **< 100 KB RAM**, under **< 20 ms inference latency**, on an ARM Cortex-M33 microcontroller while maintaining high sensitivity for life-threatening ventricular events ($V$).

---

## 2. Chronological ML Development Journey (`projects/tarang-ml`)

The `projects/tarang-ml` codebase contains 40+ Jupyter experiments documenting the full progression:

```
[Phase 1: Baselines & Mismatches (v1 - v4)]
   ├── 1D-CNN on MIT-BIH (360 Hz)
   └── Found hardware sampling mismatch (360 Hz vs 250 Hz hardware ADC) -> Solved via anti-aliased polyphase resampling.
         │
         v
[Phase 2: Single-Model Class Imbalance (v5 - v7)]
   ├── PhysioNet Challenge 2017 single-lead dataset exploration.
   └── Single 5-class network suffered from majority-class bias ($N > 85\%$), yielding low $S$ and $V$ recall.
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
   └── Benchmark on PTB-XL and INCART.
         │
         v
[Phase 5: Lead-I Native Adaptation & Morphology Audit (v10 - v12)]
   ├── v10: External synthetic morphology augmentation evaluated and REJECTED (caused severe hallucination on real hardware).
   └── v11-v12: Native Lead-I projection from 12-lead INCART database to match AD8232 chest electrode vector.
         │
         v
[Phase 6: Final Quantization & Embedded Deployment (v13 - v15)]
   ├── Two-stage cascade: Gate Model (40.5 KB) + SV Classifier (32.0 KB).
   ├── Int8 Post-Training Quantization (PTQ) with representative calibration.
   └── Locked threshold deployment (`GATE_THR=0.25`, `V_THR=0.60`, `S_THR=0.35`) exported to C++ byte arrays.
```

---

## 3. Dataset Engineering & Preprocessing

1. **Databases Utilized:**
   - **St. Petersburg INCART 12-Lead Arrhythmia Database:** 75 annotated 30-minute recordings (257,000 beats). Lead-I was extracted to exactly mirror the single-lead AD8232 wearable vector.
   - **PhysioNet / Computing in Cardiology Challenge 2017:** 8,528 single-lead short ECG recordings for noise and AFib rhythm benchmarking.
   - **MIT-BIH Arrhythmia Database:** Cross-validation reference.

2. **Beat Segmentation Window:**
   - Centered on detected R-peaks: **$-70$ to $+110$ samples** at 250 Hz (total **180 samples / 720 ms window**).
   - Captures complete $P$-wave onset, $QRS$ complex, and $T$-wave repolarization.

3. **Engineered Rhythm Features ($5 \times \text{float}$):**
   - `rr_pre`: Time delta to previous R-peak.
   - `rr_post`: Time delta to following R-peak.
   - `rr_local_ratio`: $\frac{rr_{pre}}{rr_{post}}$ (identifies premature coupling).
   - `rr_mean_5`: Rolling 5-beat average RR interval.
   - `rr_std_5`: Rolling 5-beat standard deviation (quantifies heart rate variability / rhythm irregularity).

---

## 4. Final Cascade Architecture (v15)

```
[180 Raw ECG Samples + 5 RR Features]
                 |
                 v
+-------------------------------------------------------------+
| STAGE 1: GATE MODEL (gate_int8.tflite - 40.5 KB)             |
| 1D-Conv(32, k=7) -> BatchNorm -> ReLU -> MaxPool           |
| 1D-Conv(64, k=5) -> BatchNorm -> ReLU -> GlobalAvgPool      |
| Concat with 5 RR Features -> Dense(32) -> Dense(1, Sigmoid) |
+-------------------------------------------------------------+
                 |
        Is Output >= GATE_THR (0.25)?
        /                           \
    NO /                             \ YES
      v                               v
[NORMAL SINUS BEAT (N)]     +-------------------------------------------------------------+
                            | STAGE 2: SV CLASSIFIER (sv_int8.tflite - 32.0 KB)           |
                            | 1D-Conv(32, k=5) -> ReLU -> MaxPool                         |
                            | 1D-Conv(64, k=3) -> ReLU -> GlobalAvgPool                   |
                            | Concat with RR Features -> Dense(32) -> Dense(2, Softmax)   |
                            +-------------------------------------------------------------+
                                      |                                   |
                             If P(V) >= V_THR (0.60)             If P(S) >= S_THR (0.35)
                                      v                                   v
                             [VENTRICULAR BEAT (V)]              [SUPRAVENTRICULAR BEAT (S)]
```

---

## 5. Architectural & Training Trade-Off Analysis ("Why This vs. Why Not That")

### 5.1 Architecture: Two-Stage Cascade vs. Single End-to-End Multiclass vs. Recurrent/Transformer Networks vs. Classical XGBoost

| Architecture Strategy | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **Two-Stage Cascade (Gate + SV) (Chosen)** | Yes | **ADOPTED** | Decouples the easy detection of normal beats ($90\%$ of all heartbeats) from the subtle morphological discrimination between $S$ (atrial) and $V$ (ventricular) ectopy. Saves battery power because Stage 2 only runs when Stage 1 flags an abnormality. |
| **Single 5-Class 1D-CNN (v5–v7)** | Yes | **REJECTED** | Suffers severe majority-class collapse ($N > 85\%$). Training loss is dominated by normal beats, causing the network to suppress rare ventricular ectopic triggers ($V$ recall $< 72\%$). |
| **Recurrent Neural Networks (LSTM / GRU) & Transformers** | Yes | **REJECTED** | Recurrent matrix operations consume $> 120\text{ KB}$ runtime RAM and require sequential step evaluations that exceed the 20ms latency deadline on Cortex-M33. |
| **Classical Manual Features + XGBoost** | Yes | **REJECTED** | Handcrafted fiducial features (Q-wave onset, S-point offset, ST elevation) fail catastrophically when noise or baseline wander shifts fiducial markers. 1D-CNN learns robust hierarchical morphological filters. |

### 5.2 Feature Input: Raw Beat Morphology (180 Samples) + 5 RR Features vs. Raw Waveform Only vs. Multi-Second Slices

| Feature Representation | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **180 Beat Samples + 5 RR Metrics (Chosen)** | Yes | **ADOPTED** | Supraventricular ectopy ($S$) has nearly identical QRS shape to normal beats ($N$); it can ONLY be reliably distinguished by premature timing (`rr_pre` shortening and compensatory pause `rr_post`). Combining morphology + timing features resolved this. |
| **Pure 1D Morphology Only (No RR)** | Yes | **REJECTED** | Model completely failed to detect Premature Atrial Contractions ($S\text{ F1} < 0.05$) because QRS morphology alone cannot indicate premature timing. |
| **Fixed 3-Second Raw ECG Slices** | Yes | **REJECTED** | Variable heart rates (40–180 BPM) cause 3s windows to contain anywhere between 2 to 9 beats, creating inconsistent spatial alignment and requiring $4\times$ larger model parameters. |

### 5.3 Data Augmentation Decision: Why Synthetic External Morphology (v10) Was REJECTED

| Experiment | Evaluated? | Decision | Finding & Hard Engineering Rationale |
| :--- | :--- | :--- | :--- |
| **v10 Synthetic Morphology Augmentation** | Yes | **REJECTED** | Synthetic GAN / affine morphology warping was tested to artificially inflate $S$ and $V$ beat counts. While training accuracy appeared higher on paper, cross-validation on real hardware showed **severe hallucination**: normal sinus beats with mild baseline curvature were falsely classified as Ventricular Ectopy ($V$). This experiment was discarded in favor of clean Lead-I INCART real-patient data. |

### 5.4 Embedded Quantization: Int8 PTQ vs. Float32 vs. Quantization-Aware Training (QAT)

| Quantization Method | Evaluated? | Decision | Rationale & Critical Trade-Offs |
| :--- | :--- | :--- | :--- |
| **Int8 Post-Training Quantization (PTQ) (Chosen)** | Yes | **ADOPTED** | Reduces model flash footprint by $75\%$ ($160\text{ KB} \rightarrow 40.5\text{ KB}$) and leverages ARM CMSIS-NN SIMD integer multiplication instructions (`__SMLAD`), speeding up inference by $3.8\times$ with $< 0.8\%$ F1 loss. |
| **Float32 Unquantized** | Yes | **REJECTED** | Requires $> 160\text{ KB}$ Flash per model and relies on software floating-point emulation or FPU cycles, doubling inference energy draw. |
| **Quantization-Aware Training (QAT)** | Yes | **REJECTED** | Added substantial training hyperparameter complexity with no statistically significant accuracy gain over representative PTQ calibration. |

---

## 6. Performance Metrics & Embedded Benchmarks

### 6.1 Validation Metrics (INCART Lead-I Test Set):
- **Normal ($N$) F1-Score:** `0.912`
- **Ventricular Ectopy ($V$) Recall (Sensitivity):** `0.918` *(Prioritized for patient safety)*
- **Ventricular Ectopy ($V$) F1-Score:** `0.567`
- **Supraventricular ($S$) F1-Score:** `0.199` *(Reported transparently due to morphological similarity to normal beats in single-lead recordings)*
- **Macro F1-Score:** `0.559` (Overall across all ectopic classes)
- **INCART Cross-Database Macro F1:** `0.713`

### 6.2 Embedded Microcontroller Benchmarks (Cortex-M33 @ 78 MHz):
- **Gate Model Footprint:** 40,576 bytes Flash (`gate_model_data.cc`).
- **SV Classifier Footprint:** 32,064 bytes Flash (`sv_model_data.cc`).
- **Total Model RAM Arena:** 18.4 KB (Tensor arena allocated in internal SRAM).
- **Execution Time:**
  - Stage 1 Gate Inference: **7.2 ms**
  - Stage 2 SV Inference: **6.1 ms**
  - Full Worst-Case Latency: **< 14.5 ms** (well within the 250 Hz beat processing deadline).
