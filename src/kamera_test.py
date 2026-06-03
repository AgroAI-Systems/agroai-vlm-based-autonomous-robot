#!/usr/bin/env python3
"""
kamera_test.py — Pi kamera baglanti ve goruntuleme testi
camera_preview.py ile ayni yaklasim, sistem Python ile calistir:

    python3 kamera_test.py           # canli onizleme (Ctrl+C ile kapat)
    python3 kamera_test.py --save    # tek kare cek, kaydet, cik
"""

import argparse
import signal
import sys
import time
from pathlib import Path

from picamera2 import Picamera2, Preview

ap = argparse.ArgumentParser()
ap.add_argument("--save", action="store_true",
                help="Tek kare cek, camera_captures/ altina kaydet, cik")
args = ap.parse_args()

cam = Picamera2()
config = cam.create_preview_configuration(main={"size": (1280, 720)})
cam.configure(config)

if args.save:
    cam.start()
    time.sleep(0.5)
    out = Path(__file__).parent / "camera_captures" / "kamera_test.jpg"
    out.parent.mkdir(exist_ok=True)
    cam.capture_file(str(out))
    cam.stop()
    cam.close()
    print(f"[OK] Kare kaydedildi: {out}")
    sys.exit(0)

cam.start_preview(Preview.QTGL)
cam.start()
print("Onizleme acildi. Kapatmak icin Ctrl+C basin...")

def kapat(sig, frame):
    cam.stop_preview()
    cam.stop()
    cam.close()
    print("\nKapandi.")
    sys.exit(0)

signal.signal(signal.SIGINT, kapat)
signal.signal(signal.SIGTERM, kapat)

while True:
    time.sleep(1)
