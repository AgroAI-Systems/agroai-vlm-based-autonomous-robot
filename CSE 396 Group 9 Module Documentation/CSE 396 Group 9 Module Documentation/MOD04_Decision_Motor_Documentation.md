# MOD-04: Decision Motor Module Documentation

**Smart Agriculture / Weed Elimination Robot**  
**CSE396 - Computer Engineering Project - Group 9**

---

**Module ID:** MOD-04  
**Module Name:** Decision Motor  
**Version:** 0.1  
**Last Updated:** 2026-04-17  
**Header File:** `mod4.h`  
**Module Summary File:** `src/decision_motor/mod4.md`  
**Language:** C/C++ style interface for mission logic and reporting

---

## Authors

| Name | Role |
|------|------|
| Muhammed Paşa 220104004930 | Decision logic, state design, reporting |
| Fatih Mehmet Serenli 220104004012 | Integration support, actuator workflow |

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
9. [Decision Pipeline](#9-decision-pipeline)
10. [Error Handling](#10-error-handling)
11. [Known Risks and Open Questions](#11-known-risks-and-open-questions)
12. [References](#12-references)

---

## 1. Module Overview

MOD-04 (Decision Motor) is the mission-level decision module of the robot. It sits between perception and physical action. After the robot stops at a plant, this module evaluates the plant analysis result, applies the confidence policy, decides whether to `SKIP`, `SPRAY`, or `LASER`, stores the decision in a field report entry, and coordinates mission-state progression.

The module is responsible for the logical part of the "sense -> reason -> act" loop:

- receives plant analysis output from MOD-03
- uses plant localization data from MOD-02 for targeting
- decides the final action using confidence thresholds
- coordinates actuation through the low-level hardware control layer
- logs results and exposes state information to MOD-05

The public interface defined in `mod4.h` focuses on:

- mission lifecycle control
- decision evaluation
- state query and callbacks
- field report storage and summary access

The current project architecture places high-level decision making on the Raspberry Pi. Low-level hardware control is planned to run through Arduino-based controller hardware. Depending on pin availability and final electrical design, the robot may use one Arduino shared across subsystems or two separate Arduinos. That hardware split does not change the public MOD-04 decision API, but it does affect the implementation boundary below this module.

---

## 2. Responsibilities

| # | Responsibility | Description |
|---|----------------|-------------|
| 1 | Mission State Control | Maintain robot mission states such as `IDLE`, `NAVIGATE`, `SCAN`, `ANALYZE`, `DECIDE`, `ACT`, and `LOG` |
| 2 | Confidence Evaluation | Classify VLM confidence into high, medium, or low confidence tiers |
| 3 | Action Selection | Convert plant classification and confidence into `ACTION_SKIP`, `ACTION_SPRAY`, or `ACTION_LASER` |
| 4 | Re-evaluation Control | Support a retry path for medium-confidence plant analysis |
| 5 | Targeting Support | Use plant bounding-box center coordinates to derive servo aiming targets |
| 6 | Actuation Coordination | Send high-level spray or laser commands to the low-level hardware controller |
| 7 | Reporting | Store per-plant decisions in report entries and maintain report summary data |
| 8 | GUI Integration | Expose mission state and decision outputs to the dashboard module |
| 9 | Navigation Handshake | Keep the robot stopped during analysis/action and allow resume only after cycle completion |

---

## 3. System Context

The diagram below shows MOD-04's position in the overall robot architecture.

```text
                  plant stop event / resume handshake
      +-----------------------------------------------+
      |                                               |
      v                                               |
+-------------+                               +---------------+
|   MOD-01    |                               |    MOD-05     |
|   Pathing   |<----------------------------->|  Dashboard    |
|             |   mission state, logs, view   |                            nn                   jimnjknonjoio          |
+------+------+\                               +-------+-------+
       |                                               ^
       | plant detected                                |
       v                                               |
+------+-----------------------------------------------+------+
|                     MOD-04 Decision Motor                   |
|                                                            |
| - state machine                                            |
| - confidence policy                                        |
| - decision evaluation                                      |
| - report generation                                        |
| - actuation coordination                                   |
+------+--------------------------+---------------------+----+
       |                          |                     |
       | bbox / ROI request       | VLM result          | high-level
       v                          v                     | actuation commands
+------+-------+          +-------+------+             v
|   MOD-02     |          |    MOD-03    |     +---------------+
| Image Proc.  |--------->|      VLM     |     | Arduino HW    |
|              |   ROI    |              |     | Controller(s) |
+--------------+          +--------------+     +-------+-------+
                                                        |
                                                        v
                                              servos / pump / laser
```

### Hardware Interface

| Interface | Connection | Notes |
|-----------|------------|-------|
| Pi -> Arduino | USB serial or UART | Planned control path for low-level actuator and timing control |
| Arduino -> Servo pan/tilt | PWM | Aiming control for spray/laser targeting |
| Arduino -> Pump relay | Digital output | Spray activation |
| Arduino -> Laser relay/driver | Digital output | Weed elimination simulation |

**Current design note:** Arduino usage has been decided, but whether the project uses one shared Arduino or two separate Arduino boards is still open and depends on final pin budgeting and hardware integration.

---

## 4. Dependencies

### 4.1 Software / Module Dependencies

| Dependency | Type | Purpose |
|------------|------|---------|
| `mod3.h` | project header | Provides `vlm_result_t` used by `decision_evaluate()` |
| MOD-01 Pathing | peer module | Provides plant-stop trigger and navigation resume handshake |
| MOD-02 Image Processing | peer module | Provides bounding box coordinates and ROI data |
| MOD-03 VLM | peer module | Provides semantic plant analysis result |
| MOD-05 GUI | peer module | Receives runtime state and field-report information |
| pthread / task thread | system | Optional background execution for state machine and coordination logic |

### 4.2 Hardware / Integration Dependencies

| Dependency | Purpose |
|------------|---------|
| Arduino-based hardware controller | Low-level servo, pump, and laser control |
| Servo pan-tilt mechanism | Aim actuator output toward the detected plant |
| Water pump | Spray action for healthy or diseased plants |
| Laser module | Laser action for weeds |

### 4.3 Ownership Boundary

MOD-04 is a high-level decision module. It should not own raw GPIO toggling or PWM generation directly in the final architecture. Instead, it should produce high-level control intent such as:

- target pan angle
- target tilt angle
- spray duration
- laser duration
- start / stop / abort commands

The Arduino layer then executes those commands on the hardware side.

---

## 5. Configuration Constants

The following compile-time constants are defined in `mod4.h`:

| Constant | Value | Description |
|----------|-------|-------------|
| `MAX_PLANTS` | `255` | Maximum number of plants tracked in the in-memory report |
| `CONFIDENCE_HIGH` | `0.70f` | Threshold for immediate action |
| `CONFIDENCE_MEDIUM` | `0.50f` | Threshold for retry vs skip decision |
| `DECISION_MAX_RESCANS` | `2` | Maximum scan/evaluation count allowed by the current draft header |

**Interpretation note:** The team uses a "re-evaluate once" policy in the design documents. The value `DECISION_MAX_RESCANS = 2` should therefore be interpreted carefully during implementation and presentation as total evaluations, not unlimited retries.

---

## 6. Data Types Reference

### 6.1 `robot_state_t` - Mission State

Represents the current robot mission state as tracked by the Decision Motor.

```c
typedef enum {
    ROBOT_STATE_IDLE = 0,
    ROBOT_STATE_NAVIGATE,
    ROBOT_STATE_APPROACH,
    ROBOT_STATE_SCAN,
    ROBOT_STATE_ANALYZE,
    ROBOT_STATE_DECIDE,
    ROBOT_STATE_ACT,
    ROBOT_STATE_LOG,
    ROBOT_STATE_PAUSED,
    ROBOT_STATE_ABORTED,
    ROBOT_STATE_ERROR
} robot_state_t;
```

**Usage:** Used by lifecycle functions, `decision_get_state()`, and `decision_state_cb_t` to expose runtime state to other modules such as MOD-05.

---

### 6.2 `plant_status_t` - Plant Classification

Represents the final plant class handled by MOD-04.

```c
typedef enum {
    PLANT_STATUS_HEALTHY = 0,
    PLANT_STATUS_DISEASED,
    PLANT_STATUS_WEED,
    PLANT_STATUS_UNKNOWN
} plant_status_t;
```

**Usage:** Stored in decision results and field-report entries.

---

### 6.3 `action_type_t` - Final Action

Represents the action chosen by the Decision Motor.

```c
typedef enum {
    ACTION_SKIP = 0,
    ACTION_SPRAY,
    ACTION_LASER
} action_type_t;
```

**Usage:** Maps decision logic to physical behavior. In the final system, this becomes a high-level command sent to the Arduino hardware controller.

---

### 6.4 `servo_angles_t` - Target Angles

Stores the pan and tilt angles used for actuation targeting.

```c
typedef struct {
    float pan_deg;
    float tilt_deg;
} servo_angles_t;
```

**Usage:** Included in `decision_result_t` as the final targeting output of the module.

---

### 6.5 `decision_status_t` - Module Status Codes

Return status codes for MOD-04 public functions.

```c
typedef enum {
    DECISION_OK         =  0,
    DECISION_ERR_INIT   = -1,
    DECISION_ERR_STATE  = -2,
    DECISION_ERR_MODULE = -3,
    DECISION_ERR_ABORT  = -4,
    DECISION_ERR_FULL   = -5
} decision_status_t;
```

**Usage:** Returned by lifecycle, evaluation, and reporting functions.

---

### 6.6 `decision_result_t` - Decision Output

Stores the output of one decision evaluation.

```c
typedef struct {
    plant_status_t classification;
    action_type_t  decided_action;
    float          final_confidence;
    uint8_t        scan_count;
    servo_angles_t target_angles;
} decision_result_t;
```

**Usage:** Passed to callbacks and used as the final logical result of a plant inspection cycle.

---

### 6.7 `field_report_entry_t` - Per-Plant Log Entry

Stores the recorded information for one plant interaction.

```c
typedef struct {
    uint8_t        plant_id;
    uint32_t       timestamp_ms;
    plant_status_t classification;
    action_type_t  action;
    float          confidence;
    char           diagnosis[256];
    uint32_t       inference_time_ms;
    uint8_t        scan_count;
    bool           acted;
} field_report_entry_t;
```

**Usage:** Stored internally by MOD-04 and forwarded to MOD-05 for display or persistence.

---

### 6.8 `field_report_summary_t` - Summary Statistics

Stores mission-level report totals.

```c
typedef struct {
    uint16_t total_plants;
    uint16_t healthy_count;
    uint16_t diseased_count;
    uint16_t weed_count;
    uint16_t unknown_count;
    uint16_t acted_count;
    uint16_t skipped_count;
} field_report_summary_t;
```

**Usage:** Returned by `decision_get_report_summary()` for post-run reporting.

---

### 6.9 `mission_config_t` - Runtime Configuration

Configures Decision Motor thresholds and actuation durations.

```c
typedef struct {
    float    conf_high;
    float    conf_medium;
    uint8_t  max_rescans;
    uint32_t pump_duration_ms;
    uint32_t laser_duration_ms;
} mission_config_t;
```

**Usage:** Passed to `decision_init()` to override default decision thresholds and output timing.

---

### 6.10 `decision_state_cb_t` - State Callback

Callback function type for notifying other parts of the system about state changes.

```c
typedef void (*decision_state_cb_t)(robot_state_t new_state,
                                    uint8_t plant_id,
                                    const decision_result_t *result);
```

**Usage:** Registered via `decision_register_state_callback()` so the GUI or orchestrator can react to state transitions.

---

## 7. API Reference

### 7.1 `decision_init`

```c
decision_status_t decision_init(const mission_config_t *config);
```

**Description:** Initializes the Decision Motor configuration, internal state, and report storage. This function must be called before other MOD-04 operations.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `config` | `const mission_config_t *` | Mission thresholds and actuator timing. Pass `NULL` to use module defaults if supported by implementation. |

**Returns:** `DECISION_OK` on success, `DECISION_ERR_INIT` on initialization failure.

---

### 7.2 `decision_shutdown`

```c
decision_status_t decision_shutdown(void);
```

**Description:** Shuts down the Decision Motor and releases internal resources.

---

### 7.3 `decision_start_mission`

```c
decision_status_t decision_start_mission(void);
```

**Description:** Transitions the mission from idle state into active mission flow.

---

### 7.4 `decision_pause_mission`

```c
decision_status_t decision_pause_mission(void);
```

**Description:** Pauses the mission state machine.

---

### 7.5 `decision_resume_mission`

```c
decision_status_t decision_resume_mission(void);
```

**Description:** Resumes the mission after a pause.

---

### 7.6 `decision_abort_mission`

```c
decision_status_t decision_abort_mission(void);
```

**Description:** Aborts the current mission. In the final architecture this must also trigger a safe stop command toward the Arduino hardware controller.

---

### 7.7 `decision_get_state`

```c
robot_state_t decision_get_state(void);
```

**Description:** Returns the current mission state tracked by MOD-04.

---

### 7.8 `decision_register_state_callback`

```c
decision_status_t decision_register_state_callback(decision_state_cb_t cb);
```

**Description:** Registers a callback for state changes and completed decisions.

---

### 7.9 `decision_evaluate`

```c
decision_status_t decision_evaluate(const vlm_result_t *vlm_result,
                                    uint8_t scan_count,
                                    decision_result_t *result);
```

**Description:** Evaluates one VLM result using the confidence policy and produces the final `decision_result_t`.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `vlm_result` | `const vlm_result_t *` | Plant analysis result from MOD-03 |
| `scan_count` | `uint8_t` | Current evaluation count for the plant |
| `result` | `decision_result_t *` | Output decision structure |

**Returns:** `DECISION_OK` on success, or a relevant MOD-04 error code on invalid state/module failure.

---

### 7.10 `decision_add_report_entry`

```c
decision_status_t decision_add_report_entry(const field_report_entry_t *entry);
```

**Description:** Adds one plant interaction record to the internal field report.

---

### 7.11 `decision_get_report_summary`

```c
decision_status_t decision_get_report_summary(field_report_summary_t *summary);
```

**Description:** Returns aggregate counts for mission reporting.

---

### 7.12 `decision_get_report_entry`

```c
decision_status_t decision_get_report_entry(uint8_t plant_id,
                                            field_report_entry_t *entry);
```

**Description:** Returns the report entry for a specific plant identifier.

---

### 7.13 `decision_clear_report`

```c
decision_status_t decision_clear_report(void);
```

**Description:** Clears all stored field-report records and resets summary state.

---

## 8. Inter-Module Communication

### 8.1 Communication Summary Table

| Direction | Peer Module / Layer | Data / Signal | Type |
|-----------|---------------------|---------------|------|
| MOD-01 -> MOD-04 | Pathing | Plant-stop event | callback / event |
| MOD-04 -> MOD-01 | Pathing | Resume navigation signal | function call / control command |
| MOD-02 -> MOD-04 | Image Processing | `bbox_t`, detection result, ROI crop | structured data |
| MOD-04 -> MOD-03 | VLM | ROI image for analysis | function call |
| MOD-03 -> MOD-04 | VLM | `vlm_result_t` | structured result |
| MOD-04 -> Arduino | Hardware controller | aim / spray / laser / stop commands | serial or control protocol |
| MOD-04 -> MOD-05 | GUI | state changes, decision result, report data | callback / API calls |

### 8.2 Detailed Communication Descriptions

#### MOD-01 -> MOD-04: Plant Stop Trigger

When the Pathing module detects a plant marker, it stops robot motion and triggers the next stage of the mission flow. MOD-04 then starts the scan / analyze / decide / act cycle.

#### MOD-02 -> MOD-04: Localization Data

MOD-04 uses the plant detection output from MOD-02, especially the bounding-box center, to derive servo targeting coordinates. This targeting information becomes part of `decision_result_t` as `target_angles`.

#### MOD-04 <-> MOD-03: Plant Analysis

MOD-04 coordinates plant analysis by sending the cropped ROI to MOD-03 and receiving a `vlm_result_t` back. The `decision_evaluate()` function uses that result as its primary semantic input.

#### MOD-04 -> Arduino Hardware Controller

After the decision is made, MOD-04 sends high-level commands to the Arduino control layer. Example command classes include:

- move aim to pan/tilt target
- activate spray for configured duration
- activate laser for configured duration
- abort and stop all active outputs

This keeps MOD-04 independent from raw pin-level timing.

#### MOD-04 -> MOD-05: Monitoring And Reporting

MOD-04 exposes state transitions and final decision outputs to the GUI/dashboard layer so the operator can monitor mission progress and inspect plant decisions after the run.

---

## 9. Decision Pipeline

The following diagram shows the logical processing sequence of MOD-04 for one plant stop.

```text
1. Pathing stops robot at plant marker
2. Image Processing provides plant localization
3. VLM analyzes the plant ROI
4. Decision Motor evaluates result
5. If confidence >= 0.70 -> act immediately
6. If 0.50 <= confidence < 0.70 -> re-evaluate once
7. If confidence < 0.50 -> skip actuation
8. Compute target pan/tilt angles
9. Send high-level actuation command to Arduino
10. Store field-report entry
11. Publish state / result to GUI
12. Resume navigation
```

### Decision Logic

| Confidence Range | Tier | Expected Behavior |
|------------------|------|-------------------|
| `confidence >= 0.70` | High | Execute recommended action immediately |
| `0.50 <= confidence < 0.70` | Medium | Request one re-capture and re-analysis |
| `confidence < 0.50` | Low | Skip actuation and log uncertainty |

### State Flow

The intended mission flow around MOD-04 is:

```text
IDLE -> NAVIGATE -> SCAN -> ANALYZE -> DECIDE -> ACT -> LOG -> NAVIGATE
```

The public header also includes `ROBOT_STATE_APPROACH`, `ROBOT_STATE_PAUSED`, `ROBOT_STATE_ABORTED`, and `ROBOT_STATE_ERROR` for additional runtime control and fault handling.

---

## 10. Error Handling

### 10.1 Status Code Decision Table

| Status Code | Cause | Recommended Action |
|-------------|-------|--------------------|
| `DECISION_OK` | Operation completed successfully | Continue mission flow |
| `DECISION_ERR_INIT` | Module/config initialization failed | Reinitialize module and verify config |
| `DECISION_ERR_STATE` | Invalid state transition or invalid mission state | Prevent transition and log state error |
| `DECISION_ERR_MODULE` | Failure in dependent module or integration layer | Log dependency failure and fail safely |
| `DECISION_ERR_ABORT` | Mission was aborted | Stop outputs and keep mission in aborted state |
| `DECISION_ERR_FULL` | Report storage full | Stop adding new entries or flush report buffer |

### 10.2 Error Propagation

MOD-04 sits in the middle of the system and therefore must propagate or handle failures from:

- plant detection failures from MOD-02
- analysis failures from MOD-03
- actuation failures from the Arduino/hardware layer
- invalid mission state transitions

For presentation and implementation, the safe default behavior is:

- do not actuate on invalid or low-confidence results
- keep the system observable through report/log output
- ensure abort stops active hardware safely

---

## 11. Known Risks and Open Questions

| # | Risk / Issue | Severity | Status | Mitigation / Note |
|---|--------------|----------|--------|-------------------|
| 1 | Retry policy wording can be misread because `DECISION_MAX_RESCANS` is `2` while the design intent is "re-evaluate once" | Medium | Open | Clarify in implementation comments and presentation |
| 2 | Servo targeting depends on camera-to-angle calibration that is not finalized yet | Medium | Open | Perform calibration and define angle mapping before hardware demo |
| 3 | Final Arduino topology is not frozen yet: one shared board vs two separate boards | Medium | Open | Decide after pin-budget and timing review |
| 4 | Abort behavior during active spray or laser output must be fail-safe | High | Open | Reserve explicit stop command in Arduino protocol |
| 5 | GUI/report contract is still lighter than a full telemetry schema | Low | Open | Expand later if presentation or final demo requires more detail |
| 6 | In-memory report size is limited by `MAX_PLANTS` | Low | Known | Accept for current project scale or forward entries to persistent storage |

---

## 12. References

| Resource | Relevance |
|----------|-----------|
| `src/decision_motor/mod4.h` | Primary public API and type definitions for MOD-04 |
| `src/decision_motor/mod4.md` | Submitted module summary and dependency overview |
| `src/vlm/mod3.h` | Source of `vlm_result_t` used by `decision_evaluate()` |
| `src/image_processing/mod2.h` | Source of image-processing output types used in MOD-04 integration |
| `src/pathing/mod1.h` | Source of navigation and plant-stop integration points |
| `src/gui/mod5.h` | GUI/dashboard reporting interface |
| `docs/project_proposal_final.md` | Project-level sense -> reason -> act flow and confidence policy |
| `docs/modules_overview.md` | High-level role of MOD-04 within the system |

---

*Document prepared for the module documentation phase of the CSE396 Smart Agriculture / Weed Elimination Robot project.*
