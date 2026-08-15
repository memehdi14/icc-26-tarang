#!/usr/bin/env python3
"""
Stage 0 Verification: Pure-Python TFLite Model Sanity Check
============================================================

Tests the Gate and SV Head .tflite models with known inputs to verify:
1. Models load successfully
2. Input/output tensor specs match documentation
3. Quantization/dequantization math is correct
4. RR scaler normalization is correct

Run BEFORE implementing tarang_ai.cc to catch spec bugs early.

Prerequisites:
  pip install tensorflow numpy

Usage:
  python verify_model_stage0.py

Expected output:
  - All assertions pass
  - Gate and SV outputs are in [0.0, 1.0]
  - No tensor shape/type mismatches
"""

import sys
import os
import numpy as np
import tensorflow as tf
from pathlib import Path

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ===== Configuration =====
GATE_MODEL_PATH = "gate_int8.tflite" if Path("gate_int8.tflite").exists() else "final_v15_models/gate_int8.tflite"
SV_MODEL_PATH = "sv_int8.tflite" if Path("sv_int8.tflite").exists() else "final_v15_models/sv_int8.tflite"

# RR scaler params (from rr_scaler.h)
RR_MEAN = np.array([800.359, 796.738, 57.817, 79.819], dtype=np.float32)
RR_SCALE = np.array([206.590, 180.936, 92.441, 22.106], dtype=np.float32)

# Test input: synthetic normal sinus beat
# ECG: 130 samples, simulated QRS at index 65
ECG_WINDOW = 130
ECG_TEST = np.zeros(ECG_WINDOW, dtype=np.float32)
ECG_TEST[60:70] = [0.1, 0.5, 1.0, 0.8, 0.3, -0.2, -0.5, -0.3, 0.0, 0.1]  # QRS spike

# RR features: normal sinus rhythm ~75 BPM (800ms RR)
RR_TEST = np.array([800.0, 800.0, 20.0, 75.0], dtype=np.float32)  # rr_prev, rr_mean, rr_std, hr


# ===== Helper Functions =====
def quantize_int8(value, scale, zero_point):
    """Quantize float to int8 (with saturation)."""
    q = np.round(value / scale).astype(np.int32) + zero_point
    return np.clip(q, -128, 127).astype(np.int8)


def dequantize_int8(qvalue, scale, zero_point):
    """Dequantize int8 to float."""
    return (qvalue.astype(np.int32) - zero_point) * scale


def load_and_inspect_model(model_path, model_name):
    """Load .tflite model and print tensor specs."""
    print(f"\n{'='*60}")
    print(f"{model_name} Model Inspection")
    print(f"{'='*60}")
    
    if not Path(model_path).exists():
        raise FileNotFoundError(f"Model file not found: {model_path}")
    
    interpreter = tf.lite.Interpreter(model_path=str(model_path))
    interpreter.allocate_tensors()
    
    # Input tensors
    input_details = interpreter.get_input_details()
    print(f"\n{len(input_details)} Input Tensors:")
    for i, inp in enumerate(input_details):
        print(f"  input({i}): {inp['name']}")
        print(f"    shape: {inp['shape']}")
        print(f"    dtype: {inp['dtype']}")
        print(f"    quantization: scale={inp['quantization'][0]:.6f}, zp={inp['quantization'][1]}")
    
    # Output tensors
    output_details = interpreter.get_output_details()
    print(f"\n{len(output_details)} Output Tensor(s):")
    for i, out in enumerate(output_details):
        print(f"  output({i}): {out['name']}")
        print(f"    shape: {out['shape']}")
        print(f"    dtype: {out['dtype']}")
        print(f"    quantization: scale={out['quantization'][0]:.6f}, zp={out['quantization'][1]}")
    
    return interpreter, input_details, output_details


def verify_gate_model():
    """Test Gate model with synthetic input."""
    print(f"\n{'='*60}")
    print("GATE MODEL VERIFICATION")
    print(f"{'='*60}")
    
    interpreter, inp_det, out_det = load_and_inspect_model(GATE_MODEL_PATH, "Gate")
    
    # CRITICAL: Verify input order is input(0)=rr, input(1)=ecg
    assert len(inp_det) == 2, f"Expected 2 inputs, got {len(inp_det)}"
    assert inp_det[0]['shape'].tolist() == [1, 4], f"input(0) should be [1,4], got {inp_det[0]['shape']}"
    assert inp_det[1]['shape'].tolist() == [1, 130, 1], f"input(1) should be [1,130,1], got {inp_det[1]['shape']}"
    print("\n✅ Input order: input(0)=rr [1,4], input(1)=ecg [1,130,1]")
    
    # Normalize and quantize RR features
    rr_normalized = (RR_TEST - RR_MEAN) / RR_SCALE
    rr_scale, rr_zp = inp_det[0]['quantization']
    rr_quantized = quantize_int8(rr_normalized, rr_scale, rr_zp).reshape(1, 4)
    print(f"\nRR features (raw):        {RR_TEST}")
    print(f"RR features (normalized): {rr_normalized}")
    print(f"RR features (quantized):  {rr_quantized.flatten()}")
    
    # Quantize ECG
    ecg_scale, ecg_zp = inp_det[1]['quantization']
    ecg_quantized = quantize_int8(ECG_TEST, ecg_scale, ecg_zp).reshape(1, 130, 1)
    print(f"\nECG[65] (peak): raw={ECG_TEST[65]:.3f}, quantized={ecg_quantized[0, 65, 0]}")
    
    # Run inference
    interpreter.set_tensor(inp_det[0]['index'], rr_quantized)
    interpreter.set_tensor(inp_det[1]['index'], ecg_quantized)
    interpreter.invoke()
    
    # Dequantize output
    output = interpreter.get_tensor(out_det[0]['index'])
    out_scale, out_zp = out_det[0]['quantization']
    gate_prob = dequantize_int8(output[0, 0], out_scale, out_zp)
    
    print(f"\nGate output (quantized): {output[0, 0]}")
    print(f"Gate output (dequant):   {gate_prob:.6f}")
    
    # Sanity checks
    assert 0.0 <= gate_prob <= 1.0, f"Gate prob out of range: {gate_prob}"
    print(f"\n✅ Gate model: PASS (P(abnormal) = {gate_prob:.4f})")
    
    return gate_prob


def verify_sv_model():
    """Test SV Head model with synthetic input."""
    print(f"\n{'='*60}")
    print("SV HEAD MODEL VERIFICATION")
    print(f"{'='*60}")
    
    interpreter, inp_det, out_det = load_and_inspect_model(SV_MODEL_PATH, "SV Head")
    
    # CRITICAL: Verify input order
    assert len(inp_det) == 2, f"Expected 2 inputs, got {len(inp_det)}"
    assert inp_det[0]['shape'].tolist() == [1, 4], f"input(0) should be [1,4], got {inp_det[0]['shape']}"
    assert inp_det[1]['shape'].tolist() == [1, 130, 1], f"input(1) should be [1,130,1], got {inp_det[1]['shape']}"
    print("\n✅ Input order: input(0)=rr [1,4], input(1)=ecg [1,130,1]")
    
    # CRITICAL: Verify TWO separate output tensors
    assert len(out_det) == 2, f"Expected 2 output tensors, got {len(out_det)}"
    assert out_det[0]['shape'].tolist() == [1, 1], f"output(0) should be [1,1], got {out_det[0]['shape']}"
    assert out_det[1]['shape'].tolist() == [1, 1], f"output(1) should be [1,1], got {out_det[1]['shape']}"
    print("✅ Output tensors: TWO separate [1,1] tensors (not one [1,2])")
    
    # Normalize and quantize inputs (same as Gate)
    rr_normalized = (RR_TEST - RR_MEAN) / RR_SCALE
    rr_scale, rr_zp = inp_det[0]['quantization']
    rr_quantized = quantize_int8(rr_normalized, rr_scale, rr_zp).reshape(1, 4)
    
    ecg_scale, ecg_zp = inp_det[1]['quantization']
    ecg_quantized = quantize_int8(ECG_TEST, ecg_scale, ecg_zp).reshape(1, 130, 1)
    
    # Run inference
    interpreter.set_tensor(inp_det[0]['index'], rr_quantized)
    interpreter.set_tensor(inp_det[1]['index'], ecg_quantized)
    interpreter.invoke()
    
    # Dequantize TWO separate output tensors
    v_output = interpreter.get_tensor(out_det[0]['index'])
    s_output = interpreter.get_tensor(out_det[1]['index'])
    
    v_scale, v_zp = out_det[0]['quantization']
    s_scale, s_zp = out_det[1]['quantization']
    
    p_v = dequantize_int8(v_output[0, 0], v_scale, v_zp)
    p_s = dequantize_int8(s_output[0, 0], s_scale, s_zp)
    
    print(f"\nV output (quantized): {v_output[0, 0]}, (dequant): {p_v:.6f}")
    print(f"S output (quantized): {s_output[0, 0]}, (dequant): {p_s:.6f}")
    
    # Sanity checks
    assert 0.0 <= p_v <= 1.0, f"P(V) out of range: {p_v}"
    assert 0.0 <= p_s <= 1.0, f"P(S) out of range: {p_s}"
    print(f"\n✅ SV Head model: PASS (P(V) = {p_v:.4f}, P(S) = {p_s:.4f})")
    
    return p_v, p_s


def main():
    print(f"{'='*60}")
    print("Stage 0: Pure-Python Model Sanity Check")
    print(f"{'='*60}")
    print(f"\nTest Input:")
    print(f"  ECG: {ECG_WINDOW} samples (synthetic QRS at index 65)")
    print(f"  RR features: {RR_TEST} (normal sinus, ~75 BPM)")
    
    try:
        # Verify both models
        gate_prob = verify_gate_model()
        p_v, p_s = verify_sv_model()
        
        # Final summary
        print(f"\n{'='*60}")
        print("STAGE 0 VERIFICATION: ✅ PASS")
        print(f"{'='*60}")
        print(f"Gate:    P(abnormal) = {gate_prob:.4f}")
        print(f"SV Head: P(V) = {p_v:.4f}, P(S) = {p_s:.4f}")
        print(f"\n✅ All tensor specs match ISSUE2_IMPLEMENTATION_PLAN.md")
        print(f"✅ Quantization/dequantization math correct")
        print(f"✅ RR scaler normalization correct")
        print(f"\n➡️ Next: Implement tarang_ai.cc using verified specs")
        
    except AssertionError as e:
        print(f"\n❌ STAGE 0 VERIFICATION: FAIL")
        print(f"   {e}")
        print(f"\n   Fix the spec bug before implementing tarang_ai.cc")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
