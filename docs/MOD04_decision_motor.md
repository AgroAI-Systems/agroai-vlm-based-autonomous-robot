# MOD-04 — Decision & Motor Control (Orchestrator)

**Implementation:** `pi/main.cpp` → `pi/main` (the orchestrator), with actuator
firing carried out by `arduino/agroai_robot.ino`.
**Role in pipeline:** drive the full per-station cycle — wait for a station, ask
the vision server for a decision, act on it, then release the robot to continue.

`pi/main` bridges two channels:

| Channel | Peer | Purpose |
| --- | --- | --- |
| USB serial `/dev/ttyUSB0` @ 9600 | Arduino | `MARKER`/`RESUMED`/`ACK` in; `START`/`LASER_ON`/`PUMP_ON`/`RESUME` out |
| Unix socket `/tmp/robot_ipc.sock` | `robot_server.py` | sends `CAPTURE`, receives the decision JSON |

## Startup

`main()` opens the serial port (`ArduinoLink`), waits for the Arduino's `READY`,
then prompts the operator to press ENTER and sends `START` so the robot begins
following only when the user is ready. It then loops, reading serial lines and
calling `processStation()` on each `MARKER`. If the serial port can't be opened,
it runs in **DEMO mode** where pressing ENTER simulates a station.

## Per-station handling (`processStation`)

1. Call `analyzeScene()` — connect to the vision socket, send `CAPTURE`, read back
   the decision JSON.
2. If no decision comes back, send `RESUME` and move on (fail-safe: never block
   the robot on a vision error).
3. Parse the JSON fields `status`, `action`, `confidence`, `diagnosis` (a small
   hand-rolled `jsonValue()` reader — no JSON library needed).
4. Act on `action`:

| `action` | Actuator command | Duration |
| --- | --- | --- |
| `laser` | `LASER_ON 3000` → wait → `LASER_OFF` | 3 s (weed) |
| `spray` | `PUMP_ON 2000` → wait → `PUMP_OFF` | 2 s (diseased) |
| anything else (`skip`) | none | — healthy / uncertain |

5. Send `RESUME` so the Arduino leaves the band and follows the line to the next
   station.

## Decision JSON contract

`robot_server.py` returns the following object (see
[MOD-02](MOD02_image_processing.md) / [MOD-03](MOD03_vlm.md) for how it's
produced):

```json
{
  "status":            "healthy | diseased | weed | unknown",
  "confidence":        0.0,
  "diagnosis":         "...",
  "action":            "skip | spray | laser",
  "severity":          "none | low | medium | high",
  "target_position":   "center",
  "inference_time_ms": 0
}
```

`target_position` is `"center"` because YOLO has already cropped to the plant. On
any vision-side error the server returns a safe default (`status="unknown"`,
`action="skip"`) so `pi/main` skips actuation and resumes.

## Actuator safety

Actuator timing is enforced on **both** sides. `pi/main` brackets each `*_ON` with
an explicit `*_OFF` after the wait, and the firmware independently arms a
`millis()`-based auto-off from the duration in `LASER_ON <ms>` / `PUMP_ON <ms>`, so
an actuator can never latch on if an `OFF` message is lost. `RESUME` also
force-stops both actuators before the robot leaves the station.
