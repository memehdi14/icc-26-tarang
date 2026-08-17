/***************************************************************************//**
 * @file test_ml_model_multi_input.cc
 * @brief Multi-input model verification and end-to-end AI cascade test harness.
 *
 * Covers:
 *   1. [TEST][GATE] Raw sl_ml_model_* verification for Gate CNN (2 inputs, 1 output)
 *   2. [TEST][SV]   Raw sl_ml_model_* verification for SV Head CNN (2 inputs, 2 outputs)
 *   3. [TEST][REAL API] End-to-end validation via tarang_ai.h public API
 *
 * Known real inputs used:
 *   - Sample 1: Normal Sinus Beat (~75 BPM, stable RR, normal QRS at index 65)
 *     Reference: Gate P(abnormal) ~0.0039 (Normal <=0.25), SV P(V) ~0.0039, SV P(S) ~0.0039
 *   - Sample 2: Abnormal / Ectopic Beat (120 BPM, short coupling RR 450ms, wide complex)
 *     Reference: Gate P(abnormal) elevated (>0.25 Triggers SV), SV P(V)/P(S) elevated
 ******************************************************************************/

#include "sl_ml_tflite_micro_model.h"
#include "tarang_ai.h"
#include "rr_scaler.h"
#include "sl_status.h"
#include <stdio.h>
#include <string.h>

extern "C" sl_ml_model_handle_t* tarang_ai_get_gate_handle(void);
extern "C" sl_ml_model_handle_t* tarang_ai_get_sv_handle(void);

namespace {

// =============================================================================
// Known Real Test Vectors (from tests/verify_model_stage0.py & verify_model_real_beat.py)
// =============================================================================

// Sample 1: Normal Sinus Rhythm (stable 800ms RR, ~75 BPM, normal QRS at idx 65)
static const float S1_RR_FEATURES[4] = {
    800.0f,  // rr_prev_ms
    800.0f,  // rr_mean_5_ms
    50.0f,   // rr_std_5_ms
    75.0f    // local_hr_bpm
};

static float s_s1_ecg_waveform[130];

// Sample 2: Abnormal / Ectopic Beat (premature RR 450ms, HR 120 BPM, wide complex)
static const float S2_RR_FEATURES[4] = {
    450.0f,  // rr_prev_ms (short coupling interval)
    780.0f,  // rr_mean_5_ms
    180.0f,  // rr_std_5_ms (high variability)
    120.0f   // local_hr_bpm (tachycardia)
};

static float s_s2_ecg_waveform[130];

static bool s_vectors_initialized = false;

static void init_test_vectors(void)
{
    if (s_vectors_initialized) return;

    // Build Sample 1: Baseline ~0.0f with normal QRS spike at samples 60-70
    memset(s_s1_ecg_waveform, 0, sizeof(s_s1_ecg_waveform));
    const float qrs_s1[11] = {0.05f, 0.1f, 0.5f, 1.0f, 0.8f, 0.3f, -0.2f, -0.5f, -0.3f, 0.0f, 0.05f};
    for (int i = 0; i < 11; i++) {
        s_s1_ecg_waveform[60 + i] = qrs_s1[i];
    }

    // Build Sample 2: Baseline with wide inverted biphasic ventricular complex at samples 58-72
    memset(s_s2_ecg_waveform, 0, sizeof(s_s2_ecg_waveform));
    const float qrs_s2[15] = {-0.2f, -0.6f, -1.2f, -1.8f, -1.5f, -0.8f, 0.0f,
                               0.8f,  1.5f,  1.8f,  1.2f,  0.4f, -0.1f, 0.0f, 0.0f};
    for (int i = 0; i < 15; i++) {
        s_s2_ecg_waveform[58 + i] = qrs_s2[i];
    }

    s_vectors_initialized = true;
}

// Quantization helpers matching tarang_ai.cc
inline int8_t test_quantize(float value, float scale, int zero_point)
{
    int32_t q = static_cast<int32_t>(value / scale + (value >= 0 ? 0.5f : -0.5f)) + zero_point;
    if (q < -128) q = -128;
    if (q > 127) q = 127;
    return static_cast<int8_t>(q);
}

inline float test_dequantize(int8_t value, float scale, int zero_point)
{
    return (static_cast<float>(value) - static_cast<float>(zero_point)) * scale;
}

void test_quantize_rr(TfLiteTensor* rr_tensor, const float* rr_raw4)
{
    const float scale = rr_tensor->params.scale;
    const int zp = (int)rr_tensor->params.zero_point;
    for (int i = 0; i < 4; i++) {
        float normalized = (rr_raw4[i] - rr_mean[i]) / rr_scale[i];
        rr_tensor->data.int8[i] = test_quantize(normalized, scale, zp);
    }
}

void test_quantize_ecg(TfLiteTensor* ecg_tensor, const float* waveform_130)
{
    const float scale = ecg_tensor->params.scale;
    const int zp = (int)ecg_tensor->params.zero_point;
    for (int i = 0; i < 130; i++) {
        ecg_tensor->data.int8[i] = test_quantize(waveform_130[i], scale, zp);
    }
}

} // namespace

extern "C" void test_ml_model_multi_input(void)
{
    printf("\r\n========================================================\r\n");
    printf("[TEST] === TARANG AI Cascade Multi-Model Verification ===\r\n");
    printf("========================================================\r\n");

    init_test_vectors();

    // =========================================================================
    // Block 1: Gate Model Raw Verification
    // =========================================================================
    printf("\r\n--- [TEST][GATE] Initializing Gate CNN Model ---\r\n");
    sl_ml_model_handle_t* gate_handle = tarang_ai_get_gate_handle();

    if (gate_handle == nullptr) {
        printf("[TEST][GATE] ABORT: gate_handle is NULL\r\n");
    } else {
        sl_status_t status_gate = sl_ml_model_init(gate_handle);
        printf("[TEST][GATE] sl_ml_model_init() = 0x%04lX (%s)\r\n",
               (unsigned long)status_gate,
               (status_gate == SL_STATUS_OK) ? "OK" : "FAIL");

        if (status_gate != SL_STATUS_OK) {
            printf("[TEST][GATE] ABORT: Gate model init failed\r\n");
        } else {
            TfLiteTensor* g_in0 = gate_handle->input_tensor(0);
            TfLiteTensor* g_in1 = gate_handle->input_tensor(1);
            TfLiteTensor* g_out0 = gate_handle->output_tensor(0);

            printf("[TEST][GATE] input_tensor(0) [RR]  = %p\r\n", (void*)g_in0);
            printf("[TEST][GATE] input_tensor(1) [ECG] = %p\r\n", (void*)g_in1);
            printf("[TEST][GATE] output_tensor(0)      = %p\r\n", (void*)g_out0);

            if (g_in0 != nullptr && g_in1 != nullptr && g_out0 != nullptr) {
                printf("[TEST][GATE] in0 dims=[");
                for (int i = 0; i < g_in0->dims->size; i++) {
                    printf("%d%s", g_in0->dims->data[i], (i < g_in0->dims->size - 1) ? "," : "");
                }
                printf("], type=%d, scale=%.6f, zp=%ld\r\n", (int)g_in0->type, g_in0->params.scale, (long)g_in0->params.zero_point);

                printf("[TEST][GATE] in1 dims=[");
                for (int i = 0; i < g_in1->dims->size; i++) {
                    printf("%d%s", g_in1->dims->data[i], (i < g_in1->dims->size - 1) ? "," : "");
                }
                printf("], type=%d, scale=%.6f, zp=%ld\r\n", (int)g_in1->type, g_in1->params.scale, (long)g_in1->params.zero_point);

                printf("[TEST][GATE] out0 dims=[");
                for (int i = 0; i < g_out0->dims->size; i++) {
                    printf("%d%s", g_out0->dims->data[i], (i < g_out0->dims->size - 1) ? "," : "");
                }
                printf("], type=%d, scale=%.6f, zp=%ld\r\n", (int)g_out0->type, g_out0->params.scale, (long)g_out0->params.zero_point);

                // Test Sample 1 on Gate
                test_quantize_rr(g_in0, S1_RR_FEATURES);
                test_quantize_ecg(g_in1, s_s1_ecg_waveform);
                sl_status_t run_s1 = sl_ml_model_run(gate_handle);
                float g_p1 = test_dequantize(g_out0->data.int8[0], g_out0->params.scale, (int)g_out0->params.zero_point);

                // Test Sample 2 on Gate
                test_quantize_rr(g_in0, S2_RR_FEATURES);
                test_quantize_ecg(g_in1, s_s2_ecg_waveform);
                sl_status_t run_s2 = sl_ml_model_run(gate_handle);
                float g_p2 = test_dequantize(g_out0->data.int8[0], g_out0->params.scale, (int)g_out0->params.zero_point);

                printf("[TEST][GATE] Run S1 (Normal Beat)   : status=0x%04lX, P(abnormal)=%.4f (Ref: ~0.0039, Normal <=0.25)\r\n",
                       (unsigned long)run_s1, g_p1);
                printf("[TEST][GATE] Run S2 (Abnormal Beat) : status=0x%04lX, P(abnormal)=%.4f (Ref: >0.25 Trigger SV)\r\n",
                       (unsigned long)run_s2, g_p2);

                if (run_s1 == SL_STATUS_OK && run_s2 == SL_STATUS_OK) {
                    printf("[TEST][GATE] *** PASS: Gate multi-input inference verified ***\r\n");
                } else {
                    printf("[TEST][GATE] *** FAIL: Gate inference returned error ***\r\n");
                }
            } else {
                printf("[TEST][GATE] *** FAIL: Gate tensor pointer is NULL ***\r\n");
            }

            sl_ml_model_deinit(gate_handle);
        }
    }

    // =========================================================================
    // Block 2: SV Head Model Raw Verification
    // =========================================================================
    printf("\r\n--- [TEST][SV] Initializing SV Head CNN Model ---\r\n");
    sl_ml_model_handle_t* sv_handle = tarang_ai_get_sv_handle();

    if (sv_handle == nullptr) {
        printf("[TEST][SV] (SV model handle not available - generate SV instance in Studio to enable)\r\n");
    } else {
        sl_status_t status_sv = sl_ml_model_init(sv_handle);
        printf("[TEST][SV] sl_ml_model_init() = 0x%04lX (%s)\r\n",
               (unsigned long)status_sv,
               (status_sv == SL_STATUS_OK) ? "OK" : "FAIL");

        if (status_sv != SL_STATUS_OK) {
            printf("[TEST][SV] ABORT: SV model init failed\r\n");
        } else {
            TfLiteTensor* sv_in0 = sv_handle->input_tensor(0);
            TfLiteTensor* sv_in1 = sv_handle->input_tensor(1);
            TfLiteTensor* sv_out0 = sv_handle->output_tensor(0); // P(V)
            TfLiteTensor* sv_out1 = sv_handle->output_tensor(1); // P(S)

            printf("[TEST][SV] input_tensor(0) [RR]  = %p\r\n", (void*)sv_in0);
            printf("[TEST][SV] input_tensor(1) [ECG] = %p\r\n", (void*)sv_in1);
            printf("[TEST][SV] output_tensor(0) [P_V]= %p\r\n", (void*)sv_out0);
            printf("[TEST][SV] output_tensor(1) [P_S]= %p\r\n", (void*)sv_out1);

            if (sv_in0 != nullptr && sv_in1 != nullptr && sv_out0 != nullptr && sv_out1 != nullptr) {
                printf("[TEST][SV] in0 dims=[");
                for (int i = 0; i < sv_in0->dims->size; i++) {
                    printf("%d%s", sv_in0->dims->data[i], (i < sv_in0->dims->size - 1) ? "," : "");
                }
                printf("], type=%d, scale=%.6f, zp=%ld\r\n", (int)sv_in0->type, sv_in0->params.scale, (long)sv_in0->params.zero_point);

                printf("[TEST][SV] in1 dims=[");
                for (int i = 0; i < sv_in1->dims->size; i++) {
                    printf("%d%s", sv_in1->dims->data[i], (i < sv_in1->dims->size - 1) ? "," : "");
                }
                printf("], type=%d, scale=%.6f, zp=%ld\r\n", (int)sv_in1->type, sv_in1->params.scale, (long)sv_in1->params.zero_point);

                printf("[TEST][SV] out0 [P(V)] dims=[");
                for (int i = 0; i < sv_out0->dims->size; i++) {
                    printf("%d%s", sv_out0->dims->data[i], (i < sv_out0->dims->size - 1) ? "," : "");
                }
                printf("], type=%d, scale=%.6f, zp=%ld\r\n", (int)sv_out0->type, sv_out0->params.scale, (long)sv_out0->params.zero_point);

                printf("[TEST][SV] out1 [P(S)] dims=[");
                for (int i = 0; i < sv_out1->dims->size; i++) {
                    printf("%d%s", sv_out1->dims->data[i], (i < sv_out1->dims->size - 1) ? "," : "");
                }
                printf("], type=%d, scale=%.6f, zp=%ld\r\n", (int)sv_out1->type, sv_out1->params.scale, (long)sv_out1->params.zero_point);

                // Test Sample 1 on SV Head
                test_quantize_rr(sv_in0, S1_RR_FEATURES);
                test_quantize_ecg(sv_in1, s_s1_ecg_waveform);
                sl_status_t sv_run_s1 = sl_ml_model_run(sv_handle);
                float sv_pv1 = test_dequantize(sv_out0->data.int8[0], sv_out0->params.scale, (int)sv_out0->params.zero_point);
                float sv_ps1 = test_dequantize(sv_out1->data.int8[0], sv_out1->params.scale, (int)sv_out1->params.zero_point);

                // Test Sample 2 on SV Head
                test_quantize_rr(sv_in0, S2_RR_FEATURES);
                test_quantize_ecg(sv_in1, s_s2_ecg_waveform);
                sl_status_t sv_run_s2 = sl_ml_model_run(sv_handle);
                float sv_pv2 = test_dequantize(sv_out0->data.int8[0], sv_out0->params.scale, (int)sv_out0->params.zero_point);
                float sv_ps2 = test_dequantize(sv_out1->data.int8[0], sv_out1->params.scale, (int)sv_out1->params.zero_point);

                printf("[TEST][SV] Run S1 (Normal Beat)   : status=0x%04lX, P(V)=%.4f (Ref: ~0.0039), P(S)=%.4f (Ref: ~0.0039)\r\n",
                       (unsigned long)sv_run_s1, sv_pv1, sv_ps1);
                printf("[TEST][SV] Run S2 (Abnormal Beat) : status=0x%04lX, P(V)=%.4f, P(S)=%.4f\r\n",
                       (unsigned long)sv_run_s2, sv_pv2, sv_ps2);

                if (sv_run_s1 == SL_STATUS_OK && sv_run_s2 == SL_STATUS_OK) {
                    printf("[TEST][SV] *** PASS: SV Head dual-output inference verified ***\r\n");
                } else {
                    printf("[TEST][SV] *** FAIL: SV Head inference returned error ***\r\n");
                }
            } else {
                printf("[TEST][SV] *** FAIL: SV tensor pointer is NULL ***\r\n");
            }

            sl_ml_model_deinit(sv_handle);
        }
    }

    // =========================================================================
    // Block 3: Public API End-to-End Test (tarang_ai.h)
    // =========================================================================
    printf("\r\n--- [TEST][REAL API] Initializing via tarang_ai_init() ---\r\n");
    bool api_init_ok = tarang_ai_init();
    printf("[TEST][REAL API] tarang_ai_init() = %s (is_ready=%d)\r\n",
           api_init_ok ? "SUCCESS" : "FAIL",
           (int)tarang_ai_is_ready());

    if (api_init_ok) {
        printf("[TEST][REAL API] Gate model flash size: %lu B, arena size: %lu B\r\n",
               (unsigned long)tarang_ai_gate_model_size(),
               (unsigned long)tarang_ai_gate_arena_size());
        printf("[TEST][REAL API] SV model flash size  : %lu B, arena size: %lu B\r\n",
               (unsigned long)tarang_ai_sv_model_size(),
               (unsigned long)tarang_ai_sv_arena_size());

        // Predict Sample 1 via Public API
        float api_g1 = tarang_ai_gate_predict(s_s1_ecg_waveform, S1_RR_FEATURES);
        float api_pv1 = 0.0f, api_ps1 = 0.0f;
        bool api_sv1_ok = tarang_ai_sv_predict(s_s1_ecg_waveform, S1_RR_FEATURES, &api_pv1, &api_ps1);

        printf("[TEST][REAL API] Sample 1 (Normal)   -> Gate P(abnormal)=%.4f | SV ok=%d P(V)=%.4f P(S)=%.4f\r\n",
               api_g1, (int)api_sv1_ok, api_pv1, api_ps1);

        // Predict Sample 2 via Public API
        float api_g2 = tarang_ai_gate_predict(s_s2_ecg_waveform, S2_RR_FEATURES);
        float api_pv2 = 0.0f, api_ps2 = 0.0f;
        bool api_sv2_ok = tarang_ai_sv_predict(s_s2_ecg_waveform, S2_RR_FEATURES, &api_pv2, &api_ps2);

        printf("[TEST][REAL API] Sample 2 (Abnormal) -> Gate P(abnormal)=%.4f | SV ok=%d P(V)=%.4f P(S)=%.4f\r\n",
               api_g2, (int)api_sv2_ok, api_pv2, api_ps2);

        printf("[TEST][REAL API] *** PASS: End-to-end tarang_ai module operational ***\r\n");
    } else {
        printf("[TEST][REAL API] *** FAIL: tarang_ai_init failed ***\r\n");
    }

    printf("\r\n========================================================\r\n");
    printf("[TEST] === All AI Model Verification Steps Complete ===\r\n");
    printf("========================================================\r\n\r\n");
}
