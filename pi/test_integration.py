#!/usr/bin/env python3
"""
test_integration.py — Tam sistem entegrasyon testi (DONANIM GEREKTIRMEZ)

Gercek donanim olmadan main.cpp'nin uctan uca akisini dogrular:

  [Sahte Arduino]            [./pi/main]              [Sahte vision sunucusu]
   (PTY uzerinden)   <serial>             <unix socket>
   READY ----------------->
   MARKER ---------------->  CAPTURE ----------------->
                            <----------------- decision JSON
                  <-------  LASER_ON / PUMP_ON
                  <-------  LASER_OFF / PUMP_OFF
                  <-------  RESUME
   MARKER (2. istasyon) ->  ... (spray akisi) ...

Iki istasyon test edilir:
  Istasyon 1: decision action=laser  -> LASER_ON, LASER_OFF, RESUME beklenir
  Istasyon 2: decision action=spray  -> PUMP_ON, PUMP_OFF, RESUME beklenir

Calistirma:
    python3 pi/test_integration.py
"""

import os
import pty
import json
import time
import socket
import threading
import subprocess
import sys
from pathlib import Path

PI_DIR = Path(__file__).parent
MAIN_BIN = PI_DIR / "main"
SOCK_PATH = "/tmp/robot_ipc.sock"

# Sirayla servis edilecek kararlar (her CAPTURE bir sonrakini alir)
DECISIONS = [
    {"status": "weed", "confidence": 0.91, "diagnosis": "weed detected",
     "action": "laser", "severity": "none", "target_position": "center",
     "inference_time_ms": 0},
    {"status": "diseased", "confidence": 0.66, "diagnosis": "scab symptoms",
     "action": "spray", "severity": "medium", "target_position": "center",
     "inference_time_ms": 1200},
]

results = {"captures": 0, "errors": []}


# ---------------------------------------------------------------------------
# Sahte vision sunucusu (robot_server.py yerine) — unix socket
# ---------------------------------------------------------------------------
def mock_vision_server(stop_evt):
    if os.path.exists(SOCK_PATH):
        os.remove(SOCK_PATH)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK_PATH)
    srv.listen(2)
    srv.settimeout(0.5)
    idx = 0
    while not stop_evt.is_set():
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        try:
            data = conn.recv(1024).decode().strip()
            if data == "CAPTURE":
                decision = DECISIONS[min(idx, len(DECISIONS) - 1)]
                idx += 1
                results["captures"] += 1
                conn.sendall(json.dumps(decision).encode())
        finally:
            conn.close()
    srv.close()
    if os.path.exists(SOCK_PATH):
        os.remove(SOCK_PATH)


# ---------------------------------------------------------------------------
# PTY satir okuyucu
# ---------------------------------------------------------------------------
class SerialMock:
    def __init__(self, master_fd):
        self.fd = master_fd
        self.buf = b""

    def write_line(self, s):
        os.write(self.fd, (s + "\n").encode())

    def read_line(self, timeout_s):
        """master_fd'den bir satir oku (main'in serial'e yazdiklari)."""
        import select
        end = time.time() + timeout_s
        while True:
            nl = self.buf.find(b"\n")
            if nl != -1:
                line = self.buf[:nl].decode(errors="replace").strip()
                self.buf = self.buf[nl + 1:]
                return line
            remaining = end - time.time()
            if remaining <= 0:
                return None
            r, _, _ = select.select([self.fd], [], [], remaining)
            if r:
                try:
                    chunk = os.read(self.fd, 256)
                    if chunk:
                        self.buf += chunk
                except OSError:
                    return None


def expect_sequence(serial, expected_prefixes, timeout_s=10):
    """main'in serial'e yazdigi satirlarin beklenen sirada gelmesini dogrula."""
    got = []
    for prefix in expected_prefixes:
        deadline = time.time() + timeout_s
        while True:
            line = serial.read_line(max(0.1, deadline - time.time()))
            if line is None:
                results["errors"].append(
                    f"BEKLENEN '{prefix}' gelmedi. Gelenler: {got}")
                return False, got
            got.append(line)
            if line.startswith(prefix):
                break
    return True, got


# ---------------------------------------------------------------------------
# Ana test
# ---------------------------------------------------------------------------
def main():
    if not MAIN_BIN.exists():
        print(f"HATA: {MAIN_BIN} yok. Once derle: make -C pi")
        return 1

    print("=" * 60)
    print("  AgroAI — Tam Sistem Entegrasyon Testi (mock)")
    print("=" * 60)

    stop_evt = threading.Event()
    srv_thread = threading.Thread(target=mock_vision_server, args=(stop_evt,), daemon=True)
    srv_thread.start()
    time.sleep(0.3)  # sunucu hazir olsun

    # PTY: sahte seri port
    master_fd, slave_fd = pty.openpty()
    slave_name = os.ttyname(slave_fd)
    print(f"[test] sahte seri port: {slave_name}")

    # main'i bu porta bagli baslat
    proc = subprocess.Popen(
        [str(MAIN_BIN), slave_name],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )

    serial = SerialMock(master_fd)
    ok = True

    try:
        # main 2s Arduino-reset bekler + flush eder; sonra READY arar.
        time.sleep(2.6)
        serial.write_line("READY")
        time.sleep(0.3)

        # ---- ISTASYON 1: laser ----
        print("\n[test] Istasyon 1 — MARKER gonderiliyor (laser bekleniyor)...")
        serial.write_line("MARKER")
        s1_ok, seq1 = expect_sequence(
            serial, ["LASER_ON", "LASER_OFF", "RESUME"], timeout_s=12)
        print(f"[test] Istasyon 1 serial: {seq1}")
        ok &= s1_ok
        if s1_ok:
            print("[test] Istasyon 1 GECTI ✓ (laser akisi dogru)")

        # ---- ISTASYON 2: spray ----
        print("\n[test] Istasyon 2 — MARKER gonderiliyor (spray bekleniyor)...")
        serial.write_line("MARKER")
        s2_ok, seq2 = expect_sequence(
            serial, ["PUMP_ON", "PUMP_OFF", "RESUME"], timeout_s=12)
        print(f"[test] Istasyon 2 serial: {seq2}")
        ok &= s2_ok
        if s2_ok:
            print("[test] Istasyon 2 GECTI ✓ (spray akisi dogru)")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        stop_evt.set()
        srv_thread.join(timeout=2)
        os.close(master_fd)
        os.close(slave_fd)

    # ---- Dogrulamalar ----
    print("\n" + "-" * 60)
    if results["captures"] != 2:
        ok = False
        results["errors"].append(
            f"Beklenen 2 CAPTURE, gelen {results['captures']}")
    else:
        print(f"[test] Vision sunucusu 2 CAPTURE aldi ✓")

    for e in results["errors"]:
        print(f"  HATA: {e}")

    print("-" * 60)
    if ok and not results["errors"]:
        print("SONUC: Tum entegrasyon testleri GECTI ✓")
        print("  MARKER -> inspect -> action -> RESUME zinciri calisiyor.")
        return 0
    else:
        print("SONUC: Entegrasyon testi BASARISIZ ✗")
        # main ciktisini hata ayiklama icin goster
        try:
            out = proc.stdout.read()
            if out:
                print("\n--- main stdout ---\n" + out)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
