# MOD-01 — Pathing (Line Following + Station Detection)

**Implementation:** `arduino/agroai_robot.ino` (Arduino Uno R3)
**Role in pipeline:** sense/navigate — follow the tape line, stop at each plant
station, hand control to the Pi, and resume on command.

The firmware uses **3 IR sensors** (left/center/right) with a discrete follow rule
and a slight per-wheel speed bias for steering correction.

## Hardware / pin map

| Function | Pin(s) | Notes |
| --- | --- | --- |
| IR sensors | `solSensor=10`, `ortaSensor=11`, `sagSensor=12` | `INPUT_PULLUP`; left/center/right |
| Right motor | `motorSag1=6`, `motorSag2=7`, `ENA=9` | PWM enable on `ENA` |
| Left motor | `motorSol1=5`, `motorSol2=4`, `ENB=3` | PWM enable on `ENB` |
| Laser | `LASER_PIN=2` | driven via relay/MOSFET |
| Pump | `PUMP_PIN=8` | |
| Actuator polarity | `ACTUATOR_ACTIVE_HIGH=true` | set `false` for LOW-triggered relays |

Speed tuning: `SOL_MOTOR_HIZI=64`, `SAG_MOTOR_HIZI=58`, `HAFIF_ARTIS=8` (the small
steering increment). These compensate for left/right drive imbalance.

## Line-following logic

`followLine(sol, orta, sag)` reads the three digital sensors and picks one motor
command (a black line reads `0` on a sensor over the line in this hardware):

| Pattern (sol, orta, sag) | Action |
| --- | --- |
| `0, 1, 1` | `ileriGit()` — straight |
| `0, 1, 0` | `sagHafifHizlan()` — nudge right |
| `0, 0, 1` | `solHafifHizlan()` — nudge left |
| anything else | `dur()` — stop |

## Station (marker) detection

A plant station is marked by a **black band read by the left sensor only**. The
band reads `HIGH` on the left sensor in this hardware (`MARKER_LEVEL=HIGH`), while
normal track reads `LOW`. Detection is debounced: `MARKER_DEBOUNCE=3` consecutive
reads are required before a marker is accepted, which rejects noise spikes.

## State machine

`enum RobotState { WAITING, FOLLOWING, AT_MARKER, LEAVING }`

| State | Behavior |
| --- | --- |
| `WAITING` | Motors off at power-on. Stays here until a `START`/`GO` command arrives (so wheels don't spin on boot). |
| `FOLLOWING` | Runs `followLine()` and watches for a debounced marker. On a confirmed marker: stop, `delay(2000)` to settle, send `MARKER`, latch (`markerArmed=false`), go to `AT_MARKER`. |
| `AT_MARKER` | Motors off; waits for Pi commands (actuators / `RESUME`). |
| `LEAVING` | After `RESUME`: drive forward across the band, then follow the line until the left sensor sees white **continuously for `LEAVE_WHITE_MS=3000` ms**, then re-arm and return to `FOLLOWING`. Prevents re-triggering the same station. |

## Serial protocol (9600 baud, newline-terminated)

| Direction | Messages |
| --- | --- |
| Arduino → Pi | `READY` (boot), `MARKER` (stopped at station), `RESUMED`, `ACK <cmd>`, `DBG ...` (when `DEBUG_ON`) |
| Pi → Arduino | `START` / `GO`, `LASER_ON <ms>` / `LASER_OFF`, `PUMP_ON <ms>` / `PUMP_OFF`, `RESUME`, `DEBUG_ON` / `DEBUG_OFF` |

`LASER_ON <ms>` / `PUMP_ON <ms>` carry an optional duration; the firmware arms a
**safety auto-off** (`laserOffAt` / `pumpOffAt` via `millis()`) so an actuator can
never stay on forever if the matching `*_OFF` is lost. `RESUME` also force-stops
both actuators before leaving the station.

## Calibration aid

Send `DEBUG_ON` to stream raw sensor values; place the band under the left sensor
and confirm which level it reads, then set `MARKER_LEVEL` accordingly. The header
comment in the `.ino` walks through this (a wrong `MARKER_LEVEL` causes false
markers and a lockup).
