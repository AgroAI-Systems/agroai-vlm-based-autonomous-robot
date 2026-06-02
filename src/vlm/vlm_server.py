#!/usr/bin/env python3
"""
vlm_server.py — MOD-03 VLM Socket Sunucusu (Raspberry Pi 4)

Socket kontrati (main.cpp ile uyumlu):
  - /tmp/vlm_ipc.sock uzerinde dinler
  - C++ (main.cpp) bir goruntu DOSYA YOLU gonderir
  - JSON string geri doner: status / confidence / diagnosis / action / severity / target_position
  - vlm_output.json dosyasina da yazar (debug icin)

Calistirma:
  source ~/agroai-env/bin/activate
  python3 vlm_server.py

Gelistirici: Bekir Goktepe + Umut Akman
Modul: MOD-03 — VLM Plant Analysis (CSE396 Group 9)
"""

import json
import os
import socket
import sys
import time

# vlm/ klasorunu import path'e ekle
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vlm"))

SOCKET_PATH = "/tmp/vlm_ipc.sock"


def load_engine():
    """vlm_engine'i yukle ve modeli baslatir."""
    from vlm_engine import vlm_init, VlmStatus
    print("[VLM] MoondreamV2 yukleniyor...")
    t0 = time.time()
    status = vlm_init()
    if status != VlmStatus.OK:
        raise RuntimeError(f"vlm_init basarisiz: {status.name}")
    print(f"[VLM] Model hazir ({time.time()-t0:.1f}s)")


def analyze(image_path: str) -> dict:
    """
    Goruntu dosyasini MOD-03 pipeline'indan gecirir.
    Sonucu main.cpp'nin bekledigi JSON formatiyla dondurur.
    """
    from PIL import Image
    from vlm_engine import vlm_analyze_plant
    from vlm_types import VlmImage

    t0 = time.time()

    try:
        pil = Image.open(image_path).convert("RGB").resize((378, 378))
    except Exception as e:
        print(f"[VLM] HATA: goruntu acilamadi: {e}")
        return _safe_default(t0, f"goruntu acilamadi: {e}")

    vlm_image = VlmImage(
        data            = pil.tobytes(),
        width           = 378,
        height          = 378,
        stride          = 378 * 3,
        timestamp_ms    = int(time.time() * 1000),
        yolo_class_id   = -1,   # kamera.py YOLO class gondermiyor; bypass devre disi
        yolo_confidence = 0.0,
    )

    parse_status, result = vlm_analyze_plant(vlm_image)

    elapsed_ms = int((time.time() - t0) * 1000)

    print(
        f"[VLM] {os.path.basename(image_path)} -> "
        f"{result.status.name} ({result.confidence:.2f}) "
        f"-> {result.action.name}  [{elapsed_ms}ms]"
    )

    return {
        "status":            result.status.name.lower(),
        "confidence":        round(result.confidence, 2),
        "diagnosis":         result.diagnosis,
        "action":            result.action.name.lower(),
        "severity":          result.severity.name.lower(),
        "target_position":   "center",      # kamera.py zaten kırptı
        "inference_time_ms": result.inference_time_ms,
    }


def _safe_default(t0: float, reason: str) -> dict:
    return {
        "status":            "unknown",
        "confidence":        0.0,
        "diagnosis":         f"safe_default: {reason}",
        "action":            "skip",
        "severity":          "none",
        "target_position":   "center",
        "inference_time_ms": int((time.time() - t0) * 1000),
    }


def start_server():
    load_engine()

    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCKET_PATH)
    srv.listen(1)
    print(f"[VLM] Hazir — {SOCKET_PATH} uzerinde istek bekleniyor...")

    try:
        while True:
            conn, _ = srv.accept()
            data = conn.recv(1024)
            if not data:
                conn.close()
                continue

            image_path = data.decode("utf-8").strip()
            print(f"\n[VLM] Istek: '{image_path}'")

            if os.path.exists(image_path):
                result = analyze(image_path)
            else:
                print(f"[VLM] HATA: dosya yok: {image_path}")
                result = _safe_default(time.time(), "dosya bulunamadi")

            # Debug icin diske yaz
            try:
                with open("vlm_output.json", "w") as f:
                    json.dump(result, f, indent=4, ensure_ascii=False)
            except Exception:
                pass

            conn.sendall(json.dumps(result).encode("utf-8"))
            print("[VLM] Sonuc gonderildi.")
            conn.close()

    except KeyboardInterrupt:
        print("\n[VLM] Kapatiliyor...")
    finally:
        srv.close()
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)
        from vlm_engine import vlm_shutdown
        vlm_shutdown()


if __name__ == "__main__":
    start_server()
