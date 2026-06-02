# MOD-03 - VLM Plant Analysis

Performs multimodal plant health analysis using MoondreamV2.

## Authors

| Name | Student ID |
|---|---|
| Umut Akman | 250104004997 |
| Bekir Goktepe | 220104004018 |

## Purpose

Consumes cropped plant images (and optionally environmental context) and returns structured outputs: plant status, confidence, diagnosis, severity, and recommended action.

## Dependencies

| Dependency | Purpose |
|---|---|
| Image Processing System | provides ROI images |
| MoondreamV2 INT4 model | VLM inference |
| llama.cpp or ONNX Runtime | backend |
| OpenCV bindings | format conversion |
| JSON parser | structured output |

## API Summary

- `vlm_init(config)`
- `vlm_analyze_plant(image, result)`
- `vlm_status_to_string(status)`
- `vlm_plant_status_to_string(status)`
- `vlm_action_to_string(action)`
- `vlm_shutdown()`

## Data Types

Inputs:
- `vlm_image_t`
- `vlm_config_t`

Outputs:
- `vlm_result_t`
- `vlm_status_t`

Classification enums:
- `vlm_plant_status_t`: `HEALTHY`, `DISEASED`, `WEED`, `UNKNOWN`
- `vlm_action_t`: `SKIP`, `SPRAY`, `LASER`
- `vlm_severity_t`: `NONE`, `LOW`, `MEDIUM`, `HIGH`

Reserved:
- `vlm_sensor_context_t` (future use)

## Limitations and TODOs

Current:
- Inference latency (8-15 s)
- Non-deterministic confidence/diagnosis variation
- Parse failure risk on malformed model output
- Diagnosis length limit may truncate output

Planned:
- Prompt versioning
- Confidence calibration on validation data
- Image hash-based inference cache
- Telemetry logging

## Integration Note

Decision rule suggestion:
- `confidence >= 0.7`: execute action
- `0.5 <= confidence < 0.7`: recapture and re-analyze
- `confidence < 0.5`: skip and log uncertain
