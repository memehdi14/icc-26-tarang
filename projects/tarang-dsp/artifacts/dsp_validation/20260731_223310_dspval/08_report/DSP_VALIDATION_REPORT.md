# Tarang - Standalone DSP Validation Report

**Run ID:** 20260731_223310_dspval
**Generated:** 2026-07-31 23:07:57
**Artifacts:** artifacts\dsp_validation\20260731_223310_dspval
**INCART records:** 75 processed of 75 available of 75 total

---

## Validation Summary

**Verdict: NOT READY - see failures below**

| Gate | Status | Details |
|---|---|---|
| Unit tests | FAIL | 17/18 passed |
| Chunk invariance | PASS | All chunking methods identical |
| Causality | PASS | No future-sample leakage |
| Filter characterization | PASS | Impulse, step, freq response saved |
| Detector N recall | FAIL | N recall = 0.3414 (target >= 0.90) |
| No record < 0.50 recall | FAIL | 48 records below 0.50 |
| V recall (measured) | BUG (misses spread across RR intervals - investigate) | 0.1736 aggregate, 2701 missed |
| Window alignment | PASS | Mean offset +1.93 samples |
| Normalization | PASS | No future leakage, no frame reset |
| NLMS ablation | SKIPPED | No synchronized IMU data |

---

## Detector Validation

**75 of 75 available records processed (of 75 total in INCART).**

| Metric | Value |
|---|---|
| Precision | 0.9385 |
| Recall | 0.3256 |
| N recall | 0.3414 |
| V recall | 0.1736 |
| Timing mean | +5.12 ms |

## Coupling-Interval Analysis (V recall)

| Bucket | Count | % |
|---|---|---|
| < 200ms (refractory) | 0 | 0.0% |
| 200-250ms (MWI overlap) | 0 | 0.0% |
| >= 250ms (longer) | 2701 | 100.0% |
| **Decision** | BUG (misses spread across RR intervals - investigate) |

---

## Conclusion

The DSP pipeline has **failures that must be fixed**. See the table above.
- N recall (0.3414) below 0.90 target
- 48 records with recall < 0.50: ['I01', 'I03', 'I04', 'I05', 'I07', 'I08', 'I09', 'I11', 'I12', 'I13', 'I14', 'I16', 'I18', 'I19', 'I20', 'I21', 'I23', 'I24', 'I27', 'I28', 'I29', 'I30', 'I31', 'I32', 'I36', 'I37', 'I38', 'I39', 'I40', 'I42', 'I43', 'I44', 'I45', 'I56', 'I57', 'I58', 'I60', 'I61', 'I63', 'I64', 'I65', 'I66', 'I67', 'I69', 'I70', 'I72', 'I73', 'I75']

**Validated on 75 of 75 INCART records. Full re-run required on your machine.**

---

**Artifacts:** `artifacts\dsp_validation\20260731_223310_dspval`