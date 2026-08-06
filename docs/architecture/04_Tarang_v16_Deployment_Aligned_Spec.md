# Tarang v16 — Deployment-Aligned ML and DSP Build Specification

**Project:** Tarang  
**Version:** v16 planning specification  
**Status:** Implementation brief for an AI coding agent  
**Primary goal:** Rebuild the current v15 ML pipeline around one stateful, causal, deployment-oriented DSP reference, then retrain, quantize, validate, and export the cascade without silently changing the model architecture.  
**Important:** This document is a target specification. It is not evidence that v16, the DSP, the EFR32 inference path, battery life, or clinical performance have already been validated.

---

# 0. Agent mandate

Build a new version named **v16**. Do not overwrite v15 or its artifacts.

The required source files are:

```text
Tarang_v16_Deployment_Aligned.ipynb
tarang_dsp_reference.py
tarang_v16_validation.py
```

The notebook is the orchestration layer. The two Python files contain reusable implementation and validation logic.

Generated artifacts must include:

```text
artifacts/v16_runs/<RUN_ID>/
├── 00_config/
│   ├── config.json
│   ├── environment.json
│   ├── dsp_coefficients.json
│   ├── rr_scaler.json
│   └── dataset_audit.json
├── 01_data_audit/
│   ├── dataset_counts.json
│   ├── label_mapping.json
│   ├── split_manifest.csv
│   └── exclusions.csv
├── 02_dsp_validation/
│   ├── chunk_invariance.json
│   ├── detector_metrics.json
│   ├── peak_error_distribution.json
│   ├── quality_metrics.json
│   └── figures/
├── 03_features/
│   ├── train_features.npz
│   ├── val_features.npz
│   ├── test_features.npz
│   └── feature_manifest.json
├── 04_models_float/
│   ├── gate.keras
│   └── sv.keras
├── 05_models_tflite/
│   ├── gate_int8.tflite
│   └── sv_int8.tflite
├── 06_metrics/
│   ├── float_metrics.json
│   ├── int8_metrics.json
│   ├── thresholds.json
│   ├── confusion_matrices.json
│   ├── quantization_report.json
│   └── false_negative_audit.csv
├── 07_golden_vectors/
│   ├── golden_vectors.npz
│   ├── golden_vectors.json
│   └── golden_vector_summary.md
├── 08_firmware_export/
│   ├── gate_model_data.cc
│   ├── gate_model_data.h
│   ├── sv_model_data.cc
│   ├── sv_model_data.h
│   ├── thresholds.h
│   ├── rr_scaler.h
│   ├── dsp_coefficients.h
│   └── tarang_model_contract.json
└── 09_reports/
    ├── FINAL_REPORT.md
    └── REPRODUCTION_NOTES.md
```

---

# 1. Non-negotiable engineering rules

The AI agent must obey all of these.

1. **Do not modify or overwrite v15.**
2. **Do not duplicate DSP logic inside the notebook.** The notebook must import it from `tarang_dsp_reference.py`.
3. **Do not use `filtfilt` or any future-looking preprocessing.**
4. **Do not subtract the mean of an entire record.**
5. **Do not reset filter, normalization, detector, NLMS, or RR state at frame boundaries.**
6. **Do not use XQRS as the final deployment detector.**
7. **Do not generate S or V labels from timing or morphology heuristics.**
8. **Use true beat annotations for S and V wherever available.**
9. **Do not use record-level PAC/PVC diagnoses as if they were beat-level annotations.**
10. **Do not use future RR intervals.**
11. **Keep exactly four RR features as model inputs in v16.**
12. **Do not add `rr_ratio`, prematurity flags, or label-defining rules to the CNN inputs.**
13. **Do not tune thresholds on the test set.**
14. **Do not fit scalers on validation or test data.**
15. **Do not fabricate IMU references for public ECG datasets.**
16. **Do not claim that NLMS improves morphology until a paired ablation proves it.**
17. **Do not change the gate/SV architecture in the main v16 run.** v16 isolates preprocessing and deployment alignment.
18. **Fail loudly.** Replace broad `except: pass` blocks with explicit logged exclusions and exception counts.
19. **Save deterministic manifests, hashes, seeds, package versions, split identities, and coefficients.**
20. **Run a smoke test first, then a full run using the same code path.**

---

# 2. What v16 changes relative to v15

The v15 baseline already contains useful decisions:

- target ECG rate of 250 Hz;
- 130-sample beat windows;
- 65 pre-R and 65 post-R convention;
- four causal RR features;
- causal Butterworth SOS filtering;
- rolling normalization;
- gate plus two-head S/V cascade;
- full-int8 TFLite conversion;
- threshold calibration and firmware export.

v16 must preserve the useful parts while correcting the deployment gaps.

## 2.1 Remove whole-record mean subtraction

Do not use:

```python
sig = sig - np.mean(sig)
```

It uses future samples and cannot be reproduced in live streaming.

Baseline/DC handling must come from the causal high-pass component and the stateful causal normalization.

## 2.2 Replace offline array preprocessing with stateful streaming DSP

The reference must process samples or frames while preserving state.

These states must persist:

```text
SOS biquad delays
optional notch delays
NLMS reference delay line
NLMS weights
rolling normalization ring buffer
rolling sum and sum of squares
Pan–Tompkins filters
derivative history
moving-window integration state
adaptive signal/noise thresholds
refractory state
search-back state
morphology ring buffer
R-peak history
RR history
quality state
```

## 2.3 Replace XQRS-centered training windows

The final v16 window center must come from the Tarang Pan–Tompkins-style detector and morphology-path recentering.

For annotated datasets:

```text
annotation → class label
Tarang detector → practical window center
```

The detector is never allowed to create the class label.

## 2.4 Preserve the cascade architecture

The main v16 experiment keeps the current gate plus SV architecture so that any performance change can be attributed primarily to preprocessing, peak alignment, data handling, or quantization rather than architecture churn.

## 2.5 Treat NLMS as optional until validated

Public ECG datasets usually do not include synchronized IMU.

Therefore:

```text
public training ECG:
fixed causal DSP → morphology/detection paths → model

real synchronized hardware ECG+IMU:
fixed causal DSP → optional NLMS → morphology/detection paths
```

The reference file must implement NLMS, but the public-dataset training mode must use `nlms_mode="bypass"` unless real synchronized IMU exists.

---

# 3. Final v16 processing architecture

```text
Raw ECG record or stream
        ↓
Input sanitization and timestamp integrity
        ↓
Resampling to 250 Hz when needed
        ↓
Stateful causal morphology band-pass
        ↓
Optional conditional 50 Hz notch
        ↓
Optional synchronized IMU preprocessing
        ↓
Optional motion-gated NLMS
        ↓
Post-filter signal-quality evaluation
        ↓
Split into two branches
        ├── Morphology branch
        │      stateful causal rolling normalization
        │      morphology ring buffer
        │
        └── Detection branch
               QRS-emphasis filter
               derivative
               squaring
               moving-window integration
               adaptive thresholds
               refractory logic
               search-back
        ↓
Candidate peak recentering on morphology signal
        ↓
Peak validation
        ↓
Causal RR feature update
        ↓
Wait for post-R samples
        ↓
Extract 130-sample beat
        ↓
Beat quality verdict
        ↓
Four RR features scaled using training-only statistics
        ↓
Gate CNN
        ↓
If routed, SV CNN
        ↓
Threshold-based N/S/V decision
        ↓
Full-int8 TFLite conversion
        ↓
Host and firmware golden-vector export
```

---

# 4. Mathematical signal model

Model a raw digitized ECG as:

\[
x[n] = s[n] + b[n] + p[n] + m[n] + \eta[n]
\]

where:

- \(s[n]\): desired cardiac signal;
- \(b[n]\): baseline wander;
- \(p[n]\): powerline interference;
- \(m[n]\): motion artifact;
- \(\eta[n]\): electronic and quantization noise.

The DSP does not perfectly recover a mathematically pure \(s[n]\). It creates a deployment-consistent representation that preserves useful morphology and supports robust R-peak timing.

---

# 5. Step-by-step DSP specification

## 5.1 Input validation

For each input record or frame:

- reject empty arrays;
- replace or explicitly count NaN and infinite samples;
- verify monotonic timestamps;
- verify the declared sample rate;
- detect missing or duplicated samples when timestamps exist;
- retain a source identifier and record identifier;
- log every exclusion.

Basic frame statistics:

\[
\mu_x = \frac{1}{N}\sum_{n=0}^{N-1}x[n]
\]

\[
\sigma_x^2 = \frac{1}{N}\sum_{n=0}^{N-1}(x[n]-\mu_x)^2
\]

\[
x_{\mathrm{RMS}} =
\sqrt{\frac{1}{N}\sum_{n=0}^{N-1}x[n]^2}
\]

Flatline can be suspected when variance remains below a configured floor.

Saturation fraction:

\[
P_{\mathrm{sat}} =
\frac{1}{N}
\sum_{n=0}^{N-1}
\mathbf{1}
\left(
x[n]\le x_{\min}+\epsilon
\lor
x[n]\ge x_{\max}-\epsilon
\right)
\]

The function must return quality flags, not silently discard bad signals.

---

## 5.2 Rational resampling to 250 Hz

Let source rate be \(f_{\mathrm{src}}\) and target rate be:

\[
f_{\mathrm{target}} = 250\ \mathrm{Hz}
\]

Let:

\[
g = \gcd(f_{\mathrm{src}}, f_{\mathrm{target}})
\]

\[
L = \frac{f_{\mathrm{target}}}{g},
\qquad
M = \frac{f_{\mathrm{src}}}{g}
\]

Use polyphase resampling equivalent to upsampling by \(L\), low-pass filtering, and downsampling by \(M\).

Conceptually:

\[
y[m]
=
\sum_n x[n]\,
h[mM-nL]
\]

Requirements:

- use deterministic coefficients;
- preserve mapping between annotation times and resampled indices;
- convert annotation sample positions with rounding, not truncation:

\[
r_{\mathrm{new}}
=
\operatorname{round}
\left(
r_{\mathrm{old}}
\frac{250}{f_{\mathrm{src}}}
\right)
\]

- test identity behavior when source rate is already 250 Hz.

---

## 5.3 Stateful causal morphology band-pass

Target initial band:

\[
0.5\ \mathrm{Hz} \le f \le 40\ \mathrm{Hz}
\]

Use an IIR Butterworth filter represented as second-order sections.

One biquad section is:

\[
y[n]
=
b_0x[n]
+b_1x[n-1]
+b_2x[n-2]
-a_1y[n-1]
-a_2y[n-2]
\]

For \(K\) second-order sections:

\[
H(z)=\prod_{k=1}^{K}H_k(z)
\]

Requirements:

- use `output="sos"`;
- export the exact SOS matrix;
- preserve each section’s delay state across frames;
- initialize once per record or stream;
- do not prime or reset once per beat;
- record the complete design parameters;
- include chunk-invariance tests.

Chunk invariance means:

```text
process entire record in one call
approximately equals
process same record in arbitrary sequential chunks with persistent state
```

The difference must be near floating-point tolerance except for explicitly documented initialization behavior.

---

## 5.4 Optional 50 Hz notch

The notch is configurable, not automatically mandatory.

A second-order notch can be represented as:

\[
H(z)
=
\frac{
1-2\cos(\omega_0)z^{-1}+z^{-2}
}{
1-2r\cos(\omega_0)z^{-1}+r^2z^{-2}
}
\]

where:

\[
\omega_0=2\pi\frac{f_0}{f_s}
\]

For India:

\[
f_0=50\ \mathrm{Hz},
\qquad
f_s=250\ \mathrm{Hz}
\]

\[
\omega_0=0.4\pi
\]

The value \(r<1\) controls notch width.

Enable only when residual 50 Hz energy is demonstrated. Save both `notch_enabled` and coefficients in the contract.

---

## 5.5 IMU reference preprocessing

For synchronized hardware data, let accelerometer axes be:

\[
a_x[n], a_y[n], a_z[n]
\]

Estimate slowly varying gravity using an exponential smoother:

\[
g_x[n]
=
\alpha g_x[n-1]
+
(1-\alpha)a_x[n]
\]

Then dynamic acceleration:

\[
a_{x,d}[n] = a_x[n]-g_x[n]
\]

Repeat for \(y\) and \(z\).

Motion magnitude:

\[
m[n]
=
\sqrt{
a_{x,d}[n]^2+
a_{y,d}[n]^2+
a_{z,d}[n]^2
}
\]

Short-window motion RMS:

\[
M[n]
=
\sqrt{
\frac{1}{W_m}
\sum_{k=0}^{W_m-1}m[n-k]^2
}
\]

Robust rest-calibrated threshold:

\[
T_{\mathrm{motion}}
=
\max
\left(
\operatorname{median}(M_{\mathrm{rest}})
+
\kappa\operatorname{MAD}(M_{\mathrm{rest}}),
T_{\min}
\right)
\]

where:

\[
\operatorname{MAD}(x)
=
\operatorname{median}
\left(
|x-\operatorname{median}(x)|
\right)
\]

Do not collapse to magnitude only if a multi-axis NLMS path is available. Preserve dynamic \(x\), \(y\), and \(z\) references.

---

## 5.6 Motion-gated NLMS

The desired ECG input is:

\[
d[n]=s[n]+v[n]
\]

where \(v[n]\) is motion-correlated artifact.

Construct an IMU reference delay vector:

\[
\mathbf{x}[n]
=
\begin{bmatrix}
x[n] &
x[n-1] &
\cdots &
x[n-M+1]
\end{bmatrix}^{T}
\]

For three axes, concatenate all delayed axes.

Estimated artifact:

\[
\hat v[n]
=
\mathbf{w}^{T}[n]\mathbf{x}[n]
\]

Cleaned error signal:

\[
e[n]
=
d[n]-\hat v[n]
\]

NLMS update:

\[
\mathbf{w}[n+1]
=
\mathbf{w}[n]
+
g[n]
\frac{
\mu e[n]\mathbf{x}[n]
}{
\delta+\|\mathbf{x}[n]\|^2
}
\]

where:

- \(g[n]\in\{0,1\}\) is the motion/reference-valid gate;
- \(\mu\) is the adaptation rate;
- \(\delta>0\) prevents division by zero;
- \(M\) is filter length.

Optional leakage:

\[
\mathbf{w}[n+1]
=
(1-\lambda)\mathbf{w}[n]
+
g[n]
\frac{
\mu e[n]\mathbf{x}[n]
}{
\delta+\|\mathbf{x}[n]\|^2
}
\]

Rules:

- public ECG without IMU must use bypass mode;
- clean rest may freeze adaptation;
- divergence, NaN, excessive weight norm, or increased noise must trigger bypass;
- preserve weights and delay lines across frames;
- log NLMS activity rate and weight norm;
- compare band-pass-only and NLMS outputs on paired hardware data;
- do not call raw-to-clean RMS reduction “NLMS SNR improvement” unless the contribution is isolated.

---

## 5.7 Post-filter quality checks

Compare:

```text
raw ECG
fixed-filter ECG
NLMS output, when enabled
```

Useful measures include:

\[
\Delta_{\mathrm{RMS,dB}}
=
20\log_{10}
\left(
\frac{\mathrm{RMS}_{\mathrm{before}}+\epsilon}
{\mathrm{RMS}_{\mathrm{after}}+\epsilon}
\right)
\]

This is not automatically physiological SNR.

Also compute:

- clipping fraction;
- baseline drift estimate;
- high-frequency energy ratio;
- 50 Hz energy ratio;
- ECG–IMU correlation;
- NLMS coefficient norm;
- QRS amplitude ratio before/after;
- QRS width difference before/after;
- detector agreement before/after.

Quality states:

```text
GOOD
DEGRADED_BUT_USABLE
BAD
LEAD_OFF
SATURATED
MOTION
FILTER_UNSTABLE
NLMS_BYPASSED
STARTUP
```

---

## 5.8 Morphology branch

The morphology branch feeds the CNN and peak recentering.

Initial chain:

```text
fixed causal band-pass
→ optional validated NLMS
→ causal rolling normalization
→ morphology ring buffer
```

No derivative, squaring, or moving integration is allowed in the CNN input.

### Causal rolling normalization

For window length:

\[
W_z=30f_s=7500
\]

Maintain:

\[
S_1[n]
=
S_1[n-1]+x[n]-x[n-W_z]
\]

\[
S_2[n]
=
S_2[n-1]+x[n]^2-x[n-W_z]^2
\]

For current valid count \(C[n]\le W_z\):

\[
\mu[n]=\frac{S_1[n]}{C[n]}
\]

\[
\sigma^2[n]
=
\max
\left(
\frac{S_2[n]}{C[n]}-\mu[n]^2,
0
\right)
\]

\[
z[n]
=
\frac{x[n]-\mu[n]}
{\max(\sqrt{\sigma^2[n]},\epsilon)}
\]

Requirements:

- define startup behavior explicitly;
- use the exact same `ddof` convention in Python and firmware;
- record valid sample count;
- prevent negative variance caused by floating-point roundoff;
- preserve the ring buffer and sums across frames;
- no complete-record statistics.

---

## 5.9 Detection branch: Pan–Tompkins-style detector

The detection branch locates QRS complexes. It does not classify N, S, or V.

### Stage A: QRS-emphasis filter

Apply a detector-specific band-pass, initially around:

\[
5\text{–}15\ \mathrm{Hz}
\]

The exact coefficients are tunable and must be exported.

### Stage B: derivative

A causal slope operator may be:

\[
x_d[n]
=
\frac{1}{8T}
\left(
x_b[n]
+
2x_b[n-1]
-
2x_b[n-3]
-
x_b[n-4]
\right)
\]

where:

\[
T=\frac{1}{f_s}
\]

At 250 Hz:

\[
T=0.004\ \mathrm{s}
\]

### Stage C: squaring

\[
x_s[n]=x_d[n]^2
\]

### Stage D: moving-window integration

For approximately 150 ms:

\[
N_{\mathrm{MWI}}
\approx
0.15f_s
\approx
37\text{ or }38
\]

\[
x_{\mathrm{MWI}}[n]
=
\frac{1}{N_{\mathrm{MWI}}}
\sum_{k=0}^{N_{\mathrm{MWI}}-1}
x_s[n-k]
\]

### Stage E: adaptive peak estimates

For candidate peak \(P\):

If signal:

\[
\mathrm{SPKI}
=
0.125P+0.875\mathrm{SPKI}
\]

If noise:

\[
\mathrm{NPKI}
=
0.125P+0.875\mathrm{NPKI}
\]

Primary threshold:

\[
\mathrm{TH}_1
=
\mathrm{NPKI}
+
0.25
\left(
\mathrm{SPKI}-\mathrm{NPKI}
\right)
\]

Search-back threshold:

\[
\mathrm{TH}_2
=
0.5\mathrm{TH}_1
\]

### Stage F: refractory logic

Initial refractory duration:

\[
N_{\mathrm{refractory}}
=
0.2f_s
=
50\ \mathrm{samples}
\]

The exact value must be validated for high-rate records.

### Stage G: missed-beat search-back

Let recent RR mean be:

\[
\overline{RR}
=
\frac{1}{K}
\sum_{j=1}^{K}RR_j
\]

If the current interval exceeds:

\[
RR_{\mathrm{current}}>\gamma\overline{RR}
\]

search previous candidates using the lower threshold.

### Stage H: T-wave rejection

For a close candidate, compare derivative slope with the previous accepted QRS slope.

A candidate may be rejected when:

\[
S_{\mathrm{candidate}}
<
\alpha S_{\mathrm{previous\,QRS}}
\]

and its timing is consistent with a T-wave region.

Do not hard-code these as clinically final. Keep them configurable and validate against annotations.

---

## 5.10 Candidate recentering

The detection branch introduces delay and identifies QRS energy rather than the exact morphology peak.

Let candidate be \(r_0\).

Search the morphology signal within:

\[
L
=
0.06f_s
=
15\ \mathrm{samples}
\]

Refined location:

\[
r^*
=
\underset{k\in[r_0-L,r_0+L]}
{\operatorname{argmax}}
|x_{\mathrm{morph}}[k]|
\]

Requirements:

- handle upright and inverted QRS;
- define behavior for flat or clipped windows;
- reject duplicate refined peaks;
- record detector candidate and refined index separately;
- measure timing error against annotations.

---

## 5.11 Detector-to-annotation matching

For datasets with beat annotations, the class label comes from the annotation, while the window center comes from the detector.

For detected peak \(r_i\), find the nearest annotation \(a_j\).

Match only when:

\[
|r_i-a_j|
\le
\tau_{\mathrm{match}}
\]

A reasonable initial tolerance is 100–150 ms, but it must be recorded.

Rules:

- one annotation can match at most one detected peak;
- one detected peak can match at most one annotation;
- unmatched detections count as false positives;
- unmatched annotations count as false negatives;
- matched annotation symbol is mapped through the AAMI mapping;
- ignored symbols remain ignored;
- save per-record match statistics.

Detector metrics:

\[
\mathrm{Precision}
=
\frac{TP}{TP+FP}
\]

\[
\mathrm{Recall}
=
\frac{TP}{TP+FN}
\]

\[
F_1
=
2
\frac{\mathrm{Precision}\cdot\mathrm{Recall}}
{\mathrm{Precision}+\mathrm{Recall}}
\]

Timing error:

\[
e_i=r_i-a_{j(i)}
\]

Save mean, median, standard deviation, MAE, percentiles, and histogram of \(e_i\).

---

## 5.12 Causal RR features

Given refined peaks \(r_i\) at sample rate \(f_s\):

\[
RR_i^{\mathrm{ms}}
=
1000
\frac{r_i-r_{i-1}}{f_s}
\]

The four model features are:

### 1. Previous RR

\[
f_1=RR_i^{\mathrm{ms}}
\]

### 2. Recent mean RR

Using up to the most recent five valid intervals:

\[
f_2
=
\overline{RR}_{5}
=
\frac{1}{K}
\sum_{j=0}^{K-1}RR_{i-j}^{\mathrm{ms}}
\]

where \(1\le K\le5\).

### 3. Recent RR standard deviation

\[
f_3
=
\sigma_{RR,5}
=
\sqrt{
\frac{1}{K}
\sum_{j=0}^{K-1}
\left(
RR_{i-j}^{\mathrm{ms}}-\overline{RR}_5
\right)^2
}
\]

Use the population convention consistently.

### 4. Local heart rate

\[
f_4
=
HR_i
=
\frac{60000}
{\max(\overline{RR}_5,\epsilon)}
\]

Feature order is frozen:

```text
[rr_previous_ms, rr_mean_5_ms, rr_std_5_ms, local_hr_bpm]
```

Do not add future intervals.

Do not add `rr_ratio` or prematurity as CNN inputs in v16.

---

## 5.13 RR standardization

Fit `StandardScaler` on training features only.

For each RR feature \(j\):

\[
z_j
=
\frac{x_j-\mu_j}
{\max(\sigma_j,\epsilon)}
\]

Export:

```text
rr_mean[4]
rr_scale[4]
```

Validation and test use the frozen training statistics.

---

## 5.14 Beat-window extraction

Freeze:

```text
sample rate = 250 Hz
window length = 130
pre-R = 65
post-R = 65
```

Use one explicit indexing convention:

\[
b_i[j]
=
z[r_i-65+j]
\]

for:

\[
j=0,1,\ldots,129
\]

This extracts:

```text
r_i - 65 through r_i + 64
```

The R-peak is at index 65.

Total duration:

\[
\frac{130}{250}
=
0.52\ \mathrm{s}
\]

Requirements:

- wait until post-R samples are available;
- reject incomplete windows;
- save raw, filtered, normalized, and extracted examples for audit;
- keep frame size separate from beat-window size;
- acquisition frames may be 256 samples, but the model input remains 130.

---

## 5.15 Beat quality verdict

Each beat packet must include:

```text
GOOD
LOW_CONFIDENCE
Q_UNUSABLE
```

Potential rejection reasons:

- no full pre/post window;
- startup state not warm enough;
- lead-off;
- saturation;
- severe motion;
- detector confidence too low;
- duplicate or implausible peak;
- invalid RR;
- filter/NLMS instability.

A Q beat must not be forced into N/S/V during live deployment.

For supervised dataset training, unusable beats are excluded and logged.

---

# 6. Dataset and label policy

## 6.1 Lead policy

Use Lead I for the primary deployment-aligned training line where available.

Document any external cross-database lead mismatch explicitly.

## 6.2 Label sources

Preserve v15’s baseline data direction unless a verified improvement is made:

```text
N:
PTB-XL and CPSC records tagged as normal sinus rhythm
This is weak record-level normal supervision and must be labeled as such.

S and V:
INCART Lead I with true beat-level annotations
```

AAMI mapping:

```text
N family: N, L, R, e, j
S family: A, a, J, S
V family: V, E
```

Any other symbols must be ignored or separately audited.

## 6.3 Important normal-label caveat

A record-level NSR diagnosis does not prove every detected beat is normal.

Therefore:

- mark these as `N_weak`;
- run signal and detector quality checks;
- avoid overclaiming their label purity;
- keep true annotated INCART N beats separately identifiable;
- report counts by source and supervision type.

## 6.4 No pseudo-label creation

Forbidden:

```text
short RR → label S
wide QRS → label V
PVC diagnosis at record level → every beat V
PAC diagnosis at record level → every beat S
```

Heuristics may be evaluated as baselines or triggers, never used to define the same labels the model is evaluated against.

## 6.5 Split policy

Use patient-wise split whenever true patient IDs exist.

For PTB-XL:

```text
strat_fold 1–8 → train
strat_fold 9 → validation
strat_fold 10 → test
```

For sources without exposed patient identity:

- state clearly that split is record-wise;
- detect duplicate records;
- avoid any record appearing in multiple splits;
- never describe record-wise split as fully patient-wise;
- store a split manifest.

The agent must assert disjoint identities and hashes across splits.

---

# 7. Peak alignment policy for training

There are two possible beat-center sources:

## 7.1 Detector-centered primary deployment evaluation

Use the Tarang detector peak for window extraction.

Then match that detection to a true annotation for the class.

This represents real deployment behavior, including detector timing error.

## 7.2 Annotation-centered oracle diagnostic

Also generate an oracle evaluation using annotation-centered windows.

This is not the deployment result. It is an ablation answering:

> How much performance is lost because of the detector rather than the classifier?

Report both:

```text
annotation-centered model evaluation
detector-centered model evaluation
```

The detector-centered result is the primary deployment-aligned number.

## 7.3 Peak-jitter augmentation

Measure the detector’s timing-error distribution on training records only.

Use that measured distribution to jitter training windows.

Do not invent arbitrary jitter when an empirical distribution is available.

Do not jitter validation or test data.

---

# 8. Feature generation contract

Every saved feature must include metadata:

```text
record_id
patient_id or record identity
source
split
lead
source_fs
target_fs
annotation_symbol
AAMI_class
annotation_index
detected_index
refined_index
peak_error_samples
quality_state
quality_flags
RR_valid_count
NLMS_mode
DSP_config_hash
```

Arrays:

```text
X_ecg: shape [N, 130, 1], float32
X_rr_raw: shape [N, 4], float32
X_rr_scaled: shape [N, 4], float32
y_class: shape [N], int
```

Class mapping:

```text
0 = N
1 = S
2 = V
3 = Q only for runtime/event interfaces, not a supervised CNN class in v16
```

---

# 9. Balancing and augmentation

Only training data may be balanced or augmented.

## 9.1 Downsampling

Downsample N only when required to make training tractable.

Never downsample validation or test.

Save original and final class counts.

## 9.2 ECG augmentation

Initial allowed augmentations:

- shift within an empirically defensible range;
- amplitude scaling;
- small additive noise;
- optional baseline perturbation only if produced causally and plausibly.

Example:

\[
x_{\mathrm{aug}}[n]
=
a\,x[n-\Delta]
+
\epsilon[n]
\]

where:

\[
a\sim U(0.85,1.15)
\]

\[
\Delta \in [-3,3]
\]

\[
\epsilon[n]\sim\mathcal N(0,0.02^2)
\]

The exact values are inherited from v15 for the baseline run.

Do not augment RR features by simply duplicating them if the ECG shift changes the implied timing. For small morphology-only shifts around a frozen center, duplication may be retained as a controlled baseline, but document the assumption.

## 9.3 Leakage baseline

Run a simple RR-only baseline.

If a trivial RR rule nearly perfectly separates S and N, investigate circular leakage.

Do not use the rule to label data.

---

# 10. Model architecture

Keep the v15 architecture unchanged in the principal v16 run.

## 10.1 Gate model

Inputs:

```text
ecg_input: [130, 1]
rr_input: [4]
```

ECG branch:

```text
reshape to [130, 1, 1]
Conv2D 16 filters, kernel (7,1)
BatchNorm
ReLU
MaxPool
SpatialDropout

Conv2D 32 filters, kernel (5,1)
BatchNorm
ReLU
MaxPool
SpatialDropout

Conv2D 64 filters, kernel (5,1)
BatchNorm
ReLU
MaxPool
SpatialDropout

Conv2D 64 filters, kernel (3,1)
BatchNorm
ReLU

GlobalAveragePooling
```

RR branch:

```text
Dense 16 ReLU
Dropout 0.2
Dense 8 ReLU
```

Fusion:

```text
Concatenate
Dense 32 without bias
BatchNorm
ReLU
Dropout 0.35
Dense 1 sigmoid
```

Output:

\[
P_{\mathrm{gate}}=P(\mathrm{abnormal})
\]

Target:

\[
y_{\mathrm{gate}}
=
\mathbf{1}(y\ne N)
\]

## 10.2 SV model

Use the same input contract.

ECG filters:

```text
16, 32, 48, 48
```

Kernel sequence:

```text
7, 5, 5, 3
```

RR and fusion branches remain the same.

Outputs:

\[
P_V=P(y=V)
\]

\[
P_S=P(y=S)
\]

Use two sigmoid heads:

```text
v_head
s_head
```

---

# 11. Training mathematics

## 11.1 Binary cross-entropy

For target \(y\in\{0,1\}\) and predicted probability \(p\):

\[
\mathcal L_{\mathrm{BCE}}
=
-\left[
y\log(p+\epsilon)
+
(1-y)\log(1-p+\epsilon)
\right]
\]

For weighted BCE:

\[
\mathcal L
=
-w_y
\left[
y\log(p+\epsilon)
+
(1-y)\log(1-p+\epsilon)
\right]
\]

The gate uses class weighting.

The SV model uses per-output sample weights for the V and S heads.

## 11.2 L2 regularization

For weights \(W\):

\[
\mathcal L_{\mathrm{total}}
=
\mathcal L_{\mathrm{data}}
+
\lambda\sum_i W_i^2
\]

Baseline:

\[
\lambda=10^{-4}
\]

## 11.3 Optimizer and schedule

Baseline inherited from v15:

```text
Adam
learning rate = 1e-3
maximum epochs = 60
batch size = 256
early-stop patience = 12
seed = 42
```

Smoke test may use 5 epochs, but it must use identical preprocessing and artifact paths.

## 11.4 Routing for SV training

The gate is trained first.

For training beat \(i\):

\[
\mathrm{route}_i
=
\mathbf{1}
\left(
P_{\mathrm{gate},i}
>
T_{\mathrm{route}}
\right)
\]

Use the inherited baseline routing threshold of 0.10 for initial routed training unless the validation design explicitly changes it.

Save:

- number routed by class;
- percentage routed by class;
- S/V losses and AUCs;
- head-collapse warnings.

---

# 12. Cascade decoding

Given:

\[
g=P_{\mathrm{gate}}
\]

\[
v=P_V
\]

\[
s=P_S
\]

One explicit decoder is:

```text
if g <= T_gate:
    N
else:
    if v > T_v:
        V
    elif s > T_s:
        S
    else:
        N
```

If both \(v\) and \(s\) exceed thresholds, the arbitration policy must be frozen.

Initial baseline:

```text
V priority over S
```

because this matches the current v15 decoder direction.

Save this policy in the contract. Never leave output ordering or arbitration implicit.

---

# 13. Threshold calibration

Thresholds are selected on validation only.

## 13.1 Gate threshold

Search candidate thresholds and report:

- abnormal recall;
- V-through-gate recall;
- S-through-gate recall;
- N rejection;
- routed fraction.

The gate must prioritize not dropping V before the specialist.

A constrained objective may be:

```text
among thresholds satisfying V-through-gate recall ≥ required floor,
choose the one minimizing routed fraction or maximizing abnormal F1
```

The exact constraint must be saved.

## 13.2 V threshold

Search validation predictions only.

Possible constrained rule:

```text
choose threshold with maximum V recall
subject to validation V precision ≥ configured floor
```

If no threshold meets the floor, report failure rather than secretly relaxing it.

## 13.3 S threshold

Choose from validation only.

Possible objective:

```text
maximize validation S F1
subject to preserving the already locked V behavior
```

## 13.4 Test set

After all thresholds are frozen:

```text
run test set exactly once for final reporting
```

Do not choose a threshold based on test performance.

---

# 14. Evaluation metrics

For class \(c\):

\[
\mathrm{Precision}_c
=
\frac{TP_c}{TP_c+FP_c}
\]

\[
\mathrm{Recall}_c
=
\frac{TP_c}{TP_c+FN_c}
\]

\[
F1_c
=
2
\frac{
\mathrm{Precision}_c\mathrm{Recall}_c
}{
\mathrm{Precision}_c+\mathrm{Recall}_c
}
\]

Macro F1:

\[
F1_{\mathrm{macro}}
=
\frac{1}{3}
\left(
F1_N+F1_S+F1_V
\right)
\]

Report:

- confusion matrix;
- N/S/V precision, recall, F1;
- macro F1;
- support;
- gate routing metrics;
- per-source metrics;
- annotation-centered versus detector-centered metrics;
- clean versus degraded quality metrics;
- float versus int8 metrics;
- false-negative audit for S and V.

Do not hide zero-support classes.

---

# 15. Full-int8 quantization

Use a representative dataset generated after all v16 preprocessing changes.

The converter must use:

```text
Optimize.DEFAULT
representative_dataset
TFLITE_BUILTINS_INT8
int8 input
int8 output
```

## 15.1 Input quantization

For real-valued input \(x\), scale \(s\), and zero point \(z\):

\[
q
=
\operatorname{clip}
\left(
\operatorname{round}
\left(
\frac{x}{s}+z
\right),
-128,
127
\right)
\]

## 15.2 Output dequantization

\[
\hat x
=
s(q-z)
\]

Extract scales and zero points from the actual TFLite interpreter. Do not assume them.

## 15.3 Representative dataset

Include a stratified mixture of:

- N, S, V;
- different sources;
- low and high amplitudes;
- clean and mildly degraded quality;
- empirically jittered windows;
- startup-normalization examples if they can reach inference;
- real hardware windows when available;
- band-pass-only and NLMS-processed paired hardware windows when available.

Representative samples need not be labeled, but must reflect deployment activation ranges.

---

# 16. Quantization validation

Run the complete held-out test set through:

```text
float Keras gate + SV
int8 TFLite gate + SV
```

Compare:

\[
\mathrm{MAE}
=
\frac{1}{N}
\sum_i
|p_i^{\mathrm{float}}-p_i^{\mathrm{int8}}|
\]

Class mismatch:

\[
R_{\mathrm{mismatch}}
=
\frac{1}{N}
\sum_i
\mathbf{1}
\left(
\hat y_i^{\mathrm{float}}
\ne
\hat y_i^{\mathrm{int8}}
\right)
\]

Also report per-head correlation and verify output order.

Never assume TFLite output 0 is V and output 1 is S. Verify names or correlation and save the resolved mapping.

Thresholds intended for firmware must be calibrated or at least revalidated on int8 outputs.

---

# 17. DSP validation required before model claims

The DSP reference must pass these tests.

## 17.1 Chunk invariance

Process the same signal:

```text
one complete array
1-sample chunks
random chunks
256-sample chunks
```

Persistent-state outputs must agree within tolerance.

## 17.2 Causality test

Perturb samples after time \(n\).

Outputs before or at \(n\) must remain unchanged, except where a deliberately delayed output waits for post-R context.

## 17.3 Filter impulse and step tests

Save:

- impulse response;
- step response;
- frequency response;
- startup transient behavior.

## 17.4 Pan–Tompkins test

On annotated data, report:

- detection precision;
- detection recall;
- timing MAE;
- duplicate detections;
- missed beats;
- false peaks;
- performance by source and class.

## 17.5 Window alignment test

For random examples, plot:

```text
raw ECG
morphology signal
detection energy
annotation
candidate peak
refined peak
130-sample window boundaries
```

## 17.6 Normalization test

Verify:

- no future leakage;
- no frame reset;
- finite output at startup;
- exact count behavior;
- Python reference consistency.

## 17.7 NLMS ablation

On synchronized hardware recordings:

```text
fixed filter only
versus
fixed filter + NLMS
```

Compare:

- motion-window residual;
- QRS amplitude change;
- QRS width change;
- R-peak precision/recall or agreement;
- CNN output shift;
- confidence shift;
- weight stability.

NLMS becomes part of the CNN morphology path only after this ablation is acceptable.

---

# 18. Golden vectors for EFR32

Generate a deterministic set containing:

```text
exact int8 ECG tensor [130,1]
exact int8 RR tensor [4]
expected gate int8 output
expected dequantized gate probability
expected V int8 output
expected S int8 output
expected final class
source metadata
quality metadata
```

Include:

- normal examples;
- S examples;
- V examples;
- near-threshold examples;
- minimum/maximum activation examples;
- poor-quality examples not allowed into inference;
- representative hardware examples when available.

Create both `.npz` and JSON summaries.

The firmware must receive byte-identical tensors.

---

# 19. Model contract

Generate `tarang_model_contract.json` containing at least:

```json
{
  "pipeline_version": "v16",
  "sample_rate_hz": 250,
  "window_length": 130,
  "pre_r_samples": 65,
  "post_r_samples": 65,
  "r_peak_index_in_window": 65,
  "rr_feature_count": 4,
  "rr_feature_order": [
    "rr_previous_ms",
    "rr_mean_5_ms",
    "rr_std_5_ms",
    "local_hr_bpm"
  ],
  "class_mapping": {
    "0": "N",
    "1": "S",
    "2": "V",
    "3": "Q"
  },
  "decoder_policy": "gate_then_v_priority_then_s",
  "gate_threshold": 0.0,
  "v_threshold": 0.0,
  "s_threshold": 0.0,
  "rr_mean": [],
  "rr_scale": [],
  "gate_inputs": {},
  "gate_outputs": {},
  "sv_inputs": {},
  "sv_outputs": {},
  "dsp_config_hash": "",
  "split_manifest_hash": "",
  "gate_model_sha256": "",
  "sv_model_sha256": "",
  "created_at": ""
}
```

Also include:

- exact SOS coefficients;
- notch configuration;
- detector coefficients and thresholds;
- normalization convention;
- output order;
- quantization scale and zero point;
- TensorFlow and Python versions;
- Git commit when available.

---

# 20. How the three source files work together

## 20.1 `tarang_dsp_reference.py`

This is the single source of truth for preprocessing and beat generation.

It owns:

```text
resampling
stateful SOS filtering
optional notch
quality checks
IMU preprocessing
optional NLMS
morphology normalization
Pan–Tompkins state
peak recentering
annotation matching
RR features
beat extraction
BeatPacket construction
DSP configuration export
```

It must not import TensorFlow.

## 20.2 `Tarang_v16_Deployment_Aligned.ipynb`

This is the experiment orchestrator.

It owns:

```text
paths and run configuration
dataset audit
split creation
calling the DSP reference
feature assembly
balancing and augmentation
RR scaler fitting
model definition
training
calling validation utilities
report display
```

It must not reimplement DSP.

## 20.3 `tarang_v16_validation.py`

This is the independent validation/export layer.

It owns:

```text
model reload and reproduction
threshold search
cascade decoding
float metrics
TFLite conversion
TFLite inference
float/int8 comparison
golden-vector generation
manifest generation
C array/header export
report generation
artifact hashing
```

It must not train models and must not silently modify saved weights.

## 20.4 Data flow

```text
tarang_dsp_reference.py
        ↓
feature arrays + metadata
        ↓
Tarang_v16_Deployment_Aligned.ipynb
        ↓
trained gate.keras + sv.keras + splits + scaler
        ↓
tarang_v16_validation.py
        ↓
locked thresholds + int8 models + golden vectors + firmware export
```

---

# 21. Required interface for `tarang_dsp_reference.py`

The exact implementation can vary, but expose a stable API similar to:

```python
@dataclass(frozen=True)
class DSPConfig:
    target_fs: int
    morphology_low_hz: float
    morphology_high_hz: float
    morphology_order: int
    notch_enabled: bool
    notch_hz: float
    normalization_window_sec: float
    detector_low_hz: float
    detector_high_hz: float
    detector_mwi_sec: float
    refractory_sec: float
    recenter_ms: float
    pre_r: int
    post_r: int
    nlms_mode: str
    nlms_order: int
    nlms_mu: float
    nlms_delta: float
```

```python
@dataclass
class BeatPacket:
    waveform: np.ndarray
    rr_raw: np.ndarray
    r_peak_index: int
    r_peak_timestamp_sec: float
    detector_candidate_index: int
    quality_state: str
    quality_flags: tuple[str, ...]
    detector_confidence: float
    motion_score: float | None
    nlms_active: bool
```

```python
class StreamingTarangDSP:
    def reset(self) -> None: ...
    def process_sample(...) -> list[BeatPacket]: ...
    def process_frame(...) -> list[BeatPacket]: ...
    def process_record(...) -> list[BeatPacket]: ...
    def export_config(self) -> dict: ...
```

Utility functions:

```python
resample_signal(...)
match_detected_peaks_to_annotations(...)
map_aami_symbol(...)
evaluate_detector(...)
plot_dsp_audit(...)
```

Requirements:

- full type hints;
- docstrings with equations and units;
- explicit exceptions;
- no global mutable state;
- deterministic reset behavior;
- no TensorFlow dependency;
- unit tests for every stateful block.

---

# 22. Required interface for `tarang_v16_validation.py`

Expose functions similar to:

```python
def decode_cascade(gate_p, v_p, s_p, thresholds): ...
def search_gate_threshold(...): ...
def search_v_threshold(...): ...
def search_s_threshold(...): ...
def evaluate_cascade(...): ...
def convert_full_int8(...): ...
def run_tflite_dual_input(...): ...
def compare_float_and_int8(...): ...
def generate_golden_vectors(...): ...
def export_model_contract(...): ...
def export_c_arrays(...): ...
def hash_artifacts(...): ...
def write_final_report(...): ...
```

Requirements:

- validation-only behavior;
- reload models from disk before final evaluation;
- validation threshold selection only;
- locked test evaluation;
- output-order verification;
- no hidden test-set optimization;
- deterministic golden-vector selection;
- full artifact hashes;
- explicit failure messages.

---

# 23. Notebook execution order

The notebook must use these sections.

## Section 1 — Environment and reproducibility

- imports;
- versions;
- seeds;
- GPU/CPU info;
- paths;
- run ID;
- smoke/full mode;
- output folders.

## Section 2 — Configuration

- dataset paths;
- DSP config;
- ML config;
- split config;
- threshold constraints;
- target metrics;
- save `config.json`.

## Section 3 — Dataset governance audit

For every source:

- verify directory;
- verify `.hea`/signal/annotation files;
- verify lead names;
- verify sample rates;
- verify metadata;
- count records;
- count patients when available;
- count beat symbols;
- save audit;
- abort on unresolved contradictions.

## Section 4 — Import and test DSP reference

- instantiate config;
- run synthetic impulse/step/chunk tests;
- verify causality;
- save coefficients and validation results.

## Section 5 — Build split manifests

- freeze identities before feature extraction;
- assert disjointness;
- save CSV and hashes.

## Section 6 — Extract features

- run DSP per record;
- detect peaks;
- match to annotations where available;
- extract beat packets;
- map labels;
- log exclusions;
- save arrays and metadata.

## Section 7 — DSP evaluation

- detector metrics;
- timing error;
- example plots;
- quality counts;
- annotation-centered versus detector-centered comparison.

## Section 8 — Fit RR scaler

- training data only;
- save mean and scale.

## Section 9 — Balance and augment training data

- preserve original counts;
- downsample/augment only training;
- save post-balance counts.

## Section 10 — Build and train gate

- architecture unchanged;
- early stop;
- checkpoint;
- save learning curves.

## Section 11 — Route and train SV model

- route using frozen baseline rule;
- report routed counts;
- train two heads;
- detect collapse.

## Section 12 — Validation threshold calibration

- validation only;
- save all searched candidates;
- lock thresholds.

## Section 13 — Float evaluation

- reload saved weights;
- final val and test metrics;
- false-negative audit;
- per-source metrics.

## Section 14 — Int8 conversion

- representative dataset;
- convert both models;
- inspect tensors and operators;
- save sizes.

## Section 15 — Int8 evaluation

- complete test-set inference;
- output-order verification;
- float/int8 metrics;
- threshold revalidation.

## Section 16 — Golden vectors and firmware export

- deterministic examples;
- model arrays;
- threshold header;
- scaler header;
- DSP coefficient header;
- model contract;
- hashes.

## Section 17 — Final report

- data sources;
- supervision quality;
- split caveats;
- DSP metrics;
- float metrics;
- int8 metrics;
- model sizes;
- limitations;
- exact next hardware validation steps.

---

# 24. Acceptance gates for v16

v16 is not “complete” because the notebook runs.

Minimum software acceptance:

```text
[ ] v15 artifacts remain untouched
[ ] clean-kernel execution succeeds
[ ] smoke and full modes use same path
[ ] no filtfilt
[ ] no complete-record mean subtraction
[ ] state persists across chunks
[ ] chunk-invariance tests pass
[ ] Tarang detector replaces XQRS for primary windows
[ ] detector matched against true annotations
[ ] four RR features only
[ ] no S/V pseudo labels
[ ] split manifest is disjoint
[ ] scaler fitted on training only
[ ] thresholds selected on validation only
[ ] test evaluated after threshold lock
[ ] float models reload reproducibly
[ ] full-int8 conversion succeeds
[ ] int8 complete test evaluation succeeds
[ ] output tensor order is verified
[ ] golden vectors exported
[ ] model contract exported
[ ] all hashes saved
[ ] limitations are explicit
```

Hardware inference validation begins only after these gates pass.

---

# 25. Prompt 1 — Build the v16 notebook

Copy the prompt below into the AI coding agent.

```text
You are building Tarang v16 from the existing uploaded notebooks:
- Tarang_v15_FINAL.ipynb
- Tarang_v15_Validation_FINAL.ipynb
- Tarang_v14_FINAL.ipynb, only when historical context is required

Create a NEW notebook named:
Tarang_v16_Deployment_Aligned.ipynb

Do not overwrite any existing notebook or artifact.

Read the complete specification in:
Tarang_v16_Deployment_Aligned_Spec.md

Your job is to build the orchestration notebook only. All DSP logic must be imported from tarang_dsp_reference.py. All independent threshold, quantization, golden-vector, contract, and export logic must be imported from tarang_v16_validation.py.

Main goals:
1. Remove whole-record mean subtraction.
2. Use stateful causal preprocessing.
3. Replace XQRS-centered primary windows with Tarang Pan–Tompkins detector-centered and morphology-recentered windows.
4. Preserve annotation labels independently of the detector.
5. Keep exactly four causal RR model features.
6. Preserve the v15 gate and SV model architectures for the baseline v16 run.
7. Train using patient-wise splits wherever possible and explicitly labeled record-wise splits otherwise.
8. Calibrate thresholds using validation only.
9. Convert both models to full-int8 TFLite.
10. Export reproducible artifacts, golden vectors, and a complete model contract.

Notebook rules:
- Do not define a second version of filtering, normalization, Pan–Tompkins, RR extraction, peak matching, or beat extraction inside the notebook.
- Do not use filtfilt.
- Do not use sig - np.mean(sig) over an entire recording.
- Do not create S/V labels from RR timing, QRS width, record-level PAC/PVC diagnosis, or other heuristics.
- Do not fit scalers on validation/test.
- Do not tune thresholds on test.
- Do not use broad except: pass. Log each failure to exclusions.csv.
- Do not fabricate IMU or run NLMS on public records without real synchronized IMU.
- Use nlms_mode="bypass" for public ECG training.
- Keep true annotated and weak normal supervision identifiable in metadata.
- Use clean deterministic seeds.
- Save environment, config, coefficients, split manifests, counts, metrics, figures, and hashes.

Required notebook sections:
1. Environment and reproducibility
2. Config and paths
3. Dataset governance audit
4. DSP import and unit checks
5. Split manifests
6. Feature extraction
7. DSP detector evaluation
8. RR scaler fit
9. Training-only balancing and augmentation
10. Gate training
11. SV training
12. Validation-only threshold calibration
13. Reloaded float evaluation
14. Full-int8 conversion
15. Complete int8 evaluation
16. Golden vectors and firmware export
17. Final report

Use the current v15 architecture exactly for the principal v16 comparison:
- Gate filters: 16/32/64/64 with kernels 7/5/5/3
- SV filters: 16/32/48/48 with kernels 7/5/5/3
- RR branch: Dense 16 then Dense 8
- Fusion: Dense 32, BatchNorm, ReLU, Dropout
- Gate output: one sigmoid
- SV outputs: V sigmoid and S sigmoid
- Inputs: ECG [130,1], RR [4]

Use 250 Hz, a 130-sample beat, 65 pre-R, 65 post-R, and feature order:
[rr_previous_ms, rr_mean_5_ms, rr_std_5_ms, local_hr_bpm]

At the beginning, inspect the old notebooks and produce a concise migration table:
old behavior → v16 behavior → reason → validation test.

Before the full run, execute a smoke test through every stage, including TFLite conversion and one golden vector.

Do not claim hardware parity or production readiness. End by listing the exact remaining EFR32 validation tasks.
```

---

# 26. Prompt 2 — Build `tarang_dsp_reference.py`

```text
Create a production-oriented Python reference module named:
tarang_dsp_reference.py

Read and obey:
Tarang_v16_Deployment_Aligned_Spec.md

Purpose:
This module is the single mathematical and executable source of truth for Tarang v16 DSP and beat-packet generation. It must be usable by the training notebook, validation tools, replay tests, and future Python-versus-C parity tests.

Do not import TensorFlow.
Do not include model training.
Do not use filtfilt.
Do not use whole-record mean subtraction.
Do not hide failures.

Implement typed, documented, testable components for:

1. DSPConfig dataclass
2. BeatPacket dataclass
3. Signal quality flags and states
4. Rational resampling to 250 Hz
5. Stateful causal Butterworth SOS morphology band-pass
6. Optional stateful 50 Hz notch
7. IMU timestamp alignment and interpolation
8. Dynamic acceleration/gravity removal
9. Motion RMS and robust MAD-based thresholding
10. Multi-axis motion-gated NLMS with persistent weights
11. NLMS bypass and stability safeguards
12. Stateful causal rolling z-score normalization using ring buffer, running sum, and sum of squares
13. Detector-specific QRS band-pass
14. Causal derivative
15. Squaring
16. Moving-window integration
17. Adaptive SPKI/NPKI thresholds
18. Refractory logic
19. T-wave rejection
20. Missed-beat search-back
21. Morphology-path peak recentering
22. Peak validation and duplicate rejection
23. Annotation matching
24. AAMI symbol mapping
25. Four causal RR features
26. 130-sample beat extraction
27. Beat quality verdict
28. StreamingTarangDSP class with process_sample, process_frame, and process_record
29. DSP config and coefficient export
30. Audit plotting helpers

Mathematical requirements:
- Implement the exact equations in the spec.
- Preserve all state across frames.
- Reset only when explicitly requested.
- Make units explicit in variable names and docstrings.
- Return candidate and refined peaks separately.
- Return quality and exclusion reasons.
- Public-data mode must support nlms_mode="bypass".
- Hardware mode may accept synchronized 3-axis IMU.
- Never synthesize IMU internally.

Required tests:
- 250 Hz identity resampling
- annotation index rescaling
- impulse response
- step response
- one-shot versus random-chunk invariance
- one-shot versus 256-sample chunk invariance
- causality test
- normalization startup and steady-state test
- no NaN/Inf test
- detector test on synthetic QRS-like pulses
- refractory duplicate-rejection test
- RR feature unit test
- exact 130-sample window indexing test
- annotation one-to-one matching test
- NLMS zero-reference test
- NLMS bypass test
- NLMS bounded-weight test

API expectations:

@dataclass(frozen=True)
class DSPConfig: ...

@dataclass
class BeatPacket:
    waveform: np.ndarray
    rr_raw: np.ndarray
    r_peak_index: int
    r_peak_timestamp_sec: float
    detector_candidate_index: int
    quality_state: str
    quality_flags: tuple[str, ...]
    detector_confidence: float
    motion_score: float | None
    nlms_active: bool

class StreamingTarangDSP:
    def __init__(self, config: DSPConfig): ...
    def reset(self) -> None: ...
    def process_sample(...): ...
    def process_frame(...): ...
    def process_record(...): ...
    def export_config(self) -> dict: ...

Also expose:
resample_signal
match_detected_peaks_to_annotations
evaluate_detector
map_aami_symbol
plot_dsp_audit

Coding quality:
- full type hints;
- clear docstrings;
- no global mutable state;
- no silent exception swallowing;
- deterministic behavior;
- numerically guarded formulas;
- functions small enough to test independently;
- saveable coefficients;
- future C-port-friendly state layouts.

At the end, print or document a concise state-memory inventory showing which values firmware must preserve.
```

---

# 27. Prompt 3 — Build `tarang_v16_validation.py`

```text
Create an independent validation and firmware-export module named:
tarang_v16_validation.py

Read and obey:
Tarang_v16_Deployment_Aligned_Spec.md

Purpose:
This file must validate already-trained v16 models, calibrate thresholds on validation only, convert to full-int8 TFLite, compare float and int8 behavior, generate golden vectors, create firmware arrays/headers, generate a complete model contract, and write final reports.

It must NOT train models.
It must NOT silently edit model weights.
It must reload saved .keras models before locked evaluation.

Implement:

1. decode_cascade
2. gate-threshold search
3. V-threshold search with explicit precision floor
4. S-threshold search
5. complete validation metrics
6. locked test metrics
7. per-source metrics
8. false-negative audit
9. float model reload/reproduction check
10. representative dataset builder
11. full-int8 TFLite conversion
12. TFLite tensor inspection
13. TFLite operator inventory
14. dual-input int8 inference
15. output dequantization
16. V/S output-order verification
17. float-versus-int8 MAE and class mismatch
18. complete int8 test evaluation
19. deterministic golden-vector selection
20. .npz and JSON golden-vector export
21. C model-array export
22. thresholds.h export
23. rr_scaler.h export
24. dsp_coefficients.h export
25. tarang_model_contract.json export
26. SHA-256 hashes
27. final Markdown report

Validation rules:
- Thresholds are selected only from validation predictions.
- Test metrics are computed after thresholds are frozen.
- Never choose a threshold because it improves test performance.
- Save every candidate threshold and objective value.
- Fail if a requested precision/recall constraint cannot be met.
- Verify model input names, shapes, dtypes, scales, and zero points.
- Verify output mapping instead of assuming output order.
- Evaluate the entire test set, not a convenient subset.
- Representative data must come from v16-preprocessed training data only, with optional unlabeled real hardware examples for activation-range coverage.
- Include N/S/V, different amplitudes, jitter, quality states, and sources.
- Golden vectors must include normal, S, V, near-threshold, and activation-extreme examples.
- Q/unusable examples must be exported as DSP-blocked examples, not sent through the classifier as a fourth CNN class.

Required function signatures may resemble:

def decode_cascade(gate_p, v_p, s_p, thresholds): ...
def search_gate_threshold(y_true, gate_p, constraints): ...
def search_v_threshold(y_true, gate_p, v_p, constraints): ...
def search_s_threshold(y_true, gate_p, v_p, s_p, constraints): ...
def evaluate_cascade(...): ...
def convert_full_int8(model, representative_dataset, output_path): ...
def run_tflite_dual_input(...): ...
def compare_float_and_int8(...): ...
def generate_golden_vectors(...): ...
def export_model_contract(...): ...
def export_c_arrays(...): ...
def write_final_report(...): ...

Model contract must include:
- v16 pipeline version
- sample rate
- window geometry
- four RR feature names and order
- class mapping
- decoder arbitration
- frozen thresholds
- RR scaler
- model input/output metadata
- quantization parameters
- DSP config hash
- split-manifest hash
- model SHA-256 hashes
- software versions
- creation timestamp

Write tests for:
- cascade decoder boundaries
- both-heads-active arbitration
- no-route behavior
- threshold selection without test data
- int8 quantize/dequantize round trip
- tensor-name resolution
- deterministic golden selection
- hash stability
- C-array byte equality with original .tflite file

End with a machine-readable pass/fail summary for every acceptance gate.
```

---

# 28. Final execution order for the AI agent

The AI agent must work in this sequence:

```text
1. Inspect v15 and validation notebook.
2. Create migration table.
3. Implement tarang_dsp_reference.py.
4. Run DSP unit tests.
5. Implement tarang_v16_validation.py.
6. Run validation utility tests with dummy models/data.
7. Create Tarang_v16_Deployment_Aligned.ipynb.
8. Run clean-kernel smoke test.
9. Review all exclusion logs and split audits.
10. Run full feature extraction.
11. Validate detector and window alignment.
12. Train gate.
13. Train SV model.
14. Lock validation thresholds.
15. Reload models and run float test.
16. Convert to int8.
17. Run complete int8 test.
18. Generate golden vectors.
19. Export firmware headers and contract.
20. Write final report.
21. Stop before claiming EFR32 parity.
```

---

# 29. What happens after v16

After software v16 passes:

```text
model-only EFR32 golden-vector test
        ↓
Python-versus-C DSP replay parity
        ↓
raw ECG+IMU replay through full EFR32 pipeline
        ↓
live rest/motion/lead-off testing
        ↓
latency, RAM, flash, dropped-frame measurement
        ↓
current measurement and battery estimate
```

Do not begin by interpreting live human N/S/V predictions. First prove that the device receives the same bytes and produces the same quantized outputs as the host.

---

# 30. Final definition of done

v16 is ready for hardware inference validation when:

```text
the DSP is causal and stateful;
detector-centered windows are reproducible;
labels remain independent of detector heuristics;
the four-feature contract is frozen;
splits are auditable;
float models are reloadable;
thresholds are locked without test leakage;
int8 metrics are measured;
golden vectors are exported;
the firmware contract contains every constant needed to reproduce host inference.
```

Until then, v16 remains an experiment under construction.
