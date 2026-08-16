#!/usr/bin/env python3
"""
Tarang DSP — Root-Cause Diagnostic for Wholesale Detector Failures

This script diagnoses WHY the Pan-Tompkins detector fails completely on
~30% of INCART records (0.000 recall). It does NOT fix anything — it
collects the evidence needed to identify the root cause.

Run it on your machine where all 75 INCART records are available:
    python dsp_failure_diagnostic.py

It will produce:
    dsp_diagnostic_report.txt  — per-record analysis
    dsp_diagnostic_figures/    — raw vs filtered vs MWI plots for worst records

The three hypotheses being tested (per review feedback):
  2a. Channel/lead index, sample rate, silently swallowed exceptions
  2b. Adaptive threshold drift over 30-minute records (recall per 5-min chunk)
  2c. Amplitude/gain consistency (does recall correlate with raw signal std?)
"""
import os
import sys
import json
import time
import traceback
from pathlib import Path
import numpy as np

INCAR_DIR = os.environ.get("INCART_DIR", str(Path(__file__).resolve().parents[2] / "dataset" / "incartdb"))

OUTPUT_DIR = Path('dsp_diagnostic_output')
OUTPUT_DIR.mkdir(exist_ok=True)
FIG_DIR = OUTPUT_DIR / 'figures'
FIG_DIR.mkdir(exist_ok=True)

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

import wfdb
sys.path.insert(0, '.')
import tarang_dsp_reference as dsp

AAMI = {'N':'N','L':'N','R':'N','e':'N','j':'N',
        'A':'S','a':'S','J':'S','S':'S',
        'V':'V','E':'V'}

config = dsp.DSPConfig()

# ── Find all INCART records ──
incart_recs = []
for i in range(1, 76):
    r = f'I{i:02d}'
    if all(os.path.exists(os.path.join(INCAR_DIR, f'{r}.{ext}')) for ext in ['hea', 'dat', 'atr']):
        incart_recs.append(r)

print(f"Found {len(incart_recs)} INCART records")
print(f"INCAR_DIR: {INCAR_DIR}")
print()

# ── Storage ──
all_lines = []
all_stats = []

def log(msg):
    all_lines.append(msg)
    print(msg)

log("=" * 80)
log("TARANG DSP — ROOT-CAUSE DIAGNOSTIC FOR WHOLESALE DETECTOR FAILURES")
log("=" * 80)
log("")
log(f"Records: {len(incart_recs)}")
log(f"Hypotheses being tested:")
log("  2a. Channel/lead index, sample rate, silently swallowed exceptions")
log("  2b. Adaptive threshold drift over 30-minute records")
log("  2c. Amplitude/gain consistency (recall vs raw signal std)")
log("")

# ── Process each record ──
for rec_name in incart_recs:
    log(f"--- {rec_name} ---")
    
    try:
        # ── 2a: Check channel/lead info ──
        rec_full = wfdb.rdrecord(os.path.join(INCAR_DIR, rec_name))
        ann = wfdb.rdann(os.path.join(INCAR_DIR, rec_name), 'atr')
        
        log(f"  fs={rec_full.fs} Hz, sig_len={rec_full.sig_len}, duration={rec_full.sig_len/rec_full.fs:.1f}s")
        log(f"  sig_name={rec_full.sig_name}")
        log(f"  n_sig={rec_full.n_sig}, units={rec_full.units}")
        
        # Verify Lead I index
        if 'I' in rec_full.sig_name:
            lead_i_idx = rec_full.sig_name.index('I')
            log(f"  Lead I at index {lead_i_idx}")
        else:
            lead_i_idx = 0
            log(f"  WARNING: 'I' not in sig_name! Using channel 0 ({rec_full.sig_name[0]})")
        
        # Read channel 0 (what the detector uses)
        rec = wfdb.rdrecord(os.path.join(INCAR_DIR, rec_name), channels=[0])
        raw = rec.p_signal[:, 0].astype(np.float64)
        src_fs = rec.fs
        
        # ── 2c: Raw signal stats ──
        raw_std = float(np.std(raw))
        raw_range = float(np.max(raw) - np.min(raw))
        raw_pp = raw_range  # peak-to-peak
        sat_frac = float(np.mean(np.abs(raw) > 0.99 * np.max(np.abs(raw))))
        
        log(f"  Raw ch0: std={raw_std:.4f} range={raw_range:.4f} sat_frac={sat_frac:.6f}")
        
        # ── Resample and run detector ──
        sig = dsp.resample_signal(raw, src_fs, 250)
        ann_target = np.round(ann.sample.astype(np.float64) * 250 / src_fs).astype(int)
        
        stream = dsp.StreamingTarangDSP(config)
        packets = stream.process_record(sig)
        detected = [p.r_peak_index for p in packets 
                    if p.quality_state == 'GOOD' or 'STARTUP' not in p.quality_flags]
        
        # True annotations
        true_peaks = []
        true_labels = []
        for s, sym in zip(ann_target, ann.symbol):
            aami = AAMI.get(sym, 'IGNORE')
            if aami == 'IGNORE':
                continue
            true_peaks.append(int(s))
            true_labels.append(aami)
        
        # Match
        tol = 37  # 150ms at 250Hz
        matched_true = set()
        for d_peak in detected:
            best_idx, best_diff = -1, tol + 1
            for j in range(len(true_peaks)):
                if j in matched_true:
                    continue
                diff = abs(true_peaks[j] - d_peak)
                if diff < best_diff:
                    best_diff = diff
                    best_idx = j
            if best_idx >= 0 and best_diff <= tol:
                matched_true.add(best_idx)
        
        tp = len(matched_true)
        fp_count = len(detected) - tp
        fn_count = len(true_peaks) - tp
        precision = tp / max(tp + fp_count, 1)
        recall = tp / max(tp + fn_count, 1)
        
        # Per-class
        pc = {}
        for cls in ['N', 'S', 'V']:
            ci = [j for j, l in enumerate(true_labels) if l == cls]
            cm = sum(1 for j in ci if j in matched_true)
            pc[cls] = {'total': len(ci), 'detected': cm, 'recall': cm / max(len(ci), 1)}
        
        # ── 2a: Check SPKI/NPKI/TH1 after processing ──
        spki = stream._thresh_state.SPKI
        npki = stream._thresh_state.NPKI
        th1 = stream._thresh_state.TH1
        
        log(f"  Detector: {len(detected)} detected, {len(true_peaks)} true, recall={recall:.4f}")
        log(f"  N_rec={pc['N']['recall']:.3f} S_rec={pc['S']['recall']:.3f} V_rec={pc['V']['recall']:.3f}")
        log(f"  Final: SPKI={spki:.2f} NPKI={npki:.2f} TH1={th1:.2f}")
        
        # ── 2b: Recall per 5-minute chunk ──
        chunk_size = 5 * 60 * 250  # 5 minutes at 250Hz
        n_chunks = max(1, len(sig) // chunk_size)
        chunk_recalls = []
        
        for chunk_idx in range(n_chunks):
            chunk_start = chunk_idx * chunk_size
            chunk_end = min((chunk_idx + 1) * chunk_size, len(sig))
            
            # Annotations in this chunk
            chunk_true = [tp for tp in true_peaks if chunk_start <= tp < chunk_end]
            # Detections in this chunk
            chunk_det = [d for d in detected if chunk_start <= d < chunk_end]
            
            # Match within chunk
            chunk_matched = 0
            used = set()
            for d in chunk_det:
                best_j, best_diff = -1, tol + 1
                for j in range(len(chunk_true)):
                    if j in used:
                        continue
                    diff = abs(chunk_true[j] - d)
                    if diff < best_diff:
                        best_diff = diff
                        best_j = j
                if best_j >= 0 and best_diff <= tol:
                    chunk_matched += 1
                    used.add(best_j)
            
            chunk_recall = chunk_matched / max(len(chunk_true), 1)
            chunk_recalls.append(chunk_recall)
        
        # Report chunk recalls
        chunk_str = " ".join(f"{r:.2f}" for r in chunk_recalls)
        log(f"  Recall per 5-min chunk: [{chunk_str}]")
        
        # Detect drift: does recall drop significantly in later chunks?
        if len(chunk_recalls) >= 4:
            early_recall = np.mean(chunk_recalls[:2])
            late_recall = np.mean(chunk_recalls[-2:])
            drift = late_recall - early_recall
            log(f"  Drift: early={early_recall:.3f} late={late_recall:.3f} delta={drift:+.3f}")
            if drift < -0.2:
                log(f"  *** SIGNIFICANT DRIFT DETECTED (recall drops >0.20 from early to late) ***")
        else:
            drift = 0.0
        
        # ── 2b: SPKI/NPKI/TH1 at key points ──
        # Re-run and sample SPKI at 1min, 5min, 10min, 20min, 30min
        stream2 = dsp.StreamingTarangDSP(config)
        spki_samples = []
        check_points = [1*60*250, 5*60*250, 10*60*250, 20*60*250, 30*60*250]
        check_idx = 0
        
        for i in range(len(sig)):
            packets_step = stream2.process_sample(float(sig[i]))
            if check_idx < len(check_points) and i >= check_points[check_idx]:
                spki_samples.append((i / 250.0 / 60.0, stream2._thresh_state.SPKI, 
                                    stream2._thresh_state.NPKI, stream2._thresh_state.TH1))
                check_idx += 1
        
        spki_str = " ".join(f"{s[0]:.0f}min:SPKI={s[1]:.1f}/TH1={s[3]:.1f}" for s in spki_samples)
        log(f"  SPKI/TH1 over time: {spki_str}")
        
        # ── Store stats for 2c analysis ──
        all_stats.append({
            'record': rec_name,
            'recall': recall,
            'precision': precision,
            'n_recall': pc['N']['recall'],
            'v_recall': pc['V']['recall'],
            'raw_std': raw_std,
            'raw_range': raw_range,
            'spki_final': spki,
            'th1_final': th1,
            'drift': drift,
            'n_detected': len(detected),
            'n_true': len(true_peaks),
            'chunk_recalls': chunk_recalls,
            'spki_over_time': [(s[0], s[1], s[3]) for s in spki_samples],
        })
        
        # ── 2a: Plot raw/filtered/MWI for worst records ──
        if recall < 0.10:
            log(f"  *** CATASTROPHIC FAILURE (recall < 0.10) — generating diagnostic plot ***")
            
            # Get MWI output for first 30 seconds
            stream3 = dsp.StreamingTarangDSP(config)
            stream3.process_record(sig[:7500])  # 30 seconds
            
            morph = []
            mwi = []
            for i in range(min(7500, len(sig))):
                v = stream3._get_buffer_value(stream3._norm_buffer, i)
                morph.append(v if v is not None else 0.0)
                v = stream3._get_buffer_value(stream3._mwi_buffer, i)
                mwi.append(v if v is not None else 0.0)
            
            anns_30s = [int(a) for a in ann_target if a < 7500]
            dets_30s = [d for d in detected if d < 7500]
            
            fig, axes = plt.subplots(4, 1, figsize=(16, 14), constrained_layout=True)
            t = np.arange(min(7500, len(sig))) / 250.0
            
            # Raw
            axes[0].plot(t, sig[:7500], 'b-', lw=0.5)
            axes[0].set_title(f'{rec_name} — Raw signal (ch0, 250Hz) — recall={recall:.3f}')
            axes[0].set_ylabel('Amplitude')
            for a in anns_30s:
                axes[0].axvline(x=a/250.0, color='green', lw=0.5, alpha=0.4)
            axes[0].grid(True, alpha=0.3)
            
            # Filtered (morphology)
            axes[1].plot(t, morph, 'g-', lw=0.5)
            axes[1].set_title('Morphology (z-scored)')
            axes[1].set_ylabel('Z-score')
            for a in anns_30s:
                axes[1].axvline(x=a/250.0, color='green', lw=0.5, alpha=0.4)
            axes[1].grid(True, alpha=0.3)
            
            # MWI
            axes[2].plot(t, mwi, 'r-', lw=0.5)
            axes[2].set_title(f'MWI output (SPKI={spki:.1f}, TH1={th1:.1f})')
            axes[2].set_ylabel('MWI')
            axes[2].axhline(y=th1, color='black', ls='--', lw=1, label=f'TH1={th1:.1f}')
            axes[2].axhline(y=spki, color='blue', ls=':', lw=1, label=f'SPKI={spki:.1f}')
            for a in anns_30s:
                axes[2].axvline(x=a/250.0, color='green', lw=0.5, alpha=0.4)
            axes[2].legend(fontsize=8)
            axes[2].grid(True, alpha=0.3)
            
            # SPKI/TH1 over time
            if spki_samples:
                times = [s[0] for s in spki_samples]
                spkis = [s[1] for s in spki_samples]
                th1s = [s[3] for s in spki_samples]
                axes[3].plot(times, spkis, 'b-o', label='SPKI', lw=1.5)
                axes[3].plot(times, th1s, 'r-o', label='TH1', lw=1.5)
                axes[3].set_title('SPKI and TH1 over time (threshold drift check)')
                axes[3].set_xlabel('Time (minutes)')
                axes[3].set_ylabel('Threshold value')
                axes[3].legend()
                axes[3].grid(True, alpha=0.3)
            
            fig.savefig(str(FIG_DIR / f"failure_{rec_name}.png"), dpi=120)
            plt.close()
            log(f"  Plot saved: figures/failure_{rec_name}.png")
        
    except Exception as e:
        log(f"  ERROR: {type(e).__name__}: {str(e)[:200]}")
        log(f"  {traceback.format_exc()[:500]}")
        all_stats.append({
            'record': rec_name, 'recall': -1, 'error': str(e)[:200],
            'raw_std': 0, 'raw_range': 0, 'spki_final': 0, 'th1_final': 0,
            'drift': 0, 'n_detected': 0, 'n_true': 0,
            'chunk_recalls': [], 'spki_over_time': [],
            'n_recall': 0, 'v_recall': 0, 'precision': 0,
        })
    
    log("")

# ── 2c: Amplitude/gain correlation analysis ──
log("=" * 80)
log("SECTION 2c: AMPLITUDE/GAIN CORRELATION ANALYSIS")
log("=" * 80)
log("")

valid_stats = [s for s in all_stats if s.get('recall', -1) >= 0]
if len(valid_stats) >= 5:
    recalls = np.array([s['recall'] for s in valid_stats])
    raw_stds = np.array([s['raw_std'] for s in valid_stats])
    raw_ranges = np.array([s['raw_range'] for s in valid_stats])
    spkis = np.array([s['spki_final'] for s in valid_stats])
    th1s = np.array([s['th1_final'] for s in valid_stats])
    
    # Correlation: recall vs raw_std
    corr_std = np.corrcoef(recalls, raw_stds)[0, 1] if len(recalls) > 1 else 0
    corr_range = np.corrcoef(recalls, raw_ranges)[0, 1] if len(recalls) > 1 else 0
    corr_spki = np.corrcoef(recalls, spkis)[0, 1] if len(recalls) > 1 else 0
    corr_th1 = np.corrcoef(recalls, th1s)[0, 1] if len(recalls) > 1 else 0
    
    log(f"Correlation (recall vs raw_std):     {corr_std:+.4f}")
    log(f"Correlation (recall vs raw_range):   {corr_range:+.4f}")
    log(f"Correlation (recall vs SPKI_final):  {corr_spki:+.4f}")
    log(f"Correlation (recall vs TH1_final):   {corr_th1:+.4f}")
    log("")
    
    if abs(corr_th1) > 0.5:
        log(f"*** STRONG CORRELATION between recall and TH1 ({corr_th1:+.4f}) ***")
        log(f"    Records with high TH1 tend to have {'low' if corr_th1 < 0 else 'high'} recall.")
        log(f"    This suggests TH1 is being set too high on some records.")
    
    # Sort by recall and show top/bottom 5
    log("")
    log("Top 5 (best recall):")
    sorted_stats = sorted(valid_stats, key=lambda x: x['recall'], reverse=True)
    log(f"  {'rec':<6} {'recall':>7} {'raw_std':>8} {'SPKI':>8} {'TH1':>8} {'drift':>7}")
    for s in sorted_stats[:5]:
        log(f"  {s['record']:<6} {s['recall']:>7.4f} {s['raw_std']:>8.4f} {s['spki_final']:>8.1f} {s['th1_final']:>8.1f} {s['drift']:>+7.3f}")
    
    log("")
    log("Bottom 5 (worst recall):")
    log(f"  {'rec':<6} {'recall':>7} {'raw_std':>8} {'SPKI':>8} {'TH1':>8} {'drift':>7}")
    for s in sorted_stats[-5:]:
        log(f"  {s['record']:<6} {s['recall']:>7.4f} {s['raw_std']:>8.4f} {s['spki_final']:>8.1f} {s['th1_final']:>8.1f} {s['drift']:>+7.3f}")
    
    # Check for drift
    log("")
    log("Drift analysis (recall drops from early to late in record):")
    drifted = [s for s in valid_stats if s.get('drift', 0) < -0.2]
    log(f"  Records with significant drift (early-late > 0.20): {len(drifted)}")
    for s in drifted:
        chunk_str = " ".join(f"{r:.2f}" for r in s.get('chunk_recalls', []))
        log(f"    {s['record']}: drift={s['drift']:+.3f}, chunks=[{chunk_str}]")
    
    if not drifted:
        log(f"  No significant drift detected — failure is NOT time-dependent.")

# ── Summary ──
log("")
log("=" * 80)
log("DIAGNOSTIC SUMMARY")
log("=" * 80)
log("")

n_total = len(all_stats)
n_valid = len(valid_stats)
n_broken = sum(1 for s in valid_stats if s['recall'] < 0.10)
n_partial = sum(1 for s in valid_stats if 0.10 <= s['recall'] < 0.50)
n_working = sum(1 for s in valid_stats if s['recall'] >= 0.50)

log(f"Total records: {n_total}")
log(f"  Valid (no error): {n_valid}")
log(f"  Broken (recall < 0.10): {n_broken}")
log(f"  Partial (0.10 <= recall < 0.50): {n_partial}")
log(f"  Working (recall >= 0.50): {n_working}")
log("")

# List broken records
broken_recs = [s['record'] for s in valid_stats if s['recall'] < 0.10]
if broken_recs:
    log(f"Broken records: {broken_recs}")
    log("")
    log("Check the diagnostic plots in figures/ for each broken record.")
    log("Look at: raw signal amplitude, MWI output vs TH1, SPKI over time.")

# ── Save everything ──
report_path = OUTPUT_DIR / "dsp_diagnostic_report.txt"
report_path.write_text("\n".join(all_lines) + "\n", encoding="utf-8")
print(f"\nReport saved: {report_path}")
print(f"Figures saved: {FIG_DIR}/")

# Save JSON stats
json_path = OUTPUT_DIR / "dsp_diagnostic_stats.json"
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(all_stats, f, indent=2, default=str)
print(f"Stats JSON saved: {json_path}")
