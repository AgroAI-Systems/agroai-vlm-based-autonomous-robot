# AgroAI — System Documentation

CSE396 Senior Design Project — Group 9 (AgroAI Systems).

An autonomous ground robot that follows a tape line through a row of plants, stops
at each plant, classifies it on-device, and acts: a laser for weeds, a water pump
for diseased crops. All inference runs locally on the robot.

## Contents

| Document | Covers |
| --- | --- |
| [MOD01_pathing.md](MOD01_pathing.md) | Arduino line-following + station (marker) detection |
| [MOD02_image_processing.md](MOD02_image_processing.md) | Pi camera capture + YOLO (`best.pt`) detection and ROI crop |
| [MOD03_vlm.md](MOD03_vlm.md) | SmolVLM-256M analysis stage + YOLO→VLM bypass gate |
| [MOD04_decision_motor.md](MOD04_decision_motor.md) | Orchestrator (`pi/main.cpp`) + actuator control on the Arduino |
| [MOD05_dashboard.md](MOD05_dashboard.md) | Read-only web monitoring dashboard |

## Architecture

The system runs as four processes across two boards:

```
 [Arduino: agroai_robot.ino]      line-follow + station stop + actuators (MOD1 + MOD4 act)
        ▲   USB serial 9600
        │   MARKER / RESUMED / ACK            LASER_ON / PUMP_ON / RESUME
        ▼
 [Pi: pi/main]  (main.cpp)         orchestrator — waits for MARKER, drives the cycle (MOD4)
        ▲   Unix socket /tmp/robot_ipc.sock
        │   "CAPTURE"                          decision JSON
        ▼
 [Pi: src/robot_server.py]         camera + YOLO + bypass gate + SmolVLM (MOD2 + MOD3)
        │   writes /tmp/robot_server.log, src/camera_captures/, src/vlm_crops/, src/vlm_output.json
        ▼
 [Pi: src/dashboard.py]            read-only web UI that tails those files (MOD5)
```

Per-plant cycle: the Arduino follows the line until the left IR sensor reads the
black station band → the robot stops, settles for 2 s, and sends `MARKER` →
`pi/main` calls `robot_server.py` over the socket → YOLO classifies the plant and
the bypass gate decides whether to also run the VLM → a decision JSON comes back →
`pi/main` fires the laser (weed) or pump (diseased) on the Arduino, then sends
`RESUME` → the Arduino leaves the band and resumes following until the next
station.

### Run order

```sh
# Pi, terminal 1 — vision server (loads YOLO + VLM once, then waits)
source ~/agroai-env/bin/activate
python3 src/robot_server.py

# Pi, terminal 2 — orchestrator (press ENTER to send START to the Arduino)
cd pi && make && ./main            # ./main /dev/ttyUSB1 to override the port

# Pi, terminal 3 — optional dashboard
python3 src/dashboard.py           # http://<pi-ip>:8000
```

`run_robot.sh` and `run_dashboard.sh` wrap these. If no Arduino is connected,
`pi/main` falls back to a DEMO mode where pressing ENTER simulates a station.

## Source layout

The canonical runtime is the files marked **runtime** below; the rest are
bring-up and test scripts.

| Path | Role | |
| --- | --- | --- |
| `arduino/agroai_robot.ino` | MOD1 line-follow + MOD4 actuators (firmware) | **runtime** |
| `pi/main.cpp` → `pi/main` | MOD4 orchestrator | **runtime** |
| `src/robot_server.py` | MOD2+MOD3 unified vision server | **runtime** |
| `src/mod2_mod3_pipeline.py` | YOLO+VLM pipeline core (`load_yolo` / `run_pipeline_on_image` / `load_vlm_engine`, imported by `robot_server.py`) plus a standalone `--images` CLI test harness | **runtime** core + test CLI |
| `src/vlm/` | MOD3 VLM engine, parser, types | **runtime** (`vlm_engine.py`, `vlm_parser.py`, `vlm_types.py`) |
| `src/dashboard.py` | MOD5 web monitor | **runtime** |
| `pi/controller.cpp` → `pi/controller` | Older stdin→serial bridge, superseded by `main.cpp` | legacy |
| `src/vlm/{demo,benchmark,smoke_test,test_photos,mock_vlm}.py`, `src/vlm/tests/` | VLM dev/test scripts | test |
| `pi/test_integration.py`, `src/test_robot_scenarios.py`, `src/kamera_test.py` | Test / bring-up harnesses | test |
| `src/best.pt` | Trained YOLO weights (3 classes) | model |
