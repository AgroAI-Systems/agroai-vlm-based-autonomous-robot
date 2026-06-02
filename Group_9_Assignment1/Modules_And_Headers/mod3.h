#ifndef MOD3_H
#define MOD3_H

#include <stdint.h>
#include <stdbool.h>

#define VLM_MAX_DIAGNOSIS_LEN     256
#define VLM_MAX_PROMPT_LEN        1024
#define VLM_TIMEOUT_MS            30000
#define VLM_CONFIDENCE_HIGH       0.70f
#define VLM_CONFIDENCE_MID        0.50f

typedef enum {
    VLM_OK                =  0,
    VLM_ERR_INIT          = -1,
    VLM_ERR_INVALID_INPUT = -2,
    VLM_ERR_INFERENCE     = -3,
    VLM_ERR_TIMEOUT       = -4,
    VLM_ERR_PARSE         = -5,
    VLM_ERR_MEMORY        = -6
} vlm_status_t;

typedef enum {
    VLM_STATUS_HEALTHY = 0,
    VLM_STATUS_DISEASED,
    VLM_STATUS_WEED,
    VLM_STATUS_UNKNOWN
} vlm_plant_status_t;

typedef enum {
    VLM_ACTION_SKIP = 0,
    VLM_ACTION_SPRAY,
    VLM_ACTION_LASER
} vlm_action_t;

typedef enum {
    VLM_SEVERITY_NONE = 0,
    VLM_SEVERITY_LOW,
    VLM_SEVERITY_MEDIUM,
    VLM_SEVERITY_HIGH
} vlm_severity_t;

typedef struct {
    uint8_t  *data;
    uint32_t width;
    uint32_t height;
    uint32_t stride;
    uint32_t timestamp_ms;
} vlm_image_t;

typedef struct {
    float    soil_moisture_percent;
    uint16_t light_level_lux;
    uint32_t timestamp_ms;
    bool     valid;
} vlm_sensor_context_t;

typedef struct {
    vlm_plant_status_t status;
    float              confidence;
    char               diagnosis[VLM_MAX_DIAGNOSIS_LEN];
    vlm_action_t       action;
    vlm_severity_t     severity;
    uint32_t           inference_time_ms;
} vlm_result_t;

typedef struct {
    const char *model_path;
    uint32_t    max_inference_ms;
    bool        verbose_logging;
} vlm_config_t;

vlm_status_t vlm_init(const vlm_config_t *config);
vlm_status_t vlm_analyze_plant(const vlm_image_t *image, vlm_result_t *result);
const char*  vlm_status_to_string(vlm_status_t status);
const char*  vlm_plant_status_to_string(vlm_plant_status_t status);
const char*  vlm_action_to_string(vlm_action_t action);
void         vlm_shutdown(void);

#endif /* MOD3_H */
