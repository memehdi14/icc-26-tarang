#!/usr/bin/env python3
"""
Stage 0 (Real Beat): Model Evaluation on Actual ECG Beat from kedartest.csv
==========================================================================
Extracts an actual R-peak window (130 samples, z-score normalized) and 
4 causal RR features from kedartest.csv to test Gate and SV Head models
on real human ECG data.
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path
import tensorflow as tf
from scipy import signal

# UTF-8 encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

FS = 250
GATE_MODEL_PATH = "gate_int8.tflite"
SV_MODEL_PATH = "sv_int8.tflite"

RR_MEAN = np.array([800.3590007725985, 796.7384548255626, 57.816683070621934, 79.81930623356297], dtype=np.float32)
RR_SCALE = np.array([206.5901695512491, 180.93584827296453, 92.44083802297374, 22.106307552466347], dtype=np.float32)

def quantize_int8(value, scale, zero_point):
    q = np.round(value / scale).astype(np.int32) + zero_point
    return np.clip(q, -128, 127).astype(np.int8)

def dequantize_int8(qvalue, scale, zero_point):
    return (qvalue.astype(np.float32) - zero_point) * scale

def load_kedartest():
    path = Path("../../tarang-dsp/integration_validation/captures/legacy/kedartest.csv")
    df = pd.read_csv(path, comment='#')
    ecg_rows = df[df['raw_line'].str.contains(r'\[ECG\]\s*raw=', na=False)]
    raw_vals = ecg_rows['raw_line'].str.extract(r'raw=(\d+)')[0].dropna().astype(int).values
    return raw_vals

def main():
    print("=" * 70)
    print("STAGE 0 VALIDATION: Real Human Beat from kedartest.csv")
    print("=" * 70)

    raw = load_kedartest()

    # Morphology filter (0.5 - 40 Hz)
    b_morph, a_morph = signal.butter(4, [0.5 / 125.0, 40.0 / 125.0], btype='bandpass')
    morph = signal.lfilter(b_morph, a_morph, raw)

    # Locate R-peaks on morphology
    gt_peaks, _ = signal.find_peaks(morph, distance=int(0.35 * FS), prominence=500)

    # Select a stable beat after initial startup (e.g. beat index 20, ~t=15s)
    beat_idx = 20
    r_peak_loc = gt_peaks[beat_idx]
    
    # 1. Extract 130-sample window centered at R-peak (65 pre-R, 65 post-R)
    start_idx = r_peak_loc - 65
    end_idx = r_peak_loc + 65
    raw_beat_window = morph[start_idx:end_idx].astype(np.float32)

    # Z-score normalize the 130-sample window (per DSP spec)
    mean_val = np.mean(raw_beat_window)
    std_val = np.std(raw_beat_window)
    if std_val < 1e-4: std_val = 1.0
    norm_beat_window = (raw_beat_window - mean_val) / std_val

    # 2. Compute 4 causal RR features from previous 5 beats
    past_peaks = gt_peaks[beat_idx-5 : beat_idx+1]
    rr_intervals_ms = np.diff(past_peaks) * (1000.0 / FS)
    
    rr_prev_ms = rr_intervals_ms[-1]
    rr_mean_5_ms = np.mean(rr_intervals_ms)
    rr_std_5_ms = np.std(rr_intervals_ms)
    local_hr_bpm = 60000.0 / rr_mean_5_ms

    rr_raw4 = np.array([rr_prev_ms, rr_mean_5_ms, rr_std_5_ms, local_hr_bpm], dtype=np.float32)

    print(f"\nExtracted Beat Details (Beat #{beat_idx} at t = {r_peak_loc/FS:.2f}s):")
    print(f"  R-peak sample index: {r_peak_loc}")
    print(f"  RR Features (Raw):   [rr_prev={rr_prev_ms:.1f}ms, mean5={rr_mean_5_ms:.1f}ms, std5={rr_std_5_ms:.1f}ms, HR={local_hr_bpm:.1f}bpm]")
    
    # Normalize RR features
    rr_normalized = (rr_raw4 - RR_MEAN) / RR_SCALE
    print(f"  RR Features (Norm):  {rr_normalized}")

    # Load Gate Model
    gate_interp = tf.lite.Interpreter(model_path=GATE_MODEL_PATH)
    gate_interp.allocate_tensors()
    g_inps = gate_interp.get_input_details()
    g_outs = gate_interp.get_output_details()

    # Quantize inputs for Gate
    g_rr_q = quantize_int8(rr_normalized, g_inps[0]['quantization'][0], g_inps[0]['quantization'][1]).reshape(1, 4)
    g_ecg_q = quantize_int8(norm_beat_window, g_inps[1]['quantization'][0], g_inps[1]['quantization'][1]).reshape(1, 130, 1)

    gate_interp.set_tensor(g_inps[0]['index'], g_rr_q)
    gate_interp.set_tensor(g_inps[1]['index'], g_ecg_q)
    gate_interp.invoke()

    g_out = gate_interp.get_tensor(g_outs[0]['index'])
    gate_prob = dequantize_int8(g_out[0, 0], g_outs[0]['quantization'][0], g_outs[0]['quantization'][1])

    # Load SV Head Model
    sv_interp = tf.lite.Interpreter(model_path=SV_MODEL_PATH)
    sv_interp.allocate_tensors()
    sv_inps = sv_interp.get_input_details()
    sv_outs = sv_interp.get_output_details()

    # Quantize inputs for SV Head
    sv_rr_q = quantize_int8(rr_normalized, sv_inps[0]['quantization'][0], sv_inps[0]['quantization'][1]).reshape(1, 4)
    sv_ecg_q = quantize_int8(norm_beat_window, sv_inps[1]['quantization'][0], sv_inps[1]['quantization'][1]).reshape(1, 130, 1)

    sv_interp.set_tensor(sv_inps[0]['index'], sv_rr_q)
    sv_interp.set_tensor(sv_inps[1]['index'], sv_ecg_q)
    sv_interp.invoke()

    v_out = sv_interp.get_tensor(sv_outs[0]['index'])
    s_out = sv_interp.get_tensor(sv_outs[1]['index'])

    p_v = dequantize_int8(v_out[0, 0], sv_outs[0]['quantization'][0], sv_outs[0]['quantization'][1])
    p_s = dequantize_int8(s_out[0, 0], sv_outs[1]['quantization'][0], sv_outs[1]['quantization'][1])

    print("\n" + "=" * 70)
    print("INFERENCE RESULTS ON REAL NORMAL SINUS BEAT")
    print("=" * 70)
    print(f"Gate CNN (P(abnormal)):       {gate_prob:.6f}  (Threshold: 0.25 -> {'REJECTED as Normal N' if gate_prob <= 0.25 else 'TRIGGER SV HEAD'})")
    print(f"SV Head Head 1 (P(V) - PVC):  {p_v:.6f}  (Threshold: 0.60 -> {'NORMAL' if p_v <= 0.60 else 'PVC (V)'})")
    print(f"SV Head Head 2 (P(S) - PAC):  {p_s:.6f}  (Threshold: 0.35 -> {'NORMAL' if p_s <= 0.35 else 'PAC (S)'})")

    # Evaluate several beats across the recording to verify consistency
    print("\n" + "=" * 70)
    print("MULTI-BEAT CHECK (Evaluating 10 Consecutive Real Beats):")
    print("=" * 70)
    for b in range(10, 20):
        ploc = gt_peaks[b]
        w = morph[ploc-65 : ploc+65].astype(np.float32)
        w_norm = (w - np.mean(w)) / (np.std(w) if np.std(w) > 1e-4 else 1.0)
        
        past_p = gt_peaks[b-5 : b+1]
        rrs = np.diff(past_p) * (1000.0 / FS)
        rr_raw = np.array([rrs[-1], np.mean(rrs), np.std(rrs), 60000.0/np.mean(rrs)], dtype=np.float32)
        rr_norm = (rr_raw - RR_MEAN) / RR_SCALE
        
        # Gate
        gate_interp.set_tensor(g_inps[0]['index'], quantize_int8(rr_norm, g_inps[0]['quantization'][0], g_inps[0]['quantization'][1]).reshape(1, 4))
        gate_interp.set_tensor(g_inps[1]['index'], quantize_int8(w_norm, g_inps[1]['quantization'][0], g_inps[1]['quantization'][1]).reshape(1, 130, 1))
        gate_interp.invoke()
        gp = dequantize_int8(gate_interp.get_tensor(g_outs[0]['index'])[0, 0], g_outs[0]['quantization'][0], g_outs[0]['quantization'][1])
        
        # SV
        sv_interp.set_tensor(sv_inps[0]['index'], quantize_int8(rr_norm, sv_inps[0]['quantization'][0], sv_inps[0]['quantization'][1]).reshape(1, 4))
        sv_interp.set_tensor(sv_inps[1]['index'], quantize_int8(w_norm, sv_inps[1]['quantization'][0], sv_inps[1]['quantization'][1]).reshape(1, 130, 1))
        sv_interp.invoke()
        pv = dequantize_int8(sv_interp.get_tensor(sv_outs[0]['index'])[0, 0], sv_outs[0]['quantization'][0], sv_outs[0]['quantization'][1])
        ps = dequantize_int8(sv_interp.get_tensor(sv_outs[1]['index'])[0, 0], sv_outs[1]['quantization'][0], sv_outs[1]['quantization'][1])
        
        print(f"Beat #{b} (t={ploc/FS:5.2f}s | HR={60000.0/np.mean(rrs):4.1f}bpm): Gate P={gp:.4f} | P(V)={pv:.4f} | P(S)={ps:.4f} -> Final Class: Normal N")

if __name__ == "__main__":
    main()
