# MOD-03 — VLM Plant Analysis (SmolVLM-256M + Bypass Gate)

**Implementation:** `src/vlm/` — `vlm_engine.py` (inference), `vlm_parser.py`
(JSON parsing/validation), `vlm_types.py` (enums, `VlmImage`, `VlmResult`,
thresholds), `vlm_errors.py`.
**Model:** `HuggingFaceTB/SmolVLM-256M-Instruct` via HuggingFace `transformers`
(PyTorch CPU).
**Role in pipeline:** take the cropped ROI + YOLO class/confidence from MOD-02 and
produce a validated `VlmResult` (status, confidence, diagnosis, action, severity).
The enum integer values mirror the `mod3.h` C contract so the Python and C sides
agree.

## The YOLO → VLM bypass gate (key design point)

To avoid paying ~15–30 s of VLM latency on every plant, MOD-03 can skip inference
entirely and synthesise a `VlmResult` directly from the YOLO class. The gate is
controlled by per-class thresholds in `vlm_types.py`:

```python
YOLO_VLM_THRESHOLDS = {
    YOLO_CLASS_WEED:     0.0,   # bypass at any confidence
    YOLO_CLASS_HEALTHY:  0.0,   # bypass at any confidence
    YOLO_CLASS_DISEASED: 0.0,   # bypass at any confidence
}
```

If `yolo_confidence >= threshold` for the detected class, the VLM is **bypassed**
and the result is synthesised from the YOLO class.

All three thresholds are set to `0.0`, so the VLM is bypassed for every class and
YOLO drives the decision — this is what keeps the per-plant cycle fast on the Pi 4.
The SmolVLM stage stays fully wired: raising a threshold above the YOLO confidence
(e.g. `0.75` for HEALTHY/DISEASED) routes those cases through the VLM for a second
opinion on the harder healthy-vs-diseased boundary.

When the gate does **not** bypass, the ROI and a strict JSON-only prompt are sent
to SmolVLM-256M with a timeout (~15 s); on timeout or error it falls back to the
YOLO-derived result.

## Data types (`vlm_types.py`)

Enum integer values mirror `mod3.h` exactly so the Python and C sides agree.

| Enum | Values |
| --- | --- |
| `VlmStatus` | `OK=0`, `ERR_INIT=-1`, `ERR_INVALID_INPUT=-2`, `ERR_INFERENCE=-3`, `ERR_TIMEOUT=-4`, `ERR_PARSE=-5`, `ERR_MEMORY=-6` |
| `VlmPlantStatus` | `HEALTHY=0`, `DISEASED=1`, `WEED=2`, `UNKNOWN=3` |
| `VlmAction` | `SKIP=0`, `SPRAY=1`, `LASER=2` |
| `VlmSeverity` | `NONE=0`, `LOW=1`, `MEDIUM=2`, `HIGH=3` |

**`VlmImage`** (input from MOD-02): `data` (RGB bytes), `width`/`height` (224),
`stride`, `timestamp_ms`, and the optional bypass fields `yolo_class_id`
(`-1` = unknown) and `yolo_confidence`.

**`VlmResult`** (output to MOD-04): `status`, `confidence`, `diagnosis`, `action`,
`severity`, `inference_time_ms`. It is **never `None`** — even on parse failure it
returns safe defaults (`UNKNOWN` / `0.0` / `SKIP` / `NONE`). `inference_time_ms > 0`
indicates the VLM actually ran; `0` indicates a YOLO bypass.

## Prompt and parsing

The prompt asks SmolVLM to classify the leaf and reply **only** with JSON
(`status`, `confidence`, `diagnosis`, `action`, `severity`). `vlm_parser.py`
extracts and validates that JSON, maps the string fields to the enums above
(case-insensitive via `PLANT_STATUS_MAP` / `ACTION_MAP` / `SEVERITY_MAP`), and
truncates `diagnosis` to `VLM_MAX_DIAGNOSIS_LEN - 1 = 255` chars. Malformed or
hallucinated output yields the safe-default `VlmResult` rather than an exception.

## Entry point

`vlm_analyze_plant(vlm_image) -> (VlmStatus, VlmResult)` is the single public call
used by the pipeline. `vlm_init()` loads the model once (auto-downloads to the
HuggingFace cache on first run) and `vlm_shutdown()` releases it.

## Test/dev files (not part of the runtime)

`demo.py`, `benchmark.py`, `smoke_test.py`, `test_photos.py`, `mock_vlm.py`, and
`tests/` were used during development and are not invoked by the running robot.
