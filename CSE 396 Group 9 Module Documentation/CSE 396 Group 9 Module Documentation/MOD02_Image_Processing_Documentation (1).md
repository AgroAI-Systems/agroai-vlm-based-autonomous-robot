# MOD-02: Image Processing Module Documentation

**Smart Agriculture / Weed Elimination Robot**
**CSE396 — Computer Engineering Project — Group 9**

---

**Module ID:** MOD-02
**Module Name:** Image Processing
**Version:** 0.1
**Last Updated:** 2026-03-29
**Header File:** `mod2.h`
**Main Implementation File:** `image_processing.py`
**Language:** Python 3.11+ (with C-compatible header contract)

---

## Authors

| Name             | Student ID     | Role                                          |
|------------------|----------------|-----------------------------------------------|
| Mustafa Başaran  | 220104004084   | Pi Camera pipeline, OpenCV preprocessing      |
| Salih Cengiz     | 220104004007   | YOLOv8-nano inference, bounding box output    |

---

## Table of Contents

1. [Module Overview](#1-module-overview)
2. [Responsibilities](#2-responsibilities)
3. [System Context](#3-system-context)
4. [Dependencies](#4-dependencies)
5. [Configuration Constants](#5-configuration-constants)
6. [Data Types Reference](#6-data-types-reference)
7. [API Reference](#7-api-reference)
8. [Inter-Module Communication](#8-inter-module-communication)
9. [Processing Pipeline](#9-processing-pipeline)
10. [Error Handling](#10-error-handling)
11. [Known Risks and Open Questions](#11-known-risks-and-open-questions)
12. [References](#12-references)

---

## 1. Module Overview

MOD-02 (Image Processing) manages the full camera pipeline from raw frame capture to structured detection output. It uses `picamera2` to acquire frames from the Raspberry Pi Camera Module V3, applies OpenCV preprocessing (resize, color-space conversion, contrast normalization), and runs YOLOv8-nano inference on the Pi 5 CPU to locate plant regions within the frame.

The module outputs:

- A **bounding box struct** (`bbox_t`) containing pixel coordinates and detection confidence, consumed by MOD-04 (Decision Motor) for servo targeting.
- A **cropped ROI image** forwarded to MOD-03 (VLM) for semantic plant analysis via MoondreamV2.
- **Annotated frames** (with YOLO bounding boxes drawn) streamed to MOD-05 (GUI) for live monitoring.

All inference runs entirely on-device on the Raspberry Pi 5 CPU — zero cloud dependency.

---

## 2. Responsibilities

| # | Responsibility | Description |
|---|----------------|-------------|
| 1 | Frame Capture | Acquire frames from Pi Camera V3 via `picamera2` over the MIPI CSI-2 interface |
| 2 | Preprocessing | Resize, color-space conversion (BGR → RGB), contrast normalization via OpenCV |
| 3 | Object Detection | Run YOLOv8-nano inference to locate plant regions and produce bounding boxes |
| 4 | ROI Extraction | Crop the detected plant region from the full frame for VLM analysis |
| 5 | Annotation | Draw bounding boxes (green rectangle + confidence label) on the full frame |
| 6 | Output Delivery | Deliver `bbox_t` to Decision Motor, `image_frame_t` ROI to VLM, annotated frame to GUI |
| 7 | Re-capture Support | Handle re-capture requests from Decision Motor on mid-confidence re-evaluation |

---

## 3. System Context

The diagram below shows MOD-02's position within the overall system architecture and its data flow connections to other modules.

```
                    ┌───────────────────────┐
                    │  MOD-04               │
                    │  Decision Motor       │
                    │                       │
                    │  - Requests capture   │
                    │  - Receives bbox_t    │
                    │  - Re-capture trigger │
                    └───────┬───▲───────────┘
                            │   │
               imgproc_     │   │  bbox_t
               capture_and_ │   │  (pixel coords
               detect()     │   │   + confidence)
                            │   │
┌──────────────┐    ┌───────▼───┴───────────┐    ┌──────────────┐
│  Pi Camera   │    │                       │    │  MOD-03      │
│  Module V3   │───►│  MOD-02               │───►│  VLM         │
│  (CSI/MIPI)  │    │  IMAGE PROCESSING     │    │              │
│              │    │                       │    │  Receives    │
└──────────────┘    │  - picamera2 capture  │    │  cropped ROI │
                    │  - OpenCV preprocess  │    │  (image_     │
                    │  - YOLOv8-nano detect │    │   frame_t)   │
                    │  - ROI crop & annotate│    └──────────────┘
                    │                       │
                    └───────────┬────────────┘
                                │
                                │  gui_update_feed()
                                │  image_frame_t + bbox_t
                                ▼
                    ┌───────────────────────┐
                    │  MOD-05              │
                    │  GUI Dashboard       │
                    │                      │
                    │  Receives annotated  │
                    │  camera feed         │
                    └──────────────────────┘
```

**Hardware Interface:**

| Interface | Connection | Notes |
|-----------|-----------|-------|
| CSI / libcamera | Pi ↔ Pi Camera V3 | MIPI CSI-2 interface, accessed via `picamera2` library |

---

## 4. Dependencies

### 4.1 Software Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `picamera2` | >= 0.3 | Camera capture from Pi Camera V3 via libcamera backend |
| `opencv-python` (cv2) | >= 4.8 | Image preprocessing, color-space conversion, annotation |
| `ultralytics` | >= 8.0 | YOLOv8-nano object detection inference |
| `numpy` | >= 1.24 | Image array manipulation and numerical operations |
| `libcamera` | system | System-level backend for picamera2 |

### 4.2 Installation

```bash
pip install picamera2 opencv-python ultralytics numpy
```

> **Note:** `libcamera` is installed as a system package on Raspberry Pi OS and is a prerequisite for `picamera2`.

### 4.3 Hardware Requirements

| Component | Specification |
|-----------|---------------|
| Camera | Raspberry Pi Camera Module V3 (wide-angle) |
| Interface | MIPI CSI-2 connector on Raspberry Pi 5 |
| Compute | Raspberry Pi 5 CPU (all inference on-device) |

---

## 5. Configuration Constants

The following compile-time constants are defined in `mod2.h`:

| Constant | Value | Description |
|----------|-------|-------------|
| `IMGPROC_VERSION_STR` | `"0.1"` | Module version string |
| `FRAME_WIDTH` | 1280 | Captured frame width in pixels |
| `FRAME_HEIGHT` | 960 | Captured frame height in pixels |
| `YOLO_INPUT_SIZE` | 640 | Input size for YOLOv8-nano (640×640 px) |
| `VLM_CROP_SIZE` | 378 | Crop size for VLM ROI output (378×378 px) |
| `YOLO_CONF_MIN` | 0.45 | Minimum YOLO confidence threshold for valid detection |
| `BBOX_MIN_AREA` | 2000 | Minimum bounding box area (px²) to suppress spurious detections |
| `MAX_DETECTIONS` | 8 | Maximum number of detections stored per frame |

---

## 6. Data Types Reference

### 6.1 `bbox_t` — Bounding Box

Represents a single object detection result with pixel coordinates and confidence.

```c
typedef struct {
    uint16_t x;            // Top-left corner X coordinate (pixels)
    uint16_t y;            // Top-left corner Y coordinate (pixels)
    uint16_t width;        // Bounding box width (pixels)
    uint16_t height;       // Bounding box height (pixels)
    float    confidence;   // YOLO detection confidence [0.0 – 1.0]
    int32_t  class_id;     // Detected class ID from YOLO model
} bbox_t;
```

**Usage:** Consumed by MOD-04 (Decision Motor) for servo pan-tilt angle computation via `dm_compute_servo_target()`. The bounding box center `(x + width/2, y + height/2)` is used as the aiming point.

---

### 6.2 `camera_frame_t` — Camera Frame

Represents a raw or annotated image frame.

```c
typedef struct {
    uint8_t  *data;          // Pointer to RGB pixel buffer
    uint32_t  width;         // Frame width in pixels
    uint32_t  height;        // Frame height in pixels
    uint32_t  channels;      // Number of color channels (3 for RGB)
    uint32_t  stride;        // Number of bytes per row (width × channels, with padding)
    uint32_t  timestamp_ms;  // Capture timestamp in milliseconds
    bool      annotated;     // true if bounding boxes have been drawn on this frame
} camera_frame_t;
```

**Usage:** Used in two contexts:
- **Full frame** (annotated): Forwarded to GUI via `gui_update_feed()` with YOLO bounding boxes drawn (green rectangle + confidence label).
- **ROI crop**: Cropped plant region forwarded to VLM via `vlm_analyze_plant()` for semantic analysis.

---

### 6.3 `imgproc_status_t` — Status Codes

Enumeration of all possible return status codes from module functions.

```c
typedef enum {
    IMGPROC_OK              =  0,   // Operation completed successfully
    IMGPROC_ERR_INIT        = -1,   // Initialization failure (camera or model)
    IMGPROC_ERR_CAPTURE     = -2,   // Frame capture failure
    IMGPROC_ERR_INFERENCE   = -3,   // YOLO inference failure
    IMGPROC_ERR_NO_DETECT   = -4,   // No plant detected above confidence threshold
    IMGPROC_ERR_INVALID_ARG = -5,   // Invalid argument passed to function
    IMGPROC_ERR_NOT_INIT    = -6    // Module not initialized (init() not called)
} imgproc_status_t;
```

---

### 6.4 `imgproc_config_t` — Module Configuration

Runtime configuration parameters for the Image Processing module.

```c
typedef struct {
    uint32_t frame_width;      // Capture resolution width (default: FRAME_WIDTH = 1280)
    uint32_t frame_height;     // Capture resolution height (default: FRAME_HEIGHT = 960)
    float    yolo_conf_min;    // Minimum YOLO confidence (default: YOLO_CONF_MIN = 0.45)
    uint32_t bbox_min_area;    // Minimum bbox area in px² (default: BBOX_MIN_AREA = 2000)
    bool     fix_exposure;     // If true, fix camera exposure at startup (recommended)
} imgproc_config_t;
```

**Note:** The `fix_exposure` flag is recommended to be set to `true` for consistent image quality under variable indoor lighting. When enabled, the camera's auto-exposure and white-balance are locked at pipeline startup.

---

### 6.5 `detection_result_t` — Detection Result

Aggregate result of a single capture-and-detect cycle.

```c
typedef struct {
    imgproc_status_t status;                    // Operation status
    camera_frame_t   full_frame;                // Full-resolution annotated frame
    camera_frame_t   roi_crop;                  // Cropped plant ROI for VLM
    bbox_t           detections[MAX_DETECTIONS]; // All valid detections (up to 8)
    uint8_t          detection_count;            // Number of valid detections
    bbox_t           best_bbox;                  // Highest-confidence detection
    bool             plant_detected;             // true if at least one valid detection
} detection_result_t;
```

**Note:** When multiple plant regions are detected in a single frame, the module selects the `best_bbox` (highest confidence detection) for downstream processing. All detections are still stored in the `detections[]` array for potential future use.

---

### 6.6 `imgproc_frame_cb_t` — Frame Callback

Function pointer type for asynchronous frame delivery.

```c
typedef void (*imgproc_frame_cb_t)(const detection_result_t *result);
```

**Usage:** Registered via `imgproc_set_frame_callback()`. The callback is invoked after each successful detection cycle, allowing downstream modules (e.g., GUI) to receive results without polling.

---

## 7. API Reference

### 7.1 `imgproc_init`

```c
imgproc_status_t imgproc_init(const imgproc_config_t *cfg);
```

**Description:** Initializes the Image Processing module. Sets up the Pi Camera V3 connection via `picamera2`, loads the YOLOv8-nano model, and applies the provided configuration. Must be called before any other module function.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `cfg` | `const imgproc_config_t *` | Module configuration. Pass `NULL` to use default values. |

**Returns:** `IMGPROC_OK` on success, `IMGPROC_ERR_INIT` on failure.

**Default Configuration (when `cfg` is NULL):**

| Parameter | Default |
|-----------|---------|
| `frame_width` | 1280 |
| `frame_height` | 960 |
| `yolo_conf_min` | 0.45 |
| `bbox_min_area` | 2000 |
| `fix_exposure` | false |

---

### 7.2 `imgproc_capture_and_detect`

```c
imgproc_status_t imgproc_capture_and_detect(detection_result_t *out);
```

**Description:** Performs a complete capture-and-detect cycle:

1. Captures a frame from Pi Camera V3
2. Applies OpenCV preprocessing (resize to `YOLO_INPUT_SIZE`, color-space conversion, contrast normalization)
3. Runs YOLOv8-nano inference
4. Filters detections by `YOLO_CONF_MIN` threshold and `BBOX_MIN_AREA` minimum area
5. Selects the best (highest confidence) detection
6. Crops the ROI to `VLM_CROP_SIZE` for VLM analysis
7. Annotates the full frame with bounding boxes
8. Populates the output `detection_result_t` struct

This is the **primary function** called by MOD-04 (Decision Motor) to initiate the image capture and detection pipeline.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `out` | `detection_result_t *` | Pointer to result struct to be populated |

**Returns:**

| Status | Condition |
|--------|-----------|
| `IMGPROC_OK` | Detection successful; `plant_detected = true` |
| `IMGPROC_ERR_NOT_INIT` | Module not initialized |
| `IMGPROC_ERR_INVALID_ARG` | `out` pointer is NULL |
| `IMGPROC_ERR_CAPTURE` | Camera frame capture failed |
| `IMGPROC_ERR_INFERENCE` | YOLO model inference failed |
| `IMGPROC_ERR_NO_DETECT` | No detection above threshold; `plant_detected = false` |

**Typical Call Sequence:**
```
MOD-04 calls: imgproc_capture_and_detect(&result)
         ├── result.best_bbox  → used for dm_compute_servo_target()
         ├── result.roi_crop   → passed to vlm_analyze_plant()
         └── result.full_frame → forwarded to gui_update_feed()
```

---

### 7.3 `imgproc_get_last_frame`

```c
imgproc_status_t imgproc_get_last_frame(camera_frame_t *out);
```

**Description:** Retrieves the most recently captured full frame without triggering a new capture or detection cycle. Useful for GUI refresh or debugging purposes.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `out` | `camera_frame_t *` | Pointer to frame struct to be populated |

**Returns:** `IMGPROC_OK` on success, `IMGPROC_ERR_NOT_INIT` if module not initialized, `IMGPROC_ERR_INVALID_ARG` if pointer is NULL.

---

### 7.4 `imgproc_set_frame_callback`

```c
void imgproc_set_frame_callback(imgproc_frame_cb_t cb);
```

**Description:** Registers a callback function that is invoked after each successful capture-and-detect cycle. The callback receives a pointer to the `detection_result_t`. Pass `NULL` to unregister.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `cb` | `imgproc_frame_cb_t` | Callback function pointer, or `NULL` to unregister |

---

### 7.5 `imgproc_status_to_string`

```c
const char* imgproc_status_to_string(imgproc_status_t status);
```

**Description:** Returns a human-readable string representation of the given status code. Useful for logging and debugging.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `status` | `imgproc_status_t` | Status code to convert |

**Returns:** Pointer to a static string (e.g., `"IMGPROC_OK"`, `"IMGPROC_ERR_CAPTURE"`).

---

### 7.6 `imgproc_shutdown`

```c
void imgproc_shutdown(void);
```

**Description:** Releases all resources held by the module: closes the camera connection, unloads the YOLO model, and frees allocated memory. After this call, `imgproc_init()` must be called again before using any other function.

---

## 8. Inter-Module Communication

### 8.1 Communication Summary Table

| Direction | Peer Module | Data / Signal | Type | Frequency |
|-----------|-------------|---------------|------|-----------|
| **MOD-02 → MOD-03** (VLM) | MOD-03 VLM | Cropped ROI image | `image_frame_t` | Once per plant stop (or twice on re-eval) |
| **MOD-02 → MOD-04** (Decision Motor) | MOD-04 Decision Motor | Bounding box coordinates | `bbox_t` | Once per detection, for servo targeting |
| **MOD-02 → MOD-05** (GUI) | MOD-05 GUI | Annotated camera feed + overlay | `image_frame_t` + `bbox_t` | Per detection cycle, via `gui_update_feed()` |
| **MOD-04 → MOD-02** (Re-capture) | MOD-04 Decision Motor | Re-capture request | Function call | On mid-confidence (0.5–0.7), max 1 retry |

### 8.2 Detailed Communication Descriptions

#### MOD-02 → MOD-04 (Decision Motor): Bounding Box

The Image Processing module provides a `bbox_t` struct containing the pixel coordinates (`x`, `y`, `width`, `height`) and YOLO detection confidence of the detected plant region. The Decision Motor uses the bounding box center to compute servo pan-tilt angles via `dm_compute_servo_target()`, enabling the spray or laser to be aimed at the detected plant.

**Data exchanged:** `bbox_t` struct — pixel coordinates and detection confidence.

#### MOD-02 → MOD-03 (VLM): Image ROI

When the Image Processing module completes YOLO detection, it crops the plant region from the full frame (resized to `VLM_CROP_SIZE` = 378×378 px) and passes it to the VLM module via `vlm_analyze_plant()`. The input includes the cropped image data (RGB pixel buffer) and image dimensions. The VLM module constructs a multi-modal prompt incorporating the visual data, then invokes MoondreamV2 to generate a structured JSON response.

**Data exchanged:** `camera_frame_t` (ROI crop) — RGB image buffer (`uint8_t` array), width, height, stride.

#### MOD-02 → MOD-05 (GUI): Annotated Camera Feed

The Image Processing module forwards every captured and annotated frame to the GUI via `gui_update_feed()`. The frame passed is the full-resolution image (1280×960) with YOLO bounding boxes already drawn (green rectangle + confidence score label). This call is made once per detection cycle — approximately once per plant stop — rather than at a continuous video rate, since inference is the bottleneck. The GUI module is responsible for rendering the frame; Image Processing does not retain a reference after the call.

**Data exchanged:** `camera_frame_t` (annotated full frame) + `bbox_t` (bounding box coordinates and confidence for overlay rendering).

#### MOD-04 → MOD-02: Re-Capture Request

When the VLM confidence falls in the mid range (0.5–0.7), the Decision Motor directly calls `imgproc_capture_and_detect()` to re-capture and re-detect the plant. This happens at most once per plant (`DM_MAX_REEVALUATIONS = 1`). On the second evaluation, the result is accepted regardless of confidence.

**Data exchanged:** Uses the standard `detection_result_t` return type.

---

## 9. Processing Pipeline

The following diagram shows the complete processing pipeline within MOD-02 for a single capture-and-detect cycle:

```
                    imgproc_capture_and_detect() called
                                │
                                ▼
                   ┌────────────────────────┐
                   │  1. FRAME CAPTURE      │
                   │  picamera2 → raw frame │
                   │  Resolution: 1280×960  │
                   └───────────┬────────────┘
                               │
                               ▼
                   ┌────────────────────────┐
                   │  2. PREPROCESSING      │
                   │  • Resize → 640×640    │
                   │    (YOLO_INPUT_SIZE)   │
                   │  • BGR → RGB convert   │
                   │  • Contrast normalize  │
                   └───────────┬────────────┘
                               │
                               ▼
                   ┌────────────────────────┐
                   │  3. YOLO INFERENCE     │
                   │  YOLOv8-nano on CPU    │
                   │  ~1–3 seconds/frame    │
                   └───────────┬────────────┘
                               │
                               ▼
                   ┌────────────────────────┐
                   │  4. DETECTION FILTER   │
                   │  • conf ≥ YOLO_CONF_MIN│
                   │    (0.45)              │
                   │  • area ≥ BBOX_MIN_AREA│
                   │    (2000 px²)          │
                   │  • Select best_bbox    │
                   └───────────┬────────────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
              plant_detected         plant_detected
              = true                 = false
                    │                     │
                    ▼                     ▼
         ┌──────────────────┐    Return ERR_NO_DETECT
         │  5. ROI CROP     │
         │  Crop best_bbox  │
         │  Resize → 378×378│
         │  (VLM_CROP_SIZE) │
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │  6. ANNOTATION   │
         │  Draw green rect │
         │  + conf label on │
         │  full 1280×960   │
         │  frame           │
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │  7. OUTPUT       │
         │                  │
         │  → bbox_t        │──► MOD-04 (servo targeting)
         │  → roi_crop      │──► MOD-03 (VLM analysis)
         │  → full_frame    │──► MOD-05 (GUI display)
         │                  │
         │  Return IMGPROC_OK│
         └──────────────────┘
```

### Timing Constraints

| Stage | Estimated Duration |
|-------|-------------------|
| Frame capture | ~50 ms |
| OpenCV preprocessing | ~20 ms |
| YOLOv8-nano inference | ~1–3 seconds |
| Post-processing (filter, crop, annotate) | ~10 ms |
| **Total per cycle** | **~1–3 seconds** |

---

## 10. Error Handling

### 10.1 Status Code Decision Table

| Status Code | Cause | Recommended Action |
|-------------|-------|--------------------|
| `IMGPROC_OK` | Successful capture and detection | Proceed with detection result |
| `IMGPROC_ERR_INIT` | Camera or YOLO model failed to initialize | Check camera connection and model file; retry `imgproc_init()` |
| `IMGPROC_ERR_CAPTURE` | Camera frame capture failed | Check CSI cable; retry capture |
| `IMGPROC_ERR_INFERENCE` | YOLO model inference failed | Check model file integrity; restart module |
| `IMGPROC_ERR_NO_DETECT` | No plant found above threshold | Decision Motor should treat as "no plant" and resume navigation |
| `IMGPROC_ERR_INVALID_ARG` | NULL pointer passed to function | Fix caller code |
| `IMGPROC_ERR_NOT_INIT` | Function called before `imgproc_init()` | Call `imgproc_init()` first |

### 10.2 Error Propagation

All public functions return `imgproc_status_t`. Callers (primarily MOD-04 Decision Motor) should check return values before accessing result data. The `imgproc_status_to_string()` utility function is provided for human-readable logging.

Example usage:
```c
detection_result_t result;
imgproc_status_t status = imgproc_capture_and_detect(&result);

if (status != IMGPROC_OK) {
    printf("Image processing error: %s\n", imgproc_status_to_string(status));
    // handle error...
}
```

---

## 11. Known Risks and Open Questions

| # | Risk / Issue | Severity | Status | Mitigation |
|---|-------------|----------|--------|------------|
| 1 | **YOLOv8-nano false detections** on non-plant objects (track surface markings, cables, pots without plants) if confidence threshold is too low | Medium | Open | Tune `YOLO_CONF_MIN` threshold during testing; `BBOX_MIN_AREA` filter suppresses small spurious detections |
| 2 | **Lighting variability and image quality**: Pi Camera V3 auto-exposure may produce overexposed or underexposed frames under variable indoor lighting | Medium | Open | Set `fix_exposure = true` in config to lock exposure and white-balance at startup; test under actual demo conditions |
| 3 | **Camera barrel distortion**: Pi Camera V3 wide-angle lens may introduce distortion that degrades bounding box accuracy at frame edges | Medium | Open | May need non-linear calibration lookup table for pixel-to-angle mapping |
| 4 | **Model not fine-tuned**: YOLOv8-nano uses pretrained weights, not yet fine-tuned for project-specific plant types | Medium | Open | Plan dataset collection and fine-tuning during development phase |
| 5 | **Multiple detections reduced to best_bbox**: if multiple plants are in frame, only the highest-confidence detection is used | Low | By design | Current pipeline assumes one plant per stop; revisit if parkour layout changes |
| 6 | **No continuous video stream**: camera feed is captured per-detection-cycle, not at continuous video rate | Low | By design | Inference is the bottleneck (~1–3 sec); continuous streaming would not add value at this rate |
| 7 | **GPIO/CSI allocation**: final GPIO pin assignments not finalized; need to verify no conflicts with CSI camera interface | Low | Open | Coordinate with MOD-01 (Pathing) for pin allocation |

---

## 12. References

| Resource | URL |
|----------|-----|
| Ultralytics YOLOv8 Documentation | https://docs.ultralytics.com/ |
| picamera2 Library | https://github.com/raspberrypi/picamera2 |
| OpenCV Python Documentation | https://docs.opencv.org/ |
| Raspberry Pi Camera Documentation | https://www.raspberrypi.com/documentation/accessories/camera.html |
| Raspberry Pi 5 Documentation | https://www.raspberrypi.com/documentation/ |

---

*Document generated for CSE396 Computer Engineering Project — Group 9*
*Smart Agriculture / Weed Elimination Robot — Autonomous On-Device Plant Inspection and Precision Actuation System*
