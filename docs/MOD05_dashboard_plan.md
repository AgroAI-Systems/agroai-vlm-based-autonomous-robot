# MOD-05 Dashboard — Implementation Plan

Operator dashboard for the weed-elimination robot. Built as a **separate Flask
process** on the Pi that reads the files the pipeline already produces and writes
one control file. Browser polls for updates. No coupling into the C++ pipeline
except a single command channel.

## Decisions

| Choice | Decision |
|--------|----------|
| Stack | Python + Flask (matches `kamera.py` / `vlm_server.py`) |
| Live updates | Browser polling (~1 s) — no WebSocket |
| Scope | Monitoring **+ mission controls** (start/pause/resume/abort) |
| Camera | **On-demand "Take Picture"** (not a live video stream) |

## Architecture

```
browser ──poll──> Flask (app.py) ──reads──> field_report.db / status.json / latest_frame.jpg
   │                   │
   │                   ├──"CAPTURE"──> kamera.py (/tmp/kamera_ipc.sock)   [Take Picture]
   │                   │
   └──POST command──>  └──writes──> command.json ──polled by──> main.cpp (supervised loop)
```

The dashboard never links the pipeline. It reads three files, talks to the
existing camera socket for snapshots, and drops commands in a file the robot
loop polls.

## Data contracts

| Channel | Producer | Status |
|---------|----------|--------|
| `field_report.db` (SQLite) | `main.cpp` | exists |
| `status.json` | `main.cpp` | exists — **extend** with `mission_state`, `uptime_ms` |
| `latest_frame.jpg` | `kamera.py` | exists (annotated frame) |
| `command.json` | **Flask** | new — `{ "cmd": "pause", "ts": ... }` |

## Required pipeline change

`main.cpp`: convert one-shot → **supervised loop** with a mission state machine
`IDLE → RUNNING ⇄ PAUSED → ABORTED`. Each iteration reads `command.json`, applies
`start/pause/resume/abort`, and reflects the state in `status.json`. Since mod1
(line-following) is not integrated, the loop processes one plant per "tick"
(timer, or an explicit `next` command driving a "process next plant" button).
File-driven, no new C++ libraries.

## On-demand "Take Picture"

Button → `POST /api/capture` → Flask opens `/tmp/kamera_ipc.sock`, sends
`CAPTURE`, receives the detection JSON. `kamera.py` writes the annotated
`latest_frame.jpg` and returns `status/conf/class`; the page then fetches
`/frame.jpg` and shows the readout. `main.cpp` (during a mission) and the
dashboard share the socket; `kamera.py` serves one request at a time, so they
serialize. No camera contention.

## Folder layout

```
dashboard/
  app.py                 Flask: routes + DB/file reads + socket capture
  templates/index.html   single-page dashboard
  static/app.js          polling + DOM updates
  static/style.css
  README.md              run instructions
```

## HTTP endpoints

| Route | Method | Purpose |
|-------|--------|---------|
| `/` | GET | dashboard page |
| `/api/status` | GET | `status.json` (live state) |
| `/api/report` | GET | DB rows (`?status=&limit=&newest=1`) |
| `/api/summary` | GET | aggregate counts (healthy/diseased/weed, acted/skipped) |
| `/api/capture` | POST | sends `CAPTURE` to the camera socket; returns detection JSON |
| `/frame.jpg` | GET | latest annotated frame (cache-busted) |
| `/api/command` | POST | writes `command.json` (start/pause/resume/abort/next) |
| `/api/clear` | POST | empties the `field_report` table |

## Frontend panels

1. **Live status** — state, plant ID, mission active, last action, uptime.
2. **Camera** — "Take Picture" button → latest annotated still + detection info.
3. **Latest VLM result** — status, confidence, diagnosis, severity, action.
4. **Run log** — table from `/api/report` + summary counts.
5. **Controls** — Start / Pause / Resume / Abort / Next / Clear-DB.

## Build order (each step independently testable)

1. **Read-only API + page** — `/api/status`, `/api/report`, `/api/summary`,
   `/frame.jpg`. Testable now against a DB populated by running `./main` a few
   times in demo mode.
2. **Frontend** — panels + 1 s polling loop.
3. **Take Picture** — `/api/capture` ↔ camera socket.
4. **Pipeline change** — `main.cpp` supervised loop + `command.json` + extended
   `status.json`.
5. **Wire controls** — `/api/command` ↔ the loop; verify pause halts processing.
6. **Polish** — Clear-DB, client poll-resume/reconnect, styling.

## Dependencies & testing

- `pip install flask` (SQLite is stdlib). No new C++ libraries.
- Steps 1–3 verifiable off-robot with an existing `.db` and a captured frame;
  steps 4–5 need the Pi (or demo-mode `main` on Linux).

## Notes / risks

- Only coupling is `command.json` ↔ `main.cpp`; everything else is read-only.
- `main.cpp` stays the sole SQLite writer; Flask uses read-only connections — no
  contention.
- No authentication — lab/demo network only.
