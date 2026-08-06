# Tarang - Standalone DSP Validation Report

**Run ID:** 20260801_003842_dspval
**Generated:** 2026-08-01 01:11:49
**Artifacts:** artifacts\dsp_validation\20260801_003842_dspval
**INCART records:** 75 processed of 75 available of 75 total

---

## Validation Summary

**Verdict: NOT READY - see failures below**

| Gate | Status | Details |
|---|---|---|
| Unit tests | FAIL | 15/18 passed |
| Chunk invariance | FAIL | All chunking methods identical |
| Causality | PASS | No future-sample leakage |
| Filter characterization | PASS | Impulse, step, freq response saved |
| Detector N recall | FAIL | N recall = 0.6768 (target >= 0.90) |
| No record < 0.50 recall | FAIL | 23 records below 0.50 |
| V recall (measured) | BUG (misses spread across RR intervals - investigate) | 0.4434 aggregate, 5255 missed |
| Window alignment | PASS | Mean offset +1.90 samples |
| Normalization | PASS | No future leakage, no frame reset |
| NLMS ablation | SKIPPED | No synchronized IMU data |

---

## Detector Validation

**75 of 75 available records processed (of 75 total in INCART).**

| Metric | Value |
|---|---|
| Precision | 0.9445 |
| Recall | 0.6519 |
| N recall | 0.6768 |
| V recall | 0.4434 |
| Timing mean | +4.90 ms |

## Coupling-Interval Analysis (V recall)

| Bucket | Count | % |
|---|---|---|
| < 200ms (refractory) | 0 | 0.0% |
| 200-250ms (MWI overlap) | 0 | 0.0% |
| >= 250ms (longer) | 5255 | 100.0% |
| **Decision** | BUG (misses spread across RR intervals - investigate) |

---

## Conclusion

The DSP pipeline has **failures that must be fixed**. See the table above.
- N recall (0.6768) below 0.90 target
- 23 records with recall < 0.50: ['I03', 'I04', 'I13', 'I14', 'I18', 'I21', 'I24', 'I27', 'I28', 'I30', 'I31', 'I32', 'I37', 'I38', 'I39', 'I43', 'I56', 'I57', 'I60', 'I63', 'I64', 'I66', 'I73']

**Validated on 75 of 75 INCART records. Full re-run required on your machine.**

---

**Artifacts:** `artifacts\dsp_validation\20260801_003842_dspval`