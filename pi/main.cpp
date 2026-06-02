#include <iostream>
#include <string>
#include <cstring>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <fcntl.h>
#include <termios.h>

using namespace std;

// =====================================================================
// 1. DONANIM YÖNETİCİSİ (HARDWARE MANAGER)
// =====================================================================
class HardwareManager {
    int serial_fd;
public:
    HardwareManager(const char* port = "/dev/ttyUSB0") {
        serial_fd = open(port, O_RDWR | O_NOCTTY | O_SYNC);
        if (serial_fd < 0) {
            cerr << "[Donanim] UYARI: " << port << " bulunamadi. Demo modunda calisiliyor." << endl;
            return;
        }
        termios tty{};
        tcgetattr(serial_fd, &tty);
        cfsetospeed(&tty, B9600); cfsetispeed(&tty, B9600);
        tty.c_cflag = (tty.c_cflag & ~CSIZE) | CS8;
        tty.c_cflag |= (CLOCAL | CREAD); tty.c_cflag &= ~(PARENB | CSTOPB | CRTSCTS);
        tcsetattr(serial_fd, TCSANOW, &tty);
        usleep(2000000); tcflush(serial_fd, TCIOFLUSH);
        cout << "[Donanim] Arduino baglantisi BASARILI" << endl;
    }
    ~HardwareManager() { if (serial_fd >= 0) close(serial_fd); }
    void sendCommand(const string& cmd) {
        if (serial_fd >= 0) { string msg = cmd + "\n"; write(serial_fd, msg.c_str(), msg.size()); cout << "[Donanim] Iletildi: " << cmd << endl; } 
        else { cout << "[Donanim] SIMULASYON: " << cmd << endl; }
    }
    void activateLaser(int ms) { sendCommand("LASER_ON " + to_string(ms)); }
    void deactivateLaser() { sendCommand("LASER_OFF"); }
    void activatePump(int ms) { sendCommand("PUMP_ON " + to_string(ms)); }
    void deactivatePump() { sendCommand("PUMP_OFF"); }
};

// =====================================================================
// 2. KAMERA (YOLO) İLETİŞİM FONKSİYONU
// =====================================================================
string takePhoto() {
    string socketPath = "/tmp/kamera_ipc.sock";
    int sock = 0;
    struct sockaddr_un serv_addr;
    char buffer[1024] = {0};

    if ((sock = socket(AF_UNIX, SOCK_STREAM, 0)) < 0) return "";
    serv_addr.sun_family = AF_UNIX;
    strncpy(serv_addr.sun_path, socketPath.c_str(), sizeof(serv_addr.sun_path) - 1);

    cout << "[C++] Kamera sunucusuna baglaniliyor..." << endl;
    if (connect(sock, (struct sockaddr *)&serv_addr, sizeof(serv_addr)) < 0) {
        cerr << "[C++] HATA: Kamera baglantisi basarisiz! (kamera_server.py calisiyor mu?)" << endl;
        close(sock);
        return "";
    }

    // Kamera sunucusuna "CAPTURE" emrini fırlatıyoruz
    string cmd = "CAPTURE";
    send(sock, cmd.c_str(), cmd.length(), 0);

    // Kırpılmış fotoğrafın dosya yolunu bekliyoruz
    int valread = read(sock, buffer, 1024);
    string response = "";
    if (valread > 0) {
        response = string(buffer, valread);
        cout << "[C++] Kamera ve YOLO isini bitirdi. Kesilmis Fotograf Yolu: " << response << endl;
    }
    close(sock);
    return response;
}

// =====================================================================
// 3. VLM (YAPAY ZEKA) İLETİŞİM FONKSİYONU
// =====================================================================
string triggerVLM(const string& imagePath) {
    string socketPath = "/tmp/vlm_ipc.sock";
    int sock = 0;
    struct sockaddr_un serv_addr;
    char buffer[2048] = {0};

    if ((sock = socket(AF_UNIX, SOCK_STREAM, 0)) < 0) return "";
    serv_addr.sun_family = AF_UNIX;
    strncpy(serv_addr.sun_path, socketPath.c_str(), sizeof(serv_addr.sun_path) - 1);

    if (connect(sock, (struct sockaddr *)&serv_addr, sizeof(serv_addr)) < 0) {
        cerr << "[C++] HATA: VLM baglantisi basarisiz! (vlm_server.py calisiyor mu?)" << endl;
        close(sock);
        return "";
    }

    cout << "[C++] VLM uyariliyor. Hedef: " << imagePath << endl;
    send(sock, imagePath.c_str(), imagePath.length(), 0);

    int valread = read(sock, buffer, 2048);
    string response = "";
    if (valread > 0) {
        response = string(buffer, valread);
    }
    close(sock);
    return response;
}

// =====================================================================
// 4. ANA ORKESTRATÖR (MODÜL 4)
// =====================================================================
int main() {
    cout << "=========================================" << endl;
    cout << "   MODUL 4: ANA KONTROL SISTEMI BASLADI  " << endl;
    cout << "=========================================\n" << endl;

    HardwareManager hardware("/dev/ttyUSB0");

    cout << "\n[Sistem] Bitki karsisinda duruldu. Ajan (Kamera+YOLO) tetikleniyor..." << endl;
    
    // 1. ADIM: Kamerayı tetikle ve kırpılmış yaprağın yolunu al
    string croppedImagePath = takePhoto(); 
    
    if (!croppedImagePath.empty()) {
        cout << "\n[Sistem] Ajan isini bitirdi. Doktor (VLM) analize cagiriliyor..." << endl;
        
        // 2. ADIM: O kırpılmış yaprağın yolunu VLM'e gönder
        string vlmResult = triggerVLM(croppedImagePath); 

        if (!vlmResult.empty()) {
            cout << "\n--- KARAR MOTORU DEVREDE ---" << endl;
            cout << "VLM'den Gelen JSON:\n" << vlmResult << endl;
            
            // 3. ADIM: Donanımı Yönet (Lazer / Pompa)
            if (vlmResult.find("\"action\": \"laser\"") != string::npos) {
                cout << "-> Karar: Yabani Ot! Lazer Atesleniyor..." << endl;
                hardware.activateLaser(3000);
                sleep(3);
                hardware.deactivateLaser();
            } 
            else if (vlmResult.find("\"action\": \"spray\"") != string::npos) {
                cout << "-> Karar: Hastalikli Bitki! Ilaclama Baslatiliyor..." << endl;
                hardware.activatePump(2000);
                sleep(2);
                hardware.deactivatePump();
            } 
            else if (vlmResult.find("\"action\": \"skip\"") != string::npos) {
                cout << "-> Karar: Saglikli Bitki. Es geciliyor." << endl;
            } 
            cout << "----------------------------\n" << endl;
        }
    }

    return 0;
}