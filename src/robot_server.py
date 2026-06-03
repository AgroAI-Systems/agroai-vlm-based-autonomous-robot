#!/usr/bin/env python3
"""
robot_server.py — MOD-02 + MOD-03 BIRLESIK vision sunucusu (Raspberry Pi 4)

Eski mimari (gecici, placeholder):
    main.cpp ──socket──> kamera.py    (CAPTURE -> kirpilmis foto yolu)
    main.cpp ──socket──> vlm_mock.py  (foto yolu -> SAHTE JSON karar)
  Sorun: YOLO sinif+confidence bilgisi iki socket arasinda KAYBOLUYORDU,
  bu yuzden VLM bypass gate (Pi 4 hizlandirma) calisamiyordu.

Yeni mimari (birlesik, gercek modeller):
    main.cpp ──socket──> robot_server.py
        CAPTURE
          -> Pi kamera kare yakala (picamera2)
          -> YOLO (best.pt: SCAB / Purslane / healthy)
          -> bypass gate (YOLO yeterince guvenliyse VLM atlanir)
          -> SmolVLM-256M (gerekirse, 15s timeout, timeout'ta YOLO fallback)
          -> karar JSON
  Tek surecte oldugu icin YOLO bilgisi dogrudan VLM bypass gate'ine akar.

Socket: /tmp/robot_ipc.sock
Protokol:
    Istek : "CAPTURE"          -> kameradan kare cek + analiz et
            "<dosya_yolu>"      -> verilen goruntuyu analiz et (test icin)
    Cevap : main.cpp'nin bekledigi JSON
            {"status","confidence","diagnosis","action","severity",
             "target_position","inference_time_ms"}

Calistirma:
    source ~/agroai-env/bin/activate
    python3 robot_server.py

Gelistirici: Umut Akman + Bekir Goktepe — CSE396 Group 9
"""

import json
import logging
import os
import socket
import sys
import time
from pathlib import Path

# src/ ve src/vlm/ import path'e
SRC_DIR = Path(__file__).parent
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(SRC_DIR / "vlm"))

# Pipeline mantigini yeniden kullan (kamera->YOLO->bypass->VLM hepsi burada)
from mod2_mod3_pipeline import load_yolo, run_pipeline_on_image, load_vlm_engine

SOCKET_PATH = "/tmp/robot_ipc.sock"
CAPTURE_DIR = SRC_DIR / "camera_captures"
MODEL_PATH  = str(SRC_DIR / "best.pt")

log = logging.getLogger("robot.server")


def open_camera():
    """Pi kamerasini surekli acik tutar (kamera_test.py ile ayni calisan config)."""
    from picamera2 import Picamera2
    cam = Picamera2()
    cam.configure(cam.create_preview_configuration(main={"size": (1280, 720)}))
    cam.start()
    time.sleep(0.5)  # exposure stabilizasyonu
    log.info("Pi kamera acildi (1280x720)")
    return cam


def decision_from_result(r: dict) -> dict:
    """
    run_pipeline_on_image() cikti dict'ini main.cpp'nin bekledigi
    JSON formatina cevirir (enum isimleri lowercase).
    """
    return {
        "status":            r["plant_status"].lower(),   # healthy/diseased/weed/unknown
        "confidence":        r["confidence"],
        "diagnosis":         r["diagnosis"],
        "action":            r["action"].lower(),         # skip/spray/laser
        "severity":          r["severity"].lower(),       # none/low/medium/high
        "target_position":   "center",                    # YOLO zaten kirpti
        "inference_time_ms": r["vlm_time_ms"],
    }


def safe_default(reason: str) -> dict:
    """Hata durumunda main.cpp'nin guvenle 'skip' edecegi karar."""
    return {
        "status":            "unknown",
        "confidence":        0.0,
        "diagnosis":         f"safe_default: {reason}",
        "action":            "skip",
        "severity":          "none",
        "target_position":   "center",
        "inference_time_ms": 0,
    }


def start_server():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    CAPTURE_DIR.mkdir(exist_ok=True)

    # 1) Modelleri bir kez yukle
    log.info("YOLO + VLM yukleniyor (bir kez)...")
    yolo = load_yolo(MODEL_PATH)
    load_vlm_engine()

    # 2) Kamerayi bir kez ac, surekli acik tut
    cam = open_camera()

    # 3) Socket sunucusu
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCKET_PATH)
    srv.listen(1)
    log.info(f"HAZIR — {SOCKET_PATH} uzerinde 'CAPTURE' bekleniyor...")

    idx = 0
    try:
        while True:
            conn, _ = srv.accept()
            try:
                data = conn.recv(1024)
                if not data:
                    continue
                req = data.decode("utf-8").strip()

                try:
                    if req == "CAPTURE" or req == "":
                        idx += 1
                        img_path = str(CAPTURE_DIR / f"capture_{idx:04d}.jpg")
                        cam.capture_file(img_path)
                        log.info(f"[{idx}] kare yakalandi -> {os.path.basename(img_path)}")
                    else:
                        # Dogrudan dosya yolu gonderildi (test/regresyon)
                        img_path = req
                        if not os.path.exists(img_path):
                            conn.sendall(json.dumps(safe_default("dosya yok")).encode())
                            continue

                    # Tam pipeline: YOLO -> bypass gate -> VLM
                    r = run_pipeline_on_image(yolo, img_path, idx or 1, idx or 1)
                    decision = decision_from_result(r)
                except Exception as exc:
                    log.error(f"analiz hatasi: {exc}")
                    decision = safe_default(str(exc))

                # Debug icin diske de yaz (vlm_mock.py ile ayni aliskanlik)
                try:
                    with open(SRC_DIR / "vlm_output.json", "w") as f:
                        json.dump(decision, f, indent=4, ensure_ascii=False)
                except Exception:
                    pass

                conn.sendall(json.dumps(decision).encode("utf-8"))
                log.info(
                    f"karar -> status={decision['status']} "
                    f"action={decision['action']} conf={decision['confidence']}"
                )
            finally:
                conn.close()

    except KeyboardInterrupt:
        log.info("kapatiliyor...")
    finally:
        srv.close()
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)
        cam.stop()
        cam.close()
        from vlm_engine import vlm_shutdown
        vlm_shutdown()
        log.info("temiz kapatildi.")


if __name__ == "__main__":
    start_server()
