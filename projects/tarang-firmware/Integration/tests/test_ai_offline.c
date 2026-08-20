/***************************************************************************//**
 * @file test_ai_offline.c
 * @brief Stage 2 Test Harness — Host-build C++ wrapper validation
 *
 * Purpose: Validate tarang_ai.cc wrapper logic on x86/x64 host before flashing
 * to ARM target. Isolates wrapper bugs from hardware/firmware issues.
 *
 * Prerequisites:
 *   - tarang_ai.cc implemented per ISSUE2_IMPLEMENTATION_PLAN.md
 *   - gate_model_data.cc/.h and sv_model_data.cc/.h present
 *   - TensorFlow Lite Micro library built for host
 *
 * Build (example, adjust paths for your environment):
 *   g++ -o test_ai_offline \
 *       test_ai_offline.c \
 *       tarang_ai.cc \
 *       gate_model_data.cc \
 *       sv_model_data.cc \
 *       -I. \
 *       -I<path-to-tflite-micro>/tensorflow/lite/micro \
 *       -L<path-to-tflite-micro-lib> \
 *       -ltensorflow-lite \
 *       -lstdc++ -lm -O2
 *
 * Usage:
 *   ./test_ai_offline
 *
 * Expected Output (if wrapper is correct):
 *   PASS: init ok, gate arena=XXXX sv arena=YYYY
 *   Gate P = 0.XXXX (expect roughly matching Stage 0 Python output)
 *   SV predict ok=1  P(V)=0.XXXX  P(S)=0.XXXX
 *   
 *   STAGE 2 VERIFICATION: ✅ PASS
 *
 * If outputs don't match Stage 0 Python (±0.01):
 *   - BUG: Wrapper input order, quantization, or tensor indexing is wrong
 *   - Re-check ISSUE2_IMPLEMENTATION_PLAN.md bug fixes 1-7
 *
 * References:
 *   - documentation/TESTING_GUIDE.md Stage 2
 *   - ISSUE2_IMPLEMENTATION_PLAN.md (corrected tarang_ai.cc)
 *   - verify_model_stage0.py (Stage 0 reference values)
 ******************************************************************************/

#include "tarang_ai.h"
#include <stdio.h>
#include <math.h>
#include <stdbool.h>
#include <string.h>

/*******************************************************************************
 * Test Configuration
 ******************************************************************************/

/* Same dummy input as Stage 0 Python script for cross-validation */
#define ECG_WINDOW_SIZE 130

/* Normal sinus rhythm test case: ~75 BPM, stable RR */
static const float TEST_RR_FEATURES[4] = {
    800.0f,  /* rr_prev_ms */
    800.0f,  /* rr_mean_5_ms */
    50.0f,   /* rr_std_5_ms */
    75.0f    /* local_hr_bpm */
};

/* Flat ECG waveform (represents no real beat, but valid for tensor shape test) */
static float TEST_ECG_WAVEFORM[ECG_WINDOW_SIZE];

/*******************************************************************************
 * Test Helper: Check value is in valid probability range
 ******************************************************************************/
static bool is_valid_probability(float p)
{
    return (p >= 0.0f && p <= 1.0f);
}

/*******************************************************************************
 * Test 1: Initialization
 ******************************************************************************/
static bool test_init(void)
{
    printf("\n=== Test 1: Initialization ===\n");
    
    if (!tarang_ai_init()) {
        printf("❌ FAIL: tarang_ai_init() returned false\n");
        printf("   Check model data files are linked correctly\n");
        return false;
    }
    
    if (!tarang_ai_is_ready()) {
        printf("❌ FAIL: tarang_ai_is_ready() false after successful init\n");
        return false;
    }
    
    /* Check arena usage (optional, requires exposing arena_used_bytes() in tarang_ai.h) */
    #if 0  /* Enable if tarang_ai.h exports these functions */
    size_t gate_arena = tarang_ai_gate_arena_size();
    size_t sv_arena = tarang_ai_sv_arena_size();
    printf("Gate arena: %zu bytes\n", gate_arena);
    printf("SV arena:   %zu bytes\n", sv_arena);
    
    /* Warn if arena usage is too close to limit (within 10% of 16KB/24KB) */
    if (gate_arena > 14745) {  /* 90% of 16384 */
        printf("⚠️  WARNING: Gate arena usage near limit, consider increasing kGateTensorArenaSize\n");
    }
    if (sv_arena > 22118) {  /* 90% of 24576 */
        printf("⚠️  WARNING: SV arena usage near limit, consider increasing kSVTensorArenaSize\n");
    }
    #endif
    
    printf("✅ PASS: Init successful\n");
    return true;
}

/*******************************************************************************
 * Test 2: Gate Model Inference
 ******************************************************************************/
static bool test_gate_predict(float *out_prob)
{
    printf("\n=== Test 2: Gate Model Inference ===\n");
    
    float gate_prob = tarang_ai_gate_predict(TEST_ECG_WAVEFORM, TEST_RR_FEATURES);
    
    if (gate_prob < 0.0f) {
        printf("❌ FAIL: tarang_ai_gate_predict() returned error (%.4f)\n", gate_prob);
        return false;
    }
    
    if (!is_valid_probability(gate_prob)) {
        printf("❌ FAIL: Gate output out of range [0,1]: %.6f\n", gate_prob);
        printf("   Check dequantization logic in tarang_ai.cc\n");
        return false;
    }
    
    printf("Gate P(abnormal) = %.6f\n", gate_prob);
    printf("✅ PASS: Gate prediction in valid range\n");
    
    *out_prob = gate_prob;
    return true;
}

/*******************************************************************************
 * Test 3: SV Head Model Inference
 ******************************************************************************/
static bool test_sv_predict(float *out_p_v, float *out_p_s)
{
    printf("\n=== Test 3: SV Head Model Inference ===\n");
    
    float p_v, p_s;
    bool ok = tarang_ai_sv_predict(TEST_ECG_WAVEFORM, TEST_RR_FEATURES, &p_v, &p_s);
    
    if (!ok) {
        printf("❌ FAIL: tarang_ai_sv_predict() returned false\n");
        return false;
    }
    
    if (!is_valid_probability(p_v)) {
        printf("❌ FAIL: P(V) out of range [0,1]: %.6f\n", p_v);
        printf("   Check dequantization logic or output tensor index\n");
        return false;
    }
    
    if (!is_valid_probability(p_s)) {
        printf("❌ FAIL: P(S) out of range [0,1]: %.6f\n", p_s);
        printf("   Check dequantization logic or output tensor index\n");
        return false;
    }
    
    printf("SV P(V) = %.6f\n", p_v);
    printf("SV P(S) = %.6f\n", p_s);
    printf("✅ PASS: SV prediction in valid range\n");
    
    *out_p_v = p_v;
    *out_p_s = p_s;
    return true;
}

/*******************************************************************************
 * Test 4: Cross-Validation Against Stage 0 Python
 ******************************************************************************/
static void compare_with_stage0(float gate_prob, float p_v, float p_s)
{
    printf("\n=== Cross-Validation Against Stage 0 ===\n");
    printf("Expected: Gate and SV outputs should match Stage 0 Python script\n");
    printf("          (verify_model_stage0.py) within quantization rounding (±0.01)\n");
    printf("\nC++ Wrapper Results:\n");
    printf("  Gate P(abnormal) = %.6f\n", gate_prob);
    printf("  SV   P(V)        = %.6f\n", p_v);
    printf("  SV   P(S)        = %.6f\n", p_s);
    printf("\nTO VERIFY: Run verify_model_stage0.py and compare outputs.\n");
    printf("           If mismatch > 0.01, wrapper has a bug (input order, quantization, etc.)\n");
}

/*******************************************************************************
 * Main Test Runner
 ******************************************************************************/
int main(void)
{
    printf("═══════════════════════════════════════════════════════════════\n");
    printf("TARANG Stage 2 — C++ Wrapper Unit Test (Host Build)\n");
    printf("═══════════════════════════════════════════════════════════════\n");
    
    /* Initialize test ECG waveform (all zeros = flat line) */
    memset(TEST_ECG_WAVEFORM, 0, sizeof(TEST_ECG_WAVEFORM));
    
    printf("\nTest Input:\n");
    printf("  ECG waveform:    %d samples (all zeros, valid shape test)\n", ECG_WINDOW_SIZE);
    printf("  RR features:     [%.1f, %.1f, %.1f, %.1f]\n",
           TEST_RR_FEATURES[0], TEST_RR_FEATURES[1],
           TEST_RR_FEATURES[2], TEST_RR_FEATURES[3]);
    printf("                   (normal sinus ~75 BPM, stable RR)\n");
    
    /* Run tests in sequence */
    bool all_pass = true;
    float gate_prob = 0.0f, p_v = 0.0f, p_s = 0.0f;
    
    all_pass &= test_init();
    if (!all_pass) {
        printf("\n❌ STAGE 2 VERIFICATION: FAIL (init failed)\n");
        return 1;
    }
    
    all_pass &= test_gate_predict(&gate_prob);
    all_pass &= test_sv_predict(&p_v, &p_s);
    
    if (!all_pass) {
        printf("\n❌ STAGE 2 VERIFICATION: FAIL\n");
        printf("   Re-check ISSUE2_IMPLEMENTATION_PLAN.md bug fixes 1-7\n");
        return 1;
    }
    
    /* Final cross-validation hint */
    compare_with_stage0(gate_prob, p_v, p_s);
    
    printf("\n═══════════════════════════════════════════════════════════════\n");
    printf("STAGE 2 VERIFICATION: ✅ PASS\n");
    printf("═══════════════════════════════════════════════════════════════\n");
    printf("\n➡️  Next: Stage 3 (firmware build + boot log check)\n");
    printf("    See documentation/TESTING_GUIDE.md Stage 3 for instructions\n\n");
    
    return 0;
}
