# AgroAI — VLM-Based Autonomous Weed Elimination Robot

An autonomous ground robot that follows a tape line through a row of plants,
stops at each plant, runs on-device vision to classify it, and acts: a water
pump for diseased crops, a laser for weeds. All inference runs locally on the
robot — no cloud.

CSE396 Senior Design Project — Group 9 (AgroAI Systems).

## Hardware

| Component        | Part                                          |
| ---------------- | --------------------------------------------- |
| Compute (vision) | Raspberry Pi 4 Model B                        |
| Compute (motion) | Arduino Uno R3                                |
| Camera           | Raspberry Pi Camera Module (via `picamera2`)  |
| Line sensor      | 3-channel IR reflectance array (left/center/right) |
| Drive            | 2× DC gear motors via L298N H-bridge          |
| Tools            | Laser diode module, 5 V mini water pump       |
| Link             | Pi ↔ Arduino over USB serial (9600 baud)      |

Pin assignments live at the top of `arduino/agroai_robot.ino`.

## How it works

The system runs as four processes across two boards. The Arduino follows the
line until its left IR sensor reads a black station band, stops, and sends
`MARKER` to the Pi. The orchestrator (`pi/main`) asks the vision server
(`robot_server.py`) for a decision — YOLO classifies the plant and a bypass gate
decides whether to also run the VLM — then fires the laser (weed) or pump
(diseased) and sends `RESUME` so the robot continues to the next station.

```
[Arduino: agroai_robot.ino]  line-follow + station stop + actuators
       ▲  USB serial 9600
       ▼
[Pi: pi/main]                orchestrator — waits for MARKER, drives the cycle
       ▲  Unix socket /tmp/robot_ipc.sock
       ▼
[Pi: robot_server.py]        camera + YOLO + bypass gate + SmolVLM
       ▼  writes log + capture/crop images + vlm_output.json
[Pi: dashboard.py]           read-only web UI
```

Full module documentation is in [`docs/`](docs/README.md).

## Repository Layout

```
arduino/agroai_robot.ino   Arduino firmware — line following + station stop + actuators
pi/
  main.cpp                 Orchestrator: serial (Arduino) + socket (vision server)
  Makefile                 Builds the orchestrator (-> pi/main)
src/
  robot_server.py          Vision server: camera + YOLO + bypass gate + SmolVLM
  mod2_mod3_pipeline.py    YOLO + VLM pipeline core (imported by robot_server.py)
  vlm/                     VLM engine, parser, and types (SmolVLM-256M)
  dashboard.py             Read-only web monitoring dashboard
  best.pt                  Trained YOLO weights (SCAB / Weeds / healthy)
docs/                      System and per-module documentation
```

### Module mapping

The project is specified as five logical modules; the physical split is by
hardware and process boundary:

| Spec module          | Lives in                                  |
| -------------------- | ----------------------------------------- |
| mod1 — Pathing       | `arduino/agroai_robot.ino`                |
| mod2 — Image Proc.   | `src/robot_server.py`, `src/mod2_mod3_pipeline.py` |
| mod3 — VLM           | `src/vlm/`                                |
| mod4 — Decision/Act  | `pi/main.cpp` + `arduino/agroai_robot.ino`|
| mod5 — Dashboard     | `src/dashboard.py`                        |

See [`docs/`](docs/README.md) for the per-module documentation.

## Quickstart

### 1. Flash the Arduino

Open `arduino/agroai_robot.ino` in the Arduino IDE, select your Uno, and upload.
The board prints `READY` on the serial monitor at 9600 baud.

### 2. Set up the Pi

```sh
sudo apt install -y python3-picamera2 python3-opencv build-essential
python3 -m venv ~/agroai-env
source ~/agroai-env/bin/activate
pip install ultralytics transformers torch pillow
```

### 3. Run

```sh
# Terminal 1 — vision server (loads YOLO + VLM once, then waits)
source ~/agroai-env/bin/activate
python3 src/robot_server.py

# Terminal 2 — orchestrator (press ENTER to send START to the Arduino)
cd pi && make && ./main          # ./main /dev/ttyUSB1 to override the port

# Terminal 3 — optional dashboard
python3 src/dashboard.py         # http://<pi-ip>:8000
```

`run_robot.sh` and `run_dashboard.sh` wrap these. If no Arduino is connected,
`pi/main` runs in DEMO mode where pressing ENTER simulates a station.

## Status

| Feature                                        | State    |
| ---------------------------------------------- | -------- |
| Line following + station detection (3-IR)      | Working  |
| Pi ↔ Arduino serial bridge                     | Working  |
| Pi camera capture + YOLO (`best.pt`) inference | Working  |
| YOLO → VLM bypass gate                          | Working  |
| SmolVLM-256M classification stage              | Working  |
| Laser firing on weed detection                 | Working  |
| Pump firing on diseased-plant detection        | Working  |
| Monitoring dashboard (mod5)                    | Working  |
