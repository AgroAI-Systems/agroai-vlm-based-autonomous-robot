# MOD-05 - Operator Dashboard and Field Report Server

Lightweight C++ server for MJPEG stream, WebSocket status, mission commands, and SQLite-backed reporting.

## Authors

| Name | Student ID |
|---|---|
| Umut Akman | 250104004997 |
| Muhammed Pasa | 220104004930 |

## Dependencies

| Dependency | Type | Purpose |
|---|---|---|
| `project_types.h` | project header | shared types |
| `vlm_engine.h` | component | frame and bbox data structures |
| cpp-httplib / Crow | external | HTTP server |
| SQLite3 (`-lsqlite3`) | external | persistence |
| OpenCV C++ | external | JPEG encoding |
| `web/` | static assets | dashboard frontend |

## API Summary

- `dashboard_init(cfg)`
- `dashboard_start()`
- `dashboard_stop()`
- `dashboard_is_running()`
- `dashboard_push_status(status)`
- `dashboard_push_vlm_result(plant_id, result)`
- `dashboard_push_frame(frame, boxes, count)`
- `dashboard_db_log_entry(entry)`
- `dashboard_db_get_entries(filter, entries, max, count)`
- `dashboard_db_get_summary(summary)`
- `dashboard_db_clear()`
- `dashboard_register_command_callback(cb)`

## Limitations and TODOs

- MJPEG bandwidth limits Wi-Fi frame rate (~10 fps).
- WebSocket supports up to 8 concurrent clients.
- SQLite single-writer contention is handled with a mutex queue.
- Frontend is static HTML/JS and may need refactor for advanced visuals.
- Robot remains autonomous even without dashboard connectivity.
