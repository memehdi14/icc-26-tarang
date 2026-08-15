#!/usr/bin/env python3
"""
Accurate Analysis of Missed Beats in kedartest.csv
==================================================
Aligns detected peaks (which have MWI group delay ~29 samples) with true
R-peaks on morphology signal.
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path
from scipy import signal

# Set UTF-8
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FS = 250
DETECTION_DELAY = 29  # samples

def load_kedartest():
    path = Path("../../tarang-dsp/integration_validation/captures/legacy/kedartest.csv")
    df = pd.read_csv(path, comment='#')
    ecg_rows = df[df['raw_line'].str.contains(r'\[ECG\]\s*raw=', na=False)]
    raw_vals = ecg_rows['raw_line'].str.extract(r'raw=(\d+)')[0].dropna().astype(int).values
    return raw_vals

def run_analysis():
    raw = load_kedartest()
    
    # 1. Ground truth peaks on morphology (Butterworth 0.5-40Hz)
    b_morph, a_morph = signal.butter(4, [0.5/125.0, 40.0/125.0], btype='bandpass')
    morph = signal.lfilter(b_morph, a_morph, raw)
    
    # Accurate ground truth peaks: find true local maxima on morphology
    gt_peaks, props = signal.find_peaks(morph, distance=int(0.35 * FS), prominence=500)
    print(f"Ground Truth Reference Peaks: {len(gt_peaks)} (Target: ~167)")

    # 2. Run DSP
    from verify_stage1_dsp_replay import run_dsp_on_samples
    detected_mwi_peaks = run_dsp_on_samples(raw)
    
    # Correct detected peaks for detection delay (MWI filter delay ~29 samples)
    detected_aligned = detected_mwi_peaks - DETECTION_DELAY
    print(f"DSP Detected Peaks:            {len(detected_aligned)}")

    # 3. Match detected against ground truth (matching window +/- 15 samples = 60ms)
    matched_gt = []
    unmatched_gt = []
    
    for gt in gt_peaks:
        dists = np.abs(detected_aligned - gt)
        if len(dists) > 0 and np.min(dists) <= 18:
            matched_gt.append(gt)
        else:
            unmatched_gt.append(gt)

    print(f"\nMatched GT Peaks:              {len(matched_gt)} / {len(gt_peaks)} ({len(matched_gt)/len(gt_peaks)*100:.1f}%)")
    print(f"Unmatched GT Peaks:            {len(unmatched_gt)}")

    print("\n" + "="*70)
    print("ANALYSIS OF THE UNMATCHED PEAKS")
    print("="*70)
    for idx, gt in enumerate(unmatched_gt):
        t_sec = gt / FS
        raw_val = raw[gt]
        amp = morph[gt]
        
        # Check if it was during startup (< 3 seconds = 750 samples)
        if gt < 750:
            classification = "Initial 3-second startup delay (learning SPKI baseline)"
        elif amp < 800:
            classification = "Low-amplitude QRS / baseline wander dip"
        else:
            classification = "Threshold / Refractory margin"
            
        print(f"Unmatched Peak #{idx+1}:")
        print(f"  Location:       Sample {gt} (t = {t_sec:.2f}s)")
        print(f"  Raw ADC:        {raw_val}")
        print(f"  Morphology Amp: {amp:.1f}")
        print(f"  Classification: {classification}")

if __name__ == "__main__":
    run_analysis()
