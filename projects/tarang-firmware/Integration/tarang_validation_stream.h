/***************************************************************************//**
 * @file tarang_validation_stream.h
 * @brief Compact, line-safe volunteer validation telemetry helpers.
 ******************************************************************************/
#ifndef TARANG_VALIDATION_STREAM_H
#define TARANG_VALIDATION_STREAM_H

#include "tarang_constants.h"

#define TARANG_VALIDATION_STREAM_VERSION       2u
#define TARANG_VALIDATION_STREAM_REQUIRED_BAUD 115200u
#define TARANG_VALIDATION_MAX_PAYLOAD          160u

#if TARANG_ENABLE_VALIDATION_STREAM
#include "sl_iostream_eusart_vcom_config.h"
#if SL_IOSTREAM_EUSART_VCOM_BAUDRATE >= TARANG_VALIDATION_STREAM_REQUIRED_BAUD
#define TARANG_VALIDATION_STREAM_ACTIVE 1
#else
#define TARANG_VALIDATION_STREAM_ACTIVE 0
#endif
#else
#define TARANG_VALIDATION_STREAM_ACTIVE 0
#endif

#if TARANG_VALIDATION_STREAM_ACTIVE

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

static inline void tarang_validation_put_u16(uint8_t *dst, uint16_t value)
{
  dst[0] = (uint8_t)value;
  dst[1] = (uint8_t)(value >> 8u);
}

static inline void tarang_validation_put_u24(uint8_t *dst, uint32_t value)
{
  dst[0] = (uint8_t)value;
  dst[1] = (uint8_t)(value >> 8u);
  dst[2] = (uint8_t)(value >> 16u);
}

static inline void tarang_validation_put_u32(uint8_t *dst, uint32_t value)
{
  dst[0] = (uint8_t)value;
  dst[1] = (uint8_t)(value >> 8u);
  dst[2] = (uint8_t)(value >> 16u);
  dst[3] = (uint8_t)(value >> 24u);
}

static inline int16_t tarang_validation_i16(float value, float scale)
{
  float scaled = value * scale;
  if (scaled > 32767.0f) return INT16_MAX;
  if (scaled < -32768.0f) return INT16_MIN;
  return (int16_t)(scaled >= 0.0f ? scaled + 0.5f : scaled - 0.5f);
}

static inline uint16_t tarang_validation_u16(float value, float scale)
{
  float scaled = value * scale;
  if (scaled <= 0.0f) return 0u;
  if (scaled >= 65535.0f) return UINT16_MAX;
  return (uint16_t)(scaled + 0.5f);
}

static inline void tarang_validation_emit(char stream_id,
                                          const uint8_t *payload,
                                          size_t payload_len)
{
  static const char alphabet[] =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  char encoded[((TARANG_VALIDATION_MAX_PAYLOAD + 2u) / 3u) * 4u + 1u];
  size_t input = 0u;
  size_t output = 0u;

  if (payload_len > TARANG_VALIDATION_MAX_PAYLOAD) return;

  while ((input + 3u) <= payload_len) {
    uint32_t word = ((uint32_t)payload[input] << 16u)
                  | ((uint32_t)payload[input + 1u] << 8u)
                  | (uint32_t)payload[input + 2u];
    encoded[output++] = alphabet[(word >> 18u) & 0x3Fu];
    encoded[output++] = alphabet[(word >> 12u) & 0x3Fu];
    encoded[output++] = alphabet[(word >> 6u) & 0x3Fu];
    encoded[output++] = alphabet[word & 0x3Fu];
    input += 3u;
  }

  if (input < payload_len) {
    uint32_t word = (uint32_t)payload[input] << 16u;
    bool have_second = (input + 1u) < payload_len;
    if (have_second) word |= (uint32_t)payload[input + 1u] << 8u;
    encoded[output++] = alphabet[(word >> 18u) & 0x3Fu];
    encoded[output++] = alphabet[(word >> 12u) & 0x3Fu];
    encoded[output++] = have_second ? alphabet[(word >> 6u) & 0x3Fu] : '=';
    encoded[output++] = '=';
  }

  encoded[output] = '\0';
  printf("@%c2,%s\r\n", stream_id, encoded);
}

#endif

#endif /* TARANG_VALIDATION_STREAM_H */
