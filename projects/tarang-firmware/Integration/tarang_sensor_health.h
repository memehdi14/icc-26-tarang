/***************************************************************************//**
 * @file tarang_sensor_health.h
 * @brief Shared, independent liveness states for TARANG sensors.
 ******************************************************************************/
#ifndef TARANG_SENSOR_HEALTH_H
#define TARANG_SENSOR_HEALTH_H

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
  TARANG_SENSOR_DISABLED = 0,
  TARANG_SENSOR_STARTING = 1,
  TARANG_SENSOR_OK = 2,
  TARANG_SENSOR_STALE = 3,
  TARANG_SENSOR_UNAVAILABLE = 4
} tarang_sensor_health_t;

static inline int tarang_sensor_health_is_valid(tarang_sensor_health_t health)
{
  return health == TARANG_SENSOR_OK;
}

#ifdef __cplusplus
}
#endif

#endif /* TARANG_SENSOR_HEALTH_H */
