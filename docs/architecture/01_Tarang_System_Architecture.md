# TARANG — System Architecture (Mega-Document)

**Project:** Tarang · Team Ocelleon · IoT Challenge 2026
**Document Type:** Consolidated System Architecture Reference
**Merged From:** 7 source documents (DSP KB, KB v1.3/v1.4/v2.0, Architecture Resolution FINAL, Arrhythmia Pipeline Design, PAC Extraction Postmortem)
**Supersession Rule:** Where source documents conflict, **KB v2.0 (2026-07-11)** is the source of truth. KB v1.3 and v1.4 are preserved for historical context. The DSP Knowledge Base (v16, 2026-08-03) is the latest DSP reference and supersedes earlier DSP descriptions for the streaming pipeline.
**Owners:** Mahdi Namdar (ML), Kedar Nayak (firmware), Team Ocelleon

---

## Table of Contents

1. [Project Overview & Goals](#1-project-overview--goals)
2. [System Architecture (4-Tier Pipeline)](#2-system-architecture-4-tier-pipeline)
3. [DSP Pipeline](#3-dsp-pipeline)
4. [ML Pipeline](#4-ml-pipeline)
5. [Clinical Decision Engine](#5-clinical-decision-engine)
6. [Firmware Architecture](#6-firmware-architecture)
7. [Validation & Testing](#7-validation--testing)
8. [Known Issues & Limitations](#8-known-issues--limitations)
9. [Architecture Decision Records (ADRs)](#9-architecture-decision-records-adrs)
10. [Claims Register](#10-claims-register)
11. [Glossary](#11-glossary)
12. [Document History](#12-document-history)

---

## 1. Project Overview & Goals

### 1.1 What Tarang Is

Tarang is a **research-grade continuous ECG screening wearable** that performs:

1. **Beat-level morphology classification** (N/S/V) via an event-driven CNN cascade
2. **Rhythm-level arrhythmia detection** (AFib, bigeminy, VT, etc.) via a deterministic Clinical Event Engine

The system is deployed on the **Silicon Labs EFR32MG26** SoC with the **MVP hardware accelerator**, with a single wrist-worn housing and a Lead I ECG acquisition chain using IMU-assisted NLMS motion filtering.

**This IS:**
- An edge-AI wearable prototype on Silicon Labs EFR32MG26
- A beat classifier + rhythm event aggregator
- A Lead I ECG acquisition system with IMU-assisted motion filtering
- A hackathon engineering demonstrator

**This is NOT:**
- A clinical diagnostic device
- A hospital-grade monitor
- A Holter replacement (yet)
- An Apple Watch competitor

### 1.2 Project Goal (DSP v16 Reference)

Build a **causal, stateful, streaming ECG DSP pipeline** that can be ported byte-for-byte to the EFR32MG26 firmware. The DSP's job is to take raw ECG samples and produce:

1. R-peak locations (for beat window extraction)
2. 130-sample beat waveforms (centered on R-peak, 65 pre-R + 65 post-R)
3. 4 causal RR features (for the CNN model input)

The pipeline must behave **identically** whether run on a full array in Python or sample-by-sample on the EFR32. No future-looking operations. No offline-only algorithms. No mean subtraction over an entire record.

**What the DSP is NOT:** It does not classify N/S/V. That's the CNN's job. The DSP only finds beats and extracts features. The Clinical Event Engine (separate, RR-based) handles arrhythmia-level detection (AFib, VT, bigeminy).

### 1.3 Product Positioning

Per ADR-019, **Tarang is positioned as an arrhythmia detection wearable, not a beat classifier.** The CNN is the enabling technology; the Clinical Event Engine is the product. Users, doctors, and judges care about arrhythmias (AFib, VT, bigeminy), not individual beat labels.

### 1.4 Honest Baseline Targets

#### ML Minimum Deployable Baseline (hackathon demo)

| Metric | Minimum |
|---|---:|
| Patient-wise split | required |
| Leakage check | required |
| N F1 | ≥0.90 |
| V recall / sensitivity | ≥0.85 |
| V F1 | ≥0.70 |
| S recall | ≥0.30–0.40 |
| S F1 | ≥0.25–0.30 |
| Macro F1 | ≥0.60–0.65 |
| Quantized model | must run |
| Quantization drop | ≤5–8% |
| Total model size | ≤50 KB preferred (71KB accepted per ADR-016) |
| Tensor arena | measured |
| Inference latency | measured |
| AI gate | not continuous |
| False-negative audit | required for S and V |

#### Strong 9/10 ML Prototype Target

| Metric | Strong target |
|---|---:|
| N F1 | ≥0.95 |
| V recall | ≥0.95 |
| V F1 | ≥0.85 |
| S recall | ≥0.60–0.75 |
| S F1 | ≥0.50 initially, ≥0.70 stretch |
| Macro F1 | ≥0.80 |
| External dataset gap | ≤0.10–0.15 |
| Quantization drop | ≤3–5% |
| EFR32 latency | <50 ms preferred |
| AI duty at rest | <1% of beats |
| AI duty normal use | <5% of beats |
| BLE raw ECG streaming | forbidden in battery mode |

#### Long-Term Clinical-Style ML Target (future, not current sprint)

| Metric | Target |
|---|---:|
| S F1 | ≥0.85 |
| V F1 | ≥0.85 |
| External validation | mandatory |
| Prospective validation | mandatory |
| Cardiologist label review | mandatory |
| False-negative audit | mandatory |
| Risk-control documentation | mandatory |
| Calibration/reliability | mandatory |

### 1.5 The 12 Dilemmas That Defined the Architecture

Throughout the v9-v10 sprint, 12 interlocking dilemmas emerged that appeared to force compromises. The Architecture Resolution FINAL document proved each was a false dilemma. They are catalogued and resolved in [Section 9 ADRs](#9-architecture-decision-records-adrs) (specifically ADR-015, ADR-016, ADR-017, ADR-018, ADR-019) and Section 8 (Known Limitations).

The resolution in one sentence: **Lead I hardware + Lead I training + event-driven CNN + Clinical Event Engine** satisfies every constraint simultaneously.

### 1.6 Demo Day Positioning

**Strong honest demo statement:**

> Tarang validates a low-power wearable ECG pipeline: synchronized ECG and IMU acquisition, DSP filtering, R-peak detection, RR extraction, motion-aware quality scoring, and frame preparation for gated edge-AI arrhythmia screening. The current system is a research prototype and does not claim clinical diagnosis.

**Acceptable phrasings:**
- "Clinical-adjacent engineering prototype"
- "Foundation for edge-AI arrhythmia screening"
- "Validated acquisition and DSP pipeline on real sensor data"

**Avoid:**
- "Tarang diagnoses arrhythmia"
- "Hospital-ready"
- "Clinically validated"

---

## 2. System Architecture (4-Tier Pipeline)

*Source: KB v2.0 Section 1 (LOCKED); Arrhythmia Pipeline Design Executive Summary; Architecture Resolution Part 3*

### 2.1 The 4-Tier Event-Driven Pipeline (LOCKED)

```text
┌─────────────────────────────────────────────────────────────────┐
│ TIER 0: ALWAYS-ON (pure DSP, zero-CPU beyond acquisition)       │
│                                                                 │
│  ECG electrodes → AD8232 AFE → IADC @ 250 Hz (PRS+LDMA)       │
│  IMU @ 100 Hz (co-located with IN- electrode)                   │
│                                                                 │
│  NLMS adaptive filter (IMU reference, partial coverage)         │
│  Pan-Tompkins R-peak detection                                  │
│  RR interval computation                                        │
│  Rolling 30s z-score normalization                              │
│  130-sample beat window extraction (65 pre / 65 post)           │
│  7 RR features per beat                                         │
│                                                                 │
│  Cheap anomaly heuristics (Tier 0 trigger):                     │
│    - Prematurity check (rr_prev / rr_mean_5 < 0.85)            │
│    - RR irregularity (CoV > 0.12 over 30 beats)                │
│    - HR extremes (>120 or <45)                                  │
│    - Compensatory pause detection                               │
│    - Signal quality check                                       │
│                                                                 │
│  Output: beat_suspicious flag (YES/NO)                          │
│  Runs 24/7, ~40µA, EM2 sleep >99%                              │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               │ if beat_suspicious == YES
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ TIER 1: GATE CNN (~8 KB Int8 TFLite, ~12.7ms on MVP)           │
│                                                                 │
│  Input: 130-sample window + 7 RR features                       │
│  Output: P(abnormal) — single sigmoid                           │
│                                                                 │
│  If P(abnormal) ≤ 0.10 → classify as N, skip Tier 2            │
│  If P(abnormal) > 0.10 → proceed to Tier 2                      │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               │ if gate says abnormal
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ TIER 2: SV HEAD CNN (~18 KB Int8 TFLite, ~10.2ms on MVP)       │
│                                                                 │
│  Input: same 130-sample window + 7 RR features                  │
│  Output: P(V), P(S) — two independent sigmoids                  │
│                                                                 │
│  Decision:                                                      │
│    if P(V) > V_THR    → classify as V                           │
│    elif P(S) > S_THR  → classify as S                           │
│    else                → classify as N (gate was wrong)          │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               │ every beat (regardless of CNN)
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ TIER 3: CLINICAL EVENT ENGINE (~1.5 KB C code, sub-ms)         │
│                                                                 │
│  Runs EVERY beat — even when CNN was skipped                    │
│  Uses beat_class + RR intervals to detect rhythms               │
│                                                                 │
│  AFib: CoV > 0.12 AND pRR50 > 0.10 AND RMSSD > 30ms            │
│        AND not (bigeminy or v_run) — 30 beat minimum            │
│  Bigeminy: N-V-N-V-N-V pattern (6 beats)                        │
│  Trigeminy: N-N-V-N-N-V pattern (6 beats)                       │
│  Couplets: S-S or V-V (2 consecutive)                           │
│  Triplets: S-S-S or V-V-V (3 consecutive)                       │
│  V-Run: ≥3 consecutive V beats                                  │
│  VT: ≥5 V beats + HR > 100                                      │
│  SVT: ≥3 consecutive S beats (low sensitivity — S-class weak)   │
│  Sinus Tach: HR > 100, no AFib                                  │
│  Sinus Brady: HR < 60, no AFib                                  │
│  HRV: SDNN, RMSSD, pRR50 (every 30 beats)                      │
│                                                                 │
│  Output: 16-byte BLE event packet                               │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Executive Summary of the Pipeline

1. **Tier 0 (Always-on, pure DSP):** Pan-Tompkins R-peak detection + RR interval tracking + cheap anomaly heuristics. Decides whether to wake the CNN.
2. **Tier 1 (Gate CNN, ~8KB):** N-vs-abnormal classifier. Runs only on suspicious beats.
3. **Tier 2 (SV Head CNN, ~18KB):** V-vs-S classifier. Runs only when Gate says abnormal.
4. **Tier 3 (Clinical Event Engine, ~1.5KB):** Deterministic rhythm analysis. Runs every beat. Detects AFib, bigeminy, trigeminy, runs, VT, HRV.

**The CNN does NOT run continuously.** It runs on <1% of beats at rest (event-driven trigger). This preserves the 30-day battery target while still catching every clinically significant arrhythmia.

**The CNN does NOT detect AFib.** AFib is a rhythm, not a beat morphology. AFib is detected by the Clinical Event Engine via RR-irregularity analysis (Lorenz plot + CoV + pRR50). This is a published, validated technique with ≥95% sensitivity on MIT-BIH AFib Database.

### 2.3 Hardware Topology (Architecture Resolution — Final)

```
COMPACT WRIST WEARABLE (single housing, like a watch)
═══════════════════════════════════════════════════

    ┌─────────────────────────────────────────┐
    │              WRIST STRAP                │
    │                                         │
    │   ┌─────────────────────────────────┐   │
    │   │       TARIANG CASE (back)       │   │
    │   │                                 │   │
    │   │   ┌──────┐  ┌──────┐  ┌──────┐ │   │
    │   │   │ Elec │  │ Elec │  │ Elec │ │   │
    │   │   │  A   │  │ RLD  │  │  B   │ │   │
    │   │   │(RA)  │  │(Ref) │  │(LA)  │ │   │
    │   │   └──┬───┘  └──┬───┘  └──┬───┘ │   │
    │   │      │         │         │     │   │
    │   │  ┌───┴─────────┴─────────┴───┐ │   │
    │   │  │         PCB                │ │   │
    │   │  │  ┌─────────────────────┐   │ │   │
    │   │  │  │   EFR32MG26 SoC     │   │ │   │
    │   │  │  │   MVP Accelerator   │   │ │   │
    │   │  │  │   BLE 5.3           │   │ │   │
    │   │  │  └─────────────────────┘   │ │   │
    │   │  │  ┌─────────────────────┐   │ │   │
    │   │  │  │   IMU (MPU6050 or   │   │ │   │
    │   │  │  │   ICM-20648)        │   │ │   │
    │   │  │  │   CO-LOCATED with   │   │ │   │
    │   │  │  │   electrodes       │   │ │   │
    │   │  │  └─────────────────────┘   │ │   │
    │   │  │  ┌─────────────────────┐   │ │   │
    │   │  │  │   AD8232/AD8422     │   │ │   │
    │   │  │  │   Analog Front-End  │   │ │   │
    │   │  │  └─────────────────────┘   │ │   │
    │   │  │  ┌─────────────────────┐   │ │   │
    │   │  │  │   Battery (CR2032   │   │ │   │
    │   │  │  │   or LiPo)          │   │ │   │
    │   │  │  └─────────────────────┘   │ │   │
    │   │  └───────────────────────────────┘ │   │
    │   └─────────────────────────────────┘   │
    │                                         │
    └─────────────────────────────────────────┘

ELECTRODE CONFIGURATION:
  - Electrode A: back of case, left side (contacts wrist skin = RA position)
  - Electrode B: back of case, right side (contacts wrist skin = LA position)
  - RLD: back of case, center (reference/ground for noise reduction)
  - Separation: 3-5 cm (case width)
  - Lead vector: RA → LA across wrist = LEAD I

RESULT:
  - Continuous Lead I ECG (no user action required)
  - IMU co-located with electrodes (NLMS valid)
  - Compact single-housing form factor
  - No harness, no cable, no crown touch
```

*Note: KB v2.0 lists an alternate "wrist + wire to left arm" topology. The Architecture Resolution FINAL document locks the compact single-housing design as the canonical one. Both are documented for historical context; the compact single-housing variant supersedes the wire variant.*

### 2.4 Silicon Labs Hardware Utilization

| Component | Status | Evidence |
|---|---|---|
| EFR32MG26B510F3200IM68 | ✅ Target device | ML Profiler JSON |
| MVP Accelerator | ✅ Active (Conv2D, MaxPool, FC) | Profiler: 11 accel layers (Gate), 12 (SV) |
| Int8 TFLite Micro | ✅ Working | Profiler reports successful inference |
| Flash Used | 358 KB / 3200 KB (11%) | Profiler JSON |
| RAM Arena | 9 KB / 512 KB | Profiler JSON |
| Gate Inference | 12.7 ms (78 inf/sec) | Profiler JSON |
| SV Inference | 10.2 ms (98 inf/sec) | Profiler JSON |
| Total Inference | ~23 ms per abnormal beat | Sum of both |
| Model Size | ~71 KB (evidence model, NOT <50KB target) | TFLite files |

**Note:** The 71KB model size is acceptable (ADR-016). EFR32MG26 has 3200 KB flash. The self-imposed 50KB limit was unnecessary.

### 2.5 Frame Geometry (Firmware)

| Item | Value |
|---|---:|
| ECG sample rate | 250 Hz |
| ECG samples per frame | 256 |
| Frame duration | 1.024 s |
| IMU sample rate | 100 Hz |
| IMU SPI frame bytes | 512 |
| PPG samples per frame | 32 if enabled (currently disabled per ADR-017) |
| AI beat window | 130 samples around R-peak for current ML line |
| BLE anomaly packet | compact event, not raw stream |

### 2.6 Why Cascade/Gated AI Makes Sense

- N dominates beat datasets
- S and V are minority but clinically important
- DSP can reject clean normal stretches cheaply
- CNN should not run continuously
- BLE should send events only

### 2.7 What the Gate Must Guarantee

- High abnormal recall
- Especially high V recall
- Do not block dangerous beats before AI sees them

Minimum target:
```
Gate dangerous-event recall >99% eventually
```

Practical hackathon target:
```
V recall through gate ≥85%
AI run rate at rest <1% of beats
AI run rate normal day <5% of beats
```

---

## 3. DSP Pipeline

*Source: Tarang DSP Knowledge Base v16 (2026-08-03) — the authoritative streaming DSP reference; supplemented by KB v1.3 Section 6-8 where applicable.*

### 3.1 Architecture (Single-Sample Step Functions)

Per the spec's structural rule: every stateful block is implemented as **one single-sample step function** with explicit `(input, state) → (output, new_state)` signature. `process_frame` and `process_record` are loops over `process_sample` — no vectorized sibling exists.

This design decision means the Python code transcribes directly to C: the state struct becomes a C struct, the loop structure is identical, and there's no "translation" step that can introduce subtle bugs.

### 3.2 Processing Chain

```
Raw ECG (250 Hz)
    ↓
Input sanitization (NaN/Inf → 0)
    ↓
Morphology bandpass (0.5–40 Hz, SOS Butterworth, order 4)
    ↓
Optional 50 Hz notch (default OFF — config-gated)
    ↓
NLMS bypass (default — no IMU on public datasets)
    ↓
    ├── Morphology branch:
    │     Rolling z-score normalization (30s window, ring buffer + running sums)
    │     → morphology ring buffer (for recentering + window extraction)
    │
    └── Detection branch:
          QRS bandpass (5–15 Hz, SOS Butterworth, order 2)
          → 5-tap derivative: (x[n] + 2x[n-1] - 2x[n-3] - x[n-4]) / (8T)
          → Squaring
          → Moving-window integration (N=38, ~150ms)
          → Adaptive threshold (SPKI/NPKI/TH1/TH2)
          → Refractory (50 samples = 200ms)
          → Search-back (gamma=1.66 × recent RR mean)
          → T-wave rejection (slope ratio)
          ↓
    Candidate recentering (±15 samples on morphology signal)
    ↓
    Wait for 65 post-R samples
    ↓
    Extract 130-sample beat window
    ↓
    Compute 4 causal RR features
    ↓
    Emit BeatPacket
```

### 3.3 Frozen Parameters

| Parameter | Value | Rationale |
|---|---|---|
| Target sample rate | 250 Hz | Matches v15 model training |
| Beat window | 130 samples | 65 pre-R + 65 post-R (R at index 65) |
| Morphology bandpass | 0.5–40 Hz, order 4 | Standard ECG bandwidth |
| QRS bandpass | 5–15 Hz, order 2 | Pan-Tompkins emphasis band |
| MWI window | N=38 samples (~152ms) | Standard Pan-Tompkins integration |
| Refractory | 50 samples (200ms) | Prevents duplicate detection |
| Recenter search | ±15 samples (60ms) | Spec 5.10 |
| Detection delay correction | 29 samples | Cumulative group delay of Stages A-D at 10 Hz = 28.38, ceil = 29 |
| RR features | 4 (frozen order) | `[rr_prev_ms, rr_mean_5_ms, rr_std_5_ms, local_hr_bpm]` |
| NLMS mode | bypass | No synchronized IMU on public datasets |
| Notch | disabled | Config-gated, enable only if 50 Hz residual demonstrated |

> **Historical note:** KB v1.3 referenced "7 RR features per beat." The v16 DSP reference freezes the order to 4 causal features (`[rr_prev_ms, rr_mean_5_ms, rr_std_5_ms, local_hr_bpm]`). Where older sections reference 7, the 4-feature set should be considered canonical for the streaming DSP path; 7 was a superset that included non-causal statistics later dropped.

### 3.4 Key Engineering Decisions & Their Rationale

#### 3.4.1 Detection Delay Correction (29 samples)

The detection branch (QRS bandpass → derivative → squaring → MWI) introduces cumulative group delay:
- Stage A (QRS bandpass at 10 Hz): 7.88 samples
- Stage B (derivative): 2.00 samples
- Stage C (squaring): 0.00 samples
- Stage D (MWI N=38): 18.50 samples
- **Total: 28.38 samples**

The MWI peak lags the true QRS by ~28 samples. Before recentering, we subtract 29 (= ceil(28.38)) from the MWI candidate to get the approximate QRS location, then search ±15 samples for the morphology peak.

**Validated across 10 QRS morphologies** (narrow/wide, upright/inverted, PVC-like) and 4 heart-rate contexts (40–200 bpm). Empirical delay range: [29, 33] samples. Max deviation from 29: 4 samples. Margin to ±15 window: 11 samples. No widening of search radius needed.

#### 3.4.2 Signal-Specific Peak Finders

Three instances of the peak-finder trap were caught and fixed:

| Iteration | Where | Bug | Fix |
|---|---|---|---|
| v1 | Stage A peak finder | `argmax(\|out_A\|)` picked ring peaks on notched PVCs | First-significant-local-max of \|signal\| above 50% of window-global-max |
| v2 | Stage D peak finder | First-significant-local-max picked saddle/plateau on wide PVC @ HR=200 | Global argmax (MWI is always-positive, monotonic-decaying) |
| v3 | SPKI/NPKI | Rising-edge detection fired too early, invalidating 29-sample correction | Local-max via downward zero-crossing of MWI derivative |

**Standing rule:**
- Signed signals (bandpass output, morphology post-NLMS) → **first-significant-local-max**
- Positive monotonic signals (MWI output, post-squaring) → **global argmax**

#### 3.4.3 Hysteresis on Peak Detection (1% of prev_val)

Without hysteresis, sample-to-sample noise on the MWI plateau causes multiple spurious peak detections per QRS. Fix: `peak_detected = val < prev_val - max(0.01 * |prev_val|, 1e-6)`.

**Watch-item for firmware:** The 1% constant was validated on synthetic test signals only. On real INCART data, watch for over-detection (precision drops — hysteresis too small) or under-detection (recall drops — hysteresis too large).

#### 3.4.4 Refractory-Filtered Search-Back Candidates

Without this filter, the sample immediately after an accepted peak gets buffered as a search-back candidate. Later, search-back re-accepts it as a duplicate. Fix: skip candidates within the refractory window of the last accepted peak.

### 3.5 The Root Cause: SPKI Lock-In from MWI Startup Transient

#### 3.5.1 The Problem

On 18 of 75 INCART records, the detector achieved **0.000 recall** — not a single beat detected in 30 minutes. On 5 more records, recall started high then collapsed mid-record.

#### 3.5.2 The Mechanism

1. MWI ring buffer starts empty (all zeros)
2. First samples produce huge MWI values (ring buffer hasn't filled, so averages are skewed by the filter startup transient)
3. The first "peak" detected by the adaptive threshold is this transient spike (e.g., MWI=9387 on I39)
4. `SPKI = 0.125 × 9387 = 1173` (set from transient, not from real QRS)
5. `TH1 = NPKI + 0.25 × (1173 - NPKI) ≈ 423` (way too high)
6. Real QRS peaks produce MWI ~200–300, never exceed TH1=423
7. No peaks detected → SPKI never updates → **stuck forever**
8. The 0.125/0.875 EMA weighting means SPKI adapts very slowly even if a few peaks sneak through

#### 3.5.3 The Evidence

**Broken records (SPKI frozen across 20 minutes):**
```
I27:  SPKI = 485.7 at 1min → 485.7 at 5min → 485.7 at 10min → 485.7 at 20min  (recall=0.000)
I38:  SPKI = 5110.0 — never moves  (recall=0.000)
I39:  SPKI = 991.7 — never moves  (recall=0.000)
I73:  SPKI = 278.1 — never moves  (recall=0.000)
```

**Working records (SPKI adapts normally):**
```
I06:  SPKI = 180.1 at 1min → 184.8 at 5min → 179.1 at 10min → 206.3 at 20min  (recall=0.984)
I07:  SPKI = 208.2 → 202.3 → 160.3 → 172.1  (recall=0.984)
```

**Correlation:** `recall vs SPKI_final = -0.3938` (higher SPKI → lower recall)

**Drift records (same mechanism triggered mid-record):**
```
I57:  SPKI = 61.9 at 1min → 56.1 at 5min → 2988.8 at 10min → recall drops from 0.89 to 0.00
I15:  SPKI = 38.8 at 10min → 1351.4 at 20min → recall drops from 0.99 to 0.00
```

#### 3.5.4 Why the Existing Search-Back Didn't Save These Records

Search-back triggers when `(idx - last_R) > gamma × recent_rr_mean`. But `recent_rr_mean` is computed from previously accepted peaks. If the very first "peak" was the poisoning spike, no valid RR intervals exist, so `recent_rr_mean = 0`, and the trigger condition `> 1.66 × 0` is never satisfied. The escape hatch itself depends on having had a prior valid peak.

### 3.6 The Fix (3 Mechanisms)

#### 3.6.1 Startup Delay (500 samples / 2 seconds)

For the first 500 samples, no peaks are accepted. MWI values are collected. After 500 samples:
- `SPKI = np.percentile(mwi_values, 95)` (robust to transient spikes — not max)
- `NPKI = np.median(mwi_values)` (noise floor)

This prevents the MWI startup transient from being accepted as a signal peak.

#### 3.6.2 SPKI Ceiling (rolling median/MAD)

A rolling median and MAD of the MWI signal are maintained independently of peak detection:
- `robust_amp = mwi_median + 3 × mwi_mad` (covers ~99.7% of signal)
- `spki_ceiling = 5 × robust_amp`
- If SPKI ever exceeds the ceiling, it's clamped: `SPKI = min(SPKI, spki_ceiling)`

This prevents a single anomalous MWI spike (motion artifact, filter transient, noise burst) from poisoning the threshold for the rest of the record.

#### 3.6.3 Hard Timeout (750 samples / 3 seconds)

If no peak is detected for 3 seconds — **independent of `recent_rr_mean`** — TH1 is forced down:
- `th1_floor = 0.5 × robust_amp`
- `TH1 = min(TH1, th1_floor)`
- `SPKI = min(SPKI, robust_amp × 2.0)`

This is the escape hatch that doesn't depend on ever having had a valid prior peak. It rescues both the startup-frozen records AND the mid-record drift records.

#### 3.6.4 Test Results (7 records, before → after)

| Record | Before | After | SPKI before → after |
|---|---|---|---|
| I03 | 0.001 | **0.982** | 348 → 48.8 |
| I27 | 0.000 | **0.687** | 485 → 19.5 |
| I39 | 0.000 | **0.969** | 991 → 45.5 |
| I01 | 0.859 | 0.859 | 338 → 338 (unchanged) |
| I05 | 0.918 | **0.959** | 32 → 32 (improved) |
| I06 | 0.984 | 0.984 | 241 → 241 (unchanged) |
| I40 | 0.985 | 0.985 | 66 → 66 (unchanged) |

**3 previously-broken records now work. Working records unaffected.**

### 3.7 V (PVC) Recall — Measured, Not Assumed

#### 3.7.1 The Original Hypothesis (Disproved)

The I01 single-record test initially suggested MWI peak merging (closely-coupled PVC energy absorbed into the preceding normal beat's MWI peak within <250ms coupling interval) as the cause of low V recall.

#### 3.7.2 The Actual Data (from 75-record diagnostic)

```
Coupling-interval buckets for missed V beats:
  < 200ms (refractory blocking):   0 (0.0%)
  200-250ms (MWI overlap):         0 (0.0%)
  >= 250ms (longer separation):  2701 (100.0%)
```

**100% of missed V beats have coupling interval ≥ 250ms.** The "MWI merge" hypothesis is disproved as the dominant cause. The V recall problem is the same SPKI lock-in bug affecting N recall — once that's fixed, V recall should improve substantially.

#### 3.7.3 Gate Decision

If ≥70% of misses fall under 250ms after the fix → known limitation (MWI structural limit) with a soft floor baseline. If <70% → it's a bug, gate on it. The post-fix coupling-interval analysis (from the 75-record re-run) will determine which.

#### 3.7.4 Deployment Strategy for V (PVC) Detection

Even after the SPKI fix, beat-level V detection may remain weaker than N (PVCs have wider, notched QRS morphology that produces different MWI characteristics). The deployment strategy:

1. **Annotation-centered oracle extraction** for V/S training data — the detector doesn't need to find every PVC for the CNN to learn PVC morphology from real examples
2. **Clinical Event Engine (RR-irregularity-based)** as the primary real-world PVC-flagging mechanism — operates on RR interval patterns, not per-beat QRS energy
3. **Document the tradeoff** with real numbers once post-fix validation is complete

### 3.8 Window-Center Alignment (XQRS vs Pan-Tompkins)

v15's Gate/SV models were trained on beat windows centered by XQRS (offline detector). v16's Pan-Tompkins (causal, streaming) places R-peaks at slightly different sample indices. If the offset is too large, the 130-sample windows won't match what the model was trained on.

#### 3.8.1 Results (from 75-record run)

```
Matched peaks: 7047
Mean offset: +1.93 samples (+7.73ms)
Std: 1.49 samples (5.98ms)
P5: +1.00, P95: +3.00
Retrain risk: NO (mean offset <= 5 samples = 20ms)
```

**The models do NOT need retraining.** The offset is well within the ±15-sample recenter window.

### 3.9 Full 75-Record Diagnostic Results (Pre-Fix)

#### 3.9.1 Aggregate (before fix)

| Metric | Value |
|---|---|
| Precision | 0.9385 |
| Recall | 0.3256 |
| N recall | 0.3414 |
| S recall | 0.6393 |
| V recall | 0.1736 |
| Records broken (recall < 0.10) | 18 |
| Records drifting (recall collapses mid-record) | 5 |
| Records working (recall ≥ 0.50) | 52 |

#### 3.9.2 Broken Records

`I03, I04, I13, I14, I24, I27, I28, I31, I32, I37, I38, I39, I43, I56, I60, I63, I66, I73`

All have SPKI frozen at startup transient value (never adapts). All have drift=+0.000 (SPKI identical at every checkpoint).

#### 3.9.3 Drift Records

`I12, I15, I18, I57, I64` — recall collapses mid-record when SPKI runs away after an anomalously large MWI value.

#### 3.9.4 Expected Post-Fix

- 18 broken records → should drop to ~0–2 (I27 partial at 68.7% may need further investigation)
- 5 drift records → hard timeout should rescue all 5
- N recall → 0.90+ (from 0.34)
- V recall → substantial improvement (from 0.17)
- 52 working records → unaffected (fix only clamps outliers, doesn't change normal operation)

### 3.10 DSP Standing Engineering Rules

1. **No filtfilt** — causal SOS only
2. **No whole-record mean subtraction** — causal rolling normalization only
3. **No state reset at frame boundaries** — only on explicit `.reset()`
4. **No XQRS** — Pan-Tompkins only (causal, streamable)
5. **No pseudo-labels** — INCART real annotations only for S/V, PTB-XL/CPSC NSR-tagged for N
6. **No future RR intervals** — 4 causal features only
7. **No architecture changes** — v16 isolates DSP, not model
8. **Fail loudly** — no bare `except: pass`
9. **Save deterministic manifests** — config, hashes, seeds, package versions
10. **Fresh-process verification** — clear `__pycache__`, use `python -B`, verify file modification time before trusting test results
11. **File-write-then-Read** — don't trust Bash stdout capture for file-content claims (ANSI escape stripping can corrupt output)
12. **Investigate, don't adjust** — trace the actual mechanism before tuning thresholds

### 3.11 DSP File Inventory

| File | Purpose | Status |
|---|---|---|
| `tarang_dsp_reference.py` | DSP module (1467 lines) | Fixed (startup delay + SPKI ceiling + hard timeout) |
| `Tarang_DSP_Validation.ipynb` | Validation notebook (19 cells) | Updated with all fixes |
| `dsp_failure_diagnostic.py` | 75-record diagnostic script | Working |
| `test_phase1_v2.py` | Block-level unit tests (26 tests) | All PASS |
| `test_phase2.py` | Assembled pipeline tests (5 tests) | All PASS |
| `test_phase2_regressions.py` | Bug regression tests (3 tests) | All PASS (each FAILS if fix reverted) |

### 3.12 DSP Remaining Path to Deployment

1. **Re-run full 75-record diagnostic with fixed DSP** — confirm N recall ≥ 0.90, 0 broken records
2. **Re-run coupling-interval analysis** — determine if V recall is now a known limitation or a bug
3. **Generate golden vectors** (raw → filtered → normalized → detector energy → refined peak) from the fixed pipeline
4. **Port to firmware C** — one DSP stage at a time, checking each against its golden vector
5. **Integrate with frozen v15 model** — confirm window geometry, feature order, scaling match
6. **Bench test on hardware** — known ECG strip through full chain
7. **On-body testing** — only after bench test looks sane

---

## 4. ML Pipeline

*Source: KB v2.0 Section 2; KB v1.4 Section 29 (v10 negative result); KB v1.3 Section 9 (ML history).*

### 4.1 Current State: v9.3 Rebuild (Lead II, MIT-BIH)

| Metric | Value | AAMI Target | Status |
|---|---:|---:|---|
| N F1 | 0.912 | — | Strong |
| V F1 | 0.567 | — | Moderate |
| V Recall | 0.918 | ≥0.85 | ✅ PASSING |
| S F1 | 0.199 | — | Weak (structural ceiling) |
| S Recall | 0.157 | ≥0.40 | ❌ FAILING |
| Macro F1 | 0.559 | — | Below target |
| INCART Macro F1 | 0.713 | — | Decent generalization |

### 4.2 v8.7 → v9.4 Experiment History (Detailed Log)

*This is the imported post-hardware-validation sprint log from KB v1.3 Section 23.*

**Date range:** 2026-07-02 sprint (post hardware validation)
**Notebooks covered:** `tarang_v8_7_routing_fix.ipynb`, `tarang_v9_diagnostics.ipynb`, `tarang_v9_1.ipynb`, `tarang_v92_label_noise.ipynb`, `tarang_v93_cleaned_retrain.ipynb`, `tarang_v94_three_phase.ipynb`

**Context:** At the start of this sprint, v8.6 was the best recorded model. The sprint objective was to reach clinical relevance (AAMI targets: S recall ≥40%, V recall ≥85%) in time for hardware integration and competition submission.

#### 4.2.1 Open Questions Closed (from hardware validation)

- **130 vs 256-sample input contract:** CLOSED. ML pipeline uses 130-sample windows at 250 Hz (520ms). The 256-sample frames from the ESP32 bring-up logger must be trimmed to 130 samples centered on the R-peak before being fed to `tarang_ai_process()`.
- **WHO_AM_I mismatch:** ACTIVE BLOCKER. Production SLCP specifies ICM-20648 (WHO_AM_I = 0xE0); bring-up hardware reported MPU6500 (WHO_AM_I = 0x70); `tarang_nlms.c` checks for 0x68 (MPU6050). All three differ. Must be resolved before production flash.
- **`tarang_ai_process()` must consume `ecg_clean`, not raw ECG.** Confirmed by hardware validation: bandpass+notch+NLMS removes 32% of noise power.

#### 4.2.2 v8.7 — Routing Distribution Fix

| Metric | v8.6 | v8.7 | Δ |
|---|---|---|---|
| N recall / F1 | 69.6% / 0.817 | 83.8% / 0.902 | +14.2pp / +0.085 |
| S recall / F1 | 18.5% / 0.083 | 17.8% / 0.170 | −0.7pp / +0.087 |
| V recall / F1 | 93.9% / 0.453 | 89.3% / 0.559 | −4.6pp / +0.106 |
| V precision | 29.9% | 40.7% | +10.8pp |
| Macro F1 MIT-BIH | 0.451 | 0.543 | +0.092 |
| Macro F1 INCART | 0.375 | 0.538 | +0.163 |
| INT8 quantization | Crashes (RESHAPE) | Works, <0.10% drop | Fixed |

**Three changes bundled (cannot attribute individually):**

1. Gate threshold: silent-fallback-to-0.10 replaced with deliberate selection. Chose thr=0.70 — in hindsight over-optimized N precision, collapsed S-at-gate recall to 37.6%. Design error in objective function, corrected in v9.
2. SV N hard-negative mining introduced (N_SHARE_TARGET=0.35). Root cause of v8.6 V precision collapse (0.13–0.30): SV head trained on ~5% N population, deployed into ~85% N stream. N mining gave the head real N-rejection signal.
3. TFLite rep-dataset key-by-name fix. Positional list yielding caused 7-element RR tensor to land in 260-element ECG slot → `(7 != 260) RESHAPE` crash. Fixed by yielding `{'ecg_input': ..., 'rr_input': ...}`.

**OPEN QUESTIONS from v8.7:** Flash budget 75 KB vs 50 KB target (parked). Gate thr=0.70 needs S floor in objective.

#### 4.2.3 v9 Diagnostics

**Joint Threshold Sweep:** 25×17×17 = 7,225 combinations on v8.7 val (4 records, ~47 S beats). Best: gate=0.700, V=0.15, S=0.60 → val Macro F1=0.627, S recall=0.192.

Patient-level bootstrap (50 resamples, 4 patients): gate_thr std=0.244, macro_f1 std=0.076. **Verdict: unstable. 4 val patients is insufficient for threshold selection.** The bootstrap confirmed instability rather than providing a CI.

**Per-Patient S Regime (v9 model, MIT-BIH test, 26 test patients):**

| Regime | Count |
|---|---|
| both_low (recall AND precision low) | 11 patients |
| both_ok | 6 patients |
| no_target (≤2 S beats) | 6 patients |
| low_precision_only | 2 patients |
| low_recall_only | 1 patient |

Mean S recall: 0.116. Mean S precision: 0.142. Failure is distributed across 11 patients — not concentrated in 2–3. Cannot be fixed by patient exclusion.

**Train S Distribution:** MIT-BIH S beats in 18 training records are concentrated in 2 records: mitbih_232 (1382), mitbih_222 (209). Eight records have 0 S beats. 3-fold CV is therefore inherently imbalanced (Fold 0: 1416 S, Fold 1: 239 S, Fold 2: 40 S). MIT-BIH alone cannot support reliable S CV — SVDB is essential.

**v9.1 Overnight Batch — All Variants Failed:**

| Experiment | Δ S F1 | Notes |
|---|---|---|
| RR zeroed | −0.022 | Val showed +0.295 jump — val/test divergence; val unreliable at 47 S |
| RR branch removed | −0.064 | Same val/test divergence |
| Decoupled N-mining (train@0.20, infer@0.70) | −0.171 → S F1=0.000 | Self-inflicted train/inference mismatch. Confirms core lesson. |
| Gate 2× capacity | −0.161, V recall→45.5% | Bigger gate overfit; became worse router |
| Window 200 samples (rushed) | −0.018 | Undertrained, not a fair comparison |

**LESSON LEARNED:** Val with ~47 S beats is not a reliable signal for any decision. RR-removal looked like a breakthrough on val and was a regression on test. Every architectural change must be verified on held-out test before reporting.

#### 4.2.4 v9.2 — Quantitative Label Noise Analysis

**Test S beats (n=961), prematurity index analysis:**

| Category | Count | % |
|---|---|---|
| genuinely_premature (<0.85) | 451 | 46.9% |
| mildly_premature (0.85–0.95) | 115 | 12.0% |
| not_premature (0.95–1.05) | 340 | 35.4% |
| late_escape (>1.05) | 55 | 5.7% |
| **Suspicious (not_prem + escape)** | **395** | **41.1%** |

Raw symbols: 79.6% are 'A' (atrial premature), 14.7% 'a' (aberrant atrial), 5.5% 'J' (junctional), 0.2% 'S'. Only 2 of 961 test "S" AAMI beats carry a raw 'S' annotation.

**Critical patient — mitbih_207:** 107 S beats, 85.0% not premature by RR criterion, mean prematurity index 0.993. These are not supraventricular premature beats by the primary RR criterion.

**Re-evaluation with cleaned S sets:**

| Set | n_S | S recall | S F1 | Macro F1 |
|---|---|---|---|---|
| Original | 961 | 0.135 | 0.171 | 0.581 |
| Strict clean (prem<0.95) | 566 | 0.154 | 0.155 | 0.576 |
| Very strict (prem<0.85) | 451 | 0.160 | 0.143 | 0.572 |

**INTERPRETATION:** Label noise is real (41.1% suspicious). But cleaning does not improve S F1 — the model is also failing on genuinely premature S beats. Both problems coexist independently.

#### 4.2.5 v9.3 — Cleaned Label Retrain

Cleaning threshold 0.95 (removes 395/961 test S, 3285/13889 train S). Retrain from scratch.

**Decisive comparison:**

| Configuration | Macro F1 | S F1 | S recall | V F1 | n_S |
|---|---|---|---|---|---|
| v9 / original test | 0.5806 | 0.171 | 0.135 | 0.638 | 961 |
| v9 / cleaned test | 0.5759 | 0.155 | 0.154 | 0.638 | 566 |
| v9.3 / original test | 0.5378 | 0.138 | 0.093 | 0.567 | 961 |
| v9.3 / cleaned test | 0.5592 | **0.199** | 0.157 | 0.567 | 566 |

Fair comparison (v9.3 cleaned vs v9 original): S F1 +0.028, Macro F1 −0.021, V F1 −0.071. Label cleaning provides modest S gain at the cost of V.

#### 4.2.6 v9.4 — Three-Phase Systematic Evaluation

**Phase A — Cleaning Threshold Sweep:**

| Threshold | n_test_S | test_S_F1 | test_S_rec | test_Macro_F1 |
|---|---|---|---|---|
| 0.85 | 451 | 0.178 | 0.162 | 0.552 |
| **0.95** | **566** | **0.199** | **0.157** | **0.559** |
| 1.05 | 906 | 0.131 | 0.098 | 0.536 |

Best: threshold 0.95. Loose cleaning (1.05) harms performance.

**Phase B — 3-Fold CV Stability (18 train patients, cleaned):**

| Fold | gate_thr | macro_f1 | S recall | n_S |
|---|---|---|---|---|
| 0 | 0.150 | 0.975 | 0.961 | 736 |
| 1 | 0.150 | 0.909 | 0.751 | 209 |
| 2 | 0.200 | 0.987 | 1.000 | 40 |

Gate threshold now stable across folds (spread 0.050 vs 0.600 in v8.7 bootstrap). V/S threshold spread ±0.10 is acceptable. Note: fold macro_f1 values are within-fold val numbers, not test-comparable.

**Phase C — Window 200 Samples (incomplete SVDB):**

Result: S F1 = 0.000, Macro F1 = 0.583, V F1 = 0.777.

**CRITICAL NOTE:** Multiple svdb_8xx records missing from local filesystem (`[Errno 2] No such file or directory` for svdb_813 through svdb_833 and others). The 200-sample model had drastically fewer S training examples than the 130-sample baseline. **S collapse to zero is a data availability artifact, not evidence against larger windows. This experiment must be re-run with complete SVDB.**

**Final Summary Table:**

| Experiment | Macro F1 | S F1 | S recall | V F1 |
|---|---|---|---|---|
| v9 baseline (noisy) | 0.5806 | 0.171 | 0.135 | 0.638 |
| v9.3 / thr0.95 | 0.5592 | **0.199** | 0.157 | 0.567 |
| Phase A / thr0.85 | 0.5518 | 0.178 | **0.162** | 0.565 |
| Phase A / thr0.95 | 0.5592 | 0.199 | 0.157 | 0.567 |
| Phase A / thr1.05 | 0.5358 | 0.131 | 0.098 | 0.568 |
| Phase C / window200 | 0.5829 | 0.000 | 0.000 | 0.777 |

**Best S F1 in any experiment: 0.199 (on cleaned test of 566 beats). AAMI S recall target ≥40%: not met. Best achieved: 16.2%.**

#### 4.2.7 What We Now Know About S (Evidence-Based)

1. 41.1% of test S beats fail the primary RR-based prematurity criterion — annotation artifacts from AAMI remapping.
2. The model also fails on genuinely premature S beats (S recall = 15.7% on prem<0.95 subset).
3. S failure is distributed across 11/26 test patients — not fixable by patient exclusion.
4. Gate routing is not the bottleneck: ~9% of S beats lost at Gate, ~72% reach SV head and still get missed.
5. The SV head CAN learn S with enough clean signal: 3-fold CV Fold 0 achieved S recall = 0.961 with 736 clean S beats.
6. Window 200-sample experiment was confounded by missing SVDB records — no conclusion about window size is possible from Phase C.
7. RR features contribute to test performance — their removal hurt test despite val appearing to show improvement.

### 4.3 v10 External Augmentation — Honest Negative Result

*Source: KB v1.4 Section 29. Status: COMPLETE — v10 REJECTED, v9.3 remains production baseline. Date: 2026-07-06 to 2026-07-07. Experiments run: 4 (v9.3 baseline + 3 v10 variants).*

#### 4.3.1 What Was Tested

Three v10 variants, each retraining ONLY the SV head (gate frozen from v9.3) with external PAC beats from PTB-XL (398 records, SNOMED-CT 284470004) and CPSC2018 (616 records, REFERENCE.csv / SNOMED):

| Variant | External beats | Lead | External proportion of S |
|---|---:|---|---:|
| v10a (30%, lead I) | 4,693 | Lead I (channel 0) | 30.7% |
| v10b (10%, lead I) | 1,060 | Lead I (channel 0) | 9.1% |
| v10c (10%, lead II) | 1,060 | Lead II (channel 1) | 9.1% |

#### 4.3.2 Results — All Three Failed

| Metric | v9.3 (baseline) | v10a (30%, lead I) | v10b (10%, lead I) | v10c (10%, lead II) |
|---|---:|---:|---:|---:|
| **S F1** | **0.199** | 0.147 | 0.152 | 0.152 |
| S Recall | 0.157 | 0.148 | 0.108 | 0.117 |
| S Precision | 0.271 | 0.145 | 0.224 | 0.219 |
| V F1 | 0.567 | 0.587 | 0.576 | 0.576 |
| V Recall | 0.918 | 0.876 | 0.787 | 0.907 |
| N F1 | 0.912 | 0.919 | 0.938 | 0.916 |
| Macro F1 | 0.559 | 0.551 | 0.569 | 0.548 |
| INCART Macro F1 | 0.713 | 0.622 | 0.595 | 0.706 |
| **Success criteria** | — | ❌ FAIL | ❌ FAIL | ❌ FAIL |

#### 4.3.3 Confusion Matrix Analysis (the diagnostic)

The dominant error mode in all variants was S→V confusion (the SV head classifies PAC beats as PVCs rather than as S):

| Variant | S→V confusions | S correctly classified |
|---|---:|---:|
| v9.3 baseline | 291 | 151 |
| v10a | 290 | 142 |
| v10b | 270 | 104 |
| v10c | 281 | 112 |

**Key finding:** External data didn't reduce S→V confusion (291 → 290) — the S prototype never shifted because the leads didn't match (v10a/b mixed Lead I with MIT-BIH Lead II).

#### 4.3.4 Why v10 Failed (Root Cause Confirmed)

v10 tried to **augment** MIT-BIH Lead II with external Lead I/II data. This is adding mismatched data to a mismatched model. The confusion matrix proved it: external data didn't reduce S→V confusion (291 → 290) — the S prototype never shifted because the leads didn't match.

**v11 inverts the approach:** train on Lead I natively, validate on held-out Lead I patients, deploy on Lead I hardware. No MIT-BIH in training. No lead mismatch. No 18-patient ceiling.

### 4.4 v11 Lead I Native Training — APPROVED (3-Week Sprint)

**Decision:** Retrain gate + SV head from scratch on Lead I data (PTB-XL + CPSC2018). No MIT-BIH in training.

| Data Source | Records | Lead | Patients | Role |
|---|---:|---|---:|---|
| PTB-XL | 21,837 | Lead I (channel 0) | ~18,000 | Primary train + test |
| CPSC2018 | 6,877 | Lead I (channel 0) | ~1,000 | Primary train + test |
| MIT-BIH | 48 | Lead II (MLII) | 18 | Secondary cross-check only |
| INCART | 75 | Lead I available | 32 | External validation |
| AFDB | 23 | ECG | — | Event Engine validation only |

**Expected outcome:**
- S F1: 0.25-0.35 (up from 0.199, still below AAMI 0.40)
- N F1: ~0.90+ (should maintain)
- V Recall: ~0.85+ (should maintain AAMI compliance)
- The 18-patient ceiling is destroyed (thousands of patients now)

**Architecture unchanged:** Same gate + SV cascade, same 130-sample window, same 7 RR features, same hyperparameters. Only the training data changes.

### 4.5 ML Training Pipeline (Lead I Native)

```
TRAINING DATA (Lead I, matches hardware):
═══════════════════════════════════════════

Source 1: PTB-XL v1.0.3
  - 21,837 records, 12-lead, 500 Hz, 10s clips
  - Lead I extracted (channel 0)
  - Labels: .hea #Dx: SNOMED-CT codes
    * PAC (284470004): 398 records
    * PVC (427172004): 1,027 records
    * NSR (426783006): 18,092 records
  - Patient-wise split via strat_fold column (folds 1-8 train, 9 val, 10 test)

Source 2: CPSC2018
  - 6,877 records, 12-lead, 500 Hz, 6-60s clips
  - Lead I extracted (channel 0)
  - Labels: REFERENCE.csv 3-letter labels
    * PAC: 616 records
    * PVC: 672 records
    * N: 918 records
  - Patient-wise split (no patient overlap between train/val/test)

COMBINED LEAD I DATASET:
  - ~28,714 total records
  - ~1,014 PAC records → ~5,000-8,000 PAC beats (after prematurity filter)
  - ~1,699 PVC records → ~10,000-15,000 PVC beats
  - ~19,010 NSR records → ~200,000+ N beats
  - Thousands of unique patients (vs MIT-BIH's 18)

BEAT EXTRACTION:
  - WFDB XQRS R-peak detection (validated, published)
  - 130-sample window (65 pre / 65 post @ 250 Hz)
  - Rolling 30s z-score normalization
  - 7 RR features (same as v9.3)
  - Prematurity filter: KEEP beats with prematurity_index < 0.95 (for S)
  - PVC: wide-QRS beats from PVC records
  - N: random beats from NSR records (not premature)

PATIENT-WISE SPLIT (NO LEAKAGE):
  - Train: 80% of patients
  - Val: 10% of patients
  - Test: 10% of patients (held-out Lead I — the new benchmark)

TRAINING:
  - Gate CNN: trained from scratch (NOT frozen from v9.3)
  - SV Head CNN: trained from scratch
  - Same architecture as v9.3 (Conv2D 16/7→32/5→48/5→48/3 + Dense(16,8) RR + Dense(32) merge + V/S heads)
  - Same hyperparameters (60 epochs, Adam 1e-3, class-weighted BCE, early stop 12)
  - Same augmentation (shift ±3, amplitude 0.85-1.15, noise 0.02)

EVALUATION:
  - Primary: held-out Lead I test patients (PTB-XL + CPSC)
  - Secondary: MIT-BIH test set (Lead II — expect lower due to lead mismatch, document honestly)
  - Tertiary: INCART (Lead I available — external generalization check)
```

### 4.6 ML Profiling Results (DONE)

Gate and SV models profiled on EFR32MG26 (BRD2608A) via Silicon Labs ML Profiler:

| Metric | Gate | SV Head |
|---|---:|---:|
| Inference time | 12.7 ms | 10.2 ms |
| Inferences/sec | 78.8 | 97.8 |
| Flash used (total app) | 358 KB | 350 KB |
| RAM arena | 9 KB | 9 KB |
| MVP layers | 11 | 12 |
| CPU layers | 7 | 8 |
| CPU utilization | 45.8% | 47.5% |
| Total MACs | 707,824 | 539,408 |

All Conv2D, MaxPool2D, and FullyConnected layers are accelerated on MVP. CPU handles only reshape, concatenation, mean, and logistic. The MEAN layer (GlobalAveragePooling2D) is the CPU bottleneck at 3.6ms — documented as future optimization target.

### 4.7 TFLite Quantization Parity

**Status:** Output dequantization fix applied (Section 22 of FINAL notebook). Previous MAE≈70 was measurement error from comparing raw int8 to float probabilities. Dequantized parity must be re-validated after v11 training.

### 4.8 ML History — Key Conclusions

1. N dominance made accuracy misleading.
2. S is rare, subtle, and timing-dependent.
3. V is easier to recover than S but precision/recall tradeoff matters.
4. Cascade was attempted to reduce N dominance.
5. Single softmax underperformed due to N dominance and minority squeeze.
6. Old cascade had a routed-distribution bug: SV saw Gate-routed data at inference but clean abnormal-only data during training.
7. TFLite conversion was fragile for SeparableConv1D / Conv2D shape manipulation.
8. v9-v9.4 analysis suggests label noise was real but not the only issue.
9. v9.3 appears to be the MIT-BIH ceiling for the current architecture family.
10. Patient generalization remains unresolved (until v11 Lead I native training).

### 4.9 ML Latest Snapshot (v9.3 → v11 in progress)

| Metric / Finding | Status |
|---|---|
| v9.3 cleaned label model | current MIT-BIH ceiling for this architecture |
| Macro F1 | 0.559 on cleaned MIT-BIH test |
| N F1 | 0.912 |
| S F1 | 0.199 |
| S precision | 0.271 |
| V recall | 0.918 |
| S label noise | 41% of test S beats not premature |
| Patient generalization | unresolved; val S recall 0.904 vs test S recall 0.157 |
| Window 200 | inconclusive; Phase C was confounded by missing SVDB records |
| Gate capacity increase | rejected (ADR-014 in v9 sprint plan) |
| RR branch as S blocker | rejected (ADR-015 in v9 sprint plan) |
| External data / complete SVDB | next priority; PTB-XL + CPSC2018 now the active S-augmentation path |
| v9.5 (PTB-XL + CPSC2018 PAC augmentation) | in progress; notebook ready, awaiting extraction + training run |
| v9.5 expected yield | 7,000–10,000 clean PAC beats (PTB-XL 1.5–2.5k + CPSC 5–8k) after prematurity<0.95 filter |
| Honest S F1 ceiling | ~0.30–0.35 even with external data; AAMI ≥40% recall target may remain unmet |

Interpretation:
- The v8.7→v9.4 addendum is the most detailed ML experiment record and should be consulted before changing the ML roadmap.
- Architecture can learn S on validation-like distributions.
- It does not generalize well to unseen MIT-BIH test patients.
- v9.5 (Section 26 of v1.3) is the first external-data intervention. PTB-XL native annotation yielded only 37 PAC records (the "PTB-XL Fiasco", Section 8); the fix (ADR-011) switches to PhysioNet Challenge 2021 SNOMED-CT re-annotation in .hea files, unlocking 555 PTB-XL S-class records. CPSC2018 adds 616 records with longer 6–60s clips and is the primary external S source.
- Even with v9.5, the honest ceiling for S F1 is 0.30–0.35. The 18-patient MIT-BIH ceiling and 41% label noise are structural limits, not solvable by more data alone.

### 4.10 ML One-Line Verdict

**V recall target met (89%+), N strong, S at 16.2% vs 40% AAMI target with all model-side levers exhausted on current data; complete SVDB at 200-sample windows is the only remaining unexplored S lever; firmware integration is now the highest-priority unblocked task.**

**v1.3 update:** The highest-leverage S lever has shifted from "complete SVDB at 200 samples" to "external data augmentation via PTB-XL (SNOMED-CT filter, ADR-011) + CPSC2018 (ADR-012)". v9.5 is the active experiment. The firmware integration task remains the longest unblocked work item — v9.3 is the deployable floor regardless of v9.5 outcome.

---

## 5. Clinical Decision Engine

*Source: KB v1.4 Section 30 (full design); KB v2.0 Section 3; Arrhythmia Pipeline Design document.*

### 5.1 Purpose

The Clinical Event Engine converts a continuous stream of beat classifications (N/S/V per R-peak) into clinically meaningful rhythm-level summaries. It is **deterministic** — no neural network, no inference latency, ~1.5 KB code.

This is where **arrhythmia detection** happens. The CNN detects beats. The Engine detects rhythms.

### 5.2 Input Contract

```c
// Per-beat input from the CNN pipeline (every R-peak)
typedef struct {
    uint32_t timestamp_ms;     // R-peak timestamp
    uint8_t  beat_class;       // 0=N, 1=S, 2=V, 3=Q (from CNN)
    uint8_t  confidence;       // 0-255 (CNN probability × 255)
    uint16_t rr_interval_ms;   // RR since previous beat
    uint8_t  signal_quality;   // 0=bad, 255=excellent (from DSP)
} tarang_beat_input_t;
```

### 5.3 Internal State

```c
// Ring buffers (fixed-size, no heap)
#define RR_WINDOW_SIZE 30       // 30-beat rolling window for HRV
#define PATTERN_WINDOW_SIZE 8   // 8-beat pattern buffer for bigeminy/trigeminy

typedef struct {
    // RR interval ring buffer (for HRV + AFib)
    uint16_t rr_buffer[RR_WINDOW_SIZE];
    uint8_t  rr_head;
    uint8_t  rr_count;
    
    // Beat class pattern buffer (for couplets/triplets/runs/bigeminy/trigeminy)
    uint8_t  pattern_buffer[PATTERN_WINDOW_SIZE];
    uint8_t  pattern_head;
    uint8_t  pattern_count;
    
    // Running counters (reset every reporting interval)
    uint32_t total_beats;
    uint32_t pac_count;         // S beats
    uint32_t pvc_count;         // V beats
    
    // Episode tracking (for sustained arrhythmias)
    uint8_t  consecutive_v;     // current V run length
    uint8_t  consecutive_s;     // current S run length
    uint16_t afib_suspicion_counter;  // beats since AFib criteria last met
    
    // Last computed metrics
    uint8_t  current_hr;        // BPM
    uint8_t  rhythm_flags;      // bitfield (see 5.5)
} tarang_clinical_engine_t;
```

### 5.4 Algorithms (all deterministic, published)

#### 5.4.1 Heart Rate
```
HR = 60000 / mean(last 8 RR intervals)
Update every beat. If signal_quality < 128, hold previous HR.
```

#### 5.4.2 PAC / PVC Count and Burden
```
pac_count += (beat_class == S)
pvc_count += (beat_class == V)
total_beats += 1

PAC_burden = pac_count / total_beats × 100   (computed at reporting time)
PVC_burden = pvc_count / total_beats × 100
```

#### 5.4.3 Couplets (two consecutive ectopic beats of same class)
```
if pattern_buffer[-2] == S and pattern_buffer[-1] == S:
    couplet_S_count += 1
if pattern_buffer[-2] == V and pattern_buffer[-1] == V:
    couplet_V_count += 1
```

#### 5.4.4 Triplets (three consecutive ectopic beats of same class)
```
if pattern_buffer[-3] == S and pattern_buffer[-2] == S and pattern_buffer[-1] == S:
    triplet_S_count += 1
if pattern_buffer[-3] == V and pattern_buffer[-2] == V and pattern_buffer[-1] == V:
    triplet_V_count += 1
```

#### 5.4.5 Bigeminy (N-V-N-V-N-V pattern)
```
Check last 6 beats:
  if pattern == [N, V, N, V, N, V]:
      bigeminy_flag = 1
      bigeminy_duration += 1
  else:
      if bigeminy_duration > 0:
          emit_event(BIGEMINY_EPISODE, bigeminy_duration)
      bigeminy_flag = 0
      bigeminy_duration = 0
```

#### 5.4.6 Trigeminy (N-N-V-N-N-V pattern)
```
Check last 6 beats:
  if pattern == [N, N, V, N, N, V]:
      trigeminy_flag = 1
      trigeminy_duration += 1
  else:
      if trigeminy_duration > 0:
          emit_event(TRIGEMINY_EPISODE, trigeminy_duration)
      trigeminy_flag = 0
      trigeminy_duration = 0
```

#### 5.4.7 Ventricular Run (≥3 consecutive V beats)
```
if beat_class == V:
    consecutive_v += 1
    if consecutive_v == 3:
        emit_event(V_RUN_START)
    if consecutive_v >= 3 and consecutive_v % 10 == 0:
        emit_event(V_RUN_ONGOING, consecutive_v)  // telemetry every 10 beats
else:
    if consecutive_v >= 3:
        emit_event(V_RUN_END, consecutive_v)
        if consecutive_v >= 5 and current_hr > 100:
            emit_event(VT_SUSPECTED)  // ventricular tachycardia
    consecutive_v = 0
```

#### 5.4.8 Supraventricular Run (≥3 consecutive S beats)
```
if beat_class == S:
    consecutive_s += 1
    if consecutive_s == 3:
        emit_event(SVT_RUN_START)  // supraventricular tachycardia
else:
    if consecutive_s >= 3:
        emit_event(SVT_RUN_END, consecutive_s)
    consecutive_s = 0
```

**Note:** SVT detection depends on S-class detection, which is weak (F1 0.199). SVT events will have low sensitivity. This is documented in the capability matrix (Section 5.8).

#### 5.4.9 AFib Screening (Lorenz Plot + RR Irregularity)

This is the **most important rhythm detector** — and it does NOT use the CNN. It uses only RR intervals.

```
Compute over last 30 RR intervals:
  mean_rr = mean(rr_buffer)
  sdnn   = std(rr_buffer)            // standard deviation
  cov    = sdnn / mean_rr            // coefficient of variation
  rmssd  = sqrt(mean(diff(rr_buffer)^2))  // root mean square successive differences
  pRR50  = count(|diff(rr_buffer)| > 50ms) / 29  // proportion of successive RR differing >50ms

AFib criteria (all must be met):
  1. cov > 0.12                    // irregularly irregular
  2. pRR50 > 0.10                  // high variability
  3. rmssd > 30ms                  // substantial short-term variability
  4. No dominant V pattern         // exclude V bigeminy (which also has irregular RR)
  5. mean_rr < 1000ms OR > 600ms   // not extreme brady/tachy (which can mimic AFib)

if all criteria met for 30 consecutive beats:
    rhythm_flags |= AFIB_SUSPECTED
    emit_event(AFIB_EPISODE_START)
```

**Published sensitivity:** ≥95% on MIT-BIH AFib Database (AFDB) — Lynn et al. 1991, Linker et al. 2003, Tateno et al. 2001.

#### 5.4.10 Sinus Tachycardia / Bradycardia
```
if current_hr > 100 and not AFIB_SUSPECTED:
    rhythm_flags |= SINUS_TACH
if current_hr < 60 and not AFIB_SUSPECTED:
    rhythm_flags |= SINUS_BRADY
```

#### 5.4.11 HRV Metrics (for dashboard)
```
Computed every 30 beats:
  SDNN  = std(rr_buffer)
  RMSSD = sqrt(mean(diff(rr_buffer)^2))
  pRR50 = count(|diff(rr_buffer)| > 50ms) / (rr_count - 1)

Transmitted in periodic telemetry packet (not event-driven).
```

### 5.5 Output Contract

```c
// Per-beat output (sent via BLE on anomaly, or buffered for periodic telemetry)
typedef struct {
    uint32_t timestamp_ms;
    uint8_t  beat_class;        // 0=N, 1=S, 2=V, 3=Q
    uint8_t  confidence;
    uint16_t rr_interval_ms;
    uint8_t  rhythm_flags;      // bitfield:
                                //   bit 0: AFIB_SUSPECTED
                                //   bit 1: SINUS_TACH
                                //   bit 2: SINUS_BRADY
                                //   bit 3: BIGEMINY
                                //   bit 4: TRIGEMINY
                                //   bit 5: V_RUN (≥3 V)
                                //   bit 6: SVT_RUN (≥3 S)
                                //   bit 7: VT_SUSPECTED (≥5 V + HR>100)
    uint8_t  pac_burden_pct;    // running PAC burden %
    uint8_t  pvc_burden_pct;    // running PVC burden %
    uint8_t  current_hr;
    uint16_t sdnn_ms;           // HRV (updated every 30 beats)
    uint16_t rmssd_ms;          // HRV (updated every 30 beats)
} __attribute__((packed)) tarang_event_packet_t;  // 15 bytes (16 with padding)
```

### 5.6 Event-Driven BLE Telemetry

The Clinical Event Engine produces two types of BLE traffic:

**Event packets (anomaly-driven, immediate):**
- Sent when rhythm_flags changes (new arrhythmia starts/ends)
- Sent when a significant event occurs (couplet, triplet, V run, VT suspected)
- ~10-50 packets per hour during normal wear (mostly N → brief S/V events)
- ~100-500 packets per hour during arrhythmia episodes

**Periodic telemetry (every 5 minutes):**
- HR, HRV metrics, PAC/PVC burden, total beat count
- ~12 packets per hour regardless of rhythm

**Total BLE duty cycle:** <1% of connection intervals. Fits 30-day battery budget.

### 5.7 Per-Beat Pipeline (Firmware Pseudocode)

*Source: Arrhythmia Pipeline Design document.*

```c
// Pseudocode — tarang_pipeline.c

void tarang_on_r_peak(uint32_t timestamp_ms, float *ecg_window_130, 
                       float *rr_features_7, uint8_t signal_quality) {
    
    // ── TIER 0: Always-on (pure DSP) ─────────────────────────────────
    beat_input_t beat;
    beat.timestamp_ms = timestamp_ms;
    beat.rr_interval_ms = compute_rr_interval(timestamp_ms);
    beat.signal_quality = signal_quality;
    
    // Update rolling stats
    engine_update_rr(&engine, beat.rr_interval_ms);
    beat.hr = engine_compute_hr(&engine);
    
    // Cheap anomaly heuristics — decide whether to run CNN
    bool suspicious = beat_is_suspicious(&beat, &engine);
    
    // ── TIER 1 & 2: CNN (only if suspicious) ──────────────────────────
    if (suspicious) {
        // Run Gate CNN (~5ms on MVP)
        float gate_prob = cnn_gate_predict(ecg_window_130, rr_features_7);
        
        if (gate_prob > GATE_THRESHOLD) {  // 0.10
            // Run SV Head CNN (~10ms on MVP)
            float v_prob, s_prob;
            cnn_sv_predict(ecg_window_130, rr_features_7, &v_prob, &s_prob);
            
            if (v_prob > V_THRESHOLD)       beat.beat_class = V_CLASS;
            else if (s_prob > S_THRESHOLD)  beat.beat_class = S_CLASS;
            else                             beat.beat_class = N_CLASS;
            beat.confidence = (beat.beat_class == V_CLASS) ? 
                              (uint8_t)(v_prob * 255) : (uint8_t)(s_prob * 255);
        } else {
            beat.beat_class = N_CLASS;
            beat.confidence = (uint8_t)((1.0f - gate_prob) * 255);
        }
    } else {
        // Skip CNN entirely — heuristics say this is normal
        beat.beat_class = N_CLASS;
        beat.confidence = 255;
    }
    
    // ── TIER 3: Clinical Event Engine (always runs) ──────────────────
    engine_process_beat(&engine, &beat);
    
    // Check if we need to send a BLE event
    if (engine.rhythm_flags_changed || engine.significant_event) {
        ble_send_event_packet(&beat, &engine);
    }
}
```

### 5.8 Arrhythmia Detection Capability Matrix

#### 5.8.1 STRONG Claims (defensible, validated)

| Arrhythmia | How detected | Sensitivity | Notes |
|---|---|---|---|
| **PVC** | CNN V-class (recall 91.8%) | High | AAMI EC57 compliant (≥85% target met) |
| **Ventricular Bigeminy** | Engine: N-V-N-V-N-V pattern | High | 6-beat pattern match |
| **Ventricular Trigeminy** | Engine: N-N-V-N-N-V pattern | High | 6-beat pattern match |
| **Ventricular Couplets** | Engine: V-V (2 consecutive) | High | |
| **Ventricular Triplets** | Engine: V-V-V (3 consecutive) | High | |
| **Ventricular Run** | Engine: ≥3 consecutive V | High | Pre-VT indicator |
| **Ventricular Tachycardia** | Engine: ≥5 V + HR>100 | Medium | Life-threatening, immediate alert |
| **AFib** | Engine: RR CoV>0.12 + pRR50>0.10 + RMSSD>30ms | ≥95%* | Published technique, validated on AFDB |
| **Sinus Tachycardia** | Engine: HR>100, no AFib | 100% | |
| **Sinus Bradycardia** | Engine: HR<60, no AFib | 100% | |
| **HRV Metrics** | Engine: SDNN, RMSSD, pRR50 | 100% | Wellness/recovery monitoring |

*Published sensitivity for RR-based AFib detection (Lynn 1991, Tateno 2001, Linker 2003).

#### 5.8.2 WEAK Claims (honest, screening only)

| Arrhythmia | Why weak | What to say |
|---|---|---|
| **PAC** | CNN S-class F1=0.199 (18-patient ceiling, 41% label noise) | "PAC screening — low sensitivity, for trend monitoring only" |
| **SVT** | Depends on S-class detection | "SVT screening — low sensitivity" |
| **Atrial Bigeminy/Trigeminy** | Depends on S-class | "Screening only" |

#### 5.8.3 NOT DETECTABLE (do not claim)

- Atrial Flutter (needs P-wave sawtooth analysis)
- Heart Block (needs PR interval analysis)
- ST Elevation/Depression (needs ischemia model)
- Bundle Branch Block (needs QRS duration classifier)
- Ventricular Fibrillation (needs continuous waveform analysis, not beat-based)

### 5.9 Validation Status

| Test | Status | Result |
|---|---|---|
| Normal sinus (synthetic) | ✅ PASS | AFib=False (correct) |
| AFib irregular (synthetic) | ✅ PASS | AFib=True (correct) |
| VT run (synthetic) | ✅ PASS | VT=True (correct) |
| Bigeminy (synthetic) | ✅ PASS | Bigeminy=True, AFib=False (correct — Fix #12) |
| AFDB (real data) | ❌ PENDING | Not yet executed |

### 5.10 Validation Plan (Independent of CNN)

| Dataset | Purpose | Metric |
|---|---|---|
| MIT-BIH AFib Database (AFDB) | AFib screening sensitivity/specificity | ≥90% sensitivity, ≥85% specificity |
| MIT-BIH Arrhythmia (test set) | PVC burden estimation, bigeminy/trigeminy detection | Event agreement ≥80% |
| INCART | External generalization of rhythm detection | Macro F1 ≥0.70 |

**Critical:** The Clinical Event Engine validation does NOT require the CNN to be accurate on S. AFib detection uses only RR intervals. PVC burden uses V class (which is accurate). Only SVT/run detection depends on S — and those events are documented as low-sensitivity.

### 5.11 Ventricular Pattern Detection — Firmware Pseudocode

```c
void engine_check_ventricular_patterns(engine_state_t *s, uint8_t beat_class) {
    // Update consecutive counters
    if (beat_class == V_CLASS) {
        s->consecutive_v++;
        s->consecutive_s = 0;
        
        // V run detection
        if (s->consecutive_v == 3) {
            s->rhythm_flags |= V_RUN;
            s->significant_event = true;
        }
        // VT detection (≥5 V + high HR)
        if (s->consecutive_v >= 5 && s->current_hr > 100) {
            s->rhythm_flags |= VT_SUSPECTED;
            s->significant_event = true;  // CRITICAL — immediate alert
        }
    } else {
        if (s->consecutive_v >= 3) {
            s->rhythm_flags &= ~V_RUN;
            s->significant_event = true;  // V run ended
        }
        if (s->rhythm_flags & VT_SUSPECTED) {
            s->rhythm_flags &= ~VT_SUSPECTED;
            s->significant_event = true;  // VT episode ended
        }
        s->consecutive_v = 0;
    }
    
    // Couplets (V-V)
    if (s->pattern_count >= 2) {
        uint8_t p1 = s->pattern_buffer[(s->pattern_head - 2 + PATTERN_WINDOW_SIZE) % PATTERN_WINDOW_SIZE];
        uint8_t p2 = s->pattern_buffer[(s->pattern_head - 1 + PATTERN_WINDOW_SIZE) % PATTERN_WINDOW_SIZE];
        if (p1 == V_CLASS && p2 == V_CLASS) {
            s->couplet_v_count++;
            s->significant_event = true;
        }
    }
    
    // Bigeminy (N-V-N-V-N-V)
    if (s->pattern_count >= 6) {
        bool bigeminy = true;
        for (int i = 0; i < 6; i++) {
            uint8_t idx = (s->pattern_head - 6 + i + PATTERN_WINDOW_SIZE) % PATTERN_WINDOW_SIZE;
            uint8_t expected = (i % 2 == 0) ? N_CLASS : V_CLASS;
            if (s->pattern_buffer[idx] != expected) {
                bigeminy = false;
                break;
            }
        }
        if (bigeminy && !(s->rhythm_flags & BIGEMINY)) {
            s->rhythm_flags |= BIGEMINY;
            s->significant_event = true;
        } else if (!bigeminy && (s->rhythm_flags & BIGEMINY)) {
            s->rhythm_flags &= ~BIGEMINY;
            s->significant_event = true;
        }
    }
    
    // Trigeminy (N-N-V-N-N-V) — similar logic
    // ... (see 5.4.6 above)
}
```

### 5.12 AFib Detection Firmware Pseudocode

```c
// Runs every beat, uses 30-beat rolling RR buffer
void engine_check_afib(engine_state_t *s) {
    if (s->rr_count < 30) return;  // not enough data yet
    
    // Compute RR statistics
    float mean_rr = engine_rr_mean(s);
    float sdnn    = engine_rr_std(s);
    float cov     = sdnn / mean_rr;
    float rmssd   = engine_rr_rmssd(s);
    float pRR50   = engine_rr_prr50(s);
    
    // AFib criteria (all must be met)
    bool afib_criteria_met = 
        (cov > 0.12f) &&           // irregularly irregular
        (pRR50 > 0.10f) &&         // high short-term variability
        (rmssd > 30.0f) &&         // substantial variability
        (mean_rr > 400 && mean_rr < 1200) &&  // not extreme HR
        !s->v_bigeminy_active;     // exclude V bigeminy (also irregular)
    
    if (afib_criteria_met) {
        s->afib_counter++;
        if (s->afib_counter >= 30 && !(s->rhythm_flags & AFIB_SUSPECTED)) {
            s->rhythm_flags |= AFIB_SUSPECTED;
            s->significant_event = true;  // trigger BLE packet
        }
    } else {
        if (s->rhythm_flags & AFIB_SUSPECTED) {
            s->rhythm_flags &= ~AFIB_SUSPECTED;
            s->significant_event = true;  // AFib episode ended
        }
        s->afib_counter = 0;
    }
}
```

### 5.13 Why This Architecture Was Chosen

Compared to direct rhythm classification via a single long-window NN:

| Advantage | Explanation |
|---|---|
| ✓ Lower Flash | Two small Int8 TFLite models (~26 KB) + deterministic engine (~1 KB) vs 200 KB+ for a long-window NN |
| ✓ Lower RAM | 30-float ring buffer vs full signal-window tensor |
| ✓ Lower latency | Gate runs every beat (~5 ms), SV head runs on ~10% of beats, rhythm engine is signal-processing (sub-ms) |
| ✓ Better battery life | <1% AI duty cycle vs continuous inference |
| ✓ Modular software | Beat classifier and Clinical Event Engine can be upgraded independently |
| ✓ Independent validation | Per-class AAMI compliance (beat) + AFDB episode detection (rhythm) are separate metrics |
| ✓ Easier firmware deployment | Two model files + one struct output, fits existing BLE event architecture |
| ✓ Easier future upgrades | Rhythm logic can be updated without retraining the CNN; CNN can be retrained without touching rhythm logic |

### 5.14 Clinical Claims

**Tarang currently claims:**
- ✓ Beat Classification (N / S / V per R-peak)
- ✓ Embedded AI Deployment (TFLite Micro on EFR32MG26)
- ✓ Clinical Event Aggregation (PAC/PVC burden, couplets, triplets, bigeminy, trigeminy, runs, RR stats, AF screening)
- ✓ Continuous Monitoring (event-gated, low-power)

**Tarang does NOT currently claim:**
- ✗ Autonomous Clinical Diagnosis
- ✗ Hospital-grade Arrhythmia Diagnosis
- ✗ Replacement of Holter Monitoring
- ✗ Direct AF Detection using CNN (AF is detected by the deterministic Clinical Event Engine via RR irregularity, not by the CNN)

---

## 6. Firmware Architecture

*Source: KB v1.3 Section 11; KB v2.0 Section 1.3; Arrhythmia Pipeline Design Power Budget Analysis.*

### 6.1 Intended Firmware Shape

```text
LETIMER → PRS → IADC → LDMA
        ↓
double-buffered sensor_frame_matrix_t
        ↓
DSP event
        ↓
AI event only if gated
        ↓
BLE event only if anomaly
        ↓
sleep / EM2 between work
```

### 6.2 Firmware Hard Rules

1. No heap allocation in runtime DSP path.
2. No blocking calls in ISR.
3. No serial spam in acquisition path.
4. No raw ECG BLE streaming in battery mode.
5. AI must be event-gated.
6. Model header does not prove runtime inference.
7. `tarang_ai_process()` must actually call TFLite Micro before integration is considered complete.
8. Watchdog and diagnostic counters must remain active.
9. Frame ownership must be explicit and checked.
10. Simplicity Studio generated files must not be manually patched.

### 6.3 EFR32 DSP-Only Acceptance Gates

| Gate | Target |
|---|---:|
| ECG 250 Hz verified on board | pass |
| IMU 100 Hz verified on board | pass |
| 30 min no dropped frames | pass |
| 30 min no DMA overruns | pass |
| frame_sequence monotonic | pass |
| DSP runtime per 256-sample frame | <25 ms minimum, <10 ms strong |
| heap use | 0 |
| watchdog resets | 0 |
| sleep between frames | yes |
| per-frame quality verdict | yes |

**Required finalization script reference:** Use `16_per_frame_quality.py` as the Python source-of-truth for frame verdict definitions before porting verdict logic to EFR32.

### 6.4 EFR32 ML Acceptance Gates

| Gate | Target |
|---|---:|
| `tarang_ai_process()` invokes TFLite Micro | required |
| model version string | included |
| input quantization | implemented |
| output dequantization | implemented |
| thresholds | compiled/configured and logged |
| tensor arena | measured |
| model size | measured |
| inference latency | measured |
| operators | TFLM-compatible |
| deterministic replay frame test | passes |
| live sensor gated inference | passes |
| AI trigger rate | measured |
| BLE event emission | compact and guarded |

### 6.5 BLE Event Packet

```c
// 15 bytes (16 with padding) — sent on rhythm_flags change or significant event
typedef struct __attribute__((packed)) {
    uint32_t timestamp_ms;       // 4 bytes — R-peak timestamp
    uint8_t  beat_class;         // 1 byte  — 0=N, 1=S, 2=V, 3=Q
    uint8_t  confidence;         // 1 byte  — 0-255
    uint16_t rr_interval_ms;     // 2 bytes
    uint8_t  rhythm_flags;       // 1 byte  — bitfield (see below)
    uint8_t  pac_burden_pct;     // 1 byte  — running PAC %
    uint8_t  pvc_burden_pct;     // 1 byte  — running PVC %
    uint8_t  current_hr;         // 1 byte  — BPM
    uint16_t sdnn_ms;            // 2 bytes — HRV (updated every 30 beats)
    uint16_t rmssd_ms;           // 2 bytes — HRV (updated every 30 beats)
} tarang_event_packet_t;        // Total: 16 bytes

// rhythm_flags bitfield:
#define RHYTHM_NORMAL        0x00
#define RHYTHM_AFIB          0x01  // bit 0
#define RHYTHM_SINUS_TACH    0x02  // bit 1
#define RHYTHM_SINUS_BRADY   0x04  // bit 2
#define RHYTHM_BIGEMINY      0x08  // bit 3
#define RHYTHM_TRIGEMINY     0x10  // bit 4
#define RHYTHM_V_RUN         0x20  // bit 5
#define RHYTHM_SVT_RUN       0x40  // bit 6
#define RHYTHM_VT_SUSPECTED  0x80  // bit 7 — CRITICAL
```

### 6.6 Power Budget Analysis

| State | CPU duty | CNN duty | BLE duty | Battery life |
|---|---|---|---|---|
| Rest (normal sinus) | <0.1% (DSP only) | <0.1% | <0.1% | 30+ days |
| Occasional PAC (1/min) | <0.5% | ~0.1% | <0.5% | 30 days |
| PVC bigeminy | ~5% | ~5% | ~2% | 15-20 days |
| AFib episode | ~10% | ~9% | ~5% | 7-10 days |
| Sustained VT | ~15% | ~10% | ~10% | 3-5 days (acceptable — medical emergency) |

**At rest (the 99% case):** 30+ day battery confirmed. CNN runs on <0.1% of beats.

**During arrhythmia:** Battery life decreases, but this is acceptable — arrhythmia episodes are rare, short, and medically important (you WANT the device active during them).

### 6.7 30-Day Budget Formula

```text
Average current budget = battery_mAh × usable_fraction / 720 hours
```

Use usable_fraction = 0.7 unless measured otherwise.

| Battery | 30-day average current budget |
|---|---:|
| 200 mAh | ~0.19 mA |
| 500 mAh | ~0.49 mA |
| 1000 mAh | ~0.97 mA |

So the system likely needs average current under roughly **0.5–1.0 mA**, depending on battery capacity.

### 6.8 Required Power Components

Measure or estimate:

```text
I_avg =
I_sleep
+ I_sensors_avg
+ I_adc_dma_avg
+ I_dsp_avg
+ I_ai_avg
+ I_ble_avg
```

### 6.9 Required Firmware Counters

Add counters:

```c
frames_processed;
dsp_time_us;
nlms_time_us;
rpeak_time_us;
ai_trigger_count;
ai_time_us;
ble_packet_count;
sleep_time_us;
dropped_frames;
dma_overruns;
watchdog_feeds;
sequence_gaps;
```

### 6.10 Battery Acceptance Gates

| Gate | Target |
|---|---:|
| AI continuous | forbidden |
| BLE raw ECG streaming | forbidden in battery mode |
| AI trigger rate at rest | <1% of beats |
| AI trigger rate normal use | <5% of beats |
| BLE event rate | documented |
| current profile | measured or defensibly estimated |
| 30-day calculation | present |
| sleep time fraction | measured |

### 6.11 Noise Source Inventory

| # | Noise Source | Mitigation | Status |
|---|---|---|---|
| N1 | Powerline (50/60 Hz) | RLD + bandpass 0.5-40Hz | ⚠️ RLD on same wrist is weak; may need notch |
| N2 | Electrode half-cell drift | Bandpass high-pass 0.5Hz | ✅ Handled |
| N3 | Baseline wander (respiration) | Bandpass high-pass 0.5Hz | ✅ Handled |
| N4 | Motion (right wrist electrode) | NLMS (IMU co-located) | ⚠️ Should work, unvalidated on final HW |
| N5 | Motion (left arm electrode) | NONE — IMU doesn't see it | ❌ Unmitigated |
| N6 | Wire triboelectric | NONE — IMU doesn't see it | ❌ Unmitigated |
| N7 | Wire tug at electrode | NONE — IMU doesn't see it | ❌ Unmitigated |
| N8 | EMG (skeletal muscle) | Bandpass low-pass 40Hz | ✅ Mostly removed |
| N9 | ADC quantization | 12-bit IADC | ✅ Negligible |
| N10 | RF noise (BLE) | PCB ground plane | ⚠️ Unverified |
| N11 | Power supply ripple | Decoupling caps, LDO | ⚠️ Unverified |

**Critical risk (wrist+wire topology):** N5, N6, N7 are all caused by the wire to the left arm. The compact single-housing topology (Architecture Resolution FINAL) eliminates the wire risk by co-locating both electrodes on the case back. Both topologies are documented; the compact one supersedes the wire one.

### 6.12 Signal Processing Pipeline (Always-On, Continuous)

```
ALWAYS RUNNING (24/7, 30 days, EM2 sleep >99%):
═══════════════════════════════════════════════

Skin (Electrode A & B)
    │
    ▼
AD8232/AD8422 Analog Front-End
  - Instrumentation amplifier (100× gain)
  - RLD driven back to skin (common-mode rejection)
  - Bandpass filter (0.5-40 Hz)
    │
    ▼
IADC @ 250 Hz (EFR32MG26)
  - PRS-triggered, LDMA to buffer
  - Zero-CPU acquisition
    │
    ▼
NLMS Adaptive Filter (always-on)
  - Reference: IMU acceleration (co-located)
  - Filters motion artifact correlated with physical movement
  - VALID because IMU and electrodes are on the same housing
  - SNR improvement: ~3.3 dB (validated on ESP32 prototype)
    │
    ▼
Pan-Tompkins R-Peak Detection (always-on)
  - DC removal → bandpass → derivative → square → MWI → adaptive threshold
  - Detects R-peaks at 250 Hz
  - Outputs: R-peak timestamp, RR interval
    │
    ▼
Rolling 30s Z-Score Normalization (always-on)
  - 30-second rolling mean and std
  - Normalizes amplitude (lead-I smaller amplitude is irrelevant)
    │
    ▼
130-Sample Beat Window Extraction (always-on)
  - 65 samples before R-peak, 65 after
  - 7 RR features computed per beat
    │
    ▼
Tier 0 Trigger Heuristics (always-on)
  - Prematurity check (rr_prev / rr_mean_5 < 0.85)
  - RR irregularity (CoV > 0.12 over 30 beats)
  - HR extremes (>120 or <45)
  - Compensatory pause (post-ectopic RR > 1.5× mean)
  - Signal quality (<128/255)
  - OUTPUT: beat_suspicious flag (YES/NO)
    │
    ├──── if NO ──→ beat_class = N, skip CNN (99.9% of beats at rest)
    │
    └──── if YES ─→ wake CNN (Tier 1)
```

### 6.13 Implementation Priority

| # | Task | Owner | Status | ETA |
|---|---|---|---|---|
| 1 | v11 Lead I retraining (notebook + train) | Mahdi | APPROVED | 1 week |
| 2 | Wire `tarang_ai_process()` in firmware | Kedar | NOT STARTED | 1 week |
| 3 | Implement Clinical Event Engine in C | Kedar | NOT STARTED | 3 days |
| 4 | Validate AFib on AFDB | Mahdi | NOT STARTED | 1 day |
| 5 | BLE event packet implementation | Kedar | NOT STARTED | 2 days |
| 6 | Dashboard (Raspberry Pi + Python) | Pal | NOT STARTED | 2 days |
| 7 | Video demo recording | Team | NOT STARTED | 1 day |
| 8 | Correct PPT (remove PPG, fix AFib attribution) | Team | NOT STARTED | 0.5 day |
| 9 | GitHub repo hygiene (topics, license, README) | Team | NOT STARTED | 0.5 day |

### 6.14 Artifact and Repository Organization

Recommended structure:

```text
tarang/
  docs/
    BASELINE_SPEC.md
    CURRENT_STATUS.md
    SOURCE_OF_TRUTH_KB.md
    DSP_VALIDATION_PROTOCOL.md
    ML_BASELINE_PROTOCOL.md
    EFR32_ACCEPTANCE_GATES.md
    BATTERY_BUDGET.md
    CLAIM_GUARDRAILS.md

  data/
    esp32_logs/
    efr32_logs/
    manual_labels/
    stress_tests/
    synthetic/

  dsp/
    python_reference/
    c_reference/
    validation_scripts/
    reports/

  ml/
    notebooks/
    training/
    export/
    tflite_models/
    metrics/
    manifests/

  firmware/
    efr32/
    replay_tests/
    model_headers/
    configs/

  reports/
    dsp_reports/
    ml_reports/
    efr32_reports/
    review_reports/

  tools/
    annotation/
    plotting/
    conversion/
```

---

## 7. Validation & Testing

*Source: Tarang DSP Knowledge Base v16 Sections 4 (phase-by-phase results); KB v1.3 Section 6-8 (DSP validation protocol, RR/DSP failure-mode taxonomy, stress-test verdict logic).*

### 7.1 Phase 1: Block-Level Tests (26/26 PASS)

Each stateful block tested individually:
- Impulse response (bounded + decaying)
- Causality (perturbing future doesn't change past)
- Chunk invariance (1-sample, 37-sample, 256-sample, whole-array — bit-identical)
- Normalizer startup (no NaN/Inf, no negative variance, 8000 samples)
- Scipy parity: `sos_step` matches `scipy.signal.sosfilt` to 2.06e-13 (cold start)
- Notch parity: bit-exact (0.00e+00) vs `scipy.signal.lfilter`
- Rolling norm closed-form: matches `-1/sqrt(C-1)` to 1.39e-17

### 7.2 Phase 2: Assembled Pipeline Tests (5/5 PASS)

- Chunk invariance on full pipeline: 28 beats, max diff 0.00e+00 across all chunk sizes
- Causality: 15 safe beats, 0 mismatches
- SPKI/NPKI local-max detection: verified structurally and behaviorally
- `process_frame == process_record` (no vectorized sibling)
- Beat detection sanity: correct count on synthetic signal

### 7.3 Phase 2 Regression Tests (3/3 PASS — each FAILS if fix is reverted)

- Bug 1: Local-max detection (rising-edge would fire at sample 47, not 50)
- Bug 2: Hysteresis (oscillating plateau would fire at sample 15, not 30)
- Bug 3: Refractory filter (search-back would create duplicate at 243/244)

### 7.4 DSP Validation Protocol (KB v1.3 Reference)

Required finalization scripts:
- `09_rr_quality_analysis.py` — RR taxonomy report
- `15_stress_test_runner.py` — scenario verdict report
- `16_per_frame_quality.py` — frame verdict report (source-of-truth for verdict logic)

### 7.5 RR/DSP Failure-Mode Taxonomy (from KB v1.2)

Per-frame quality verdict definitions are defined in `16_per_frame_quality.py`. The firmware verdict names must match Section 6.8 of KB v1.3 unless a documented change is approved.

### 7.6 Stress-Test Verdict Logic (from KB v1.2)

Sprint 1 pass gates for the DSP:
- R-peak precision/recall >95% manual
- RR CV <0.15 clean rest
- NLMS stable
- rest motion gate <5%
- intentional motion gate >70%

### 7.7 Sprint Roadmap

#### Sprint 1 — Freeze DSP Reference and Stress Tests

Goal: Make DSP defensible.

Deliverables:
- clean rest recording
- motion recording
- loose-electrode recording
- cable-tug recording
- manual R-peak labels for at least 60 sec
- R-peak precision/recall/F1 report
- calibrated motion gate
- NLMS-only metrics report
- frame-quality verdict system
- `09_rr_quality_analysis.py` RR taxonomy report
- `15_stress_test_runner.py` scenario verdict report
- `16_per_frame_quality.py` frame verdict report

Pass gates:
- R-peak precision/recall >95% manual
- RR CV <0.15 clean rest
- NLMS stable
- rest motion gate <5%
- intentional motion gate >70%

#### Sprint 2 — Port DSP to EFR32 and Prove Parity

Goal: Move from ESP32/Python to EFR32 firmware.

Deliverables:
- EFR32 acquisition test
- EFR32 250 Hz ECG verification
- EFR32 100 Hz IMU verification
- fixed-point DSP implementation
- Python-vs-C replay test
- timing counters
- no heap / no blocking audit
- 30-min no-overrun test

Pass gates:
- 0 dropped frames in 30 min
- DSP time <25 ms/frame
- Python vs C R-peak mismatch <1 beat/min clean rest
- HR difference <3 bpm
- no overflow

#### Sprint 3 — Integrate Gated ML and Measure Battery

Goal: Make edge-AI real and battery-aware.

Deliverables:
- final quantized model manifest
- TFLM inference in `tarang_ai_process()`
- tensor arena measurement
- inference latency measurement
- gated AI trigger logic
- BLE compact anomaly packet
- current measurement
- 30-day battery estimate

Pass gates:
- model fits memory
- inference works on EFR32
- AI not continuous
- AI trigger rate at rest <1%
- BLE raw stream disabled in battery mode
- current budget supports target battery or explicitly fails

### 7.8 Open Validation Questions

#### 7.8.1 Hardware/Firmware
1. Which exact EFR32MG26 board/part will be final?
2. Which exact ECG analog front-end will be used: AD8232 for demo or AD8422/RLD for production?
3. Which exact IMU will be used: MPU6050/MPU6500 bring-up module or ICM-20648 production target?
4. What are the final memory limits?
5. Is the MVP accelerator path available and tested?
6. What is the measured current in EM2, acquisition, DSP, AI, BLE?

#### 7.8.2 DSP
1. Does Pan-Tompkins precision/recall exceed 95% on manual labels?
2. Does RR CV fall below 0.15 on clean rest?
3. Does NLMS produce >3 dB motion-window improvement over bandpass+notch?
4. Does NLMS preserve QRS morphology?
5. Does fixed-point C match Python reference?

#### 7.8.3 ML
1. What are the 3 additional datasets?
2. Can external data raise S F1 beyond 0.35–0.50?
3. Is the 0.95 prematurity threshold clinically acceptable?
4. Should junctional beats mapped to S be reconsidered?
5. Which model is final for EFR32: v9.3, v8 cascade, or v10 external-data model?

#### 7.8.4 Product/Claims
1. Is the project target hackathon demo, publication, or clinical prototype?
2. What exact claim will be made to judges?
3. What claim will explicitly not be made?
4. Will a medical expert review labels or results?

### 7.9 PTB-XL PAC Extraction Postmortem

*Source: `v95_pac_extraction_postmortem.md` (2026-07-06). This is the deep-dive investigation that produced ADR-011.*

#### 7.9.1 TL;DR

The sprint plan assumed PTB-XL contained ~700 PAC records we could use for S-class augmentation. After three rounds of debugging, we discovered:

1. The original notebook filter (`scp_codes.str.contains('PAC')`) was matching **pacemaker records** (`PACE`) and **ruled-out PACs** (`PAC: 0.0` likelihood) — producing 398 false positives.
2. The corrected filter (parse `scp_codes` as a dict, require `PAC > 0` likelihood) found only **37 real PAC records** in PTB-XL — far below the sprint's 1,000-beat yield floor.
3. The 37-vs-398 discrepancy triggered a deeper investigation that revealed: **PTB-XL's native `scp_codes` annotation is much stricter than PhysioNet's Challenge 2021 re-annotation.** The Challenge organizers re-labeled PTB-XL records with looser criteria, finding **398 PAC + 157 SVPB = 555 S-class records** in the same files we already had on disk.
4. The fix is not a new download — it's switching the filter from `ptbxl_database.csv` substring matching to `.hea` file `# Dx:` SNOMED-CT code lookup. This unlocks 555 S-class records we already have.
5. Adding CPSC2018 (616 PAC records, already in the notebook) brings total expected yield to **7,000–10,000 clean PAC beats** — comfortably clears the 1,000-beat sprint floor.

**No re-download needed. No new data source needed. Just fix the filter.**

#### 7.9.2 Stage 0 — The Sprint Plan Assumption (Wrong)

The 1-week sprint plan opened with:

> **The Primary Lever:** Adding external patient data (PTB-XL) to break the 18-patient MIT-BIH overfitting trap.

And specified the extraction code:

```python
pac_records = ptbxl_db[
    ptbxl_db['scp_codes'].str.contains('SVPB', na=False) |
    ptbxl_db['scp_codes'].str.contains('PAC', na=False)
]
```

**The assumption:** PTB-XL has hundreds-to-thousands of PAC records, so substring filtering would catch them all. The plan estimated "3,000–5,000 clean PAC beats" yield.

**The reality:** This filter has two compounding bugs that we didn't catch until we ran it against the actual data.

#### 7.9.3 Stage 1 — Bug #1: Substring Matching Picked Up Pacemakers

The PTB-XL `scp_codes` column is a Python dict literal string like `{'NORM': 80.0, 'PAC': 0.0, 'SR': 0.0}`. The substring `'PAC'` matches three completely different things:

| Substring match | What it actually is | Useful for S-class? |
|---|---|---|
| `'PAC'` in `{'PAC': 100.0}` | Real premature atrial contraction | ✅ Yes |
| `'PAC'` in `{'PAC': 0.0}` | PAC mentioned but **ruled out** (likelihood = 0) | ❌ No — noise |
| `'PAC'` in `{'PACE': 100.0}` | **Pacemaker rhythm** (PACE ≠ PAC) | ❌ No — totally different |

The original notebook's filter caught all three. Looking at the user's actual data dump:

```
ecg_id 144:  {'PACE': 100.0}                                    ← pacemaker
ecg_id 257:  {'ASMI': 50.0, 'IMI': 100.0, 'PAC': 0.0, ...}      ← PAC ruled out
ecg_id 421:  {'NORM': 80.0, 'PAC': 0.0, 'SR': 0.0}              ← PAC ruled out
```

Out of the first 10 records the original filter "matched," zero were real PACs.

#### 7.9.4 Stage 2 — Bug #2: Likelihood = 0 Means "Ruled Out," Not "Present"

Even after fixing the pacemaker false positive, we still had the `PAC: 0.0` problem. PTB-XL's `scp_codes` is a dict of `{diagnosis_code: likelihood}` where likelihood is a 0–100 confidence score from the annotator. A likelihood of 0 means "this diagnosis was considered and rejected" — **not** "this diagnosis is present at low confidence."

The corrected filter parsed the dict and required `float(d['PAC']) > 0`:

```python
def has_real_pac(scp_str):
    d = ast.literal_eval(scp_str)
    if 'PAC' in d and float(d['PAC']) > 0:
        return True
    if 'SVPB' in d and float(d['SVPB']) > 0:
        return True
    return False
```

We validated this against the user's data. The filter was correct. The result was devastating:

```
PTB-XL real PAC records (PAC likelihood > 0): 37
PTB-XL total records in CSV:                  21,799
  → Real PAC prevalence: 0.170% of PTB-XL
```

**37 records.** Not 700. Not 398. **37.**

At ~5 PAC beats per record (10-second clips, PACs are sparse), the expected yield was **~150 clean PAC beats** — far below the 1,000-beat sprint floor.

#### 7.9.5 Stage 3 — The CPSC2018 Pivot

At this point the user surfaced CPSC2018 statistics:

| Class | Records |
|---|---:|
| Normal | 918 |
| AF | 1,098 |
| I-AVB | 704 |
| LBBB | 207 |
| RBBB | 1,695 |
| **PAC** | **556** |
| PVC | 672 |
| STD | 825 |
| STE | 202 |

**556 PAC records** — 15× more than PTB-XL's 37. CPSC clips are also 6–60 seconds (vs PTB-XL's 10 seconds), so each record yields more beats. We added CPSC extraction to the notebook as the primary external S source.

But this raised a question: **why does PTB-XL only have 37 PAC records when the published literature suggests it has hundreds?**

#### 7.9.6 Stage 4 — The Discovery: PhysioNet Challenge 2021 Re-Annotation

The user then surfaced a much larger dataset card: **PhysioNet Challenge 2021** — an 88,253-record umbrella dataset that aggregates 8 source databases (including PTB-XL and CPSC2018) with SNOMED-CT re-annotation.

The Challenge 2021 dataset card showed:

| Diagnosis | Count |
|---|---:|
| PAC | **3,041** |
| SVPB | 224 |
| PVC | 1,279 |
| VPB | 659 |

We pulled the official `dx_mapping_scored.csv` from the `physionetchallenges/evaluation-2021` GitHub repo. The relevant rows:

```
premature atrial contraction,284470004,PAC,616,73,3,0,398,639,258,1054,3041
supraventricular premature beats,63593006,SVPB,0,53,4,0,157,1,0,9,224
```

The columns are: `Dx, SNOMEDCTCode, Abbreviation, CPSC, CPSC_Extra, StPetersburg, PTB, PTB_XL, Georgia, Chapman_Shaoxing, Ningbo, Total, Notes`

**PTB-XL column shows 398 PAC + 157 SVPB = 555 S-class records.** Not 37.

#### 7.9.7 Stage 5 — Root Cause of the 37-vs-398 Discrepancy

Two different annotation systems were applied to the same PTB-XL records:

| Annotation source | Method | PAC count |
|---|---|---:|
| PTB-XL native (`ptbxl_database.csv` `scp_codes` column) | Human expert annotators, strict criteria, likelihood scores | 37 |
| PhysioNet Challenge 2021 re-annotation (`.hea` file `# Dx:` field, SNOMED-CT codes) | Automated + physician review, looser criteria, binary presence/absence | 398 |

The 361-record gap is the difference between:
- **PTB-XL native:** "This record has a PAC with high confidence (likelihood ≥ 50)" — 37 records
- **Challenge 2021:** "This record contains a PAC somewhere, even as a secondary finding" — 398 records

The Challenge 2021 annotation is the one used by the cardiology research community. It's what's in the `.hea` file's `# Dx:` line as SNOMED-CT codes:

```
# Dx: 426783006 284470004 164909002
       ↑          ↑          ↑
       NSR        PAC        LBBB
```

**We were reading the wrong file.** The notebook was parsing `ptbxl_database.csv` (strict annotations) instead of the `.hea` files (PhysioNet's looser re-annotations).

#### 7.9.8 Stage 6 — The Good News: No Re-Download Needed

The .hea files we already downloaded from PTB-XL contain the Challenge 2021 SNOMED codes in their `# Dx:` field. We have 21,544 .hea files on disk (out of 21,837). The fix is a one-function change in the notebook — no new download, no new dependency.

#### 7.9.9 The Fix

Replace the CSV-based PAC filter with .hea-based SNOMED-CT code lookup.

**Before (broken):**
```python
# Reads ptbxl_database.csv scp_codes column (strict PTB-XL native annotation)
pac_mask = ptbxl_db['scp_codes'].apply(has_real_pac)  # finds 37 records
pac_records = ptbxl_db[pac_mask]
```

**After (correct):**
```python
# Reads .hea file # Dx: line (PhysioNet Challenge 2021 re-annotation)
PAC_SNOMED = {'284470004', '63593006'}  # PAC + SVPB (scored as same diagnosis)

def get_ptbxl_snomed_codes(ecg_id):
    sub = f"{ecg_id // 1000 * 1000:05d}"
    hea_path = f'{PTBXL_PATH}/records100/{sub}/{ecg_id:05d}_lr.hea'
    with open(hea_path) as f:
        for line in f:
            if line.startswith('# Dx:'):
                return set(line.strip().split()[2:])
    return set()

# Iterates all 21,544 .hea files on disk, finds 555 S-class records
pac_records = [rid for rid in all_ecg_ids
                if PAC_SNOMED & get_ptbxl_snomed_codes(rid)]
```

#### 7.9.10 Why Option (B) — Keep CSV for Metadata, .hea for Labels

Two reasons:

1. **The CSV has patient metadata we want for analysis.** `ptbxl_database.csv` columns: `patient_id`, `age`, `sex`, `height`, `weight`, `nurse`, `site`, `device`, `baseline_drift`, `static_noise`, `burst_noise`, `electrodes_problems`, `extra_beats`, `pacemaker`, `strat_fold`. The .hea file has none of this. For KB Section 44 we'll want to slice results by patient demographics — that requires the CSV.

2. **Defensive redundancy.** If the .hea Dx field is missing or malformed for a record (rare but possible), we can fall back to the CSV's `scp_codes` as a secondary check.

#### 7.9.11 Expected Yield After Fix

| Source | S-class records | Beats per record | Total beats (est.) |
|---|---:|---:|---:|
| PTB-XL (.hea SNOMED filter) | 555 | ~3 (10s clips, sparse PACs) | 1,500–2,500 |
| CPSC 2018 (REFERENCE.csv filter) | 616 | ~10 (6–60s clips, dominant rhythm) | 5,000–8,000 |
| **Combined** | **1,171** | — | **7,000–10,000** |

After prematurity<0.95 filter (typically 70–90% survival):
- **Expected clean PAC beats: 5,000–9,000**
- Sprint plan floor (1,000): ✅ PASS
- v9.5 partial floor (200): ✅ PASS

#### 7.9.12 Lessons Learned

**Lesson 1: Substring Matching on Dict-Encoded Fields Is a Bug Factory.** `scp_codes.str.contains('PAC')` was a three-line bug that took three debugging rounds to surface. The PTB-XL `scp_codes` field is a stringified Python dict — substring matching on it can match keys, values, or substrings of unrelated keys (`PAC` ⊂ `PACE`). The correct pattern is `ast.literal_eval()` then key lookup. This applies to any field that's a stringified data structure.

**Lesson 2: Always Cross-Check Dataset Statistics Against the Source Paper.** The sprint plan's "~700 PAC records in PTB-XL" assumption was never sourced. If we had pulled the PhysioNet Challenge 2021 paper (`Perez Alday et al. 2020`) on Day 0, we'd have seen the official `dx_mapping_scored.csv` table and known PTB-XL has 555 S-class records, not 700.

**Lesson 3: PTB-XL Has Two Annotation Layers — Be Explicit About Which One You're Using.**

| Layer | Where | Strictness | PAC count |
|---|---|---|---:|
| PTB-XL native | `ptbxl_database.csv` `scp_codes` | Strict (human expert, likelihood-scored) | 37 |
| Challenge 2021 re-annotation | `.hea` file `# Dx:` field | Loose (automated + physician review, binary) | 398 |

These are not interchangeable. The 10× gap is real — it reflects different annotation criteria, not data corruption.

**Lesson 4: When a Filter Returns a Surprising Number, Don't Trust It.** When the corrected CSV filter returned 37 PAC records, the right response was "this contradicts the published literature — something is wrong with our filter or our understanding of the data." Instead we initially accepted it and pivoted to CPSC2018.

**Lesson 5: SNOMED-CT Codes Are the Source of Truth for PhysioNet Challenges.** PTB-XL's `scp_codes` uses its own custom abbreviation system. PhysioNet Challenge 2020/2021 re-annotated everything with SNOMED-CT codes (`284470004` for PAC, `63593006` for SVPB, `10370003` for PACE, etc.). The SNOMED codes are unambiguous, externally validated, and in the .hea file (so they travel with the data).

---

## 8. Known Issues & Limitations

*Source: KB v2.0 Section 7; KB v1.3 Section 14 (Technical Debt Register).*

### 8.1 Honest System Limitations

The CNN performs beat-level N/S/V morphology classification. It does not directly diagnose AFib.
AFib screening is handled separately by RR-irregularity logic in the Clinical Event Engine.
S/PAC performance remains weak and must be reported honestly.
MIT-BIH/PhysioNet offline validation does not prove performance on the final wearable hardware.
Hardware-domain validation is still required (wrist Lead I signal quality unproven).
Motion artifact reduction via NLMS covers right-wrist motion only; wire and left-arm artifacts are unaddressed (in the wire topology; the compact single-housing topology eliminates this).
"Multi-day" battery life is an architecture target unless measured on final firmware/hardware.
Gel electrodes limit continuous wear to 7-14 days.
The wire from left arm to wrist PCB is the single largest unmitigated noise and usability risk (compact topology eliminates).
PPG/SpO₂ is not implemented. MAX30102 is provisioned for future expansion only.
This is a research/hackathon prototype, not a diagnostic medical device.

### 8.2 DSP Debt

| Debt | Risk | Fix |
|---|---|---|
| R-peaks not manually validated | HR/RR may be plausible but wrong | manual annotation workflow |
| NLMS-only gain not isolated | overclaiming artifact reduction | compute bandpass+notch → NLMS only |
| hardcoded IMU baseline | false motion gating | median/MAD calibration |
| ESP32-only validation | not final hardware | repeat on EFR32 |
| Python-only DSP | not embedded proof | C fixed-point parity |

### 8.3 ML Debt

| Debt | Risk | Fix |
|---|---|---|
| S generalization weak | poor clinical relevance | external data integration (v11) |
| label cleaning not clinically reviewed | questionable S labels | cardiologist review |
| model version drift | confusion | model manifest |
| quantization/inference mismatch | model cannot run on board | TFLM operator audit |
| metrics across versions inconsistent | wrong decision-making | canonical metrics JSON |

### 8.4 Firmware Debt

| Debt | Risk | Fix |
|---|---|---|
| `tarang_ai_process()` not proven | no true embedded ML | implement TFLM runtime |
| tensor arena unknown | RAM failure | measure |
| AI timing unknown | power/latency risk | timing counters |
| power unknown | 30-day claim unsupported | current measurement |
| board part mismatch in docs | memory/config risk | confirm physical board |

### 8.5 Documentation Debt

| Debt | Risk | Fix |
|---|---|---|
| too many reports | scattered truth | this KB becomes source |
| v8/v9 naming drift | wrong baseline | experiment registry |
| clinical wording risk | overclaiming | claim guardrails |
| raw notebooks too large | hard review | compact notebook cards |
| old sections conflict | stale decisions | supersession log |

### 8.6 The S-Class Ceiling (Honest Structural Limit)

Even after the SPKI fix and v11 Lead I native training, beat-level S (PAC) detection may remain weak because:

- 18-patient MIT-BIH training ceiling (resolved by v11 Lead I native training)
- 41% label noise on S beats (partially mitigated by 0.95 prematurity filter)
- 4,500× model-size gap vs published SOTA (Hannun et al., 91MB model with S F1 0.477 vs Tarang's ~71KB model with target S F1 0.25-0.35)

This is a structural ceiling, not a data-diversity problem (confirmed by v10's 4 experiments).

### 8.7 The V (PVC) Detection Tradeoff

Even after the SPKI fix, beat-level V detection may remain weaker than N (PVCs have wider, notched QRS morphology that produces different MWI characteristics). The deployment strategy:
1. Annotation-centered oracle extraction for V/S training data
2. Clinical Event Engine (RR-irregularity-based) as primary real-world PVC-flagging mechanism
3. Document the tradeoff with real numbers once post-fix validation is complete

### 8.8 WHO_AM_I Mismatch (Active Blocker)

Production SLCP specifies ICM-20648 (WHO_AM_I = 0xE0); bring-up hardware reported MPU6500 (WHO_AM_I = 0x70); `tarang_nlms.c` checks for 0x68 (MPU6050). All three differ. The check will fail on both bring-up hardware and the production part. Must be resolved before production flash — either remove the hard check or update to the actual production part number.

---

## 9. Architecture Decision Records (ADRs)

*Source: KB v2.0 Section 8; KB v1.3 Section 15; KB v1.4 Section 33.4. Where KB v1.3 and v2.0 differ, KB v2.0 is canonical.*

### ADR-001 — 250 Hz Firmware-Aligned Pipeline
All training/inference windows match 250 Hz firmware acquisition. Accepted.

### ADR-002 — Frame-Based DSP
256-sample ECG frames for DSP and firmware handoff. Accepted.

### ADR-003 — Pan-Tompkins Before ML
R-peak detection occurs before beat classification. Accepted.

### ADR-004 — NLMS Is Motion Artifact Filter
IMU-assisted NLMS as DSP stage. Partial coverage (right-wrist only). Accepted with documented limitation.

### ADR-005 — Gated AI, Not Continuous CNN
DSP gate determines AI inference. 30-day battery impossible with continuous CNN. Accepted.

### ADR-006 — Cascade/Gated ML Direction
Deployment path is gated/cascade, not continuous single softmax. Accepted.

### ADR-007 — v9.3 MIT-BIH Ceiling
v9.3 is the MIT-BIH Lead II ceiling for current architecture family. Accepted. Superseded by ADR-015.

### ADR-008 — External Data Is Priority for S
External datasets needed for S improvement. Accepted. v10 failed (lead mixing). v11 is the resolution.

### ADR-009 — No Clinical Claims
Research prototype until external validation. Non-negotiable.

### ADR-010 — Beat Classification + Clinical Event Engine Architecture Split
CNN = beat morphology (N/S/V). Engine = rhythm detection (AFib, patterns). Accepted.

**Full text (KB v1.3):** Tarang's deployment architecture is a two-stage system: (1) a gated CNN performs **beat-level morphology classification** (N/S/V) per R-peak; (2) a deterministic **Clinical Event Engine** (no neural network) consumes the beat stream and produces **rhythm-level clinical event summaries** (PAC/PVC count and burden, couplets, triplets, bigeminy, trigeminy, ventricular/supraventricular runs, RR statistics, AF screening via Lorenz/Poincaré + RR irregularity).

**Reason:** The CNN is a morphology classifier, not a rhythm classifier. AFib, VT, NSVT, bigeminy, trigeminy, couplets, triplets, and sustained arrhythmias all require temporal analysis over multiple beats — a beat-level CNN cannot diagnose them directly. Conflating beat classification with rhythm diagnosis creates a category error. The split also: (a) reduces flash/RAM/latency (deterministic logic is ~1 KB vs 500 KB+ for a long-window NN); (b) allows independent validation (beat classifier on MIT-BIH/INCART/SVDB/PTB-XL/CPSC2018; Clinical Event Engine on AFDB and rhythm-level annotated datasets); (c) matches the per-beat BLE event telemetry architecture already specified in firmware; (d) follows published Holter workflow: beat detection → beat classification → clinical event aggregation → clinical summary.

Status: Accepted (2026-07-06).

### ADR-011 — PTB-XL SNOMED-CT Filter via .hea Dx Field
PTB-XL PAC extraction uses .hea #Dx: SNOMED codes (`284470004` for PAC, `63593006` for SVPB), not scp_codes substring. Accepted (2026-07-06). Replaces the CSV substring filter used in v9.5 notebook original draft.

**Reason:** PTB-XL has two annotation layers. The native `scp_codes` column uses strict human-expert annotation with likelihood scores (37 PAC records with likelihood > 0). The PhysioNet Challenge 2021 re-annotation, stored in the `.hea` file's `# Dx:` line as SNOMED-CT codes, uses looser criteria and finds 398 PAC + 157 SVPB = 555 S-class records in the same files. The 15× discrepancy is the difference between strict annotation (likely-true PACs only) and challenge-standard annotation (any PAC mention, including secondary findings). The challenge-standard annotation is the externally validated label set used by the cardiology research community and is appropriate for training data. The substring filter `scp_codes.str.contains('PAC')` was additionally broken — it matched `PACE` (pacemaker rhythm, 287 records) and `PAC: 0.0` (ruled-out PACs). The .hea SNOMED-CT filter is unambiguous (`284470004` is PAC, `10370003` is PACE — no collision).

### ADR-012 — CPSC2018 as Primary External S-Class Source
CPSC2018 (China Physiological Signal Challenge 2018, 6,877 records, 556 PAC records per official REFERENCE.csv) is the **primary** external S-class data source. PTB-XL (555 S-class records after ADR-011 fix) is **supplementary**. Accepted (2026-07-06).

**Reason:** CPSC clips are 6–60 seconds long with the named arrhythmia as the dominant rhythm, yielding ~10 PAC beats per record (vs PTB-XL's 10s clips with sparse PACs yielding ~3 beats/record). Expected yield: CPSC 5,000–8,000 PAC beats vs PTB-XL 1,500–2,500. CPSC's REFERENCE.csv uses unambiguous 3-letter labels (`PAC`, `PVC`, `N`, etc.) — no substring collision bug. CPSC is also a different acquisition system (Chinese hospitals, 500 Hz) which provides the patient-diversity signal needed to break the 18-patient MIT-BIH overfitting trap.

### ADR-013 — Deployment Architecture: Cascade + Rhythm Engine
Two-layer NN cascade (Gate + SV head) feeding a non-NN Clinical Event Engine. **Reject** three alternative architectures considered: (a) single 4-way beat classifier softmax (already falsified in v8.x line — V/S head competition killed S recall); (b) long-timeframe single NN model on 5–30s windows (rejected — 200KB+ model size busts the 50KB flash budget, EFR32MG26 MVP accelerator lacks efficient long-window kernels, and long-window models don't fix the S morphology generalization problem); (c) end-to-end arrhythmia classification on device (rejected — PhysioNet Challenge 2021 winners use 50M+ parameter cloud models, not feasible in 7-day sprint). Accepted (2026-07-06). Locks the deployment architecture for the firmware sprint (Day 8+).

### ADR-014 — Dataset Governance Policy
7-point checklist for all future datasets:
1. read original publication
2. read official metadata documentation
3. understand annotation hierarchy
4. verify reported class distributions
5. identify ontology mappings (SCP, SNOMED, Challenge labels)
6. reproduce published statistics
7. block model training until discrepancies are resolved

Accepted (2026-07-06). The PTB-XL Fiasco (Section 7.9) was caused by skipping steps 1–4. The dataset was correct; the extraction logic was wrong because we didn't understand PTB-XL's two annotation layers. The 7-point checklist would have caught this in 15 minutes; instead we lost 4 hours of debugging.

### ADR-015 — Lead I Native Training (v11)
**Decision:** Retrain gate + SV head from scratch on Lead I (PTB-XL + CPSC2018). No MIT-BIH in training. MIT-BIH becomes secondary cross-check only.

**Reason:** v9.3 trained on Lead II, deployed on Lead I hardware — fundamental lead mismatch. v10 tried to patch with external data, failed because it mixed leads. v11 eliminates the mismatch at the root.

**Status:** Approved (2026-07-11). 3-week sprint.

**Expected outcome:** S F1 0.25-0.35, N F1 ~0.90+, V recall ~0.85+. S still below AAMI 0.40 — structural capacity ceiling remains.

### ADR-016 — Model Size: 71KB Accepted
**Decision:** Accept 71KB total model size (Gate + SV Int8 TFLite). Do NOT shrink architecture to meet self-imposed 50KB target.

**Reason:** EFR32MG26 has 3200 KB flash. 71KB is 2.2% of total flash. The 50KB target was unnecessary. ML Profiler confirms 358 KB total flash used (app + framework + models). MVP accelerator handles the model efficiently (23ms total inference).

**Status:** Accepted (2026-07-11).

### ADR-017 — PPG/SpO₂ Dropped from Current Claims
**Decision:** Remove all PPG and SpO₂ claims from PPT and competition materials. MAX30102 remains on BOM as "future expansion."

**Reason:** Zero PPG code exists in notebook, pipeline, or firmware. Claiming PPG fusion or SpO₂ is unsupported and will sink credibility in Q&A.

**Status:** Accepted (2026-07-11).

### ADR-018 — Battery Claim Downgraded to "Multi-Day"
**Decision:** Change all "30-day battery" claims to "multi-day" until measured on final hardware.

**Reason:** Gel electrodes limit to 7-14 days. No current measurement exists. 30-day is architecture projection only.

**Status:** Accepted (2026-07-11).

### ADR-019 — Arrhythmia Detection is the Product, Not Beat Classification
**Decision:** Position Tarang as an arrhythmia detection wearable, not a beat classifier. The CNN is the enabling technology; the Clinical Event Engine is the product.

**Reason:** Users, doctors, and judges care about arrhythmias (AFib, VT, bigeminy), not individual beat labels. AFib detection is lead-agnostic (RR-based), making it robust to Lead I/Lead II mismatch. The Engine provides explainable, clinically-named outputs.

**Status:** Accepted (2026-07-11).

### 9.1 The 12 Dilemmas Catalogued and Resolved

*Source: Architecture Resolution FINAL Part 1.*

Throughout the v9-v10 sprint, 12 interlocking dilemmas emerged that appeared to force compromises. The Architecture Resolution FINAL document proved each was a false dilemma:

| # | Dilemma | Resolution |
|---|---|---|
| 1 | Lead Geometry vs ML Training Domain | Train on Lead I, deploy on Lead I. Zero lead mismatch. PTB-XL + CPSC provide ~28,000 Lead I records from thousands of patients. |
| 2 | Gel vs IMU | Compact housing with dry (or gel-optional) electrodes. IMU co-located. Electrode material is NOT the deciding factor — electrode placement is. |
| 3 | Continuous vs Battery | Continuous = always-on DSP + Clinical Event Engine, NOT continuous CNN. CNN wakes only on suspicious beats (<0.1% at rest). |
| 4 | ML Accuracy vs Data | 28,000 Lead I records > 48 Lead II records. v11 trains Lead I NATIVE — no mixing, no mismatch. |
| 5 | S-Class Ceiling | 18-patient ceiling is gone (v11 Lead I native training). Model-capacity ceiling remains (honest). 20KB vs Hannun's 91MB SOTA — structural limit. |
| 6 | Clinical Relevancy | Clinical claims come from the Clinical Event Engine, not just the CNN. PVC: CNN V-class (AAMI-compliant). AFib: RR-irregularity (≥95% sensitivity per published literature). |
| 7 | Apple Watch Benchmark | Tarang is not an Apple Watch competitor. It's a Holter replacement. Different product category. |
| 8 | Second Electrode | Both electrodes on the back of the case, 3-5 cm apart. No user action required (unlike Apple Watch's crown touch). |
| 9 | IMU NLMS Validity | Compact housing = IMU co-located with electrodes = NLMS valid. 3.3 dB SNR improvement validated. |
| 10 | MIT-BIH Benchmark | Lead I test set is the correct benchmark for Lead I deployment. MIT-BIH is secondary cross-check with honest disclaimer. |
| 11 | Architecture Freeze | Same architecture, new training data. No architecture change needed. The architecture that failed on MIT-BIH Lead II gets a fair chance on Lead I. |
| 12 | v10 Negative Result | v10 failed because it mixed leads. v11 trains Lead I native. The v10 negative result is valuable evidence that lead mixing doesn't work. |

### 9.2 Constraint Satisfaction Matrix

Every constraint the team said "we cannot compromise" is satisfied:

| Constraint | How satisfied | Evidence |
|---|---|---|
| Battery life (30+ days) | Event-driven CNN (<0.1% duty at rest), always-on DSP at ~40µA | Tier 0/1/2/3 design |
| ML accuracy | Lead I training on 28K records, thousands of patients, zero lead mismatch | v11 design |
| Clinical relevancy | Lead I is FDA-cleared (Apple Watch, KardiaMobile); Clinical Event Engine handles AFib/VT/patterns; AAMI compliance on N and V | Capability matrix |
| IMU noise subtraction | IMU co-located with electrodes in compact housing; NLMS valid | v9 DSP validation (3.3 dB SNR improvement) |
| Architecture | Gate + SV cascade + Clinical Event Engine (ADR-013) — unchanged | KB Section 2 |
| Continuous monitoring | Tier 0 always-on DSP + Clinical Event Engine runs 24/7; CNN event-driven | Tier 0 design |
| Compact form factor | Single wrist housing, no harness, both electrodes on case back | Section 2.3 |

---

## 10. Claims Register

*Source: KB v2.0 Section 6 (canonical).*

### 10.1 DEFENSIBLE Claims (you can say these)

1. ✅ On-device N and V beat classification via INT8 CNN on EFR32MG26 MVP accelerator (V recall ≥85%, AAMI-compliant)
2. ✅ AFib screening via Clinical Event Engine using RR-irregularity analysis (published ≥95% sensitivity; Tarang AFDB validation pending)
3. ✅ Ventricular pattern detection (bigeminy, trigeminy, couplets, triplets, runs, VT) via deterministic Clinical Event Engine
4. ✅ Event-driven CNN architecture (Tier 0 DSP + Tier 1 gate + Tier 2 SV + Tier 3 engine) — CNN wakes on <1% of beats at rest
5. ✅ Edge AI deployment on Silicon Labs EFR32MG26 with MVP accelerator — profiled on real hardware (12.7ms gate, 10.2ms SV)
6. ✅ Lead I ECG acquisition via 3-electrode configuration (IN+ on left arm, IN- on right wrist, RLD on right wrist) — or compact single-housing topology
7. ✅ BLE 5.3 event-driven telemetry (16-byte packets on rhythm change)
8. ✅ HRV metrics (SDNN, RMSSD, pRR50) from RR intervals
9. ✅ NLMS adaptive filtering for wrist-correlated motion artifact (partial coverage, right-wrist only)
10. ✅ Lead I native training on PTB-XL + CPSC2018 (~28K records, thousands of patients)

### 10.2 UNSUPPORTED Claims (do NOT say these)

1. ❌ "30-day battery life" → gel electrodes limit to 7-14 days; no measurement. Say "multi-day." (ADR-018)
2. ❌ "Artifact-free ECG" → NLMS reduces correlated motion only; wire artifacts unaddressed.
3. ❌ "Real-time BPM from ECG + PPG fusion" → PPG not implemented. (ADR-017)
4. ❌ "SpO₂ Level from MAX30102" → not implemented. (ADR-017)
5. ❌ "Multi-Sensor Fusion" → no fusion code.
6. ❌ "AFib detection via 1D-CNN" → AFib is via Clinical Event Engine (RR-based), NOT CNN.
7. ❌ "Hospital-grade" / "clinical-grade diagnosis" → screening only.
8. ❌ "PAC/SVT detection at clinical sensitivity" → S-class is weak, screening only.
9. ❌ "Apple Watch competitor" → different category (Holter-like, not spot-check).
10. ❌ "Zero false alarms" → no system has zero false alarms.
11. ❌ "Holter replacement" → not validated for clinical use.

### 10.3 NEEDS VALIDATION Before Claiming

1. ⚠️ NLMS SNR improvement on EFR32MG26 hardware
2. ⚠️ Lead I model accuracy after v11 retraining
3. ⚠️ TFLite quantization parity (dequantization fix applied, must re-validate)
4. ⚠️ AFib detection sensitivity on AFDB
5. ⚠️ Continuous wear comfort and wire durability
6. ⚠️ 30-day battery (or multi-day) — requires current measurement on final firmware

### 10.4 PPT Corrections Required

| Slide | Current (Wrong) | Corrected |
|---|---|---|
| 10 | "AFib and PVC classification via 1D-CNN" | "PVC detection via on-device CNN. AFib screening via RR-irregularity analysis (Clinical Event Engine)." |
| 10 | "Real-time BPM from ECG + PPG fusion" | "Real-time BPM from ECG R-peaks" (remove PPG) |
| 10 | "SpO₂ Level from MAX30102" | Remove entirely (or "Future expansion") |
| 5 | "Multi-Sensor Fusion" | "IMU-Assisted Motion Filtering" |
| 4 | "Zero false-alarm noise" | "Reduced motion artifact via NLMS adaptive filtering" |
| 4 | "30+ day battery life" | "Multi-day battery life (architecture target)" |
| 8 | "Artifact-free ECG waveform after NLMS filtering" | "Motion-filtered ECG waveform" |

### 10.5 Competition Narrative (Final)

> **Tarang: Continuous Edge-AI Arrhythmia Screening Wearable**
>
> Tarang is a wrist-worn continuous ECG monitor that performs real-time arrhythmia screening on-device. A 4-tier event-driven pipeline ensures 30-day battery life by keeping the CNN asleep >99% of the time at rest.
>
> Tier 0 (always-on DSP) acquires Lead I ECG at 250 Hz, performs NLMS adaptive motion filtering with co-located IMU reference, detects R-peaks via Pan-Tompkins, and computes RR features. Cheap anomaly heuristics wake the CNN only on suspicious beats.
>
> Tiers 1-2 (Gate + SV Head CNN, ~71KB Int8 TFLite) classify beats as N/S/V on the Silicon Labs EFR32MG26 MVP hardware accelerator (23ms total inference). The model is trained natively on Lead I data from PTB-XL + CPSC2018 (~28,000 records, thousands of patients), matching the hardware lead configuration.
>
> Tier 3 (Clinical Event Engine, ~1.5KB deterministic C code) runs on every beat, detecting AFib via RR-irregularity analysis (CoV + pRR50 + RMSSD, ≥95% sensitivity per published literature), ventricular bigeminy, trigeminy, couplets, triplets, runs, and ventricular tachycardia. AFib detection is lead-agnostic — it depends only on RR timing, not beat morphology.
>
> The system achieves AAMI EC57 compliance on V recall (≥85%). S-class (PAC) detection is documented as screening-only due to model capacity constraints (20KB vs published 91MB SOTA). Results are transmitted via BLE 5.3 as 16-byte event packets to a gateway dashboard.
>
> Total model footprint: 71KB on 3200KB flash. RAM arena: 9KB. Inference: 23ms. This is a research prototype, not a diagnostic medical device.

### 10.6 What to Tell the Team

> "The dilemmas are resolved. The answer is: compact wrist hardware (both electrodes on case back = Lead I, IMU co-located = NLMS valid), train on Lead I (PTB-XL + CPSC, 28K records, thousands of patients = no 18-patient ceiling, no lead mismatch), event-driven CNN (Tier 0 always-on DSP + CNN on demand = continuous monitoring + 30-day battery), Clinical Event Engine (AFib + ventricular patterns = clinical relevancy independent of S-class). Every constraint is satisfied. No compromises. The v10 negative result was the proof that lead mixing doesn't work — v11 trains Lead I native. This is the way forward."

---

## 11. Glossary

| Term | Meaning |
|---|---|
| AAMI | Association for the Advancement of Medical Instrumentation (EC57 standard for ECG classifier evaluation) |
| ADR | Architecture Decision Record |
| AFDB | MIT-BIH Atrial Fibrillation Database (used for Clinical Event Engine validation) |
| AFib | Atrial Fibrillation |
| AFE | Analog Front-End (AD8232 or AD8422) |
| Atrial Bigeminy | N-S-N-S pattern (every other beat is supraventricular ectopic) |
| Bigeminy | N-V-N-V-N-V pattern (every other beat is ventricular ectopic) |
| BLE | Bluetooth Low Energy (5.3) |
| Clinical Event Engine | Deterministic, RR-irregularity-based arrhythmia detection (AFib, VT, bigeminy, etc.) |
| CNN | Convolutional Neural Network (Gate + SV Head cascade in Tarang) |
| CoV | Coefficient of Variation (SDNN / mean_rr) — AFib detection metric |
| Couplet | Two consecutive ectopic beats of the same class (S-S or V-V) |
| CPSC2018 | China Physiological Signal Challenge 2018 dataset (6,877 records, primary external S source) |
| DSP | Digital Signal Processing (Tier 0 of Tarang pipeline) |
| EFR32MG26 | Silicon Labs target SoC with MVP accelerator |
| EM2 | Energy Mode 2 (deep sleep on EFR32) |
| F1 | F1 score (harmonic mean of precision and recall) |
| Gate CNN | Tier 1 — N-vs-abnormal classifier (~8KB Int8 TFLite) |
| HRV | Heart Rate Variability |
| IADC | Incremental Analog-to-Digital Converter (EFR32 peripheral) |
| IMU | Inertial Measurement Unit (MPU6050 or ICM-20648, co-located with electrodes) |
| INCART | St. Petersburg INCART 12-lead Arrhythmia Database (external generalization check) |
| LDMA | Linked Direct Memory Access (zero-CPU ECG acquisition on EFR32) |
| Lead I | ECG lead vector from RA to LA (across wrist in Tarang's compact topology) |
| Lead II | ECG lead vector from RA to LL (MIT-BIH's primary lead, mismatched with Tarang hardware) |
| Lorenz Plot / Poincaré Plot | RR_n vs RR_{n+1} scatter plot — AFib irregularity visualization |
| Macro F1 | Mean F1 across all classes (N/S/V) |
| MIT-BIH | MIT-BIH Arrhythmia Database (48 records, 18 patients, Lead II) |
| MVP | Silicon Labs "Micro Voice Plus" hardware accelerator (Conv2D/MaxPool/FC) |
| MWI | Moving-Window Integration (Pan-Tompkins detection branch output) |
| NLMS | Normalized Least Mean Squares adaptive filter (IMU-referenced motion artifact removal) |
| NPKI | Noise Peak running estimate (Pan-Tompkins adaptive threshold) |
| NSVT | Non-Sustained Ventricular Tachycardia |
| Oracle extraction | Beat windows centered on true annotations (not detector output) |
| PAC | Premature Atrial Contraction (S-class) |
| Pan-Tompkins | Real-time QRS detection algorithm (used by v16 DSP, causal/streaming) |
| PPG | Photoplethysmography (NOT IMPLEMENTED in Tarang per ADR-017) |
| PRS | Peripheral Reflex System (zero-CPU EFR32 trigger chain) |
| PVC | Premature Ventricular Contraction (V-class) |
| pRR50 | Proportion of successive RR intervals differing by >50ms (AFib metric) |
| RLD | Right Leg Drive (common-mode rejection reference electrode) |
| RMSSD | Root Mean Square of Successive Differences (HRV metric) |
| RR interval | Time between consecutive R-peaks |
| SDNN | Standard Deviation of NN intervals (HRV metric) |
| SVPB | Supraventricular Premature Beat (synonym for S-class) |
| SNOMED-CT | Systematized Nomenclature of Medicine — Clinical Terms (PhysioNet Challenge 2021 annotation standard) |
| SOS | Second-Order Sections (IIR filter representation) |
| SPKI | Signal Peak running estimate (Pan-Tompkins adaptive threshold) |
| SV Head CNN | Tier 2 — V-vs-S classifier (~18KB Int8 TFLite) |
| SVDB | MIT-BIH Supraventricular Arrhythmia Database |
| SVT | Supraventricular Tachycardia |
| TFLM | TensorFlow Lite Micro (edge inference runtime) |
| TH1 | Primary threshold = NPKI + 0.25 × (SPKI - NPKI) |
| TH2 | Search-back threshold = 0.5 × TH1 |
| Trigeminy | N-N-V-N-N-V pattern (every third beat is ventricular ectopic) |
| Triplet | Three consecutive ectopic beats of the same class |
| V-Run | ≥3 consecutive V beats (pre-VT indicator) |
| VT | Ventricular Tachycardia (≥5 V + HR>100) |
| WHO_AM_I | IMU identification register (production mismatch documented as active blocker) |
| XQRS | wfdb's offline QRS detector (used by v15 for training; replaced by Pan-Tompkins in v16) |

---

## 12. Document History

### 12.1 Source Files Merged

This mega-document was created by merging and deduplicating the following source files, in order of authority:

| # | Source File | Size | Date | Role in Mega-Doc |
|---|---|---:|---|---|
| 1 | `Tarang_DSP_Knowledge_Base.md` | 18,027 B | 2026-08-03 | **Authoritative DSP reference (v16).** Source for Section 3 (DSP Pipeline) in entirety. Most recent DSP iteration with SPKI lock-in root cause + fix. Supersedes earlier DSP descriptions in KB v1.3. |
| 2 | `Tarang_KB_v2_0.md` | 29,342 B | 2026-07-11 | **Canonical source-of-truth KB.** Supersedes KB v1.0, v1.1, v1.2, v1.3, v1.4. Source for Sections 2 (Architecture), 4.6 (Profiling), 5.8 (Capability Matrix), 6.11 (Noise Inventory), 10 (Claims Register). ADRs 015-019 are v2.0 additions. |
| 3 | `Tarang_Architecture_Resolution_FINAL.md` | 32,866 B | 2026-07-07 | **Definitive architecture resolution.** Source for the 12 Dilemmas (Section 9.1), the compact wrist topology (Section 2.3), and the Constraint Satisfaction Matrix (Section 9.2). Locks Lead I hardware + Lead I training as the canonical direction. |
| 4 | `Tarang_Arrhythmia_Pipeline_Design.md` | 13,896 B | 2026-07-07 | **Clinical Event Engine firmware design.** Source for the per-beat pipeline pseudocode (Section 5.7), AFib firmware pseudocode (Section 5.12), ventricular pattern pseudocode (Section 5.11), BLE event packet (Section 6.5), power budget (Section 6.6), and competition narrative (Section 10.5). |
| 5 | `Tarang_Source_of_Truth_KB_v1_3.md` | 110,062 B | 2026-07-06 | **Original source-of-truth KB v1.3.** Largest source file (~2437 lines). Source for: ML experiment history v8.7→v9.4 (Section 4.2), firmware rules and acceptance gates (Section 6), artifact/repo organization (Section 6.14), technical debt register (Section 8.2-8.5), sprint roadmap (Section 7.7), and the full ADR-010/011/012/013/014 text. Superseded by KB v2.0 for architecture-level decisions but preserved for ML history depth. |
| 6 | `Tarang_KB_v1_4_Update.md` | 31,846 B | 2026-07-07 | **KB v1.4 update.** Source for: v10 negative result (Section 4.3), Clinical Event Engine full design (Section 5.4 algorithms), event-driven CNN trigger logic (Section 2.1 Tier 0 heuristics), arrhythmia capability matrix (Section 5.8), PPT correction notes (Section 10.4). |
| 7 | `v95_pac_extraction_postmortem.md` | 19,668 B | 2026-07-06 | **PTB-XL PAC extraction postmortem.** Source for Section 7.9 in entirety. Deep-dive investigation that produced ADR-011 (PTB-XL SNOMED-CT filter via .hea Dx field). |

### 12.2 Deduplication Strategy

The following content was deduplicated by keeping the most recent or most authoritative version:

| Content Area | Source Conflict | Resolution |
|---|---|---|
| 4-tier pipeline architecture | Appears in 5 of 7 source files | Used KB v2.0 Section 1.1 as canonical (LOCKED status). Earlier versions preserved in ADR context. |
| Hardware topology (wire vs compact housing) | KB v2.0 documents wrist+wire; Architecture Resolution FINAL locks compact single-housing | Architecture Resolution FINAL supersedes (2026-07-07 vs 2026-07-11, but FINAL explicitly supersedes wire design). Both documented in Section 2.3 with compact variant flagged as canonical. |
| ML metrics | KB v1.3 (v9.3 ceiling), KB v1.4 (v10 negative), KB v2.0 (v11 approved) | v9.3 metrics preserved as current production baseline (Section 4.1); v10 documented as negative result (Section 4.3); v11 documented as approved next step (Section 4.4). |
| Clinical Event Engine design | KB v1.4 Section 30 (detailed), KB v2.0 Section 3 (condensed) | KB v1.4 Section 30 preserved in full (Section 5 of mega-doc) — it's the most detailed design and v2.0 condensed only because v1.4 was finalized. |
| ADRs | KB v1.3 (ADRs 001-014), KB v2.0 (ADRs 001-019, condensed) | Full ADR text from KB v1.3 preserved for ADRs 010-014; KB v2.0 condensed versions of 001-009 preserved; KB v2.0 additions 015-019 preserved in full. |
| DSP description | KB v1.3 Section 6 (brief), DSP KB v16 (detailed, fixed) | DSP KB v16 is authoritative (Section 3 in entirety). KB v1.3 DSP notes preserved where they reference validation scripts and acceptance gates. |
| RR feature count | "7 RR features" (KB v1.3, v1.4, v2.0, Arrhythmia Pipeline) vs "4 causal RR features" (DSP KB v16) | Both preserved with explicit historical note in Section 3.3. The 4-feature set is canonical for the streaming DSP path; 7 was a superset that included non-causal statistics later dropped. |
| Model size | "<50KB target" (KB v1.3) vs "71KB accepted" (KB v2.0 ADR-016) | ADR-016 supersedes — 71KB is the production size. KB v1.3's 50KB target noted as historical context. |
| Battery claim | "30+ day battery" (KB v1.3, Arrhythmia Pipeline) vs "multi-day" (KB v2.0 ADR-018) | ADR-018 supersedes — "multi-day" is the canonical claim. "30+ day" preserved as architecture projection only. |
| AFib detection attribution | "AFib via 1D-CNN" (PPT, wrong) vs "AFib via Clinical Event Engine" (KB v1.4 Section 33) | KB v1.4 Section 33 correction is canonical. PPT correction required (Section 10.4). |
| PPG/SpO₂ | Present in PPT, absent in pipeline/firmware | ADR-017 supersedes — PPG/SpO₂ dropped from current claims. |

### 12.3 Supersession Lineage

```
KB v1.0 (2026-06-??)
  ↓
KB v1.1 (2026-06-??) — added ML experiment log v8.7→v9.4 as Section 23
  ↓
KB v1.2 (2026-07-02) — added Stage Definition of Done matrix, RR/DSP failure-mode taxonomy, stress-test verdict logic
  ↓
KB v1.3 (2026-07-06) — added ADRs 010-014, PTB-XL Fiasco, v9.5 sprint plan, full Clinical Event Engine spec (Section 24)
  ↓
KB v1.4 (2026-07-07) — added v10 negative result (Section 29), Clinical Event Engine full design (Section 30), CNN trigger logic (Section 31), capability matrix (Section 32), PPT corrections (Section 33)
  ↓
Architecture Resolution FINAL (2026-07-07) — resolved 12 dilemmas, locked compact wrist topology, locked Lead I native training
  ↓
KB v2.0 (2026-07-11) — supersedes all prior. Locked architecture. ADRs 015-019 added. Lead I native training approved.
  ↓
DSP Knowledge Base v16 (2026-08-03) — root cause found and fixed for SPKI lock-in. Pending 75-record re-validation.
```

### 12.4 Mega-Document Construction Notes

- **Total source content:** ~256 KB across 7 files (after deduplication of repeated architecture descriptions, the canonical content is ~210 KB).
- **Section coverage:** All 12 requested top-level sections present.
- **Technical detail preservation:** All equations, code snippets, ADRs, claims registers, and experimental result tables preserved verbatim from sources.
- **Conflict resolution policy:** KB v2.0 supersedes KB v1.3/v1.4 for architecture-level decisions; DSP KB v16 supersedes earlier DSP descriptions; Architecture Resolution FINAL supersedes both for hardware topology.
- **Historical context preserved:** Older sections (v1.3 ML experiment log, v1.4 v10 negative result) are preserved as historical record, not removed, because they document the evidence trail that led to the final architecture decisions.

### 12.5 Next Actions After This Document

Per KB v2.0 Section 9 (Implementation Priority):

1. v11 Lead I retraining (notebook + train) — Mahdi — 1 week
2. Wire `tarang_ai_process()` in firmware — Kedar — 1 week
3. Implement Clinical Event Engine in C — Kedar — 3 days
4. Validate AFib on AFDB — Mahdi — 1 day
5. BLE event packet implementation — Kedar — 2 days
6. Dashboard (Raspberry Pi + Python) — Pal — 2 days
7. Video demo recording — Team — 1 day
8. Correct PPT (remove PPG, fix AFib attribution) — Team — 0.5 day
9. GitHub repo hygiene (topics, license, README) — Team — 0.5 day

Plus DSP-side (per Tarang DSP KB v16 Section 11):

1. Re-run full 75-record diagnostic with fixed DSP — confirm N recall ≥ 0.90, 0 broken records
2. Re-run coupling-interval analysis — determine if V recall is now a known limitation or a bug
3. Generate golden vectors from the fixed pipeline
4. Port to firmware C — one DSP stage at a time, checking each against its golden vector
5. Integrate with frozen v15 model — confirm window geometry, feature order, scaling match
6. Bench test on hardware — known ECG strip through full chain
7. On-body testing — only after bench test looks sane

---

**End of TARANG_SYSTEM_ARCHITECTURE.md — mega-document.**

*This document supersedes all 7 source files for day-to-day reference. The source files remain authoritative for their specific domains: DSP KB v16 for DSP, KB v2.0 for architecture decisions, Architecture Resolution FINAL for the 12 dilemmas and compact topology, KB v1.4 Section 30 for the Clinical Event Engine firmware spec, KB v1.3 Section 23 for the v8.7→v9.4 ML experiment history, and v95_pac_extraction_postmortem for the PTB-XL filter investigation.*
