# MOD-05: Operator Dashboard and Field Report Server — Module Documentation

**Smart Agriculture / Weed Elimination Robot**
**CSE396 — Computer Engineering Project — Group 9**

---

**Module ID:** MOD-05
**Module Name:** Operator Dashboard and Field Report Server
**Version:** 0.1
**Last Updated:** 2026-03-29
**Header File:** `mod5.h`
**Main Implementation File:** `dashboard_server.cpp`
**Language:** C++ (with C-compatible header contract)

---

## Authors

| Name            | Student ID   | Role                                                    |
|-----------------|--------------|---------------------------------------------------------|
| Umut Akman      | 250104004997 | HTTP server, WebSocket status broadcast, MJPEG stream   |
| Muhammed Paşa   | 220104004930 | SQLite persistence, field report API, mission commands  |

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

MOD-05 (Operator Dashboard and Field Report Server) is the operator-facing interface for the Smart Agriculture Robot system. It runs as a lightweight HTTP/WebSocket server on the Raspberry Pi 5 and serves a browser-based dashboard that provides real-time mission monitoring and post-run field report review.

The module is strictly a **passive consumer and display layer**. It receives data pushed from other modules and does not participate in the robot's core autonomy loop. The robot continues navigating and making decisions with no degradation even if no browser client is connected or if Wi-Fi is unavailable.

The module provides three main services:

- **MJPEG live camera stream** — annotated frames from MOD-02 (Image Processing), accessible at `/stream`.
- **WebSocket status channel** — real-time robot state and VLM result updates from MOD-04 (Decision Motor), delivered to connected browser clients at `/ws`.
- **SQLite-backed field report database** — persistent storage of all plant analysis records, queryable and clearable via the dashboard or programmatic API calls.

Additionally, MOD-05 exposes **mission control endpoints** (start / pause / resume / abort) that the operator can trigger from the browser. These commands are forwarded to MOD-04 via a registered callback.

---

## 2. Responsibilities

| # | Responsibility         | Description                                                                                         |
|---|------------------------|-----------------------------------------------------------------------------------------------------|
| 1 | HTTP Server            | Serve the static dashboard frontend (HTML/JS) and handle all HTTP routes                           |
| 2 | MJPEG Stream           | Accept annotated frames from MOD-02 and serve them as a continuous MJPEG stream at `/stream`       |
| 3 | WebSocket Broadcast    | Push robot state, VLM results, and mission status to up to 8 concurrent browser clients via `/ws`  |
| 4 | Mission Command Relay  | Receive start / pause / resume / abort commands from the browser and forward them via callback      |
| 5 | SQLite Persistence     | Log every plant analysis record (`field_report_entry_t`) to `field_report.db` on disk             |
| 6 | Report Query API       | Provide programmatic access to stored entries: per-plant lookup, filtered queries, summary stats    |
| 7 | Status Display         | Render real-time runtime status (robot state, plant ID, battery level, uptime) on the dashboard    |

---

## 3. System Context

The diagram below shows MOD-05's position in the overall system architecture and its data flow connections to other modules.

```
┌───────────────────────────────────────────────────────────────────┐
│                         Raspberry Pi 5                            │
│                                                                   │
│  ┌──────────────┐   plant_detected_cb   ┌──────────────────────┐  │
│  │  MOD-01      │ ─────────────────────►│                      │  │
│  │  Pathing     │   robot_state_t       │  MOD-04              │  │
│  └──────────────┘ ─────────────────────►│  Decision Motor      │  │
│                                         │                      │  │
│  ┌──────────────┐   camera_frame_t      │  - Orchestrates      │  │
│  │  MOD-02      │ ──────────────────────┤    the pipeline      │  │
│  │  Image Proc. │   bbox_t              │  - Evaluates VLM     │  │
│  └──────────────┘ ──────────────────────┤    results           │  │
│         │                               │  - Triggers actions  │  │
│         │ dashboard_push_frame()        └──────────┬───────────┘  │
│         │ camera_frame_t + bbox_t                  │              │
│         │                        dashboard_push_status()          │
│         │                        dashboard_push_vlm_result()      │
│         │                        dashboard_db_log_entry()         │
│         ▼                                          │              │
│  ┌────────────────────────────────────────────────▼────────────┐  │
│  │                     MOD-05                                  │  │
│  │             OPERATOR DASHBOARD SERVER                       │  │
│  │                                                             │  │
│  │   ┌─────────────┐  ┌───────────────┐  ┌─────────────────┐  │  │
│  │   │ MJPEG Stream│  │  WebSocket    │  │  SQLite DB      │  │  │
│  │   │  /stream    │  │    /ws        │  │ field_report.db │  │  │
│  │   └──────┬──────┘  └───────┬───────┘  └────────┬────────┘  │  │
│  └──────────┼─────────────────┼───────────────────┼───────────┘  │
│             │                 │                   │               │
└─────────────┼─────────────────┼───────────────────┼───────────────┘
              │                 │                   │
              ▼                 ▼                   ▼
      ┌────────────────────────────────────────────────────┐
      │            Browser  (Operator Laptop / Phone)      │
      │                                                    │
      │  Live camera feed   Real-time status   Field report│
      │  + bounding boxes   + VLM results      review /    │
      │                     + mission control  export      │
      └────────────────────────────────────────────────────┘
```

**Key architectural property:** All data flows *into* MOD-05 from other modules via push calls (`dashboard_push_*`, `dashboard_db_log_entry`). MOD-05 never calls back into the robot pipeline, with the single exception of forwarding operator mission commands via the registered `dashboard_command_cb_t`.

---

## 4. Dependencies

### 4.1 Internal Module Dependencies

| Module | Dependency Type | Data Consumed |
|--------|-----------------|---------------|
| MOD-02 Image Processing | Push source | `camera_frame_t`, `bbox_t` for MJPEG stream |
| MOD-04 Decision Motor   | Push source | `dashboard_runtime_status_t`, `vlm_result_t`, `field_report_entry_t`, `robot_state_t` |

MOD-05 also includes `mod2.h` and `mod4.h` for the shared type definitions.

### 4.2 External Library Dependencies

| Library | Purpose |
|---------|---------|
| `cpp-httplib` or `Crow` | HTTP server, MJPEG multipart stream, WebSocket support |
| `SQLite3` (`-lsqlite3`) | On-disk persistence for field report entries and summary |
| `OpenCV C++` | JPEG encoding of `camera_frame_t` for MJPEG stream output |
| `pthread` (`-lpthread`) | Background server thread (HTTP and WebSocket handlers) |

### 4.3 Installation

```bash
# System packages
sudo apt-get install libsqlite3-dev libopencv-dev

# Header-only HTTP library (if using cpp-httplib)
# Place httplib.h in the project include directory
# https://github.com/yhirose/cpp-httplib
```

### 4.4 Hardware Requirements

| Component | Requirement |
|-----------|-------------|
| Network   | Wi-Fi or Ethernet for browser clients to connect to the dashboard |
| Storage   | SD card write access for `field_report.db` (SQLite file) |
| Compute   | Raspberry Pi 5 (server runs as background thread alongside the main pipeline) |

> **Note:** The dashboard is entirely optional at runtime. If no browser connects or Wi-Fi is unavailable, the robot operates without any impact on the autonomy pipeline.

---

## 5. Configuration Constants

The following compile-time constants are defined in `mod5.h`:

| Constant                   | Value              | Description                                                     |
|----------------------------|--------------------|------------------------------------------------------------------|
| `DASHBOARD_DEFAULT_PORT`   | `8080`             | TCP port on which the HTTP server listens                        |
| `DASHBOARD_WS_PATH`        | `"/ws"`            | WebSocket endpoint path for real-time status updates             |
| `DASHBOARD_STREAM_PATH`    | `"/stream"`        | HTTP endpoint path for the MJPEG camera stream                  |
| `DASHBOARD_DB_FILENAME`    | `"field_report.db"`| SQLite database filename for persistent field report storage     |
| `DASHBOARD_MAX_WS_CLIENTS` | `8`                | Maximum number of simultaneous WebSocket browser connections     |

---

## 6. Data Types Reference

### 6.1 `dashboard_error_t` — Status / Error Code

Returned by all public API functions. Callers should check this value before using output parameters.

| Value                       | Integer | Meaning                                              |
|-----------------------------|---------|------------------------------------------------------|
| `DASHBOARD_OK`              | `0`     | Operation succeeded                                  |
| `DASHBOARD_ERR_INIT`        | `-1`    | Server failed to initialize (port bind, DB open)     |
| `DASHBOARD_ERR_PORT`        | `-2`    | TCP port already in use or insufficient permission   |
| `DASHBOARD_ERR_DB`          | `-3`    | SQLite database error (open, write, or query failure)|
| `DASHBOARD_ERR_STREAM`      | `-4`    | MJPEG stream encoding or push error                  |
| `DASHBOARD_ERR_NOT_RUNNING` | `-5`    | Function called before `dashboard_start()` succeeded |

### 6.2 `dashboard_runtime_status_t` — Robot Runtime Status

Pushed by MOD-04 on every state transition and broadcast to all connected WebSocket clients.

```c
typedef struct {
    robot_state_t current_state;     // Current robot state enum (from mod4.h)
    uint8_t       current_plant_id;  // 1-based ID of the plant currently being processed
    bool          mission_active;    // true if a mission is in progress
    float         battery_percent;   // Battery level 0.0–100.0 %
    uint32_t      uptime_ms;         // Milliseconds since dashboard_start()
} dashboard_runtime_status_t;
```

### 6.3 `dashboard_config_t` — Initialization Configuration

Passed once to `dashboard_init()`. All fields must be set by MOD-04 (or the main application) before calling `dashboard_init()`.

```c
typedef struct {
    uint16_t    port;          // Listening port; use DASHBOARD_DEFAULT_PORT (8080)
    const char *web_root;      // Path to static frontend files (HTML/JS/CSS)
    const char *db_path;       // Path for SQLite file; use DASHBOARD_DB_FILENAME
    bool        enable_stream; // Enable MJPEG stream endpoint at /stream
} dashboard_config_t;
```

### 6.4 `db_query_filter_t` — Database Query Filter

Passed to `dashboard_db_get_entries()` to retrieve a filtered subset of stored records.

```c
typedef struct {
    plant_status_t status_filter;  // Filter by classification; use -1 (or equivalent) for all
    uint8_t        limit;          // Maximum number of entries to return (0 = no limit)
    bool           newest_first;   // true = descending by timestamp; false = ascending
} db_query_filter_t;
```

### 6.5 `dashboard_command_cb_t` — Operator Command Callback

Registered by MOD-04 via `dashboard_register_command_callback()`. Called when the operator sends a mission command from the browser dashboard (start / pause / resume / abort).

```c
typedef void (*dashboard_command_cb_t)(const char *command);
```

The `command` string will be one of: `"start"`, `"pause"`, `"resume"`, `"abort"`.

---

## 7. API Reference

### 7.1 `dashboard_init()`

```c
dashboard_error_t dashboard_init(const dashboard_config_t *config);
```

Initializes the dashboard server: opens the SQLite database file (creating it if it does not exist), sets up HTTP routes, initializes the MJPEG stream buffer, and prepares the WebSocket broadcast list. Does **not** start the HTTP listener thread — call `dashboard_start()` after initialization.

| Parameter | Direction | Description                                 |
|-----------|-----------|---------------------------------------------|
| `config`  | in        | Pointer to a fully populated `dashboard_config_t`. Must not be NULL. |

**Returns:** `DASHBOARD_OK` on success; `DASHBOARD_ERR_INIT`, `DASHBOARD_ERR_PORT`, or `DASHBOARD_ERR_DB` on failure.

**Must be called once** before any other dashboard function. Calling any other function before `dashboard_init()` returns `DASHBOARD_ERR_NOT_RUNNING`.

---

### 7.2 `dashboard_start()`

```c
dashboard_error_t dashboard_start(void);
```

Starts the background HTTP/WebSocket listener thread. After this call returns `DASHBOARD_OK`, the dashboard is accessible at `http://<pi-ip>:8080`.

**Returns:** `DASHBOARD_OK` on success; `DASHBOARD_ERR_INIT` if initialization was not completed.

---

### 7.3 `dashboard_stop()`

```c
dashboard_error_t dashboard_stop(void);
```

Signals the background listener thread to shut down, closes all active WebSocket connections, and closes the SQLite database cleanly. Blocks until the thread exits.

**Returns:** `DASHBOARD_OK` on success; `DASHBOARD_ERR_NOT_RUNNING` if the server was not running.

---

### 7.4 `dashboard_is_running()`

```c
bool dashboard_is_running(void);
```

Returns `true` if the HTTP server background thread is active. Used by MOD-04 to guard push calls.

---

### 7.5 `dashboard_push_status()`

```c
dashboard_error_t dashboard_push_status(const dashboard_runtime_status_t *status);
```

Serializes `status` to JSON and broadcasts it to all connected WebSocket clients at `/ws`. Called by MOD-04 on every `robot_state_t` transition.

| Parameter | Direction | Description                                      |
|-----------|-----------|--------------------------------------------------|
| `status`  | in        | Pointer to a populated `dashboard_runtime_status_t`. Must not be NULL. |

**Returns:** `DASHBOARD_OK`; `DASHBOARD_ERR_NOT_RUNNING` if server is stopped.

**Frequency:** Once per robot state transition (event-driven).

---

### 7.6 `dashboard_push_vlm_result()`

```c
dashboard_error_t dashboard_push_vlm_result(uint8_t plant_id,
                                            const vlm_result_t *result);
```

Broadcasts the VLM analysis result for a specific plant to all connected WebSocket clients. Called by MOD-04 after each VLM inference (including re-evaluations). Displays classification, confidence, diagnosis, action, and severity on the live dashboard panel.

| Parameter  | Direction | Description                                        |
|------------|-----------|----------------------------------------------------|
| `plant_id` | in        | 1-based plant identifier for the current stop      |
| `result`   | in        | Pointer to the `vlm_result_t` from MOD-03. Must not be NULL. |

**Returns:** `DASHBOARD_OK`; `DASHBOARD_ERR_NOT_RUNNING` if server is stopped.

---

### 7.7 `dashboard_push_frame()`

```c
dashboard_error_t dashboard_push_frame(const camera_frame_t *frame,
                                       const bbox_t *overlay_boxes,
                                       uint8_t box_count);
```

Accepts an annotated full-resolution frame from MOD-02, JPEG-encodes it using OpenCV, and pushes it as the next MJPEG boundary to all clients connected to `/stream`. `overlay_boxes` allows the caller to specify additional bounding boxes for dashboard-side rendering if not already drawn on the frame.

| Parameter      | Direction | Description                                                     |
|----------------|-----------|-----------------------------------------------------------------|
| `frame`        | in        | Pointer to the annotated `camera_frame_t` from MOD-02           |
| `overlay_boxes`| in        | Array of `bbox_t` for overlay rendering; may be NULL if none    |
| `box_count`    | in        | Number of entries in `overlay_boxes`; 0 if `overlay_boxes` is NULL |

**Returns:** `DASHBOARD_OK`; `DASHBOARD_ERR_STREAM` on JPEG encode failure; `DASHBOARD_ERR_NOT_RUNNING` if server is stopped.

**Frequency:** Once per detection cycle (~once per plant stop). Not called at continuous video rate.

---

### 7.8 `dashboard_db_log_entry()`

```c
dashboard_error_t dashboard_db_log_entry(const field_report_entry_t *entry);
```

Writes one plant analysis record to the SQLite database. Called by MOD-04 at the end of each plant evaluation (LOG state), regardless of the action taken.

| Parameter | Direction | Description                                         |
|-----------|-----------|-----------------------------------------------------|
| `entry`   | in        | Pointer to a fully populated `field_report_entry_t` |

**Returns:** `DASHBOARD_OK`; `DASHBOARD_ERR_DB` on SQLite write failure.

The entry includes: `plant_id`, `timestamp_ms`, classification, action taken, confidence score, diagnosis text, inference time, scan count, and an `acted` flag indicating whether an actuator was triggered.

---

### 7.9 `dashboard_db_get_entries()`

```c
dashboard_error_t dashboard_db_get_entries(const db_query_filter_t *filter,
                                           field_report_entry_t *entries,
                                           uint8_t max_entries,
                                           uint8_t *out_count);
```

Queries the SQLite database and returns up to `max_entries` matching records into the caller-provided `entries` array. The number of records actually written is returned via `out_count`.

| Parameter     | Direction | Description                                                         |
|---------------|-----------|---------------------------------------------------------------------|
| `filter`      | in        | Query filter (classification type, limit, sort order). May be NULL for all records. |
| `entries`     | out       | Caller-allocated array of `field_report_entry_t`, size ≥ `max_entries` |
| `max_entries` | in        | Upper bound on records to return                                    |
| `out_count`   | out       | Number of records written to `entries`                              |

**Returns:** `DASHBOARD_OK`; `DASHBOARD_ERR_DB` on query failure; `DASHBOARD_ERR_INVALID_ARG` if `entries` or `out_count` is NULL.

---

### 7.10 `dashboard_db_get_summary()`

```c
dashboard_error_t dashboard_db_get_summary(field_report_summary_t *summary);
```

Computes and returns aggregate statistics over all stored field report entries: total plant count, healthy/diseased/weed/unknown counts, and acted/skipped counts.

| Parameter | Direction | Description                                           |
|-----------|-----------|-------------------------------------------------------|
| `summary` | out       | Pointer to a `field_report_summary_t` to populate     |

**Returns:** `DASHBOARD_OK`; `DASHBOARD_ERR_DB` on query failure.

---

### 7.11 `dashboard_db_clear()`

```c
dashboard_error_t dashboard_db_clear(void);
```

Deletes all records from the SQLite field report table. Used by the operator to reset the database before a new run. Irreversible — no confirmation is required by the API.

**Returns:** `DASHBOARD_OK`; `DASHBOARD_ERR_DB` on failure.

---

### 7.12 `dashboard_register_command_callback()`

```c
dashboard_error_t dashboard_register_command_callback(dashboard_command_cb_t cb);
```

Registers the function that MOD-05 will call when the operator sends a mission command (start / pause / resume / abort) from the browser dashboard. MOD-04 registers its own mission-control handler here during initialization.

| Parameter | Direction | Description                                       |
|-----------|-----------|---------------------------------------------------|
| `cb`      | in        | Pointer to the callback function; must not be NULL|

**Returns:** `DASHBOARD_OK`.

Only one callback can be registered at a time. Registering a new callback replaces the previous one.

---

## 8. Inter-Module Communication

### 8.1 Summary Table

| From              | To       | Function Called                 | Data Type                                  | Trigger                          |
|-------------------|----------|---------------------------------|--------------------------------------------|----------------------------------|
| MOD-02 Image Proc.| MOD-05   | `dashboard_push_frame()`        | `camera_frame_t` + `bbox_t`                | Once per plant detection cycle   |
| MOD-04 Decision   | MOD-05   | `dashboard_push_status()`       | `dashboard_runtime_status_t`               | Every `robot_state_t` transition |
| MOD-04 Decision   | MOD-05   | `dashboard_push_vlm_result()`   | `uint8_t plant_id` + `vlm_result_t`        | After each VLM inference         |
| MOD-04 Decision   | MOD-05   | `dashboard_db_log_entry()`      | `field_report_entry_t`                     | Once per plant, at LOG state     |
| MOD-05 (browser)  | MOD-04   | Registered `dashboard_command_cb_t` | `const char *command`                  | Operator button press in browser |

### 8.2 MOD-02 → MOD-05: Annotated Camera Feed

MOD-02 calls `dashboard_push_frame()` after each YOLO detection cycle, passing the full 1280×960 annotated frame (with bounding boxes drawn in green) and the associated `bbox_t` struct. MOD-05 JPEG-encodes the frame and writes it as the next MJPEG boundary. This call is made once per plant stop — not at a continuous video rate — because YOLO inference (~1–3 s) is the bottleneck. MOD-05 does not retain a reference to the frame after encoding.

**Data exchanged:** `camera_frame_t` (annotated full frame) + `bbox_t` array + `box_count`.

### 8.3 MOD-04 → MOD-05: Robot State Update

MOD-04 calls `dashboard_push_status()` on every state machine transition (IDLE → NAVIGATE → SCAN → ANALYZE → DECIDE → ACT → LOG → NAVIGATE, etc.). MOD-05 serializes the `dashboard_runtime_status_t` struct to JSON and broadcasts it to all connected WebSocket clients at `/ws`, so the operator can observe the robot's progress in real time.

**Data exchanged:** `dashboard_runtime_status_t` (state, plant ID, mission active, battery, uptime).

### 8.4 MOD-04 → MOD-05: VLM Result Display

After each VLM inference (including mid-confidence re-evaluations), MOD-04 calls `dashboard_push_vlm_result()` with the plant ID and the `vlm_result_t` from MOD-03. MOD-05 broadcasts this to WebSocket clients so the operator can see the classification, confidence score, diagnosis text, recommended action, and severity level in near-real time.

**Data exchanged:** `uint8_t plant_id` + `vlm_result_t` (status, confidence, diagnosis, action, severity).

### 8.5 MOD-04 → MOD-05: Field Report Log Entry

At the conclusion of each plant evaluation (LOG state), MOD-04 calls `dashboard_db_log_entry()` with the fully populated `field_report_entry_t`. MOD-05 writes this record to the SQLite database. The entry persists across reboots, allowing post-run review from the dashboard's report page.

**Data exchanged:** `field_report_entry_t` (plant ID, timestamp, classification, action, confidence, diagnosis, inference time, scan count, acted flag).

### 8.6 MOD-05 → MOD-04: Operator Mission Command

When the operator presses a mission control button in the browser (Start / Pause / Resume / Abort), MOD-05 receives the HTTP request and calls the registered `dashboard_command_cb_t` with the command string. MOD-04 registers this callback during its initialization, so MOD-05 effectively relays operator intent into the decision engine without directly calling any MOD-04 functions.

**Data exchanged:** `const char *command` — one of `"start"`, `"pause"`, `"resume"`, `"abort"`.

---

## 9. Processing Pipeline

### 9.1 Startup Sequence

```
dashboard_init(cfg) called by MOD-04 (main application init)
          │
          ▼
┌─────────────────────────┐
│  1. OPEN DATABASE       │
│  sqlite3_open(db_path)  │
│  CREATE TABLE IF NOT    │
│  EXISTS field_report    │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  2. CONFIGURE HTTP      │
│  Register routes:       │
│  GET  /           → UI  │
│  GET  /stream     → MJPEG│
│  GET  /ws         → WS  │
│  POST /command    → cmd │
│  GET  /api/report → DB  │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  3. INIT STREAM BUFFER  │
│  Allocate JPEG frame    │
│  mutex, broadcast queue │
└────────────┬────────────┘
             │
             ▼
     dashboard_start()
             │
             ▼
┌─────────────────────────┐
│  4. START LISTENER      │
│  Spawn background thread│
│  Server listens on :8080│
└─────────────────────────┘
          Ready — operator can connect browser
```

### 9.2 Per-Plant Data Flow (Runtime)

```
  MOD-01 detects plant marker
          │
          ▼
  MOD-04 transitions to SCAN
          │
          ├──► dashboard_push_status()   ──► WebSocket broadcast to browser
          │
  MOD-02 captures and runs YOLO
          │
          ├──► dashboard_push_frame()    ──► JPEG encode → MJPEG stream → browser
          │
  MOD-03 runs VLM inference
          │
  MOD-04 evaluates result (DECIDE state)
          │
          ├──► dashboard_push_status()   ──► WebSocket broadcast (state = DECIDE)
          ├──► dashboard_push_vlm_result() ► WebSocket broadcast (classification + confidence)
          │
  MOD-04 actuates (ACT state) or skips
          │
          ├──► dashboard_push_status()   ──► WebSocket broadcast (state = ACT or NAVIGATE)
          │
  MOD-04 logs entry (LOG state)
          │
          └──► dashboard_db_log_entry()  ──► SQLite INSERT → persistent storage
```

### 9.3 MJPEG Stream Encoding

When `dashboard_push_frame()` is called:

```
camera_frame_t (RGB, 1280×960)
          │
          ▼
   OpenCV imencode(".jpg", frame)  →  JPEG buffer (~30–80 KB typical)
          │
          ▼
   Write MJPEG multipart boundary to all active /stream connections:
   --boundary\r\n
   Content-Type: image/jpeg\r\n
   Content-Length: <N>\r\n
   \r\n
   <JPEG bytes>
   \r\n
```

Frame rate is not fixed — one frame is pushed per plant detection cycle (≈ once every 5–30 seconds depending on VLM latency), not at a continuous video rate.

---

## 10. Error Handling

### 10.1 Status Code Decision Table

| Status Code              | Cause                                               | Recommended Action                                              |
|--------------------------|-----------------------------------------------------|-----------------------------------------------------------------|
| `DASHBOARD_OK`           | Operation succeeded                                 | Continue normally                                               |
| `DASHBOARD_ERR_INIT`     | Server setup failed (port bind, DB open, etc.)      | Log error; robot continues autonomously without dashboard       |
| `DASHBOARD_ERR_PORT`     | Port 8080 already in use                            | Kill conflicting process or change `port` in `dashboard_config_t` |
| `DASHBOARD_ERR_DB`       | SQLite read/write failure                           | Check SD card health; data for that entry may be lost           |
| `DASHBOARD_ERR_STREAM`   | JPEG encoding failed on a frame                     | Skip that frame; pipeline continues unaffected                  |
| `DASHBOARD_ERR_NOT_RUNNING` | Push called before `dashboard_start()` succeeded | Ensure `dashboard_init()` and `dashboard_start()` succeeded first |

### 10.2 Error Propagation Strategy

All public functions return `dashboard_error_t`. MOD-04 should check the return value of each push call during development and log failures. In production, dashboard errors are **non-fatal** — the autonomy pipeline must not halt due to a dashboard error.

Example usage:

```c
dashboard_error_t err = dashboard_push_status(&status);
if (err != DASHBOARD_OK) {
    // Log the error — do NOT abort the mission
    fprintf(stderr, "Dashboard push failed: %d\n", err);
}
```

### 10.3 SQLite Write Contention

Multiple calls to `dashboard_db_log_entry()` could occur in rapid succession if the evaluation loop runs faster than SQLite can commit. MOD-05 handles this internally with a mutex-guarded write queue. Callers do not need to serialize calls themselves.

---

## 11. Known Risks and Open Questions

| # | Risk / Issue | Severity | Status | Mitigation |
|---|-------------|----------|--------|------------|
| 1 | **MJPEG bandwidth limits frame rate**: at ~30–80 KB per frame, continuous streaming over Wi-Fi is ~10 fps theoretical maximum; actual rate is much lower because frames are only pushed once per plant stop | Low | By design | Frame rate is driven by pipeline latency, not bandwidth; this is acceptable for the demo use case |
| 2 | **WebSocket client cap at 8**: more than 8 simultaneous connections will be refused | Low | By design | Only one operator is expected during demo; cap can be raised via `DASHBOARD_MAX_WS_CLIENTS` if needed |
| 3 | **SQLite single-writer contention**: concurrent log calls from fast evaluation loops could queue up | Low | Mitigated | Internal mutex queue serializes writes; test under worst-case re-evaluation timing |
| 4 | **Frontend is static HTML/JS**: no reactive framework; updating the UI requires manual DOM manipulation | Low | Open | Acceptable for the class demo; a refactor to React or similar would be needed for production |
| 5 | **No authentication or access control**: the dashboard HTTP and WebSocket endpoints are open to anyone on the same network | Medium | Open | Acceptable for isolated lab/demo Wi-Fi; do not connect to a shared or public network |
| 6 | **Pi power spikes from YOLO + VLM inference**: CPU load peaks may cause voltage drops affecting the HTTP server thread | Medium | Open | Use a dedicated 5 V / 5 A regulator for the Pi; test stability under full pipeline load |
| 7 | **Database persists across runs**: `field_report.db` accumulates across multiple runs unless `dashboard_db_clear()` is called | Low | Open | Operator must manually clear the database before each new run; add a prominent "Clear DB" button on the dashboard |
| 8 | **No graceful reconnect for WebSocket clients**: if the Pi's Wi-Fi drops, browser clients must manually reload | Low | Open | Add client-side JavaScript auto-reconnect logic in the frontend |

---

## 12. References

| Resource | URL |
|----------|-----|
| cpp-httplib (HTTP/WebSocket server) | https://github.com/yhirose/cpp-httplib |
| SQLite3 Documentation | https://www.sqlite.org/docs.html |
| OpenCV JPEG Encoding (`imencode`) | https://docs.opencv.org/4.x/d4/da8/group__imgcodecs.html |
| Raspberry Pi 5 Documentation | https://www.raspberrypi.com/documentation/ |
| MJPEG Multipart Stream Format | https://www.w3.org/Protocols/rfc1341/7_2_Multipart.html |

---

*Document prepared for CSE396 Computer Engineering Project — Group 9*
*Smart Agriculture / Weed Elimination Robot — Autonomous On-Device Plant Inspection and Precision Actuation System*
