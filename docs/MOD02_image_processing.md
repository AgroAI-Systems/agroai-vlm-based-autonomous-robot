# MOD-02 — Image Processing (Capture + YOLO Detection)

**Implementation:** `src/robot_server.py` (camera + server) and the pipeline core
in `src/mod2_mod3_pipeline.py` (`load_yolo`, `yolo_detect`, `run_pipeline_on_image`).
**Model:** `src/best.pt` — custom-trained YOLO, 3 classes.
**Role in pipeline:** on a plant stop, capture a frame, detect the plant, crop the
region of interest, and hand it (plus the YOLO class/confidence) to MOD-03.

## Capture

`robot_server.py` opens the Pi camera once via `picamera2` at **1280×720** and
keeps it open. On each `CAPTURE` request it writes a frame to
`src/camera_captures/capture_NNNN.jpg` and runs the pipeline on it. (For
regression testing, a file path can be sent instead of `CAPTURE` and that image
is analysed directly.)

## YOLO detection (`yolo_detect`)

Inference runs through Ultralytics with `conf=YOLO_DETECT_MIN_CONF=0.25` to drop
weak detections. The highest-confidence box is selected and returned as
`(mod3_class_id, confidence, yolo_class_name, bbox_xyxy)`. If nothing is detected,
`mod3_class_id = -1` ("no_detection").

### Class mapping

`best.pt` raw classes are mapped to the canonical MOD-03 class IDs:

| `best.pt` class | Name | MOD-03 class ID | Meaning |
| --- | --- | --- | --- |
| 0 | SCAB | 1 | DISEASED (apple scab / leaf disease) |
| 1 | Weeds (Purslane) | 2 | WEED |
| 2 | healthy | 0 | HEALTHY |

(The MOD-03 canonical IDs are `0=healthy, 1=diseased, 2=weed`; the
`BESTPT_TO_MOD3_CLASS` table in `mod2_mod3_pipeline.py` performs the remap so the
rest of the system never sees the raw `best.pt` ordering.)

## ROI crop → MOD-03

The detected bounding box is cropped from the full frame and resized to
**224×224** RGB. If there is no detection, the whole frame is resized to 224×224.
The exact image sent to the VLM is saved to
`src/vlm_crops/<frame>_vlm_input.jpg` for inspection / the dashboard.

The crop is wrapped in a `VlmImage` (see [MOD03](MOD03_vlm.md)) carrying the pixel
buffer plus `yolo_class_id` and `yolo_confidence` — these two fields drive the
bypass gate in MOD-03.

```python
VlmImage(
    data            = pil_img.tobytes(),   # 224x224 RGB, row-major
    width=224, height=224, stride=224*3,
    timestamp_ms    = <capture ms>,
    yolo_class_id   = mod3_class_id,        # 0/1/2, or -1 if no detection
    yolo_confidence = yolo_conf,            # [0.0, 1.0]
)
```

## Output

`run_pipeline_on_image()` returns a dict combining the YOLO and VLM results
(`yolo_name`, `yolo_confidence`, `yolo_time_ms`, `gate`, `plant_status`,
`confidence`, `action`, `severity`, `diagnosis`, `vlm_time_ms`, `total_time_ms`).
`robot_server.py` then condenses this into the decision JSON consumed by
[MOD-04](MOD04_decision_motor.md).
