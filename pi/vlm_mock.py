import socket
import os
import json
import random
import time

SOCKET_PATH = "/tmp/vlm_ipc.sock"

def generate_mock_result():
    """Rastgele VLM analiz sonucu üretir."""
    statuses = ["healthy", "diseased", "weed"]
    chosen_status = random.choice(statuses)
    confidence = round(random.uniform(0.5, 0.99), 2)

    if chosen_status == "diseased":
        action = "spray"
    elif chosen_status == "weed":
        action = "laser"
    else:
        action = "skip"

    return {
        "status": chosen_status,
        "confidence": confidence,
        "diagnosis": "Simule edilmis yaprak analizi",
        "action": action,
        "target_position": "center"
    }

def start_vlm_server():
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

    server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server_socket.bind(SOCKET_PATH)
    server_socket.listen(1)
    print(f"[Python Server] Baslatildi! {SOCKET_PATH} uzerinde tetikleme bekleniyor...")
    
    try:
        while True:
            client_connection, client_address = server_socket.accept()
            # C++'tan gelecek olan dosya yolunu (string) okuyoruz
            data = client_connection.recv(1024)
            if data:
                # Gelen metni temizle (boşlukları sil)
                image_path = data.decode('utf-8').strip()
                print(f"\n[Python Server] C++ bana su fotografi islememi soyledi: '{image_path}'")
                
                # FOTOGRAFI GÖREBİLİYOR MUYUZ KONTROLÜ
                if os.path.exists(image_path):
                    # Dosya gerçekten var! Boyutunu okuyarak ispatlayalım
                    file_size = os.path.getsize(image_path)
                    print(f"[Python Server] EVEET! Fotografi buldum. Boyutu: {file_size} byte.")
                    print("[Python Server] Fotografi VLM'e yukluyorum. Analiz yapiliyor (2 saniye)...")
                    time.sleep(2) 
                    
                    result_dict = generate_mock_result()
                    
                    # ---> EKSİK OLAN VE EKLENEN KISIM BURASI <---
                    with open("vlm_output.json", "w") as f:
                        json.dump(result_dict, f, indent=4)
                    print("[Python Server] vlm_output.json dosyasi da guncellendi.")
                    # ---------------------------------------------
                    
                else:
                    # C++ yanlış bir yol gönderdiyse veya fotoğraf yoksa
                    print(f"[Python Server] HATA! Belirtilen yolda ({image_path}) fotograf bulunamadi!")
                    result_dict = {"error": "Fotograf bulunamadi", "status": "unknown"}

                # Sonucu JSON'a çevirip C++'a geri fırlat
                json_string = json.dumps(result_dict)
                client_connection.sendall(json_string.encode('utf-8'))
                print("[Python Server] Sonuc C++'a geri gonderildi.")

            client_connection.close()

    except KeyboardInterrupt:
        print("\n[Python Server] Kapatiliyor...")
    finally:
        server_socket.close()
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)

if __name__ == "__main__":
    start_vlm_server()