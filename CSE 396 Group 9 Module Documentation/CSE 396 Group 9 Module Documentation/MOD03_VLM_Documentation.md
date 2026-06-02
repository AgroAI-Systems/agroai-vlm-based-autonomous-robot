# MOD-03: VLM Plant Analysis Module Documentation

**Smart Agriculture / Weed Elimination Robot**
**CSE396 — Computer Engineering Project — Group 9**

---

**Module ID:** MOD-03
**Module Name:** VLM Plant Analysis
**Version:** 0.1
**Last Updated:** 2026-04-18
**Header File:** `mod3.h`
**Main Implementation File:** `vlm_engine.py`
**Language:** Python 3.11+ (with C-compatible header contract)

---

## Authors

| Name          | Student ID   | Role                                                      |
|---------------|--------------|-----------------------------------------------------------|
| Umut Akman    | 250104004997 | MoondreamV2 inference pipeline, prompt engineering        |
| Bekir Göktepe | 220104004018 | JSON output parsing, result validation, error handling    |

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

MOD-03 (VLM Plant Analysis) performs multi-modal plant health analysis on the Raspberry Pi 5 CPU, entirely on-device with no cloud dependency. It accepts a cropped plant ROI image from MOD-02 (Image Processing), constructs a structured natural-language prompt, and runs MoondreamV2 (INT4 quantized) inference via `llama.cpp` or ONNX Runtime to produce a structured JSON response.

The module outputs:

- A **`vlm_result_t` struct** containing plant status classification, confidence score, diagnosis text, recommended action, and severity level — consumed by MOD-04 (Decision Motor) for confidence-gated action logic.
- The same **`vlm_result_t`** forwarded to MOD-05 (GUI) for real-time result display on the operator dashboard.

The VLM approach is prompt-driven: plant classification behavior is controlled entirely through natural language without model retraining. This makes the module flexible for different plant types and disease categories without additional training data.

---

## 2. Responsibilities

| # | Responsibility        | Description                                                                                                 |
|---|-----------------------|-------------------------------------------------------------------------------------------------------------|
| 1 | Model Initialization  | Load the MoondreamV2 INT4 quantized model via `llama.cpp` or ONNX Runtime at startup                       |
| 2 | Prompt Construction   | Build a structured prompt combining the plant ROI image and optional environmental sensor context            |
| 3 | VLM Inference         | Run MoondreamV2 on the Pi 5 CPU to generate a JSON text response for the plant image                        |
| 4 | JSON Parsing          | Parse and validate the model's JSON output into a `vlm_result_t` struct                                     |
| 5 | Result Delivery       | Return the populated `vlm_result_t` to MOD-04 (Decision Motor) as the primary output                        |
| 6 | Utility Strings       | Provide human-readable string conversions for all status and classification enumerations                     |
| 7 | Re-analysis Support   | Accept a new ROI image and re-run inference when called again by MOD-04 on mid-confidence re-evaluation      |

---

## 3. System Context

The diagram below shows MOD-03's position within the overall system architecture and its data flow connections to other modules.

```
┌──────────────────────┐
│  MOD-02              │
│  Image Processing    │
│                      │
│  - Provides ROI crop │
│    (378×378 px RGB)  │
└──────────┬───────────┘
           │
           │  vlm_analyze_plant()
           │  vlm_image_t
           │  (cropped ROI)
           ▼
┌──────────────────────────────────────────────────┐
│                                                  │
│  MOD-03 — VLM PLANT ANALYSIS                     │
│                                                  │
│  1. Build structured prompt                      │
│  2. Run MoondreamV2 INT4 (llama.cpp / ONNX)      │
│  3. Parse JSON output                            │
│  4. Return vlm_result_t                          │
│                                                  │
└──────────┬───────────────────────┬───────────────┘
           │                       │
           │  vlm_result_t         │  vlm_result_t
           │  (classification,     │  (for display)
           │   confidence,         │
           │   action, severity)   │
           ▼                       ▼
┌──────────────────┐   ┌───────────────────────────┐
│  MOD-04          │   │  MOD-05                   │
│  Decision Motor  │   │  GUI Dashboard            │
│                  │   │                           │
│  Confidence-     │   │  Displays VLM result      │
│  gated action    │   │  in real time via         │
│  logic           │   │  dashboard_push_vlm_      │
│                  │   │  result()                 │
└──────────────────┘   └───────────────────────────┘
           │
           │  Re-analysis request (function call)
           │  On mid-confidence (0.5–0.7), max 1 retry
           └──────────────────────────────────────────►  vlm_analyze_plant() called again
                                                          with new ROI from MOD-02
```

**Hardware Interface:**

| Interface  | Connection         | Notes                                                              |
|------------|--------------------|--------------------------------------------------------------------|
| CPU (Pi 5) | MoondreamV2 model  | Inference runs entirely on Pi 5 ARM CPU; no GPU or NPU required    |

---

## 4. Dependencies

### 4.1 Software Dependencies

| Package / Library         | Version      | Purpose                                                          |
|---------------------------|--------------|------------------------------------------------------------------|
| `llama-cpp-python`        | >= 0.2       | Primary inference backend for MoondreamV2 INT4 via `llama.cpp`   |
| `onnxruntime`             | >= 1.17      | Alternative inference backend (if `llama.cpp` is not used)       |
| `opencv-python` (cv2)     | >= 4.8       | Image format conversion (RGB buffer → model input format)        |
| `numpy`                   | >= 1.24      | Image array manipulation                                         |
| `json` (stdlib)           | Python stdlib | Parsing VLM JSON text output into Python dict / C struct         |

### 4.2 Installation

```bash
pip install llama-cpp-python opencv-python numpy
# OR for ONNX backend:
pip install onnxruntime opencv-python numpy
```

> **Note:** `llama-cpp-python` must be compiled for ARM (Raspberry Pi 5). Pre-built wheels for `aarch64` are available; verify compatibility before installation.

### 4.3 Model Requirement

| Model           | Quantization | Approximate Size | Source                                      |
|-----------------|--------------|------------------|---------------------------------------------|
| MoondreamV2     | INT4 (GGUF)  | ~1.7 GB          | https://github.com/vikhyat/moondream        |

> The model file path is supplied via `vlm_config_t.model_path` at initialization. The model must be pre-downloaded onto the Raspberry Pi before the first run.

### 4.4 Hardware Requirements

| Component  | Specification                                          |
|------------|--------------------------------------------------------|
| Compute    | Raspberry Pi 5 (ARM Cortex-A76, 4 GB RAM minimum)     |
| Storage    | microSD or SSD with ≥ 4 GB free (for model file)      |

---

## 5. Configuration Constants

The following compile-time constants are defined in `mod3.h`:

| Constant               | Value    | Description                                                        |
|------------------------|----------|--------------------------------------------------------------------|
| `VLM_MAX_DIAGNOSIS_LEN`| 256      | Maximum character length of the diagnosis text field in `vlm_result_t` |
| `VLM_MAX_PROMPT_LEN`   | 1024     | Maximum character length of the constructed prompt string          |
| `VLM_TIMEOUT_MS`       | 30000    | Maximum allowed inference time in milliseconds (30 seconds)        |
| `VLM_CONFIDENCE_HIGH`  | 0.70     | Confidence threshold for immediate action (used by MOD-04)         |
| `VLM_CONFIDENCE_MID`   | 0.50     | Confidence threshold for re-evaluation trigger (used by MOD-04)    |

> **Note:** `VLM_CONFIDENCE_HIGH` and `VLM_CONFIDENCE_MID` are defined in `mod3.h` for reference and documentation purposes. The actual decision logic that acts on these thresholds lives in MOD-04 (Decision Motor).

---

## 6. Data Types Reference

### 6.1 `vlm_status_t` — Status Codes

Enumeration of all possible return status codes from module functions.

```c
typedef enum {
    VLM_OK                =  0,   // Operation completed successfully
    VLM_ERR_INIT          = -1,   // Model failed to load or initialize
    VLM_ERR_INVALID_INPUT = -2,   // NULL pointer or zero-dimension image passed
    VLM_ERR_INFERENCE     = -3,   // Model inference failed (runtime error)
    VLM_ERR_TIMEOUT       = -4,   // Inference exceeded VLM_TIMEOUT_MS
    VLM_ERR_PARSE         = -5,   // Model output is not valid JSON or missing fields
    VLM_ERR_MEMORY        = -6    // Memory allocation failure
} vlm_status_t;
```

---

### 6.2 `vlm_plant_status_t` — Plant Classification

Classification result for the analyzed plant.

```c
typedef enum {
    VLM_STATUS_HEALTHY  = 0,   // Plant is healthy; no intervention needed beyond prevention spray
    VLM_STATUS_DISEASED = 1,   // Plant shows signs of disease; spray treatment recommended
    VLM_STATUS_WEED     = 2,   // Plant is a weed; laser elimination recommended
    VLM_STATUS_UNKNOWN  = 3    // Model could not classify the plant with sufficient confidence
} vlm_plant_status_t;
```

**Mapping to actions:**

| `vlm_plant_status_t`   | Default `vlm_action_t` | Physical Actuator  |
|------------------------|------------------------|--------------------|
| `VLM_STATUS_HEALTHY`   | `VLM_ACTION_SPRAY`     | Water pump (2 s)   |
| `VLM_STATUS_DISEASED`  | `VLM_ACTION_SPRAY`     | Water pump (2 s)   |
| `VLM_STATUS_WEED`      | `VLM_ACTION_LASER`     | Laser pointer (3 s)|
| `VLM_STATUS_UNKNOWN`   | `VLM_ACTION_SKIP`      | No actuation       |

> **Note:** The final action is decided by MOD-04 (Decision Motor) based on both the `vlm_action_t` field and the confidence score. The mapping above is the default; MOD-04 may override it.

---

### 6.3 `vlm_action_t` — Recommended Action

```c
typedef enum {
    VLM_ACTION_SKIP  = 0,   // Do not actuate; log and continue
    VLM_ACTION_SPRAY = 1,   // Activate water pump toward plant
    VLM_ACTION_LASER = 2    // Activate laser pointer toward plant
} vlm_action_t;
```

---

### 6.4 `vlm_severity_t` — Disease / Weed Severity

```c
typedef enum {
    VLM_SEVERITY_NONE   = 0,   // No issue detected (healthy plant)
    VLM_SEVERITY_LOW    = 1,   // Minor symptoms visible
    VLM_SEVERITY_MEDIUM = 2,   // Moderate symptoms
    VLM_SEVERITY_HIGH   = 3    // Severe symptoms or aggressive weed
} vlm_severity_t;
```

**Usage:** The severity field is informational. It is stored in the field report by MOD-04 but does not currently affect actuator behavior (duration is fixed).

---

### 6.5 `vlm_image_t` — Input Image

The image struct passed into `vlm_analyze_plant()` by MOD-02.

```c
typedef struct {
    uint8_t  *data;         // Pointer to RGB pixel buffer (row-major, 3 channels)
    uint32_t  width;        // Image width in pixels (expected: VLM_CROP_SIZE = 378)
    uint32_t  height;       // Image height in pixels (expected: VLM_CROP_SIZE = 378)
    uint32_t  stride;       // Bytes per row (width × 3, with any padding)
    uint32_t  timestamp_ms; // Capture timestamp from MOD-02 (passed through for logging)
} vlm_image_t;
```

**Usage:** This struct wraps the cropped ROI produced by MOD-02. The pixel buffer is read-only inside MOD-03; the module does not retain a reference after `vlm_analyze_plant()` returns.

---

### 6.6 `vlm_sensor_context_t` — Environmental Context (Reserved)

```c
typedef struct {
    float    soil_moisture_percent;  // Soil moisture reading [0.0 – 100.0]
    uint16_t light_level_lux;        // Ambient light level in lux
    uint32_t timestamp_ms;           // Sensor reading timestamp
    bool     valid;                  // true if sensor data is valid and should be used
} vlm_sensor_context_t;
```

**Status:** This struct is defined for future use. It is not currently used in `vlm_analyze_plant()` calls. The `valid` flag is `false` in all current invocations. When implemented, sensor context will be embedded into the prompt text to improve classification accuracy under variable conditions.

---

### 6.7 `vlm_result_t` — Analysis Output

The primary output struct returned by `vlm_analyze_plant()`.

```c
typedef struct {
    vlm_plant_status_t status;                    // Classified plant status
    float              confidence;                 // Model confidence score [0.0 – 1.0]
    char               diagnosis[VLM_MAX_DIAGNOSIS_LEN]; // Human-readable diagnosis (max 256 chars)
    vlm_action_t       action;                     // Recommended action
    vlm_severity_t     severity;                   // Assessed severity level
    uint32_t           inference_time_ms;           // Actual inference duration in milliseconds
} vlm_result_t;
```

**Field notes:**

| Field                | Source                   | Notes                                                                 |
|----------------------|--------------------------|-----------------------------------------------------------------------|
| `status`             | Parsed from JSON `status`| Mapped from string (`"healthy"`, `"diseased"`, `"weed"`) to enum      |
| `confidence`         | Parsed from JSON `confidence` | Float in [0.0, 1.0]; used by MOD-04 for threshold gating         |
| `diagnosis`          | Parsed from JSON `diagnosis` | Free-text description; truncated to `VLM_MAX_DIAGNOSIS_LEN` if needed |
| `action`             | Parsed from JSON `action`| Mapped from string (`"skip"`, `"spray"`, `"laser"`) to enum           |
| `severity`           | Parsed from JSON `severity` | Mapped from string (`"none"`, `"low"`, `"medium"`, `"high"`)        |
| `inference_time_ms`  | Measured internally      | Wall-clock duration of the MoondreamV2 inference call                 |

---

### 6.8 `vlm_config_t` — Module Configuration

Runtime configuration for the VLM module.

```c
typedef struct {
    const char *model_path;         // Absolute path to the MoondreamV2 GGUF model file
    uint32_t    max_inference_ms;   // Inference timeout in ms (default: VLM_TIMEOUT_MS = 30000)
    bool        verbose_logging;    // If true, print raw model output to stdout for debugging
} vlm_config_t;
```

---

## 7. API Reference

### 7.1 `vlm_init`

```c
vlm_status_t vlm_init(const vlm_config_t *config);
```

**Description:** Initializes the VLM module. Loads the MoondreamV2 INT4 model from the path specified in `config->model_path` using the configured inference backend (`llama.cpp` or ONNX Runtime). Must be called once before any other module function.

**Parameters:**

| Parameter | Type                   | Description                                          |
|-----------|------------------------|------------------------------------------------------|
| `config`  | `const vlm_config_t *` | Module configuration. Must not be NULL. `model_path` must be a valid, readable file path. |

**Returns:**

| Status               | Condition                                              |
|----------------------|--------------------------------------------------------|
| `VLM_OK`             | Model loaded successfully; module is ready             |
| `VLM_ERR_INIT`       | Model file not found, corrupt, or backend failed to initialize |
| `VLM_ERR_INVALID_INPUT` | `config` or `config->model_path` is NULL            |
| `VLM_ERR_MEMORY`     | Insufficient memory to load the model                  |

**Example:**
```c
vlm_config_t cfg = {
    .model_path       = "/home/pi/models/moondream2-int4.gguf",
    .max_inference_ms = 30000,
    .verbose_logging  = false
};
vlm_status_t s = vlm_init(&cfg);
if (s != VLM_OK) {
    fprintf(stderr, "VLM init failed: %s\n", vlm_status_to_string(s));
}
```

---

### 7.2 `vlm_analyze_plant`

```c
vlm_status_t vlm_analyze_plant(const vlm_image_t *image, vlm_result_t *result);
```

**Description:** The primary function of MOD-03. Accepts a cropped plant ROI image, constructs a structured prompt, runs MoondreamV2 inference, parses the JSON output, and populates the output `vlm_result_t` struct.

**Internally, this function:**

1. Validates input pointers and image dimensions
2. Converts the RGB pixel buffer to the model's expected input format
3. Constructs the structured prompt string (see prompt format below)
4. Invokes MoondreamV2 inference with a timeout of `config.max_inference_ms`
5. Parses the JSON text response
6. Maps string fields to their respective enumerations
7. Measures and records `inference_time_ms`
8. Returns `VLM_ERR_PARSE` if the JSON is malformed or missing required fields

**Parameters:**

| Parameter | Type                    | Description                                        |
|-----------|-------------------------|----------------------------------------------------|
| `image`   | `const vlm_image_t *`   | Cropped ROI image from MOD-02. Must not be NULL; `data` pointer must be valid. |
| `result`  | `vlm_result_t *`        | Pointer to result struct to be populated. Must not be NULL. |

**Returns:**

| Status                  | Condition                                                       |
|-------------------------|-----------------------------------------------------------------|
| `VLM_OK`                | Inference and parsing succeeded; `result` is fully populated    |
| `VLM_ERR_INVALID_INPUT` | `image` or `result` is NULL, or image dimensions are zero       |
| `VLM_ERR_INFERENCE`     | Model inference failed at runtime                               |
| `VLM_ERR_TIMEOUT`       | Inference exceeded `max_inference_ms`                           |
| `VLM_ERR_PARSE`         | Model output was not valid JSON or missing required fields       |
| `VLM_ERR_MEMORY`        | Memory allocation failure during processing                     |

**Prompt Format:**

The module constructs and sends the following structured prompt to MoondreamV2:

```
Analyze this plant leaf image.
Classify the plant and respond ONLY in JSON with no extra text:
{
  "status":     "healthy" | "diseased" | "weed",
  "confidence": 0.0 - 1.0,
  "diagnosis":  "brief description (max 200 characters)",
  "action":     "skip" | "spray" | "laser",
  "severity":   "none" | "low" | "medium" | "high"
}
```

**Typical Call Sequence:**
```
MOD-04 calls imgproc_capture_and_detect() → gets detection_result_t
MOD-04 calls vlm_analyze_plant(&result.roi_crop_as_vlm_image, &vlm_result)
        ├── vlm_result.status      → plant classification
        ├── vlm_result.confidence  → threshold check (≥ 0.7 / 0.5–0.7 / < 0.5)
        ├── vlm_result.action      → recommended actuator
        ├── vlm_result.severity    → stored in field report
        └── vlm_result.diagnosis   → stored in field report
```

---

### 7.3 `vlm_status_to_string`

```c
const char* vlm_status_to_string(vlm_status_t status);
```

**Description:** Returns a human-readable string representation of a `vlm_status_t` code. Useful for logging and debugging.

**Returns:** Pointer to a static string (e.g., `"VLM_OK"`, `"VLM_ERR_PARSE"`). The returned pointer must not be freed.

---

### 7.4 `vlm_plant_status_to_string`

```c
const char* vlm_plant_status_to_string(vlm_plant_status_t status);
```

**Description:** Returns a human-readable string for a `vlm_plant_status_t` value (e.g., `"HEALTHY"`, `"DISEASED"`, `"WEED"`, `"UNKNOWN"`). Used by MOD-04 when writing field report entries and by MOD-05 when rendering the dashboard.

---

### 7.5 `vlm_action_to_string`

```c
const char* vlm_action_to_string(vlm_action_t action);
```

**Description:** Returns a human-readable string for a `vlm_action_t` value (e.g., `"SKIP"`, `"SPRAY"`, `"LASER"`). Used by MOD-04 and MOD-05 for logging and display.

---

### 7.6 `vlm_shutdown`

```c
void vlm_shutdown(void);
```

**Description:** Releases all resources held by the module: unloads the MoondreamV2 model from memory and frees the inference backend context. After this call, `vlm_init()` must be called again before using any other function.

---

## 8. Inter-Module Communication

### 8.1 Communication Summary Table

| Direction              | Peer Module             | Data / Signal        | Type            | Frequency                                         |
|------------------------|-------------------------|----------------------|-----------------|---------------------------------------------------|
| **MOD-02 → MOD-03**    | MOD-02 Image Processing | Cropped ROI image    | `vlm_image_t`   | Once per plant stop; twice if mid-confidence re-eval |
| **MOD-03 → MOD-04**    | MOD-04 Decision Motor   | Analysis result      | `vlm_result_t`  | Once per `vlm_analyze_plant()` call               |
| **MOD-04 → MOD-03**    | MOD-04 Decision Motor   | Re-analysis request  | Function call   | On mid-confidence (0.5–0.7), at most once per plant |
| **MOD-03 → MOD-05**    | MOD-05 GUI Dashboard    | VLM result for display | `vlm_result_t` | Per inference, via `dashboard_push_vlm_result()`   |

### 8.2 Detailed Communication Descriptions

#### MOD-02 → MOD-03: Cropped ROI Image

When MOD-02 (Image Processing) completes YOLO detection, it crops the plant region from the full frame (resized to `VLM_CROP_SIZE` = 378×378 px) and passes it to MOD-03 as a `vlm_image_t`. The struct contains the raw RGB pixel buffer, image dimensions, stride, and the capture timestamp (passed through for logging). MOD-03 does not retain a reference to the pixel buffer after `vlm_analyze_plant()` returns; the caller (MOD-04) owns the buffer lifetime.

**Data exchanged:** `vlm_image_t` — RGB pixel buffer, width, height, stride, timestamp.

#### MOD-03 → MOD-04: Analysis Result

After inference and JSON parsing complete successfully, `vlm_analyze_plant()` populates and returns a `vlm_result_t` struct to MOD-04 (Decision Motor). MOD-04 reads the `confidence` field against the two thresholds (`VLM_CONFIDENCE_HIGH` = 0.70 and `VLM_CONFIDENCE_MID` = 0.50) to determine next action: execute immediately, re-evaluate, or skip. The `action` field is the VLM's recommendation; MOD-04 may override it (e.g., skip regardless of recommendation if confidence is too low).

**Data exchanged:** `vlm_result_t` — status, confidence, diagnosis, action, severity, inference_time_ms.

#### MOD-04 → MOD-03: Re-Analysis Request

When the VLM confidence falls in the mid range (0.5–0.7), MOD-04 requests a fresh frame from MOD-02 via `imgproc_capture_and_detect()`, then calls `vlm_analyze_plant()` again with the new ROI. This re-evaluation happens at most once per plant stop (`DECISION_MAX_RESCANS = 2` total scan attempts). On the second evaluation, the result is accepted regardless of confidence, and the robot proceeds to the ACT or skip phase.

**Data exchanged:** Standard `vlm_image_t` input and `vlm_result_t` output; same as the first call.

#### MOD-03 → MOD-05: VLM Result Display

After MOD-04 receives the `vlm_result_t`, it forwards it to MOD-05 (GUI Dashboard) via `dashboard_push_vlm_result(plant_id, &vlm_result)`. MOD-03 does not call MOD-05 directly; the forwarding is performed by MOD-04 as part of its LOG state. This keeps MOD-03 decoupled from the GUI module.

**Data exchanged:** `vlm_result_t` (passed through MOD-04 to MOD-05).

---

## 9. Processing Pipeline

The following diagram shows the complete processing pipeline within MOD-03 for a single `vlm_analyze_plant()` call:

```
              vlm_analyze_plant(image, result) called by MOD-04
                                │
                                ▼
                   ┌────────────────────────┐
                   │  1. INPUT VALIDATION   │
                   │  Check image != NULL   │
                   │  Check width/height > 0│
                   │  Check result != NULL  │
                   └───────────┬────────────┘
                               │
                               ▼
                   ┌────────────────────────┐
                   │  2. FORMAT CONVERSION  │
                   │  RGB buffer →          │
                   │  model input tensor    │
                   │  (OpenCV / numpy)      │
                   └───────────┬────────────┘
                               │
                               ▼
                   ┌────────────────────────┐
                   │  3. PROMPT BUILDING    │
                   │  Structured JSON       │
                   │  prompt (max 1024 chars│
                   │  VLM_MAX_PROMPT_LEN)   │
                   └───────────┬────────────┘
                               │
                               ▼
                   ┌────────────────────────┐
                   │  4. VLM INFERENCE      │
                   │  MoondreamV2 INT4      │
                   │  via llama.cpp / ONNX  │
                   │  ~8–15 seconds on Pi 5 │
                   │  Timeout: 30 s         │
                   └───────────┬────────────┘
                               │
                    ┌──────────┴──────────────┐
                    │                         │
               Inference OK              Timeout / Error
                    │                         │
                    ▼                         ▼
         ┌──────────────────┐       Return VLM_ERR_TIMEOUT
         │  5. JSON PARSING │       or VLM_ERR_INFERENCE
         │  Parse text →    │
         │  Python dict     │
         │  Validate fields │
         └────────┬─────────┘
                  │
         ┌────────┴─────────┐
         │                  │
      Parse OK          Parse Failed
         │                  │
         ▼                  ▼
  ┌──────────────┐   Return VLM_ERR_PARSE
  │  6. ENUM MAP │
  │  string →    │
  │  vlm_plant_  │
  │  status_t,   │
  │  vlm_action_t│
  │  vlm_severity│
  └──────┬───────┘
         │
         ▼
  ┌──────────────────────┐
  │  7. RESULT POPULATE  │
  │  Fill vlm_result_t   │
  │  Record inference_   │
  │  time_ms             │
  │  Return VLM_OK       │
  └──────┬───────────────┘
         │
         ├── result.status         ──► MOD-04 (classification)
         ├── result.confidence     ──► MOD-04 (threshold gating)
         ├── result.action         ──► MOD-04 (actuator selection)
         ├── result.severity       ──► MOD-04 → MOD-05 (field report)
         └── result.diagnosis      ──► MOD-04 → MOD-05 (field report)
```

### Timing Constraints

| Stage                      | Estimated Duration       |
|----------------------------|--------------------------|
| Input validation           | < 1 ms                   |
| Format conversion (OpenCV) | ~10–20 ms                |
| Prompt construction        | < 1 ms                   |
| MoondreamV2 INT4 inference | **~8–15 seconds**        |
| JSON parsing & enum mapping| ~5 ms                    |
| **Total per call**         | **~8–15 seconds**        |

> VLM inference is the dominant latency contributor and the primary bottleneck in the per-plant pipeline. The 30-second `VLM_TIMEOUT_MS` limit provides headroom for slower runs while still bounding worst-case plant stop time.

---

## 10. Error Handling

### 10.1 Status Code Decision Table

| Status Code             | Cause                                                    | Recommended Action                                                    |
|-------------------------|----------------------------------------------------------|-----------------------------------------------------------------------|
| `VLM_OK`                | Inference and parsing succeeded                          | Proceed with `vlm_result_t`                                           |
| `VLM_ERR_INIT`          | Model file not found or backend initialization failed    | Check `model_path` and backend installation; abort mission            |
| `VLM_ERR_INVALID_INPUT` | NULL pointer or zero-dimension image passed              | Fix caller code in MOD-04                                             |
| `VLM_ERR_INFERENCE`     | Model runtime error during inference                     | Log error; MOD-04 should skip actuation and resume navigation         |
| `VLM_ERR_TIMEOUT`       | Inference exceeded `VLM_TIMEOUT_MS` (30 s)               | Log timeout; MOD-04 should skip actuation and resume navigation       |
| `VLM_ERR_PARSE`         | JSON output is malformed or missing required fields      | Log raw output if `verbose_logging = true`; MOD-04 treats as uncertain|
| `VLM_ERR_MEMORY`        | Memory allocation failure                                | Log and abort mission; system memory may be exhausted                 |

### 10.2 Error Propagation

All public functions except `vlm_shutdown()` return `vlm_status_t`. MOD-04 (Decision Motor) must check the return value before accessing `vlm_result_t` fields. The `vlm_status_to_string()` utility is provided for human-readable logging.

Example usage:
```c
vlm_result_t result;
vlm_status_t s = vlm_analyze_plant(&roi_image, &result);

if (s != VLM_OK) {
    printf("VLM error: %s\n", vlm_status_to_string(s));
    // MOD-04 handles: skip actuation, log error, resume navigation
} else {
    printf("Plant: %s  Confidence: %.2f  Action: %s\n",
           vlm_plant_status_to_string(result.status),
           result.confidence,
           vlm_action_to_string(result.action));
}
```

### 10.3 Parse Failure Behavior

If `VLM_ERR_PARSE` is returned, the `vlm_result_t` output struct is populated with safe defaults:

| Field         | Default on Parse Failure |
|---------------|--------------------------|
| `status`      | `VLM_STATUS_UNKNOWN`     |
| `confidence`  | `0.0f`                   |
| `diagnosis`   | `"parse_error"`          |
| `action`      | `VLM_ACTION_SKIP`        |
| `severity`    | `VLM_SEVERITY_NONE`      |

This ensures MOD-04 always receives a valid (if conservative) struct regardless of model output quality.

---

## 11. Known Risks and Open Questions

| # | Risk / Issue | Severity | Status | Mitigation |
|---|-------------|----------|--------|------------|
| 1 | **Inference latency (8–15 s):** Combined with YOLO (~1–3 s) and re-evaluation, worst-case per-plant time may exceed the 30-second target | High | Open | Reduce input resolution; explore ONNX Runtime vs. llama.cpp; profile and select faster backend during development |
| 2 | **Non-deterministic output:** MoondreamV2 may produce different confidence scores or diagnoses for identical inputs across runs | Medium | Open | Evaluate temperature/sampling settings; document variance in final report |
| 3 | **Parse failure on malformed JSON:** Model may output conversational text instead of pure JSON, especially on unusual plant images | Medium | Open | Enforce strict JSON-only prompt; add regex pre-filter to strip any surrounding text before parsing |
| 4 | **Diagnosis truncation:** Free-text diagnosis field may be cut at `VLM_MAX_DIAGNOSIS_LEN` (256 chars), losing clinical context | Low | By design | 256 chars is sufficient for brief descriptions; increase constant if needed |
| 5 | **Prompt versioning not implemented:** No mechanism to track which prompt version produced which result | Low | Open | Add prompt version string to `vlm_result_t` or log entry in a future iteration |
| 6 | **`vlm_sensor_context_t` not yet integrated:** Environmental context (soil moisture, lighting) is defined but not used; may reduce accuracy under variable lighting | Medium | Planned | Integrate sensor readings into prompt when hardware sensors are connected |
| 7 | **Model file must be pre-installed:** The GGUF model (~1.7 GB) must be manually downloaded and placed on the Pi before first run; no automatic download | Low | By design | Document model download step in setup guide; verify file integrity with checksum |
| 8 | **Single-call blocking inference:** `vlm_analyze_plant()` is synchronous and blocks the calling thread for 8–15 seconds | Medium | Open | MOD-04 background thread mitigates this; robot is stationary during inference, so blocking is acceptable for current design |

---

## 12. References

| Resource                           | URL                                                      |
|------------------------------------|----------------------------------------------------------|
| MoondreamV2 Model Repository       | https://github.com/vikhyat/moondream                    |
| llama.cpp (quantized LLM inference)| https://github.com/ggerganov/llama.cpp                   |
| llama-cpp-python (Python bindings) | https://github.com/abetlen/llama-cpp-python              |
| ONNX Runtime Documentation         | https://onnxruntime.ai/docs/                             |
| OpenCV Python Documentation        | https://docs.opencv.org/                                 |
| Raspberry Pi 5 Documentation       | https://www.raspberrypi.com/documentation/               |
| Ultralytics YOLOv8 (MOD-02 ref)    | https://docs.ultralytics.com/                            |

---

*Document prepared for CSE396 Computer Engineering Project — Group 9*
*Smart Agriculture / Weed Elimination Robot — Autonomous On-Device Plant Inspection and Precision Actuation System*
