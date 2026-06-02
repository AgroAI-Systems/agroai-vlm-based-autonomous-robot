# MOD-02 - Image Processing System

Captures frames from Pi Camera V3, runs YOLOv8-nano, and outputs detections plus ROI crops.

## Authors

| Name | Student ID |
|---|---|
| Mustafa Basaran | 220104004084 |
| Salih Cengiz | 220104004007 |

## Metadata

| Field | Value |
|---|---|
| Language | Python 3.11+ |
| Main file | `image_processing.py` |
| Version | 0.1 |
| Last updated | 2026-03-29 |

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| `picamera2` | >= 0.3 | camera capture |
| `opencv-python` | >= 4.8 | preprocessing and annotation |
| `ultralytics` | >= 8.0 | YOLO inference |
| `numpy` | >= 1.24 | array operations |
| `libcamera` | system | backend for picamera2 |

Install:

```bash
pip install picamera2 opencv-python ultralytics numpy
```

## API Summary

### Constants

- `FRAME_WIDTH`, `FRAME_HEIGHT`
- `YOLO_INPUT_SIZE`, `VLM_CROP_SIZE`
- `YOLO_CONF_MIN`, `BBOX_MIN_AREA`
- `IMGPROC_VERSION`

### Status Codes

- `ImgprocStatus`: `OK`, `ERR_INIT`, `ERR_CAPTURE`, `ERR_INFERENCE`, `ERR_NO_DETECT`, `ERR_INVALID_ARG`, `ERR_NOT_INIT`

### Main Data Classes

- `BBox`
- `ImageFrame`
- `DetectionResult`
- `ImgprocConfig`

### Main Methods

- `init(cfg=None)`
- `default_config()`
- `capture_and_detect()`
- `get_last_frame()`
- `set_frame_callback(cb)`
- `shutdown()`
- `status_str(status)`

## Limitations and TODOs

- Model is not yet fine-tuned for project plants.
- Multiple detections are reduced to `best_bbox`.
- No continuous video output by default.
- Camera distortion may impact box precision.
- GPIO/CSI allocation coordination with Pathing is pending.
