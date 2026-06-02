#!/usr/bin/env python3
"""
Weed Elimination Robot — Vision + Control

Usage:
  source ~/yolo-env/bin/activate
  python detect.py

Commands at the prompt:
  Enter       — capture image, run YOLO, aim + act automatically
  l           — manual laser test (fires at current servo position)
  p           — manual pump test
  s           — center servos
  s PAN TILT  — move servos to specific angles, e.g. "s 80 100"
  c           — calibration helper (aim laser at image center crosshair)
  q           — quit

Calibration procedure:
  1. Place a small target (tape dot) where the crosshair appears in the window.
  2. Run 'c' — servos home to center, laser fires briefly.
  3. Use 's PAN TILT' to nudge until laser hits the target.
  4. Update PAN_OFFSET and TILT_OFFSET below with the difference from center.
  5. Re-run 'c' to confirm, then test with Enter on a real target.
  6. If laser over/undershoots at edges, tweak PAN_SCALE / TILT_SCALE.
"""

import os
import sys
import subprocess
import tempfile
import cv2
from ultralytics import YOLO
from picamera2 import Picamera2

# ---------------------------------------------------------------------------
# Model & class configuration — update when swapping in your trained model
# ---------------------------------------------------------------------------
MODEL_PATH      = "yolov8n.pt"
WEED_CLASSES    = {"weed", "diseased", "potted plant"}
HEALTHY_CLASSES = {"plant", "healthy", "crop"}

LASER_DURATION = 3000   # ms
PUMP_DURATION  = 2000   # ms

# ---------------------------------------------------------------------------
# Camera & servo configuration
# ---------------------------------------------------------------------------
IMAGE_W  = 640
IMAGE_H  = 480
CAM_HFOV = 62.2   # Pi Camera v2 horizontal FOV in degrees
CAM_VFOV = 48.8   # Pi Camera v2 vertical FOV in degrees

PAN_CENTER  = 90  # servo angle pointing at image center (tune with 'c')
TILT_CENTER = 90

# Calibration offsets — add these after running the 'c' calibration procedure.
# Positive PAN_OFFSET  → laser is left  of target, shifts right
# Positive TILT_OFFSET → laser is above target, shifts down
PAN_OFFSET  = 0   # degrees
TILT_OFFSET = 0   # degrees

# Scale factors — reduce below 1.0 if laser overshoots edges, raise if it undershoots
PAN_SCALE  = 1.0
TILT_SCALE = 1.0

# Set True if tilt servo is mounted inverted
TILT_INVERT = False

SERVO_MIN = 0
SERVO_MAX = 180

CONTROLLER_BIN = os.path.join(os.path.dirname(__file__), "controller")
# ---------------------------------------------------------------------------


def best_box(results, class_set):
    """Return highest-confidence detection whose class is in class_set, or None."""
    best, best_conf = None, -1.0
    for b in results[0].boxes:
        name = results[0].names[int(b.cls)]
        conf = float(b.conf)
        if name in class_set and conf > best_conf:
            best, best_conf = b, conf
    return best


def box_to_angles(box):
    """Convert a YOLO bounding box center to (pan, tilt) servo angles."""
    cx = float(box.xywh[0][0])
    cy = float(box.xywh[0][1])

    dx = cx - IMAGE_W / 2
    dy = cy - IMAGE_H / 2

    pan  = PAN_CENTER  + PAN_OFFSET  + dx * (CAM_HFOV / IMAGE_W) * PAN_SCALE
    tilt_off = dy * (CAM_VFOV / IMAGE_H) * TILT_SCALE
    tilt = TILT_CENTER + TILT_OFFSET + (tilt_off if TILT_INVERT else -tilt_off)

    return (int(max(SERVO_MIN, min(SERVO_MAX, round(pan)))),
            int(max(SERVO_MIN, min(SERVO_MAX, round(tilt)))))


def draw_crosshair(img):
    """Draw a center crosshair on the image in-place."""
    cx, cy = IMAGE_W // 2, IMAGE_H // 2
    color = (0, 255, 0)
    cv2.line(img, (cx - 20, cy), (cx + 20, cy), color, 1)
    cv2.line(img, (cx, cy - 20), (cx, cy + 20), color, 1)
    cv2.circle(img, (cx, cy), 8, color, 1)
    return img


def send(ctrl, cmd: str) -> str:
    ctrl.stdin.write(cmd + "\n")
    ctrl.stdin.flush()
    return ctrl.stdout.readline().strip()


def main():
    if not os.path.exists(CONTROLLER_BIN):
        sys.exit(f"Controller binary not found: {CONTROLLER_BIN}\n"
                 f"Run: cd ~/robot && make")

    print("Loading YOLO model...")
    model = YOLO(MODEL_PATH)

    print("Starting camera...")
    cam = Picamera2()
    cam.configure(cam.create_still_configuration(main={"size": (IMAGE_W, IMAGE_H)}))
    cam.start()

    print(f"Starting controller ({CONTROLLER_BIN})...")
    ctrl = subprocess.Popen(
        [CONTROLLER_BIN],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    send(ctrl, f"SERVO {PAN_CENTER + PAN_OFFSET} {TILT_CENTER + TILT_OFFSET}")

    print("\nReady.")
    print("  Enter       — capture & analyze")
    print("  l           — manual laser test")
    print("  p           — manual pump test")
    print("  s [pan tilt]— center or move servos")
    print("  c           — calibration helper")
    print("  q           — quit\n")

    try:
        while True:
            try:
                user_in = input("> ").strip()
            except EOFError:
                break

            lower = user_in.lower()

            if lower == "q":
                break

            if lower == "l":
                ack = send(ctrl, f"LASER_ON {LASER_DURATION}")
                print(f"  [manual] laser → {ack}")
                continue

            if lower == "p":
                ack = send(ctrl, f"PUMP_ON {PUMP_DURATION}")
                print(f"  [manual] pump  → {ack}")
                continue

            if lower == "c":
                # Calibration: home servos, capture with crosshair, fire laser briefly
                pan_c  = PAN_CENTER  + PAN_OFFSET
                tilt_c = TILT_CENTER + TILT_OFFSET
                send(ctrl, f"SERVO {pan_c} {tilt_c}")
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                    tmp = f.name
                try:
                    cam.capture_file(tmp)
                    frame = cv2.imread(tmp)
                finally:
                    os.unlink(tmp)
                draw_crosshair(frame)
                cv2.imshow("Detection", frame)
                cv2.waitKey(1)
                send(ctrl, "LASER_ON 500")   # brief flash to see where it hits
                print(f"  Calibration: servos at pan={pan_c} tilt={tilt_c}")
                print(f"  Crosshair shows image center. Laser flashed 0.5s.")
                print(f"  Use 's PAN TILT' to nudge until laser hits the crosshair target.")
                print(f"  Then set PAN_OFFSET and TILT_OFFSET at the top of detect.py.")
                continue

            if lower.startswith("s"):
                parts = lower.split()
                if len(parts) == 3:
                    try:
                        pan  = int(max(SERVO_MIN, min(SERVO_MAX, int(parts[1]))))
                        tilt = int(max(SERVO_MIN, min(SERVO_MAX, int(parts[2]))))
                    except ValueError:
                        print("  Usage: s PAN TILT  (e.g. s 80 100)")
                        continue
                else:
                    pan  = PAN_CENTER + PAN_OFFSET
                    tilt = TILT_CENTER + TILT_OFFSET
                ack = send(ctrl, f"SERVO {pan} {tilt}")
                print(f"  Servo → pan={pan}° tilt={tilt}° | {ack}")
                continue

            # --- Capture + YOLO ---
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                tmp = f.name
            try:
                cam.capture_file(tmp)
                results = model(tmp, verbose=False)
            finally:
                os.unlink(tmp)

            annotated = results[0].plot()
            draw_crosshair(annotated)
            cv2.imshow("Detection", annotated)
            cv2.waitKey(1)

            boxes = results[0].boxes
            if not len(boxes):
                print("  No objects detected.")
                continue

            for b in boxes:
                cls_name = results[0].names[int(b.cls)]
                print(f"  {cls_name}  {float(b.conf):.0%}")

            weed_box = best_box(results, WEED_CLASSES)
            if weed_box:
                pan, tilt = box_to_angles(weed_box)
                print(f"  -> Weed: aiming pan={pan}° tilt={tilt}°")
                ack = send(ctrl, f"SERVO {pan} {tilt}")
                print(f"     Servo: {ack}")
                ack = send(ctrl, f"LASER_ON {LASER_DURATION}")
                print(f"     Laser: {ack}")
                continue

            plant_box = best_box(results, HEALTHY_CLASSES)
            if plant_box:
                print("  -> Healthy plant: running pump")
                ack = send(ctrl, f"PUMP_ON {PUMP_DURATION}")
                print(f"     Pump: {ack}")
                continue

            print("  -> No plant classes matched")

    finally:
        if ctrl.poll() is None:
            send(ctrl, "LASER_OFF")
            send(ctrl, "PUMP_OFF")
            send(ctrl, f"SERVO {PAN_CENTER + PAN_OFFSET} {TILT_CENTER + TILT_OFFSET}")
            ctrl.stdin.close()
            ctrl.wait()
        cam.stop()
        cv2.destroyAllWindows()
        print("Shutdown complete.")


if __name__ == "__main__":
    main()
