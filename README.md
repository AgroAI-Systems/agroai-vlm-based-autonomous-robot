# AgroAI — VLM-Based Autonomous Weed Elimination Robot

An autonomous ground robot that follows a tape line through a row of plants,
stops at each plant, runs on-device vision to classify it, and acts: a water
pump for healthy/diseased crops, a laser for weeds. All inference runs locally
on the robot — no cloud.

CSE396 Senior Design Project — Group 9 (AgroAI Systems).

## Hardware

| Component        | Part                                          |
| ---------------- | --------------------------------------------- |
| Compute (vision) | Raspberry Pi 4 Model B                        |
| Compute (motion) | Arduino Uno R3                                |
| Camera           | Raspberry Pi Camera Module v2 (62.2° HFOV)    |
| Line sensor      | 5-channel IR reflectance array                |
| Drive            | 2× DC gear motors via L298N (or similar) H-bridge |
| Pan/tilt         | 2× SG90 micro servos                          |
| Tools            | Laser diode module, 5 V mini water pump       |
| Link             | Pi ↔ Arduino over USB serial (9600 baud)      |

Pin assignments live at the top of `arduino/weed_robot/weed_robot.ino`.

## Repository Layout

```
arduino/weed_robot/   Arduino firmware — line following + actuator control
pi/                   Raspberry Pi side — vision, VLM, decision logic
  detect.py             YOLO capture + classify + dispatch loop
  controller.cpp        Serial bridge: stdin → /dev/ttyUSB0 → Arduino
  Makefile              Builds the controller binary
docs/                 Module specs and interface documentation
```

### Module mapping

The project is specified as five logical modules; the physical split is by
hardware boundary:

| Spec module          | Lives in        |
| -------------------- | --------------- |
| mod1 — Pathing       | `arduino/`      |
| mod2 — Image Proc.   | `pi/`           |
| mod3 — VLM           | `pi/`           |
| mod4 — Decision/Act  | `pi/` + `arduino/` |
| mod5 — Dashboard     | _planned_       |

See `docs/` for the per-module interface specifications.

## Quickstart

### 1. Flash the Arduino

Open `arduino/weed_robot/weed_robot.ino` in the Arduino IDE, select your Uno,
and upload. The board should print `READY` on the serial monitor.

### 2. Set up the Pi

```sh
sudo apt install -y python3-picamera2 python3-opencv build-essential
python3 -m venv ~/yolo-env
source ~/yolo-env/bin/activate
pip install ultralytics
```

Place a YOLOv8 weights file (e.g. `yolov8n.pt`) next to `detect.py` — see
`MODEL_PATH` near the top of `detect.py` to override.

### 3. Build and run

```sh
cd pi
make
source ~/yolo-env/bin/activate
python detect.py
```

Interactive commands are printed at startup (`Enter` to capture+act, `l` for
manual laser, `p` for manual pump, `s pan tilt` to aim, `c` for calibration,
`q` to quit).

### 4. Calibrate the laser

Follow the procedure in the docstring at the top of `pi/detect.py`. Tune
`PAN_OFFSET` / `TILT_OFFSET` (and the scale factors if needed) so the laser
hits the on-screen crosshair.

## Status

| Feature                                  | State        |
| ---------------------------------------- | ------------ |
| Pi ↔ Arduino serial bridge               | Working      |
| Pi Camera capture + YOLOv8 inference     | Working      |
| Servo pan/tilt aiming from YOLO box      | Working      |
| Laser firing on weed detection           | Working (stock YOLOv8n) |
| Pump firing on healthy-plant detection   | Working (stock YOLOv8n) |
| Custom YOLO weed/crop dataset + weights  | In progress, mostly ready |
| VLM (MoondreamV2) classification stage   | In progress, mostly ready |
| Line following (5-IR PID on Arduino)     | In progress  |
| Dashboard / monitoring UI (mod5)         | Planned      |

> **Note on the model.** End-to-end tests so far use stock `yolov8n.pt` with COCO
> class names (`potted plant`, etc.) as a stand-in. A project-specific YOLO
> dataset and trained weights are being prepared; once those land, update
> `MODEL_PATH`, `WEED_CLASSES`, and `HEALTHY_CLASSES` in `pi/detect.py`.

## License

TBD.
