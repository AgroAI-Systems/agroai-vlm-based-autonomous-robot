import socket
import os
import cv2
from ultralytics import YOLO
from picamera2 import Picamera2

SOCKET_PATH = "/tmp/kamera_ipc.sock"
MODEL_PATH  = "yolov8n.pt" # Arkadaşının eğittiği veya hazır kullandığı model

# Arkadaşının kodundaki tüm sınıfları birleştirdik (amacımız sadece bitkiyi kadrajda bulmak)
DETECT_CLASSES = {"weed", "diseased", "potted plant", "plant", "healthy", "crop"}

def get_best_crop(results, image_mat):
    """YOLO'nun bulduğu en belirgin bitkinin etrafını kırpar."""
    best_box, best_conf = None, -1.0
    for b in results[0].boxes:
        name = results[0].names[int(b.cls)]
        conf = float(b.conf)
        if name in DETECT_CLASSES and conf > best_conf:
            best_box, best_conf = b, conf
            
    if best_box:
        # Kutunun köşe koordinatlarını al (x1, y1: Sol üst | x2, y2: Sağ alt)
        x1, y1, x2, y2 = map(int, best_box.xyxy[0])
        
        # Sınırların dışına çıkmayı engelle (Güvenlik önlemi)
        h, w = image_mat.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        
        # Görüntüyü o koordinatlara göre kırp (Crop)
        cropped = image_mat[y1:y2, x1:x2]
        return cropped
    return None

def start_kamera_server():
    print("[Kamera+YOLO] Sistem isiniyor, lutfen bekleyin...")
    
    # 1. YOLO'yu RAM'e Yükle (Sadece 1 kez çalışır)
    model = YOLO(MODEL_PATH)
    
    # 2. Kamerayı RAM'e al ve ısıt
    cam = Picamera2()
    cam.configure(cam.create_still_configuration(main={"size": (640, 480)}))
    cam.start()
    
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

    server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server_socket.bind(SOCKET_PATH)
    server_socket.listen(1)
    
    print(f"[Kamera+YOLO] Hazir! Uykuda bekliyor... ({SOCKET_PATH})")

    try:
        while True:
            client_connection, _ = server_socket.accept()
            data = client_connection.recv(1024)
            
            if data:
                cmd = data.decode('utf-8').strip()
                if cmd == "CAPTURE":
                    tmp_path = "/tmp/tam_kare.jpg"
                    crop_path = "/tmp/hedef_bitki.jpg"
                    
                    # 1. Fotoğrafı şipşak çek
                    cam.capture_file(tmp_path)
                    
                    # 2. YOLO ile analize sok (Milisaniyeler sürer)
                    results = model(tmp_path, verbose=False)
                    image_mat = cv2.imread(tmp_path)
                    
                    # 3. Kırpma İşlemi
                    cropped_img = get_best_crop(results, image_mat)
                    
                    if cropped_img is not None:
                        # Kırpılmış, tertemiz yaprak fotoğrafını kaydet
                        cv2.imwrite(crop_path, cropped_img)
                        print("[Kamera+YOLO] Bitki bulundu, KESIILDI ve kaydedildi.")
                        client_connection.sendall(crop_path.encode('utf-8'))
                    else:
                        # Eğer robot yanlış yerde durduysa ve kadrajda bitki yoksa, orjinali gönder
                        print("[Kamera+YOLO] UYARI: Kadrajda hicbir bitki bulunamadi! Tam fotograf gonderiliyor.")
                        client_connection.sendall(tmp_path.encode('utf-8'))

            client_connection.close()

    except KeyboardInterrupt:
        print("\n[Kamera+YOLO] Kapatiliyor...")
    finally:
        cam.stop()
        server_socket.close()
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)

if __name__ == "__main__":
    start_kamera_server()