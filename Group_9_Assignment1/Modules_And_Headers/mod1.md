# MOD-01 - Pathing and Navigation System

PID line-following with IR sensor array, plant marker detection, and DC motor control.

## Authors

| Name | Student ID |
|---|---|
| Berat Yilmaz | 2201004004069 |
| Mehmet Efe Hirkali | 230104004071 |

## Purpose

Keeps the robot on a black tape line using a 5-sensor IR array and a 100 Hz PID loop. Detects cross-tape plant markers (all sensors active), stops robot motion, triggers the Decision Engine callback, and resumes when commanded via `pathing_resume()`.

## Dependencies

| Dependency | Notes |
|---|---|
| Decision Engine | `on_plant` callback and `pathing_resume()` handshake |
| Dashboard | state callback registration |
| `RPi.GPIO` / `gpiozero` | GPIO and PWM control on Raspberry Pi 5 |
| `<stdint.h>`, `<stdbool.h>` | integer and boolean types |

## API Summary

### Constants

- `PATHING_IR_SENSOR_COUNT`
- `PATHING_IR_PIN_0..4`
- `PATHING_MOTOR_L_PWM_PIN`, `PATHING_MOTOR_R_PWM_PIN`
- `PATHING_MOTOR_PWM_FREQ_HZ`, `PATHING_MOTOR_BASE_SPEED`
- `PATHING_PID_KP_DEFAULT`, `PATHING_PID_KI_DEFAULT`, `PATHING_PID_KD_DEFAULT`
- `PATHING_PID_LOOP_RATE_HZ`
- `PATHING_PLANT_MARKER_PATTERN`

### Types

- `pathing_status_t`
- `pathing_state_t`
- `pathing_ir_reading_t`
- `pathing_pid_state_t`
- `pathing_motor_cmd_t`
- `pathing_config_t`

### Functions

- `pathing_init`
- `pathing_start`
- `pathing_resume`
- `pathing_stop`
- `pathing_read_ir`
- `pathing_set_motors`
- `pathing_get_pid_state`
- `pathing_set_pid_gains`
- `pathing_get_state`
- `pathing_deinit`

## Logic Notes

Error model:

```text
weights = [-2, -1, 0, +1, +2]
error   = sum(weights[i] * ir[i]) / sum(ir[i])
```

Motor mapping:

```text
left_duty  = base_speed + output
right_duty = base_speed - output
```

Marker detection uses `PATHING_PLANT_MARKER_PATTERN` for at least 2 consecutive cycles.

## Limitations and TODOs

- GPIO pin mapping is provisional.
- PID constants require field tuning.
- Debounce cycle count may need adjustment.
- No encoder feedback (open-loop speed).
- `pathing_set_motors()` should have stronger state guards.
