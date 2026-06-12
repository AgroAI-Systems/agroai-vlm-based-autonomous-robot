# MOD-05 — Monitoring Dashboard

**Implementation:** `src/dashboard.py`
**Role in pipeline:** a read-only web UI for watching the robot live — current
state, the latest camera frame, the VLM input crop, and the most recent decision.

It is a single self-contained file using only the Python standard library (no
`pip install` needed) and serves a web page over `http.server`.

## How it observes the robot

The dashboard **never touches the robot code or hardware**. It only reads files
that `robot_server.py` already writes:

| Source | Used for |
| --- | --- |
| `/tmp/robot_server.log` | per-frame "frame captured" + "decision" lines (the run log) |
| `src/camera_captures/*.jpg` | the most recent camera frame |
| `src/vlm_crops/*_vlm_input.jpg` | the most recent crop sent to the VLM |
| `src/vlm_output.json` | the most recent decision (all fields) |
| `/tmp/robot_ipc.sock` (existence) | "vision server is running" indicator — `robot_server.py` creates the socket on start and removes it on exit |

Because it is decoupled this way, the dashboard can be started, stopped, or
refreshed at any time without affecting a run.

## Running

```sh
python3 src/dashboard.py            # default port 8000
python3 src/dashboard.py --port 8080
```

Then open `http://<pi-ip>:8000` from a phone or laptop on the same network (find
the Pi's address with `hostname -I`). `run_dashboard.sh` wraps this.
