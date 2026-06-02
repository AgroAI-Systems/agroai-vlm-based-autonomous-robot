# MOD-04 - Task Intelligence and Decision Engine

Central orchestration brain: mission state machine, confidence decision tree, verification loops, actuator sequencing, and field report generation.

## Authors

| Name | Student ID |
|---|---|
| Muhammed Pasa | 220104004930 |
| Fatih Mehmet Serenli | 220104004012 |

## Dependencies

| Dependency | Type | Purpose |
|---|---|---|
| `project_types.h` | project header | shared types |
| `actuator_controller.h` | component | servo/pump/laser control |
| `vlm_engine.h` | component | camera + VLM analysis integration |
| `navigator.h` | component | navigation control |
| `dashboard_server.h` | component | status push and DB logging |
| pthread (`-lpthread`) | system | background thread for state machine |

## API Summary

- `decision_init(cfg)`
- `decision_shutdown()`
- `decision_start_mission()`
- `decision_pause_mission()`
- `decision_resume_mission()`
- `decision_abort_mission()`
- `decision_get_state()`
- `decision_register_state_callback(cb)`
- `decision_evaluate(vlm_result, scan_count, result)`
- `decision_add_report_entry(entry)`
- `decision_get_report_summary(summary)`
- `decision_get_report_entry(plant_id, entry)`
- `decision_clear_report()`

## Limitations and TODOs

- Multi-frame verification currently uses 2 consecutive frames.
- Single background thread can be blocked by heavy VLM calls.
- False-positive mitigation is currently threshold-only.
- In-memory report size is limited by `MAX_PLANTS`.
