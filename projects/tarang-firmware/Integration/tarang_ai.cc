/***************************************************************************//**
 * @file tarang_ai.cc
 * @brief TARANG AI inference module — TFLite Micro implementation.
 *
 * Manages two TFLite Micro interpreters for the Tier-1/2 cascade:
 *
 *   GATE CNN (Tier 1):
 *     - Model: gate_model_data[] (~40KB flash)
 *     - Input: ecg_input [1,130] int8 + rr_input [1,4] int8
 *     - Output: gate_out [1,1] int8 (sigmoid → P(abnormal))
 *     - Inference: ~12.7ms on MVP
 *     - Runs ONLY when Tier-0 heuristics flag a suspicious beat
 *
 *   SV HEAD CNN (Tier 2):
 *     - Model: sv_model_data[] (~32KB flash)
 *     - Input: ecg_input [1,130] int8 + rr_input [1,4] int8
 *     - Output: v_head [1,1] int8 + s_head [1,1] int8 (independent sigmoids)
 *     - Inference: ~10.2ms on MVP
 *     - Runs ONLY when Gate says P(abnormal) > GATE_THR
 *
 * Both models use INT8 quantization. Float inputs are quantized using the
 * model's own scale/zero_point. RR features are z-score normalized first
 * using rr_scaler.h (training-set mean/std).
 *
 * ZERO HEAP ALLOCATION: All tensor arenas are static arrays.
 *
 * How this was done in the reference project (anomaly_detection.cc):
 *   1. sl_tflite_micro_get_input_tensor() → model_input pointer
 *   2. sl_tflite_micro_get_interpreter() → interpreter pointer
 *   3. Z-score normalize raw data using MEAN[]/STD[] from constants.h
 *   4. Quantize: qi = round((z - 0) / scale + zero_point), clamp to [-128,127]
 *   5. interpreter->Invoke()
 *   6. Dequantize output: float_val = (int8_val - zero_point) * scale
 *
 * Tarang does the SAME thing, but with TWO models instead of one, and
 * we bypass the SL auto-init to manage both interpreters manually.
 *
 * Target : EFR32MG26B510F3200IM48 (Series 2, Cortex-M33 + MVP)
 ******************************************************************************/

#include "tarang_ai.h"
#include "gate_model_data.h"
#include "sv_model_data.h"
#include "rr_scaler.h"
#include "tarang_constants.h"

#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "tensorflow/lite/micro/micro_log.h"

#include <cstdio>
#include <cmath>

#define GATE_ARENA_SIZE   (24 * 1024)
#define SV_ARENA_SIZE     (28 * 1024)

static uint8_t gate_arena[GATE_ARENA_SIZE] __attribute__((aligned(16)));
static uint8_t sv_arena[SV_ARENA_SIZE] __attribute__((aligned(16)));

/*******************************************************************************
 * Op Resolver — uses AllOpsResolver to ensure all TFLite ops are supported.
 ******************************************************************************/
static tflite::MicroMutableOpResolver<12> s_op_resolver;

static bool register_ops(void)
{
  if (s_op_resolver.AddConv2D() != kTfLiteOk) return false;
  if (s_op_resolver.AddFullyConnected() != kTfLiteOk) return false;
  if (s_op_resolver.AddMaxPool2D() != kTfLiteOk) return false;
  if (s_op_resolver.AddReshape() != kTfLiteOk) return false;
  if (s_op_resolver.AddConcatenation() != kTfLiteOk) return false;
  if (s_op_resolver.AddLogistic() != kTfLiteOk) return false;
  if (s_op_resolver.AddQuantize() != kTfLiteOk) return false;
  if (s_op_resolver.AddDequantize() != kTfLiteOk) return false;
  if (s_op_resolver.AddMul() != kTfLiteOk) return false;
  if (s_op_resolver.AddAdd() != kTfLiteOk) return false;
  if (s_op_resolver.AddRelu() != kTfLiteOk) return false;
  if (s_op_resolver.AddSoftmax() != kTfLiteOk) return false;
  return true;
}

/*******************************************************************************
 * Interpreter State
 ******************************************************************************/

/* Gate CNN */
static const tflite::Model *s_gate_model = nullptr;
static tflite::MicroInterpreter *s_gate_interp = nullptr;
static TfLiteTensor *s_gate_ecg_input = nullptr;
static TfLiteTensor *s_gate_rr_input = nullptr;

/* SV Head CNN */
static const tflite::Model *s_sv_model = nullptr;
static tflite::MicroInterpreter *s_sv_interp = nullptr;
static TfLiteTensor *s_sv_ecg_input = nullptr;
static TfLiteTensor *s_sv_rr_input = nullptr;

/* Status */
static bool s_ai_ready = false;

/*******************************************************************************
 * Private: Quantize a float value to INT8 using tensor's scale/zero_point.
 *
 * Formula (same as reference project anomaly_detection.cc line 181):
 *   qi = round(float_val / scale + zero_point)
 *   clamp to [-128, 127]
 ******************************************************************************/
static inline int8_t quantize_int8(float value, float scale, int zero_point)
{
  float qf = value / scale + (float)zero_point;
  int32_t qi = (int32_t)(qf >= 0.0f ? qf + 0.5f : qf - 0.5f);
  if (qi > 127)  qi = 127;
  if (qi < -128) qi = -128;
  return (int8_t)qi;
}

/*******************************************************************************
 * Private: Dequantize an INT8 value to float.
 *
 * Formula (same as reference project anomaly_detection.cc line 220):
 *   float_val = (int8_val - zero_point) * scale
 ******************************************************************************/
static inline float dequantize_int8(int8_t value, float scale, int zero_point)
{
  return ((float)value - (float)zero_point) * scale;
}

/*******************************************************************************
 * Private: Fill ECG + RR input tensors with quantized data.
 *
 * ECG window: 130 floats → INT8 using ecg_input tensor's quant params
 * RR features: 4 floats → z-score normalize with rr_mean[]/rr_scale[]
 *              from training, THEN quantize to INT8 using rr_input params
 ******************************************************************************/
static void fill_inputs(TfLiteTensor *ecg_tensor, TfLiteTensor *rr_tensor,
                         const float *ecg_window, const float *rr_features)
{
  /* ECG input: direct quantize (already z-score normalized by DSP chain) */
  int8_t *ecg_buf = ecg_tensor->data.int8;
  float ecg_scale = ecg_tensor->params.scale;
  int ecg_zp = ecg_tensor->params.zero_point;

  for (int i = 0; i < TARANG_BEAT_WINDOW_SIZE; i++) {
    ecg_buf[i] = quantize_int8(ecg_window[i], ecg_scale, ecg_zp);
  }

  if (rr_tensor != nullptr) {
    int8_t *rr_buf = rr_tensor->data.int8;
    float rr_scale_q = rr_tensor->params.scale;
    int rr_zp = rr_tensor->params.zero_point;

    for (int i = 0; i < TARANG_RR_FEATURE_COUNT; i++) {
      float z = (rr_features[i] - rr_mean[i]) / rr_scale[i];
      rr_buf[i] = quantize_int8(z, rr_scale_q, rr_zp);
    }
  } else {
    /* Concatenated 1-input model: append 4 RR features at offset 130 */
    for (int i = 0; i < TARANG_RR_FEATURE_COUNT; i++) {
      float z = (rr_features[i] - rr_mean[i]) / rr_scale[i];
      ecg_buf[TARANG_BEAT_WINDOW_SIZE + i] = quantize_int8(z, ecg_scale, ecg_zp);
    }
  }
}

/*******************************************************************************
 * Public API
 ******************************************************************************/

bool tarang_ai_init(void)
{
  printf("[AI] Initializing TFLite Micro (dual-model cascade)...\r\n");

  /* ── Register operators ────────────────────────────────────────────── */
  if (!register_ops()) {
    printf("[AI] ERROR: Failed to register ops\r\n");
    return false;
  }

  /* ── Load Gate CNN ─────────────────────────────────────────────────── */
  s_gate_model = tflite::GetModel(gate_model_data);
  if (s_gate_model == nullptr) {
    printf("[AI] ERROR: Gate model data invalid\r\n");
    return false;
  }
  if (s_gate_model->version() != TFLITE_SCHEMA_VERSION) {
    printf("[AI] ERROR: Gate model schema version %lu, expected %d\r\n",
           (unsigned long)s_gate_model->version(), TFLITE_SCHEMA_VERSION);
    return false;
  }

  static tflite::MicroInterpreter gate_interp_obj(
      s_gate_model, s_op_resolver, gate_arena, GATE_ARENA_SIZE);
  s_gate_interp = &gate_interp_obj;

  if (s_gate_interp->AllocateTensors() != kTfLiteOk) {
    printf("[AI] ERROR: Gate tensor allocation failed (arena too small?)\r\n");
    return false;
  }

  printf("[AI] Gate CNN: model=%lu bytes, arena=%lu/%d bytes used\r\n",
         (unsigned long)gate_model_data_len,
         (unsigned long)s_gate_interp->arena_used_bytes(),
         GATE_ARENA_SIZE);

  /* ── Load SV Head CNN ──────────────────────────────────────────────── */
  s_sv_model = tflite::GetModel(sv_model_data);
  if (s_sv_model == nullptr) {
    printf("[AI] ERROR: SV model data invalid\r\n");
    return false;
  }

  static tflite::MicroInterpreter sv_interp_obj(
      s_sv_model, s_op_resolver, sv_arena, SV_ARENA_SIZE);
  s_sv_interp = &sv_interp_obj;

  if (s_sv_interp->AllocateTensors() != kTfLiteOk) {
    printf("[AI] ERROR: SV tensor allocation failed (arena too small?)\r\n");
    return false;
  }

  printf("[AI] SV Head CNN: model=%lu bytes, arena=%lu/%d bytes used\r\n",
         (unsigned long)sv_model_data_len,
         (unsigned long)s_sv_interp->arena_used_bytes(),
         SV_ARENA_SIZE);

  /* ── Validate Gate input tensors ───────────────────────────────────── */
  if (s_gate_interp->inputs_size() >= 2) {
    s_gate_ecg_input = s_gate_interp->input(0);
    s_gate_rr_input  = s_gate_interp->input(1);
  } else if (s_gate_interp->inputs_size() == 1) {
    s_gate_ecg_input = s_gate_interp->input(0);
    s_gate_rr_input  = nullptr;
  } else {
    printf("[AI] ERROR: Gate model has 0 inputs\r\n");
    return false;
  }

  if (s_gate_ecg_input->type != kTfLiteInt8) {
    printf("[AI] ERROR: Gate ecg input not INT8 (got %d)\r\n", s_gate_ecg_input->type);
    return false;
  }

  printf("[AI] Gate input 0: shape=[%d,%d], scale=%.6f, zp=%d\r\n",
         s_gate_ecg_input->dims->data[0], s_gate_ecg_input->dims->data[1],
         (double)s_gate_ecg_input->params.scale,
         (int)s_gate_ecg_input->params.zero_point);

  /* ── Validate SV input tensors ─────────────────────────────────────── */
  if (s_sv_interp->inputs_size() >= 2) {
    s_sv_ecg_input = s_sv_interp->input(0);
    s_sv_rr_input  = s_sv_interp->input(1);
  } else if (s_sv_interp->inputs_size() == 1) {
    s_sv_ecg_input = s_sv_interp->input(0);
    s_sv_rr_input  = nullptr;
  } else {
    printf("[AI] ERROR: SV model has 0 inputs\r\n");
    return false;
  }

  if (s_sv_ecg_input->type != kTfLiteInt8) {
    printf("[AI] ERROR: SV ecg input not INT8\r\n");
    return false;
  }

  printf("[AI] SV input 0:   shape=[%d,%d], scale=%.6f, zp=%d\r\n",
         s_sv_ecg_input->dims->data[0], s_sv_ecg_input->dims->data[1],
         (double)s_sv_ecg_input->params.scale,
         (int)s_sv_ecg_input->params.zero_point);

  /* ── Validate output tensors ───────────────────────────────────────── */
  printf("[AI] Gate outputs: %zu, SV outputs: %zu\r\n",
         s_gate_interp->outputs_size(),
         s_sv_interp->outputs_size());

  s_ai_ready = true;
  printf("[AI] Both models loaded and validated. Ready for inference.\r\n");
  printf("[AI] Locked thresholds: GATE=%.3f  V=%.3f  S=%.3f\r\n",
         (double)TARANG_GATE_THRESHOLD,
         (double)TARANG_V_THRESHOLD,
         (double)TARANG_S_THRESHOLD);

  return true;
}

float tarang_ai_gate_predict(const float *ecg_window, const float *rr_features)
{
  if (!s_ai_ready || ecg_window == nullptr || rr_features == nullptr) {
    return -1.0f;
  }

  /* Fill input tensors with quantized data */
  fill_inputs(s_gate_ecg_input, s_gate_rr_input, ecg_window, rr_features);

  /* Run inference */
  if (s_gate_interp->Invoke() != kTfLiteOk) {
    printf("[AI] ERROR: Gate inference failed\r\n");
    return -1.0f;
  }

  /* Read output: gate_out [1,1] int8 → dequantize to float */
  TfLiteTensor *output = s_gate_interp->output(0);
  if (output == nullptr || output->type != kTfLiteInt8) {
    return -1.0f;
  }

  float p_abnormal = dequantize_int8(output->data.int8[0],
                                      output->params.scale,
                                      output->params.zero_point);

  /* Clamp to [0, 1] — sigmoid output should already be in range,
   * but quantization rounding can cause slight overshoot */
  if (p_abnormal < 0.0f) p_abnormal = 0.0f;
  if (p_abnormal > 1.0f) p_abnormal = 1.0f;

  return p_abnormal;
}

bool tarang_ai_sv_predict(const float *ecg_window, const float *rr_features,
                           float *p_v, float *p_s)
{
  if (!s_ai_ready || ecg_window == nullptr || rr_features == nullptr) {
    return false;
  }

  /* Fill input tensors */
  fill_inputs(s_sv_ecg_input, s_sv_rr_input, ecg_window, rr_features);

  /* Run inference */
  if (s_sv_interp->Invoke() != kTfLiteOk) {
    printf("[AI] ERROR: SV inference failed\r\n");
    return false;
  }

  /* SV model has 2 outputs: v_head [1,1] and s_head [1,1]
   * Both are independent sigmoid outputs (NOT softmax — they don't sum to 1) */
  TfLiteTensor *v_out = s_sv_interp->output(0);
  TfLiteTensor *s_out = s_sv_interp->output(1);

  if (v_out == nullptr || s_out == nullptr) return false;

  *p_v = dequantize_int8(v_out->data.int8[0],
                          v_out->params.scale,
                          v_out->params.zero_point);
  *p_s = dequantize_int8(s_out->data.int8[0],
                          s_out->params.scale,
                          s_out->params.zero_point);

  /* Clamp */
  if (*p_v < 0.0f) *p_v = 0.0f;
  if (*p_v > 1.0f) *p_v = 1.0f;
  if (*p_s < 0.0f) *p_s = 0.0f;
  if (*p_s > 1.0f) *p_s = 1.0f;

  return true;
}

bool tarang_ai_is_ready(void)
{
  return s_ai_ready;
}

uint32_t tarang_ai_gate_model_size(void)
{
  return gate_model_data_len;
}

uint32_t tarang_ai_sv_model_size(void)
{
  return sv_model_data_len;
}

uint32_t tarang_ai_gate_arena_size(void)
{
  return s_gate_interp ? (uint32_t)s_gate_interp->arena_used_bytes() : 0;
}

uint32_t tarang_ai_sv_arena_size(void)
{
  return s_sv_interp ? (uint32_t)s_sv_interp->arena_used_bytes() : 0;
}
