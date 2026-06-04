#!/usr/bin/env python3
"""
dashboard.py — AgroAI canli izleme paneli (web tabanli, salt-okunur)

Robot kodunu HIC degistirmez. Sadece su dosyalari okur:
    /tmp/robot_server.log        -> her kare icin "kare yakalandi" + "karar" satirlari
    src/camera_captures/*.jpg    -> en son cekilen kamera karesi
    src/vlm_crops/*_vlm_input.jpg-> en son VLM giris kirpintisi
    src/vlm_output.json          -> en son karar (tum alanlar)

Tek dosya, sadece Python standart kutuphanesi (pip install GEREKMEZ).

Calistirma:
    python3 dashboard.py            # varsayilan port 8000
    python3 dashboard.py --port 8080

Telefon/laptop tarayicidan ac:
    http://<pi-ip>:8000      (Pi IP'si icin:  hostname -I)

Gelistirici: dashboard — CSE396 Group 9
"""

import argparse
import json
import os
import re
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# --- Yollar (bu dosya src/ icinde) ---
SRC_DIR      = Path(__file__).resolve().parent
LOG_PATH     = Path("/tmp/robot_server.log")
# robot_server.py bu soketi acilista olusturur, kapanista siler ->
# "sunucu calisiyor" sinyali olarak guvenilir (log dosyasi kapaninca da kalir)
SOCKET_PATH  = Path("/tmp/robot_ipc.sock")
CAPTURE_DIR  = SRC_DIR / "camera_captures"
CROPS_DIR    = SRC_DIR / "vlm_crops"
DECISION_JSON = SRC_DIR / "vlm_output.json"

# Robotu baslatma/durdurma (mevcut run_robot.sh'i cagirir, robot kodu degismez)
ROOT_DIR     = SRC_DIR.parent
RUN_SCRIPT   = ROOT_DIR / "run_robot.sh"
LAUNCH_LOG   = Path("/tmp/robot_launch.log")

# --- Log satir desenleri ---
RE_TIME    = re.compile(r"^(\d{2}:\d{2}:\d{2})")
RE_CAPTURE = re.compile(r"\[(\d+)\]\s*kare yakalandi\s*->\s*(\S+)")
RE_DECISION = re.compile(r"karar\s*->\s*status=(\w+)\s+action=(\w+)\s+conf=([\d.]+)")
RE_TOTAL   = re.compile(r"toplam=(\d+)ms")

# Panelde "bypass" gecen hicbir sey gosterilmez (kullanici istegi)
BYPASS_WORD = re.compile(r"bypass", re.IGNORECASE)

# action -> fiziksel robot durumu
ACTION_STATE = {
    "spray": ("PUMP", "Ilaclama yapiliyor"),
    "laser": ("LASER", "Yabani ot yakiliyor"),
    "skip":  ("IDLE", "Hareket / bekleme"),
}


def _sanitize_diagnosis(text: str) -> str:
    """Teshis metninden 'bypass' iceren ifadeleri temizle."""
    if not text:
        return ""
    if BYPASS_WORD.search(text):
        # "yolo_bypass: class=DISEASED conf=0.36 (VLM not invoked)" gibi -> sadelestir
        m = re.search(r"class=(\w+)\s+conf=([\d.]+)", text)
        if m:
            return f"YOLO siniflandirma: {m.group(1)} (conf {m.group(2)})"
        return "YOLO siniflandirma"
    return text


def _latest_file(directory: Path, pattern: str = "*.jpg"):
    """Klasordeki en son degisen dosyayi dondur (yoksa None)."""
    if not directory.is_dir():
        return None
    files = list(directory.glob(pattern))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _read_log():
    """Log dosyasini parse et: history, stats, son log satirlari."""
    history = []
    log_tail = []
    if not LOG_PATH.exists():
        return history, log_tail

    try:
        lines = LOG_PATH.read_text(errors="replace").splitlines()
    except Exception:
        return history, log_tail

    cur = {"idx": None, "file": None, "total_ms": None}
    for line in lines:
        cap = RE_CAPTURE.search(line)
        if cap:
            cur = {"idx": int(cap.group(1)), "file": cap.group(2), "total_ms": None}
            continue

        tot = RE_TOTAL.search(line)
        if tot:
            cur["total_ms"] = int(tot.group(1))
            continue

        dec = RE_DECISION.search(line)
        if dec:
            tm = RE_TIME.match(line)
            history.append({
                "time":   tm.group(1) if tm else "",
                "idx":    cur["idx"],
                "file":   cur["file"],
                "status": dec.group(1).lower(),
                "action": dec.group(2).lower(),
                "conf":   float(dec.group(3)),
                "total_ms": cur["total_ms"],
            })

    # Canli log akisi: bypass iceren satirlari gizle, son 60 satir
    for line in lines:
        if line.strip() and not BYPASS_WORD.search(line):
            log_tail.append(line)
    log_tail = log_tail[-60:]

    return history, log_tail


def _build_stats(history):
    status_counts = {"healthy": 0, "diseased": 0, "weed": 0, "unknown": 0}
    action_counts = {"spray": 0, "laser": 0, "skip": 0}
    times = []
    for h in history:
        status_counts[h["status"]] = status_counts.get(h["status"], 0) + 1
        action_counts[h["action"]] = action_counts.get(h["action"], 0) + 1
        if h["total_ms"]:
            times.append(h["total_ms"])
    avg_ms = int(sum(times) / len(times)) if times else 0
    return {
        "total_frames":  len(history),
        "status_counts": status_counts,
        "action_counts": action_counts,
        "avg_total_ms":  avg_ms,
    }


def _build_state():
    history, log_tail = _read_log()
    stats = _build_stats(history)

    # En son karar (zengin alanlar) — vlm_output.json
    decision = None
    if DECISION_JSON.exists():
        try:
            decision = json.loads(DECISION_JSON.read_text())
            decision["diagnosis"] = _sanitize_diagnosis(decision.get("diagnosis", ""))
        except Exception:
            decision = None

    # Fiziksel robot durumu — en son action'dan turet
    last_action = history[-1]["action"] if history else (
        (decision or {}).get("action", "")
    )
    robot_state, robot_desc = ACTION_STATE.get(last_action, ("IDLE", "Bekleniyor"))

    cap = _latest_file(CAPTURE_DIR)
    crop = _latest_file(CROPS_DIR, "*_vlm_input.jpg")

    return {
        "server_up":   SOCKET_PATH.exists(),
        "robot_run":   ROBOT.run_state(),
        "launch_tail": _launch_tail(),
        "console":     _robot_console(),
        "decision":    decision,
        "stats":       stats,
        "history":     history[-40:][::-1],   # en yeni ustte, son 40
        "log":         log_tail,
        "robot_state": robot_state,
        "robot_desc":  robot_desc,
        "last_capture_idx": history[-1]["idx"] if history else None,
        "has_capture": cap is not None,
        "has_crop":    crop is not None,
        "capture_mtime": int(cap.stat().st_mtime) if cap else 0,
        "crop_mtime":  int(crop.stat().st_mtime) if crop else 0,
    }


# Pi masaustunde acilacak gercek terminal pencereleri icin gecici betikler
ROBOT_TERM_SH  = Path("/tmp/agroai_robot_term.sh")
SERVER_TERM_SH = Path("/tmp/agroai_server_term.sh")

# Stop'ta kapatilacak surec desenleri
KILL_PATTERNS = (
    "run_robot.sh",
    "robot_server.py",
    f"{ROOT_DIR}/pi/main",
    f"-F {LOG_PATH}",          # vision sunucu tail penceresi
)


def _pick_terminal():
    """Kurulu terminal emulatorunu sec (Pi'de lxterminal varsayilan)."""
    for path in ("/usr/bin/lxterminal", "/usr/bin/x-terminal-emulator"):
        if Path(path).exists():
            return path
    return None


def _term_cmd(term_bin: str, title: str, script: Path):
    """Secilen emulator icin 'baslikli pencerede bu betigi calistir' komutu."""
    if term_bin.endswith("lxterminal"):
        return [term_bin, f"--title={title}", f"--command=bash {script}"]
    # x-terminal-emulator (Debian alternatifi) ve cogu emulator -e destekler
    return [term_bin, "-T", title, "-e", "bash", str(script)]


def _gui_env():
    """Masaustu (Wayland/labwc + XWayland) oturumuna ulasmak icin ortam."""
    env = dict(os.environ)
    uid = os.getuid()
    rt = f"/run/user/{uid}"
    env.setdefault("XDG_RUNTIME_DIR", rt)
    env.setdefault("WAYLAND_DISPLAY", "wayland-0")
    env.setdefault("DISPLAY", ":0")
    env.setdefault("XDG_SESSION_TYPE", "wayland")
    # GUI uygulamalarinin oturum veri yoluna ulasmasi icin sart
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={rt}/bus")
    return env


def _clear_stale_lxterminal_socket():
    """Olu lxterminal tek-ornek soketi yeni pencere acmayi sessizce engelleyebilir.
    Calisan bir lxterminal yoksa bayat soketi temizle."""
    r = subprocess.run(["pgrep", "-x", "lxterminal"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if r.returncode == 0:
        return  # canli server var -> dokunma
    uid = os.getuid()
    wd = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
    for sock in (f"/run/user/{uid}/.lxterminal-socket-{wd}",
                 f"/run/user/{uid}/.lxterminal-socket-:0"):
        try:
            os.remove(sock)
        except OSError:
            pass


class RobotController:
    """run_robot.sh'i Pi masaustunde GERCEK terminal pencerelerinde acar.

    Pencere 1 (AgroAI - Robot)        : run_robot.sh (orkestrator/pi/main, interaktif)
                                        cikti ayrica /tmp/robot_launch.log'a tee edilir
    Pencere 2 (AgroAI - Vision Sunucu): /tmp/robot_server.log canli takibi
    Robot kodu HIC degismez; sadece mevcut run_robot.sh cagirilir.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._start_ts = 0.0

    @staticmethod
    def _robot_proc_alive() -> bool:
        r = subprocess.run(["pgrep", "-f", "run_robot.sh"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return r.returncode == 0

    def _write_scripts(self):
        ROBOT_TERM_SH.write_text(
            "#!/usr/bin/env bash\n"
            f"cd '{ROOT_DIR}'\n"
            "echo '=== AgroAI · Robot (run_robot.sh) ==='\n"
            f"./run_robot.sh 2>&1 | tee '{LAUNCH_LOG}'\n"
            "echo\n"
            "read -p '[Robot durdu — pencereyi kapatmak icin Enter] '\n"
        )
        SERVER_TERM_SH.write_text(
            "#!/usr/bin/env bash\n"
            "echo '=== AgroAI · Vision Sunucu (canli) ==='\n"
            f"for i in $(seq 1 180); do [ -f '{LOG_PATH}' ] && break; sleep 1; done\n"
            f"tail -n +1 -F '{LOG_PATH}'\n"
        )

    def start(self, terminals: bool = True):
        with self._lock:
            if SOCKET_PATH.exists():
                return False, "robot zaten calisiyor"
            if self._robot_proc_alive():
                return False, "robot zaten baslatiliyor"
            if not RUN_SCRIPT.exists():
                return False, f"run_robot.sh bulunamadi: {RUN_SCRIPT}"

            term = _pick_terminal() if terminals else None

            try:
                LAUNCH_LOG.write_text("")      # eski cikti temizle

                if terminals and term is not None:
                    # --- Pi masaustunde GERCEK terminal pencereleri ---
                    self._write_scripts()
                    if term.endswith("lxterminal"):
                        _clear_stale_lxterminal_socket()
                    env = _gui_env()
                    # Once sunucu penceresi (log dosyasini bekler), sonra robot penceresi
                    subprocess.Popen(_term_cmd(term, "AgroAI · Vision Sunucu", SERVER_TERM_SH),
                                     env=env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
                    subprocess.Popen(_term_cmd(term, "AgroAI · Robot", ROBOT_TERM_SH),
                                     env=env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
                    msg = "terminal pencereleri acildi (Pi ekraninda)"
                else:
                    # --- Headless: pencere yok, cikti tarayici panelinde gorunur ---
                    logf = open(LAUNCH_LOG, "w")
                    subprocess.Popen(["bash", str(RUN_SCRIPT)],
                                     cwd=str(ROOT_DIR), stdin=subprocess.DEVNULL,
                                     stdout=logf, stderr=subprocess.STDOUT,
                                     start_new_session=True)
                    if terminals and term is None:
                        msg = "terminal emulatoru yok -> headless basladi (panelde izle)"
                    else:
                        msg = "headless basladi (cikti tarayici panelinde)"
            except Exception as exc:
                return False, f"baslatilamadi: {exc}"

            self._start_ts = time.time()
            return True, msg

    def stop(self):
        with self._lock:
            self._start_ts = 0.0
            # Robot proseslerini kapat -> run_robot.sh EXIT trap'i sunucuyu temizler
            for pat in KILL_PATTERNS:
                subprocess.run(["pkill", "-f", pat],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, "durduruldu (terminal pencerelerini elle kapatabilirsin)"

    def run_state(self) -> str:
        if SOCKET_PATH.exists():
            return "running"                                  # soket var -> hazir
        if (time.time() - self._start_ts) < 120 and self._robot_proc_alive():
            return "starting"                                 # yukleniyor
        return "stopped"


ROBOT = RobotController()


def _launch_tail(n: int = 12):
    """Baslatma logunun son satirlari (hata teshisi icin)."""
    if not LAUNCH_LOG.exists():
        return []
    try:
        return LAUNCH_LOG.read_text(errors="replace").splitlines()[-n:]
    except Exception:
        return []


def _robot_console(n: int = 120):
    """Orkestrator terminali: run_robot.sh + pi/main ciktisi (bypass gizli)."""
    if not LAUNCH_LOG.exists():
        return []
    try:
        lines = LAUNCH_LOG.read_text(errors="replace").splitlines()
    except Exception:
        return []
    return [l for l in lines if l.strip() and not BYPASS_WORD.search(l)][-n:]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # erisim loglarini sustur

    def _send(self, code, content_type, body, extra_headers=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_image(self, path: Path):
        if path is None or not path.exists():
            self._send(404, "text/plain", b"no image")
            return
        try:
            self._send(200, "image/jpeg", path.read_bytes())
        except Exception:
            self._send(404, "text/plain", b"read error")

    def do_GET(self):
        route = self.path.split("?", 1)[0]

        if route == "/":
            self._send(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
        elif route == "/api/state":
            body = json.dumps(_build_state(), ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
        elif route == "/api/image/capture":
            self._send_image(_latest_file(CAPTURE_DIR))
        elif route == "/api/image/crop":
            self._send_image(_latest_file(CROPS_DIR, "*_vlm_input.jpg"))
        else:
            self._send(404, "text/plain", b"not found")

    def do_POST(self):
        parts = self.path.split("?", 1)
        route = parts[0]
        query = parts[1] if len(parts) > 1 else ""
        if route == "/api/start":
            # terminals=0 -> headless, aksi halde gercek terminal pencereleri
            terminals = "terminals=0" not in query
            ok, msg = ROBOT.start(terminals=terminals)
        elif route == "/api/stop":
            ok, msg = ROBOT.stop()
        else:
            self._send(404, "text/plain", b"not found")
            return
        body = json.dumps({"ok": ok, "msg": msg}, ensure_ascii=False).encode("utf-8")
        self._send(200, "application/json; charset=utf-8", body)


PAGE = r"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgroAI — Canli Panel</title>
<style>
  :root{
    --bg:#0d1410; --panel:#16201a; --panel2:#1d2b22; --line:#2a3b30;
    --txt:#dbe7df; --muted:#7f9587; --accent:#4ade80; --accent2:#22c55e;
    --healthy:#4ade80; --diseased:#f87171; --weed:#fb923c; --unknown:#9ca3af;
    --pump:#38bdf8; --laser:#f87171; --idle:#9ca3af;
  }
  *{box-sizing:border-box}
  body{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;
       background:var(--bg);color:var(--txt);font-size:14px}
  header{display:flex;align-items:center;gap:14px;padding:14px 20px;
         background:linear-gradient(90deg,#10221a,#0d1410);border-bottom:1px solid var(--line)}
  header h1{font-size:18px;margin:0;font-weight:700;letter-spacing:.5px}
  header .leaf{font-size:22px}
  .pill{margin-left:auto;display:flex;align-items:center;gap:8px;font-size:13px;color:var(--muted)}
  .dot{width:10px;height:10px;border-radius:50%;background:var(--idle)}
  .dot.up{background:var(--accent);box-shadow:0 0 8px var(--accent)}
  .grid{display:grid;gap:14px;padding:16px;max-width:1280px;margin:0 auto;
        grid-template-columns:1fr 1fr}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px}
  .card h2{margin:0 0 12px;font-size:13px;text-transform:uppercase;letter-spacing:1px;color:var(--muted)}
  .span2{grid-column:1 / -1}

  /* robot state banner */
  .robot{display:flex;align-items:center;gap:18px}
  .robot .badge{font-size:26px;font-weight:800;padding:10px 20px;border-radius:10px;
                background:var(--panel2);border:1px solid var(--line)}
  .robot .badge.PUMP{color:var(--pump);border-color:var(--pump)}
  .robot .badge.LASER{color:var(--laser);border-color:var(--laser)}
  .robot .badge.IDLE{color:var(--idle)}
  .robot .desc{font-size:15px;color:var(--muted)}
  .controls{margin-left:auto;display:flex;flex-direction:column;gap:8px;align-items:flex-end}
  .ctl-row{display:flex;gap:8px}
  .btn{font-size:14px;font-weight:700;padding:10px 18px;border-radius:9px;border:1px solid var(--line);
       cursor:pointer;background:var(--panel2);color:var(--txt);transition:.15s}
  .btn:hover:not(:disabled){filter:brightness(1.15)}
  .btn:disabled{opacity:.35;cursor:not-allowed}
  .btn.start{background:var(--accent2);border-color:var(--accent2);color:#06140c}
  .btn.stop{background:#3a1d1d;border-color:var(--laser);color:var(--laser)}
  .runmsg{font-size:12px;color:var(--muted);min-height:16px;text-align:right;max-width:320px}
  .chk{font-size:12px;color:var(--muted);display:flex;align-items:center;gap:6px;cursor:pointer;user-select:none}
  .chk input{accent-color:var(--accent2);cursor:pointer}

  /* decision */
  .dec-status{font-size:34px;font-weight:800;text-transform:uppercase;letter-spacing:1px}
  .s-healthy{color:var(--healthy)} .s-diseased{color:var(--diseased)}
  .s-weed{color:var(--weed)} .s-unknown{color:var(--unknown)}
  .dec-row{display:flex;gap:24px;flex-wrap:wrap;margin-top:10px}
  .kv{display:flex;flex-direction:column}
  .kv .k{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
  .kv .v{font-size:18px;font-weight:600}
  .diag{margin-top:12px;padding:10px 12px;background:var(--panel2);border-radius:8px;
        font-size:13px;color:var(--muted);min-height:18px}
  .conf-bar{height:8px;background:var(--panel2);border-radius:4px;overflow:hidden;margin-top:6px}
  .conf-bar > div{height:100%;background:var(--accent2);width:0%}

  /* images */
  .imgwrap{position:relative;background:#000;border-radius:8px;overflow:hidden;
           aspect-ratio:16/9;display:flex;align-items:center;justify-content:center}
  .imgwrap img{width:100%;height:100%;object-fit:contain}
  .imgwrap .empty{color:var(--muted);font-size:13px}
  .imgcap{font-size:11px;color:var(--muted);margin-top:6px}
  .imgrow{display:grid;grid-template-columns:2fr 1fr;gap:12px}
  .crop .imgwrap{aspect-ratio:1/1}

  /* stats */
  .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
  .stat{background:var(--panel2);border-radius:8px;padding:12px;text-align:center}
  .stat .n{font-size:26px;font-weight:800}
  .stat .l{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-top:2px}
  .stat.healthy .n{color:var(--healthy)} .stat.diseased .n{color:var(--diseased)}
  .stat.weed .n{color:var(--weed)}
  .bars{margin-top:14px;display:flex;flex-direction:column;gap:8px}
  .bar{display:flex;align-items:center;gap:8px;font-size:12px}
  .bar .lab{width:60px;color:var(--muted);text-transform:capitalize}
  .bar .track{flex:1;height:14px;background:var(--panel2);border-radius:7px;overflow:hidden}
  .bar .fill{height:100%;border-radius:7px}
  .fill.spray{background:var(--pump)} .fill.laser{background:var(--laser)} .fill.skip{background:var(--idle)}
  .bar .cnt{width:30px;text-align:right;font-weight:600}

  /* history table */
  table{width:100%;border-collapse:collapse;font-size:12px}
  th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line)}
  th{color:var(--muted);text-transform:uppercase;font-size:10px;letter-spacing:.5px}
  .tag{padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
  .tag.healthy{background:rgba(74,222,128,.15);color:var(--healthy)}
  .tag.diseased{background:rgba(248,113,113,.15);color:var(--diseased)}
  .tag.weed{background:rgba(251,146,60,.15);color:var(--weed)}
  .tag.unknown{background:rgba(156,163,175,.15);color:var(--unknown)}
  .hist-scroll{max-height:300px;overflow:auto}

  /* log */
  .log{background:#0a0f0c;border-radius:8px;padding:10px;font-family:ui-monospace,Menlo,Consolas,monospace;
       font-size:11.5px;line-height:1.5;max-height:260px;overflow:auto;white-space:pre-wrap;color:#9fb3a6}
  @media(max-width:880px){.grid{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<header>
  <span class="leaf">🌱</span>
  <h1>AgroAI &mdash; Otonom Robot Canli Panel</h1>
  <div class="pill"><span id="dot" class="dot"></span><span id="srv">baglaniyor...</span></div>
</header>

<div class="grid">
  <!-- Robot state -->
  <div class="card span2">
    <h2>Robot Durumu</h2>
    <div class="robot">
      <div id="robotBadge" class="badge IDLE">IDLE</div>
      <div>
        <div id="robotDesc" class="desc">&mdash;</div>
        <div class="imgcap" id="frameInfo">kare: &mdash;</div>
      </div>
      <div class="controls">
        <div class="ctl-row">
          <button id="btnStart" class="btn start">&#9654; Robotu Baslat</button>
          <button id="btnStop" class="btn stop">&#9632; Durdur</button>
        </div>
        <label class="chk"><input type="checkbox" id="chkTerm" checked>
          Pi ekraninda terminal pencereleri ac</label>
        <div class="runmsg" id="runMsg">&mdash;</div>
      </div>
    </div>
  </div>

  <!-- Current decision -->
  <div class="card">
    <h2>Guncel Karar</h2>
    <div id="decStatus" class="dec-status s-unknown">&mdash;</div>
    <div class="conf-bar"><div id="confFill"></div></div>
    <div class="dec-row">
      <div class="kv"><span class="k">Guven</span><span class="v" id="decConf">&mdash;</span></div>
      <div class="kv"><span class="k">Aksiyon</span><span class="v" id="decAction">&mdash;</span></div>
      <div class="kv"><span class="k">Siddet</span><span class="v" id="decSev">&mdash;</span></div>
      <div class="kv"><span class="k">Sure</span><span class="v" id="decTime">&mdash;</span></div>
    </div>
    <div class="diag" id="decDiag">&mdash;</div>
  </div>

  <!-- Camera + crop -->
  <div class="card">
    <h2>Canli Goruntu</h2>
    <div class="imgrow">
      <div>
        <div class="imgwrap"><img id="capImg" alt=""><span class="empty" id="capEmpty">goruntu yok</span></div>
        <div class="imgcap">Kamera karesi</div>
      </div>
      <div class="crop">
        <div class="imgwrap"><img id="cropImg" alt=""><span class="empty" id="cropEmpty">yok</span></div>
        <div class="imgcap">VLM girisi</div>
      </div>
    </div>
  </div>

  <!-- Stats -->
  <div class="card">
    <h2>Istatistikler</h2>
    <div class="stats">
      <div class="stat"><div class="n" id="stTotal">0</div><div class="l">Toplam Kare</div></div>
      <div class="stat healthy"><div class="n" id="stHealthy">0</div><div class="l">Saglikli</div></div>
      <div class="stat diseased"><div class="n" id="stDiseased">0</div><div class="l">Hastalikli</div></div>
      <div class="stat weed"><div class="n" id="stWeed">0</div><div class="l">Yabani Ot</div></div>
    </div>
    <div class="bars" id="actionBars"></div>
    <div class="imgcap" style="margin-top:12px">Ortalama islem suresi: <b id="avgMs">&mdash;</b></div>
  </div>

  <!-- Log -->
  <div class="card">
    <h2>Vision Sunucu Terminali</h2>
    <div class="log" id="logBox">log bekleniyor...</div>
  </div>

  <!-- Orchestrator console -->
  <div class="card span2">
    <h2>Robot / Orkestrator Terminali</h2>
    <div class="log" id="consoleBox">terminal cikti bekleniyor... (Baslat butonu ile dolar)</div>
  </div>

  <!-- History -->
  <div class="card span2">
    <h2>Karar Gecmisi</h2>
    <div class="hist-scroll">
      <table>
        <thead><tr><th>Saat</th><th>#</th><th>Durum</th><th>Aksiyon</th><th>Guven</th><th>Sure</th></tr></thead>
        <tbody id="histBody"><tr><td colspan="6" style="color:var(--muted)">veri yok</td></tr></tbody>
      </table>
    </div>
  </div>
</div>

<script>
let lastCap = -1, lastCrop = -1;
let pending = false;   // start/stop POST sirasinda buton durumunu kilitle

function setText(id, v){ document.getElementById(id).textContent = v; }

const btnStart = document.getElementById('btnStart');
const btnStop  = document.getElementById('btnStop');

btnStart.onclick = async () => {
  if(!confirm('Robot baslatilacak. Kamera, LAZER ve POMPA aktif olabilir. Emin misin?')) return;
  pending = true;
  btnStart.disabled = true; btnStop.disabled = true;
  setText('runMsg', 'baslatma komutu gonderildi...');
  const term = document.getElementById('chkTerm').checked ? 1 : 0;
  try{
    const r = await fetch('/api/start?terminals=' + term, {method:'POST'});
    const j = await r.json();
    setText('runMsg', j.msg || '');
  }catch(e){ setText('runMsg', 'baslatma hatasi'); }
  pending = false;
};

btnStop.onclick = async () => {
  if(!confirm('Robot durdurulacak. Emin misin?')) return;
  pending = true;
  btnStart.disabled = true; btnStop.disabled = true;
  setText('runMsg', 'durduruluyor...');
  try{
    const r = await fetch('/api/stop', {method:'POST'});
    const j = await r.json();
    setText('runMsg', j.msg || '');
  }catch(e){ setText('runMsg', 'durdurma hatasi'); }
  pending = false;
};

function updateControls(s){
  if(pending) return;   // kullanici islemi beklerken dokunma
  const st = s.robot_run;
  if(st === 'running'){
    btnStart.disabled = true;  btnStop.disabled = false;
    setText('runMsg', 'robot calisiyor');
  }else if(st === 'starting'){
    btnStart.disabled = true;  btnStop.disabled = false;
    setText('runMsg', 'baslatiliyor — model + kamera yukleniyor (~15-25s)...');
  }else{ // stopped
    btnStart.disabled = false; btnStop.disabled = true;
    const tail = (s.launch_tail || []).filter(x => x.trim());
    const last = tail.length ? tail[tail.length - 1] : '';
    setText('runMsg', last ? ('durdu — son: ' + last.slice(0, 70)) : 'robot durdu');
  }
}

function pct(x){ return Math.round((x||0)*100); }

async function tick(){
  let s;
  try{
    const r = await fetch('/api/state', {cache:'no-store'});
    s = await r.json();
  }catch(e){
    document.getElementById('dot').className='dot';
    setText('srv','panel hatasi');
    return;
  }

  // server status
  document.getElementById('dot').className = s.server_up ? 'dot up' : 'dot';
  setText('srv', s.server_up ? 'sunucu calisiyor' : 'sunucu kapali');

  // start/stop kontrolleri
  updateControls(s);

  // robot state
  const badge = document.getElementById('robotBadge');
  badge.textContent = s.robot_state;
  badge.className = 'badge ' + s.robot_state;
  setText('robotDesc', s.robot_desc);
  setText('frameInfo', 'kare: ' + (s.last_capture_idx ?? '—'));

  // decision
  const d = s.decision;
  if(d){
    const st = (d.status||'unknown');
    const el = document.getElementById('decStatus');
    el.textContent = st;
    el.className = 'dec-status s-' + st;
    setText('decConf', pct(d.confidence) + '%');
    document.getElementById('confFill').style.width = pct(d.confidence) + '%';
    setText('decAction', (d.action||'—'));
    setText('decSev', (d.severity||'—'));
    setText('decTime', (d.inference_time_ms ? d.inference_time_ms+' ms' : '—'));
    setText('decDiag', d.diagnosis || '—');
  }

  // stats
  const sc = s.stats.status_counts, ac = s.stats.action_counts;
  setText('stTotal', s.stats.total_frames);
  setText('stHealthy', sc.healthy||0);
  setText('stDiseased', sc.diseased||0);
  setText('stWeed', sc.weed||0);
  setText('avgMs', s.stats.avg_total_ms ? s.stats.avg_total_ms+' ms' : '—');

  const maxA = Math.max(1, ac.spray||0, ac.laser||0, ac.skip||0);
  const bars = [['spray', ac.spray||0], ['laser', ac.laser||0], ['skip', ac.skip||0]];
  document.getElementById('actionBars').innerHTML = bars.map(([k,v]) =>
    `<div class="bar"><span class="lab">${k}</span><span class="track">`+
    `<span class="fill ${k}" style="width:${(v/maxA*100)}%"></span></span>`+
    `<span class="cnt">${v}</span></div>`).join('');

  // history
  const hb = document.getElementById('histBody');
  if(s.history.length){
    hb.innerHTML = s.history.map(h =>
      `<tr><td>${h.time||''}</td><td>${h.idx ?? ''}</td>`+
      `<td><span class="tag ${h.status}">${h.status}</span></td>`+
      `<td>${h.action}</td><td>${pct(h.conf)}%</td>`+
      `<td>${h.total_ms ? h.total_ms+' ms' : '—'}</td></tr>`).join('');
  }

  // log panels (alttayken otomatik kaydir)
  function fillLog(el, lines, empty){
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 20;
    el.textContent = (lines && lines.length) ? lines.join('\n') : empty;
    if(atBottom) el.scrollTop = el.scrollHeight;
  }
  fillLog(document.getElementById('logBox'), s.log, 'log bekleniyor...');
  fillLog(document.getElementById('consoleBox'), s.console,
          'terminal cikti bekleniyor... (Baslat butonu ile dolar)');

  // images (sadece degisince yenile -> titreme yok)
  if(s.has_capture && s.capture_mtime !== lastCap){
    lastCap = s.capture_mtime;
    const img = document.getElementById('capImg');
    img.src = '/api/image/capture?t=' + lastCap;
    img.style.display='block';
    document.getElementById('capEmpty').style.display='none';
  }
  if(s.has_crop && s.crop_mtime !== lastCrop){
    lastCrop = s.crop_mtime;
    const img = document.getElementById('cropImg');
    img.src = '/api/image/crop?t=' + lastCrop;
    img.style.display='block';
    document.getElementById('cropEmpty').style.display='none';
  }
}

tick();
setInterval(tick, 1500);
</script>
</body>
</html>
"""


def _local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    ap = argparse.ArgumentParser(description="AgroAI canli izleme paneli")
    ap.add_argument("--port", type=int, default=8000, help="HTTP port (varsayilan 8000)")
    ap.add_argument("--host", default="0.0.0.0", help="bind adresi (varsayilan tum arayuzler)")
    args = ap.parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    ip = _local_ip()
    print("=" * 56)
    print("  AgroAI Dashboard calisiyor (salt-okunur, robot kodu degismedi)")
    print(f"  Bu cihazda : http://localhost:{args.port}")
    print(f"  Aginizda   : http://{ip}:{args.port}")
    print("  Durdurmak icin: Ctrl+C")
    print("=" * 56)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nkapatiliyor...")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
