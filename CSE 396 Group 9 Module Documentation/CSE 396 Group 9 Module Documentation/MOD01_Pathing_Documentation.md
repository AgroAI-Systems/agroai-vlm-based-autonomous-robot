# MOD-01: Pathing & Navigation Module Documentation

**Smart Agriculture / Weed Elimination Robot**
**CSE396 — Computer Engineering Project — Group 9**

---

**Module ID:** MOD-01
**Module Name:** Pathing & Navigation
**Version:** 0.1
**Last Updated:** 2026-03-29
**Header File:** `mod1.h`
**Main Implementation File:** `pathing.py`
**Language:** Python 3.11+ (with C-compatible header contract)

---

## Authors

| Name              | Student ID     | Role                                              |
|-------------------|----------------|---------------------------------------------------|
| Berat Yılmaz      | 2201004004069  | PID line-following, IR sensor array, motor control |
| Mehmet Efe Hırkalı | 230104004071  | Plant marker detection, state machine, callbacks  |

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

MOD-01 (Pathing & Navigation) is responsible for all low-level locomotion on the robot. It keeps the robot on a black tape line using a 5-sensor TCRT5000 IR array and a PID controller running at 100 Hz, driving a 4WD chassis (4 × TT DC motors paired left/right via L298N dual H-bridge driver).

When all five IR sensors detect a cross-tape plant marker simultaneously, the module stops the robot and fires a callback to MOD-04 (Decision Motor) to initiate the inspection pipeline. Navigation resumes when MOD-04 calls `pathing_resume()` after actuation or skip. All state transitions are broadcast to MOD-05 (GUI/Dashboard) in real time.

All control runs entirely on-device on the Raspberry Pi 5 — zero cloud dependency.

---

## 2. Responsibilities

| # | Responsibility | Description |
|---|----------------|-------------|
| 1 | IR Sensing | Read 5-channel TCRT5000L IR sensor array at 100 Hz via GPIO digital inputs |
| 2 | PID Control | Compute weighted line-position error and apply PID correction to left/right motor pair speeds |
| 3 | Motor Control | Drive 4 × TT DC motors (paired left/right) via L298N dual H-bridge over GPIO PWM |
| 4 | Marker Detection | Detect cross-tape plant markers (all 5 sensors active for ≥ 2 consecutive cycles) with debounce |
| 5 | Stop & Notify | Stop motors and fire `pathing_plant_detected_cb_t` callback to MOD-04 |
| 6 | Resume | Resume PID navigation when `pathing_resume()` is called by MOD-04 |
| 7 | State Broadcast | Broadcast `pathing_state_t` transitions to MOD-05 via `pathing_state_change_cb_t` callback |
| 8 | Manual Override | Expose direct motor command interface for calibration and testing |

---

## 3. System Context

The diagram below shows MOD-01's position within the overall system architecture and its data flow connections to other modules.

```
┌──────────────────────────────────────────────────────────┐
│                    Raspberry Pi 5                         │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │  MOD-01 — PATHING & NAVIGATION                      │  │
│  │                                                     │  │
│  │  • 5-channel IR array (TCRT5000L) via GPIO          │  │
│  │  • PID loop @ 100 Hz                                │  │
│  │  • 4WD motor control via L298N                      │  │
│  │  • Plant marker detection + debounce                │  │
│  └──────────────────────────────────────────────────┬──┘  │
│                                                     │      │
│   plant_detected_cb_t ──────────────────────────►  │      │
│                                          MOD-04     │      │
│   pathing_resume() ◄────────────────── Decision     │      │
│                                          Motor      │      │
│                                                     │      │
│   pathing_state_change_cb_t ───────────────────►  MOD-05  │
│                                               GUI Dashboard│
└──────────────────────────────────────────────────────────┘
         │                        │
         ▼                        ▼
  ┌─────────────┐        ┌────────────────┐
  │ IR Sensor   │        │ L298N + 4×TT   │
  │ Array       │        │ DC Motors      │
  │ TCRT5000L×5 │        │ (4WD chassis)  │
  └─────────────┘        └────────────────┘
```

**Hardware Interface:**

| Interface | Connection | Notes |
|-----------|-----------|-------|
| GPIO (digital in) | Pi ↔ IR sensor array | 5 digital input pins, polled at 100 Hz |
| GPIO (PWM) | Pi ↔ L298N motor driver | 2 PWM channels for speed, 4 digital for direction |

---

## 4. Dependencies

### 4.1 Software Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `RPi.GPIO` / `gpiozero` | >= 0.7 | GPIO and PWM control on Raspberry Pi 5 |
| `threading` | stdlib | Background PID loop thread |
| `time` | stdlib | Loop timing and timestamps |

### 4.2 Installation

```bash
pip install RPi.GPIO
# or
pip install gpiozero
```

> **Note:** `RPi.GPIO` requires running as root or with appropriate GPIO permissions. On Raspberry Pi OS, add the user to the `gpio` group: `sudo usermod -aG gpio $USER`

### 4.3 Hardware Requirements

| Component | Specification |
|-----------|---------------|
| IR Sensor Array | TCRT5000L 5-channel IR line tracking module |
| Motors | 4 × TT DC Gear Motor (3–6 V) — 4WD chassis kit |
| Motor Driver | L298N Dual H-Bridge (2A per channel, 5–35 V) |
| Chassis | REX 4WD Çok Amaçlı Mobil Robot Platformu (Şeffaf) |
| Motor Power | LiPo 11.1 V 3S — separate from Pi power rail |
| Compute | Raspberry Pi 5 (all control on-device) |

---

## 5. Configuration Constants

The following compile-time constants are defined in `mod1.h`:

| Constant | Value | Description |
|----------|-------|-------------|
| `PATHING_IR_SENSOR_COUNT` | 5 | Number of IR sensors in the array |
| `PATHING_IR_PIN_0..4` | 6, 13, 19, 26, 21 | BCM GPIO pins for IR sensors (provisional) |
| `PATHING_MOTOR_L_PWM_PIN` | 12 | BCM GPIO for left motor pair PWM |
| `PATHING_MOTOR_L_IN1_PIN` | 23 | BCM GPIO for left motor direction bit 1 |
| `PATHING_MOTOR_L_IN2_PIN` | 24 | BCM GPIO for left motor direction bit 2 |
| `PATHING_MOTOR_R_PWM_PIN` | 13 | BCM GPIO for right motor pair PWM |
| `PATHING_MOTOR_R_IN1_PIN` | 20 | BCM GPIO for right motor direction bit 1 |
| `PATHING_MOTOR_R_IN2_PIN` | 16 | BCM GPIO for right motor direction bit 2 |
| `PATHING_MOTOR_PWM_FREQ_HZ` | 1000 | PWM carrier frequency for L298N |
| `PATHING_MOTOR_DUTY_MIN` | 0 | Minimum motor duty cycle (%) |
| `PATHING_MOTOR_DUTY_MAX` | 100 | Maximum motor duty cycle (%) |
| `PATHING_MOTOR_BASE_SPEED` | 60 | Default cruising duty cycle (%) |
| `PATHING_PID_KP_DEFAULT` | 0.35 | Proportional gain (requires field tuning) |
| `PATHING_PID_KI_DEFAULT` | 0.0 | Integral gain |
| `PATHING_PID_KD_DEFAULT` | 0.10 | Derivative gain (requires field tuning) |
| `PATHING_PID_LOOP_RATE_HZ` | 100 | PID control loop frequency |
| `PATHING_PID_LOOP_PERIOD_MS` | 10 | PID loop period (1000 / loop rate) |
| `PATHING_PLANT_MARKER_PATTERN` | 0x1F | IR bitmask for plant marker (all 5 active) |

---

## 6. Data Types Reference

### 6.1 `pathing_status_t` — Status Codes

Enumeration of all possible return status codes from module functions.

```c
typedef enum {
    PATHING_OK              =  0,   // Operation completed successfully
    PATHING_ERR_INIT        = -1,   // Hardware initialisation failed
    PATHING_ERR_INVALID_ARG = -2,   // NULL pointer or out-of-range argument
    PATHING_ERR_MOTOR       = -3,   // Motor GPIO / PWM failure
    PATHING_ERR_IR          = -4,   // IR sensor read failure
    PATHING_ERR_NOT_RUNNING = -5    // Function called in wrong state
} pathing_status_t;
```

---

### 6.2 `pathing_state_t` — Navigation States

High-level navigation states of the robot. Broadcast to MOD-05 on every transition.

```c
typedef enum {
    PATHING_STATE_IDLE      = 0,   // Powered, motors off
    PATHING_STATE_NAVIGATE  = 1,   // PID line-following active
    PATHING_STATE_STOPPING  = 2,   // Decelerating to plant marker
    PATHING_STATE_STOPPED   = 3,   // Stopped at marker, waiting for resume
    PATHING_STATE_ERROR     = 4    // Fault — manual reset required
} pathing_state_t;
```

---

### 6.3 `pathing_ir_reading_t` — IR Sensor Snapshot

Raw IR sensor reading at a single point in time.

```c
typedef struct {
    uint8_t  mask;                          // Bitmask: bit i = 1 if sensor i active
    uint8_t  raw[PATHING_IR_SENSOR_COUNT];  // Per-sensor values (0 or 1)
    uint32_t timestamp_ms;                  // System time of reading (ms since boot)
} pathing_ir_reading_t;
```

**Usage:** Bit `i` of `mask` corresponds to sensor `i` (0 = leftmost, 4 = rightmost). Plant marker detection fires when `mask == PATHING_PLANT_MARKER_PATTERN` (0x1F) for ≥ 2 consecutive cycles.

---

### 6.4 `pathing_pid_state_t` — PID Controller State

Internal PID state, exposed for logging and live tuning.

```c
typedef struct {
    float kp;           // Proportional gain
    float ki;           // Integral gain
    float kd;           // Derivative gain
    float error;        // Current weighted error
    float prev_error;   // Error from previous loop iteration
    float integral;     // Accumulated integral term
    float output;       // Last computed PID correction value
} pathing_pid_state_t;
```

---

### 6.5 `pathing_motor_cmd_t` — Motor Command

Speed and direction command for a single motor pair.

```c
typedef struct {
    uint8_t duty;      // Duty cycle 0–100 (%)
    bool    forward;   // true = forward, false = reverse
} pathing_motor_cmd_t;
```

---

### 6.6 `pathing_config_t` — Module Configuration

Runtime hardware and PID configuration. Pass `NULL` to `pathing_init()` for defaults.

```c
typedef struct {
    uint8_t ir_pins[PATHING_IR_SENSOR_COUNT]; // BCM GPIO pins for IR sensors
    uint8_t motor_l_pwm;   // BCM GPIO for left motor PWM
    uint8_t motor_l_in1;   // BCM GPIO for left motor direction bit 1
    uint8_t motor_l_in2;   // BCM GPIO for left motor direction bit 2
    uint8_t motor_r_pwm;   // BCM GPIO for right motor PWM
    uint8_t motor_r_in1;   // BCM GPIO for right motor direction bit 1
    uint8_t motor_r_in2;   // BCM GPIO for right motor direction bit 2
    float   kp;            // PID proportional gain
    float   ki;            // PID integral gain
    float   kd;            // PID derivative gain
    uint8_t base_speed;    // Cruising motor duty cycle (0–100)
} pathing_config_t;
```

---

### 6.7 Callback Types

```c
// Invoked when a plant marker is detected and the robot stops.
// Registered by MOD-04 (Decision Motor). No data payload — signals
// "robot stopped, ready for inspection."
typedef void (*pathing_plant_detected_cb_t)(uint32_t timestamp_ms);

// Invoked on every navigation state transition.
// Registered by MOD-05 (GUI/Dashboard).
typedef void (*pathing_state_change_cb_t)(pathing_state_t new_state);
```

---

## 7. API Reference

### 7.1 `pathing_init`

```c
pathing_status_t pathing_init(const pathing_config_t      *cfg,
                               pathing_plant_detected_cb_t  on_plant,
                               pathing_state_change_cb_t    on_state);
```

**Description:** Initialises GPIO pins, PWM channels, and the PID controller. Must be called once before any other `pathing_*` function. Uses compiled-in defaults if `cfg` is NULL.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `cfg` | `const pathing_config_t *` | Hardware and PID configuration, or NULL for defaults |
| `on_plant` | `pathing_plant_detected_cb_t` | Callback fired when plant marker is detected. Must not be NULL |
| `on_state` | `pathing_state_change_cb_t` | Callback fired on state transitions. May be NULL |

**Returns:** `PATHING_OK` on success, `PATHING_ERR_INIT` on hardware failure.

---

### 7.2 `pathing_start`

```c
pathing_status_t pathing_start(void);
```

**Description:** Starts the PID line-following loop in a background thread. Enters `PATHING_STATE_NAVIGATE`. The loop runs at `PATHING_PID_LOOP_RATE_HZ` until a plant marker is detected or `pathing_stop()` is called.

**Returns:** `PATHING_OK` on success, `PATHING_ERR_NOT_RUNNING` if not initialised.

---

### 7.3 `pathing_resume`

```c
pathing_status_t pathing_resume(void);
```

**Description:** Resumes navigation after a plant inspection is complete. Called by MOD-04 (Decision Motor) after actuation or skip. Transitions from `PATHING_STATE_STOPPED` back to `PATHING_STATE_NAVIGATE`.

**Returns:** `PATHING_OK` on success, `PATHING_ERR_NOT_RUNNING` if not in STOPPED state.

---

### 7.4 `pathing_stop`

```c
pathing_status_t pathing_stop(void);
```

**Description:** Immediately stops both motor pairs and enters `PATHING_STATE_IDLE`. Safe to call at any time. Does **not** trigger the plant-detected callback.

**Returns:** `PATHING_OK` always (best-effort GPIO write).

---

### 7.5 `pathing_read_ir`

```c
pathing_status_t pathing_read_ir(pathing_ir_reading_t *out);
```

**Description:** Copies the latest IR sensor snapshot into the caller-owned struct.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `out` | `pathing_ir_reading_t *` | Pointer to caller-owned struct to populate |

**Returns:** `PATHING_OK` on success, `PATHING_ERR_INVALID_ARG` if `out` is NULL.

---

### 7.6 `pathing_set_motors`

```c
pathing_status_t pathing_set_motors(const pathing_motor_cmd_t *left,
                                    const pathing_motor_cmd_t *right);
```

**Description:** Applies a direct motor command, bypassing the PID loop. Intended for manual testing and calibration only. Has no effect when the PID loop is running (`PATHING_STATE_NAVIGATE`).

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `left` | `const pathing_motor_cmd_t *` | Command for the left motor pair |
| `right` | `const pathing_motor_cmd_t *` | Command for the right motor pair |

**Returns:** `PATHING_OK` on success, `PATHING_ERR_MOTOR` on GPIO failure.

---

### 7.7 `pathing_get_pid_state`

```c
pathing_status_t pathing_get_pid_state(pathing_pid_state_t *out);
```

**Description:** Copies the current PID controller state for logging or live tuning.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `out` | `pathing_pid_state_t *` | Pointer to caller-owned struct to populate |

**Returns:** `PATHING_OK` on success, `PATHING_ERR_INVALID_ARG` if `out` is NULL.

---

### 7.8 `pathing_set_pid_gains`

```c
pathing_status_t pathing_set_pid_gains(float kp, float ki, float kd);
```

**Description:** Updates PID gains at runtime without stopping navigation. Changes take effect on the next loop iteration.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `kp` | `float` | New proportional gain |
| `ki` | `float` | New integral gain |
| `kd` | `float` | New derivative gain |

**Returns:** `PATHING_OK` on success.

---

### 7.9 `pathing_get_state`

```c
pathing_state_t pathing_get_state(void);
```

**Description:** Returns the current navigation state without side effects.

**Returns:** Current `pathing_state_t` value.

---

### 7.10 `pathing_deinit`

```c
pathing_status_t pathing_deinit(void);
```

**Description:** Stops motors and releases all GPIO and PWM resources. `pathing_init()` must be called again before using any other function.

**Returns:** `PATHING_OK` on success, `PATHING_ERR_INIT` if not yet initialised.

---

## 8. Inter-Module Communication

### 8.1 Communication Summary Table

| Direction | Peer Module | Data / Signal | Type | Frequency |
|-----------|-------------|---------------|------|-----------|
| **MOD-01 → MOD-04** | Decision Motor | Plant detected signal | `pathing_plant_detected_cb_t` | Event-driven: once per plant marker |
| **MOD-04 → MOD-01** | Decision Motor | Resume navigation | `pathing_resume()` function call | Once per plant, after actuation or skip |
| **MOD-01 → MOD-05** | GUI Dashboard | Navigation state update | `pathing_state_change_cb_t` | On every state transition |

### 8.2 Detailed Communication Descriptions

#### MOD-01 → MOD-04 (Decision Motor): Plant Detection Signal

When the Pathing module's IR sensors detect a plant marker, the robot stops and fires the registered `pathing_plant_detected_cb_t` callback. This triggers the full inspection pipeline: Image Processing captures a frame, VLM analyses the ROI, and Decision Motor evaluates the result. The callback mechanism allows the Decision Motor to initiate the scan-analyse-decide sequence without tight coupling to the Pathing module's internal loop.

**Data exchanged:** `uint32_t timestamp_ms` — system time at the moment of detection (ms since boot).

#### MOD-04 → MOD-01 (Decision Motor): Resume Navigation

After the Decision Motor completes its action (or decides to skip), it calls `pathing_resume()` to signal that the robot should continue navigating to the next plant marker. This ensures the robot does not move while an actuator is active.

**Data exchanged:** No data payload — function call signals "action complete, safe to move."

#### MOD-01 → MOD-05 (GUI Dashboard): Navigation State

Every state transition fires the registered `pathing_state_change_cb_t` callback with the new `pathing_state_t` value. The GUI uses this to display the current robot state in real time.

**Data exchanged:** `pathing_state_t` enum value.

#### Typical Call Sequence

```
Robot navigating...
      │
      ▼ (plant marker detected)
pathing_plant_detected_cb_t(timestamp_ms)  ──► MOD-04
      │
      │   MOD-04 runs full inspection pipeline:
      │   imgproc_capture_and_detect() → vlm_analyze() → dm_decide_and_act()
      │
      ▼
pathing_resume()  ◄── MOD-04 (after actuation or skip)
      │
      ▼
Robot navigating again...
```

---

## 9. Processing Pipeline

### 9.1 PID Line-Following Algorithm

```
                    PID Loop (100 Hz)
                         │
                         ▼
              ┌──────────────────────┐
              │  1. READ IR SENSORS  │
              │  5 × GPIO digital in │
              │  → pathing_ir_       │
              │    reading_t.mask    │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │  2. MARKER CHECK     │
              │  mask == 0x1F?       │
              │  for ≥ 2 cycles?     │
              └──────┬──────┬────────┘
                     │      │
                  YES│      │NO
                     ▼      ▼
             STOP & FIRE  CONTINUE
             CALLBACK     TO PID
                          │
                          ▼
              ┌──────────────────────┐
              │  3. ERROR COMPUTE    │
              │  weights = [-2,-1,   │
              │             0,+1,+2] │
              │  error = Σ(w×ir)/Σir │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │  4. PID OUTPUT       │
              │  integral += err×dt  │
              │  deriv = Δerr/dt     │
              │  out = Kp×e+Ki×i+Kd×d│
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │  5. MOTOR MIXING     │
              │  left  = base + out  │
              │  right = base - out  │
              │  clamp(0, 100)       │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │  6. WRITE PWM        │
              │  GPIO PWM → L298N    │
              │  → 4 × TT motors     │
              └──────────────────────┘
```

### 9.2 Timing Constraints

| Stage | Estimated Duration |
|-------|-------------------|
| IR sensor read (5 × GPIO) | < 1 ms |
| Error computation + PID | < 1 ms |
| Motor PWM write | < 1 ms |
| **Total per loop cycle** | **< 3 ms** (10 ms budget at 100 Hz) |

---

## 10. Error Handling

### 10.1 Status Code Decision Table

| Status Code | Cause | Recommended Action |
|-------------|-------|-------------------|
| `PATHING_OK` | Operation succeeded | Proceed normally |
| `PATHING_ERR_INIT` | GPIO or PWM setup failed | Check wiring; retry `pathing_init()` |
| `PATHING_ERR_INVALID_ARG` | NULL pointer passed | Fix caller code |
| `PATHING_ERR_MOTOR` | Motor GPIO write failed | Check L298N wiring; inspect power supply |
| `PATHING_ERR_IR` | IR sensor read failed | Check IR sensor wiring and GPIO pin config |
| `PATHING_ERR_NOT_RUNNING` | Called in wrong state | Check state with `pathing_get_state()` before calling |

### 10.2 Error Propagation

All public functions return `pathing_status_t`. Callers should check return values before proceeding.

Example usage:

```c
pathing_status_t status = pathing_start();
if (status != PATHING_OK) {
    printf("Pathing start failed: %d\n", status);
    pathing_deinit();
    return -1;
}
```

---

## 11. Known Risks and Open Questions

| # | Risk / Issue | Severity | Status | Mitigation |
|---|-------------|----------|--------|------------|
| 1 | **GPIO pin assignments are provisional** — final pin allocation not confirmed; conflicts with CSI camera interface possible | Medium | Open | Override at runtime via `pathing_config_t`; coordinate with all module owners before wiring |
| 2 | **PID gains are initial estimates** (Kp=0.35, Kd=0.10) — will require field tuning on the actual course | Medium | Open | Use `pathing_set_pid_gains()` for runtime adjustment without recompiling |
| 3 | **Marker debounce count (2 cycles) not validated** — may trigger false positives or miss markers depending on robot speed and marker width | Low | Open | Adjust debounce count after first physical run |
| 4 | **No encoder feedback (open-loop speed control)** — motor drift may accumulate on longer course segments | Low | Open | Monitor during testing; add encoders if drift exceeds acceptable threshold |
| 5 | **`pathing_set_motors()` lacks state guard** — accidental call during active navigation could cause unexpected movement | Low | Open | Add `PATHING_STATE_NAVIGATE` state check inside function before applying command |
| 6 | **Integral windup not clamped** — accumulated integral may cause slow recovery after sharp turns | Low | Open | Add integral saturation limit during PID implementation |
| 7 | **Motor voltage compatibility** — TT DC motors rated 3–6 V; LiPo 11.1 V 3S may over-drive motors through L298N | Medium | Open | Limit effective voltage via PWM duty cycle; monitor motor temperature during testing |

---

## 12. References

| Resource | URL |
|----------|-----|
| RPi.GPIO Documentation | https://pypi.org/project/RPi.GPIO/ |
| gpiozero Documentation | https://gpiozero.readthedocs.io/ |
| Raspberry Pi 5 Documentation | https://www.raspberrypi.com/documentation/ |
| TCRT5000 Datasheet | https://www.vishay.com/docs/83760/tcrt5000.pdf |
| L298N Motor Driver Datasheet | https://www.st.com/resource/en/datasheet/l298.pdf |

---

*Document generated for CSE396 Computer Engineering Project — Group 9*
*Smart Agriculture / Weed Elimination Robot — Autonomous On-Device Plant Inspection and Precision Actuation System*
