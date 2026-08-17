#include "tarang_ai.h"
#include "rr_scaler.h"
#include "sl_status.h"
#include <stdint.h>
#include <stdbool.h>
#include <string.h>

#include "sl_ml_model_gate_int8.h"
#include "sl_ml_model_sv_int8.h"

#define SV_MODEL_HANDLE sl_ml_sv_int8_model_handle

extern "C" sl_ml_model_handle_t* tarang_ai_get_gate_handle(void) {
  return &sl_ml_gate_int8_model_handle;
}

extern "C" sl_ml_model_handle_t* tarang_ai_get_sv_handle(void) {
  return &sl_ml_sv_int8_model_handle;
}

namespace {

static bool s_ai_initialized = false;

inline int8_t quantize(float value, float scale, int zero_point) {
  int32_t q = static_cast<int32_t>(value / scale + (value >= 0 ? 0.5f : -0.5f)) + zero_point;
  if (q < -128) q = -128;
  if (q > 127) q = 127;
  return static_cast<int8_t>(q);
}

inline float dequantize(int8_t value, float scale, int zero_point) {
  return (static_cast<float>(value) - static_cast<float>(zero_point)) * scale;
}

void quantize_rr_features(TfLiteTensor* rr_tensor, const float* rr_raw4) {
  const float scale = rr_tensor->params.scale;
  const int zp = rr_tensor->params.zero_point;
  for (int i = 0; i < 4; i++) {
    float normalized = (rr_raw4[i] - rr_mean[i]) / rr_scale[i];
    rr_tensor->data.int8[i] = quantize(normalized, scale, zp);
  }
}

void quantize_ecg_waveform(TfLiteTensor* ecg_tensor, const float* waveform_130) {
  const float scale = ecg_tensor->params.scale;
  const int zp = ecg_tensor->params.zero_point;
  for (int i = 0; i < 130; i++) {
    ecg_tensor->data.int8[i] = quantize(waveform_130[i], scale, zp);
  }
}

} // namespace

extern "C" bool tarang_ai_init(void) {
  sl_status_t status_gate = sl_ml_model_init(&sl_ml_gate_int8_model_handle);
  if (status_gate != SL_STATUS_OK) {
    s_ai_initialized = false;
    return false;
  }

#if __has_include("sl_ml_model_sv_int8.h") || __has_include("sl_ml_model_sv.h")
  sl_status_t status_sv = sl_ml_model_init(&SV_MODEL_HANDLE);
  if (status_sv != SL_STATUS_OK) {
    s_ai_initialized = false;
    return false;
  }
#endif

  s_ai_initialized = true;
  return true;
}

extern "C" bool tarang_ai_is_ready(void) {
  return s_ai_initialized;
}

extern "C" float tarang_ai_gate_predict(const float* waveform_130, const float* rr_features_4) {
  if (!s_ai_initialized || waveform_130 == nullptr || rr_features_4 == nullptr) {
    return -1.0f;
  }

  // input(0) = rr_features [1, 4], input(1) = ecg_waveform [1, 130, 1]
  TfLiteTensor* in_rr = sl_ml_gate_int8_model_handle.input_tensor(0);
  TfLiteTensor* in_ecg = sl_ml_gate_int8_model_handle.input_tensor(1);
  if (in_rr == nullptr || in_ecg == nullptr) {
    return -1.0f;
  }

  quantize_rr_features(in_rr, rr_features_4);
  quantize_ecg_waveform(in_ecg, waveform_130);

  sl_status_t status = sl_ml_model_run(&sl_ml_gate_int8_model_handle);
  if (status != SL_STATUS_OK) {
    return -1.0f;
  }

  TfLiteTensor* out_gate = sl_ml_gate_int8_model_handle.output_tensor(0);
  if (out_gate == nullptr) {
    return -1.0f;
  }

  float p_abnormal = dequantize(out_gate->data.int8[0], out_gate->params.scale, out_gate->params.zero_point);
  if (p_abnormal < 0.0f) p_abnormal = 0.0f;
  if (p_abnormal > 1.0f) p_abnormal = 1.0f;
  return p_abnormal;
}

extern "C" bool tarang_ai_sv_predict(const float* waveform_130, const float* rr_features_4, float* p_v, float* p_s) {
  if (!s_ai_initialized || waveform_130 == nullptr || rr_features_4 == nullptr) {
    return false;
  }

#if __has_include("sl_ml_model_sv_int8.h") || __has_include("sl_ml_model_sv.h")
  TfLiteTensor* in_rr = SV_MODEL_HANDLE.input_tensor(0);
  TfLiteTensor* in_ecg = SV_MODEL_HANDLE.input_tensor(1);
  if (in_rr == nullptr || in_ecg == nullptr) {
    return false;
  }

  quantize_rr_features(in_rr, rr_features_4);
  quantize_ecg_waveform(in_ecg, waveform_130);

  sl_status_t status = sl_ml_model_run(&SV_MODEL_HANDLE);
  if (status != SL_STATUS_OK) {
    return false;
  }

  // Two output heads: output(0) = P(V), output(1) = P(S)
  TfLiteTensor* out_v = SV_MODEL_HANDLE.output_tensor(0);
  TfLiteTensor* out_s = SV_MODEL_HANDLE.output_tensor(1);
  if (out_v == nullptr || out_s == nullptr) {
    return false;
  }

  if (p_v != nullptr) {
    float pv = dequantize(out_v->data.int8[0], out_v->params.scale, out_v->params.zero_point);
    if (pv < 0.0f) pv = 0.0f;
    if (pv > 1.0f) pv = 1.0f;
    *p_v = pv;
  }
  if (p_s != nullptr) {
    float ps = dequantize(out_s->data.int8[0], out_s->params.scale, out_s->params.zero_point);
    if (ps < 0.0f) ps = 0.0f;
    if (ps > 1.0f) ps = 1.0f;
    *p_s = ps;
  }
  return true;
#else
  if (p_v != nullptr) *p_v = 0.0f;
  if (p_s != nullptr) *p_s = 0.0f;
  return false;
#endif
}

extern "C" uint32_t tarang_ai_gate_model_size(void) {
  return gate_int8_length;
}

extern "C" uint32_t tarang_ai_sv_model_size(void) {
#if __has_include("sl_ml_model_sv_int8.h") || __has_include("sl_ml_model_sv.h")
  return sv_int8_length;
#else
  return 0;
#endif
}

extern "C" uint32_t tarang_ai_gate_arena_size(void) {
  uint32_t total = 0;
  for (int i = 0; i < gate_int8_buffer_count; i++) {
    total += gate_int8_buffer_sizes[i];
  }
  return total;
}

extern "C" uint32_t tarang_ai_sv_arena_size(void) {
#if __has_include("sl_ml_model_sv_int8.h") || __has_include("sl_ml_model_sv.h")
  uint32_t total = 0;
  for (int i = 0; i < sv_int8_buffer_count; i++) {
    total += sv_int8_buffer_sizes[i];
  }
  return total;
#else
  return 0;
#endif
}
