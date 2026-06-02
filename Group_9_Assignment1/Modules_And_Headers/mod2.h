#ifndef MOD2_H
#define MOD2_H

#include <stdint.h>
#include <stdbool.h>

#define IMGPROC_VERSION_STR       "0.1"
#define FRAME_WIDTH               1280
#define FRAME_HEIGHT              960
#define YOLO_INPUT_SIZE           640
#define VLM_CROP_SIZE             378
#define YOLO_CONF_MIN             0.45f
#define BBOX_MIN_AREA             2000
#define MAX_DETECTIONS            8

typedef struct {
    uint16_t x;
    uint16_t y;
    uint16_t width;
    uint16_t height;
    float confidence;
    int32_t class_id;
} bbox_t;

typedef struct {
    uint8_t *data;
    uint32_t width;
    uint32_t height;
    uint32_t channels;
    uint32_t stride;
    uint32_t timestamp_ms;
    bool annotated;
} camera_frame_t;

typedef enum {
    IMGPROC_OK              =  0,
    IMGPROC_ERR_INIT        = -1,
    IMGPROC_ERR_CAPTURE     = -2,
    IMGPROC_ERR_INFERENCE   = -3,
    IMGPROC_ERR_NO_DETECT   = -4,
    IMGPROC_ERR_INVALID_ARG = -5,
    IMGPROC_ERR_NOT_INIT    = -6
} imgproc_status_t;

typedef struct {
    uint32_t frame_width;
    uint32_t frame_height;
    float    yolo_conf_min;
    uint32_t bbox_min_area;
    bool     fix_exposure;
} imgproc_config_t;

typedef struct {
    imgproc_status_t status;
    camera_frame_t   full_frame;
    camera_frame_t   roi_crop;
    bbox_t           detections[MAX_DETECTIONS];
    uint8_t          detection_count;
    bbox_t           best_bbox;
    bool             plant_detected;
} detection_result_t;

typedef void (*imgproc_frame_cb_t)(const detection_result_t *result);

imgproc_status_t imgproc_init(const imgproc_config_t *cfg);
imgproc_status_t imgproc_capture_and_detect(detection_result_t *out);
imgproc_status_t imgproc_get_last_frame(camera_frame_t *out);
void             imgproc_set_frame_callback(imgproc_frame_cb_t cb);
const char*      imgproc_status_to_string(imgproc_status_t status);
void             imgproc_shutdown(void);

#endif /* MOD2_H */
