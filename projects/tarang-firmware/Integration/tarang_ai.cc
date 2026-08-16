#include "tarang_ai.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/system_setup.h"
#include "tensorflow/lite/schema/schema_generated.h"

#include "gate_model_data.h"
#include "sv_model_data.h"
#include "rr_scaler.h"
#include "thresholds.h"
#include "tarang_model_version.h"
#include <string_view>

// Compile-time linkage verification across all model artifacts
static_assert(std::string_view(RR_SCALER_RUN_ID) == std::string_view(TARANG_MODEL_RUN_ID),
              "Mismatch: rr_scaler.h must match TARANG_MODEL_RUN_ID");
static_assert(std::string_view(THRESHOLDS_RUN_ID) == std::string_view(TARANG_MODEL_RUN_ID),
              "Mismatch: thresholds.h must match TARANG_MODEL_RUN_ID");
static_assert(std::string_view(GATE_MODEL_RUN_ID) == std::string_view(TARANG_MODEL_RUN_ID),
              "Mismatch: gate_model_data.h must match TARANG_MODEL_RUN_ID");
static_assert(std::string_view(SV_MODEL_RUN_ID) == std::string_view(TARANG_MODEL_RUN_ID),
              "Mismatch: sv_model_data.h must match TARANG_MODEL_RUN_ID");

namespace {
  constexpr int kGateTensorArenaSize = 16 * 1024;
  constexpr int kSVTensorArenaSize   = 24 * 1024;

  alignas(16) uint8_t gate_tensor_arena[kGateTensorArenaSize];
  alignas(16) uint8_t sv_tensor_arena[kSVTensorArenaSize];

  const tflite::Model* gate_model = nullptr;
  const tflite::Model* sv_model = nullptr;
  tflite::MicroInterpreter* gate_interpreter = nullptr;
  tflite::MicroInterpreter* sv_interpreter = nullptr;
  bool ai_initialized = false;

  // Shared 10-op resolver definition — both models use identical op set
  template <unsigned int N>
  void register_ops(tflite::MicroMutableOpResolver<N>& resolver) {
    resolver.AddShape();
    resolver.AddStridedSlice();
    resolver.AddPack();
    resolver.AddReshape();
    resolver.AddConv2D();
    resolver.AddMaxPool2D();
    resolver.AddMean();
    resolver.AddFullyConnected();
    resolver.AddConcatenation();
    resolver.AddLogistic();
  }

  inline int8_t quantize(float value, float scale, int zero_point) {
    int32_t q = static_cast<int32_t>(value / scale) + zero_point;
    if (q < -128) q = -128;
    if (q > 127) q = 127;
    return static_cast<int8_t>(q);
  }

  inline float dequantize(int8_t value, float scale, int zero_point) {
    return (value - zero_point) * scale;
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
}

extern "C" bool tarang_ai_init(void) {
  gate_model = tflite::GetModel(gate_model_data);
  if (gate_model->version() != TFLITE_SCHEMA_VERSION) return false;

  static tflite::MicroMutableOpResolver<10> gate_resolver;
  register_ops(gate_resolver);

  static tflite::MicroInterpreter static_gate_interpreter(
      gate_model, gate_resolver, gate_tensor_arena, kGateTensorArenaSize);
  gate_interpreter = &static_gate_interpreter;
  if (gate_interpreter->AllocateTensors() != kTfLiteOk) return false;

  sv_model = tflite::GetModel(sv_model_data);
  if (sv_model->version() != TFLITE_SCHEMA_VERSION) return false;

  static tflite::MicroMutableOpResolver<10> sv_resolver;
  register_ops(sv_resolver);

  static tflite::MicroInterpreter static_sv_interpreter(
      sv_model, sv_resolver, sv_tensor_arena, kSVTensorArenaSize);
  sv_interpreter = &static_sv_interpreter;
  if (sv_interpreter->AllocateTensors() != kTfLiteOk) return false;

  ai_initialized = true;
  return true;
}

extern "C" bool tarang_ai_is_ready(void) { return ai_initialized; }

extern "C" float tarang_ai_gate_predict(const float* waveform_130,
                                         const float* rr_features_4) {
  if (!ai_initialized) return 0.0f;

  // NOTE: input(0) = rr_input, input(1) = ecg_input
  TfLiteTensor* rr_input = gate_interpreter->input(0);
  TfLiteTensor* ecg_input = gate_interpreter->input(1);

  quantize_rr_features(rr_input, rr_features_4);
  quantize_ecg_waveform(ecg_input, waveform_130);

  if (gate_interpreter->Invoke() != kTfLiteOk) return 0.0f;

  TfLiteTensor* output = gate_interpreter->output(0);
  return dequantize(output->data.int8[0], output->params.scale, output->params.zero_point);
}

extern "C" bool tarang_ai_sv_predict(const float* waveform_130,
                                      const float* rr_features_4,
                                      float* p_v, float* p_s) {
  if (!ai_initialized) return false;

  TfLiteTensor* rr_input = sv_interpreter->input(0);
  TfLiteTensor* ecg_input = sv_interpreter->input(1);

  quantize_rr_features(rr_input, rr_features_4);
  quantize_ecg_waveform(ecg_input, waveform_130);

  if (sv_interpreter->Invoke() != kTfLiteOk) return false;

  // TWO separate output tensors: output(0) = P(V), output(1) = P(S)
  TfLiteTensor* v_output = sv_interpreter->output(0);  // StatefulPartitionedCall:1
  TfLiteTensor* s_output = sv_interpreter->output(1);  // StatefulPartitionedCall:0

  *p_v = dequantize(v_output->data.int8[0], v_output->params.scale, v_output->params.zero_point);
  *p_s = dequantize(s_output->data.int8[0], s_output->params.scale, s_output->params.zero_point);

  return true;
}

extern "C" uint32_t tarang_ai_gate_model_size(void) { return gate_model ? (uint32_t)gate_model_data_len : 0; }
extern "C" uint32_t tarang_ai_sv_model_size(void)   { return sv_model ? (uint32_t)sv_model_data_len : 0; }
extern "C" uint32_t tarang_ai_gate_arena_size(void) { return (uint32_t)kGateTensorArenaSize; }
extern "C" uint32_t tarang_ai_sv_arena_size(void)   { return (uint32_t)kSVTensorArenaSize; }
