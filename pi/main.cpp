// =====================================================================
//  MODUL 4 — ANA KONTROL SISTEMI (ORKESTRATOR)  +  Arduino entegrasyonu
// =====================================================================
//  Tam akis:
//    [Arduino]  cizgi takip eder -> SOL sensor siyah bandi okur -> DURUR
//               -> seri porttan "MARKER" gonderir
//    [Pi/main]  "MARKER" gorunce robot_server.py'yi tetikler:
//               kamera -> YOLO -> bypass gate -> SmolVLM-256M -> karar JSON
//               karara gore Arduino'ya LASER_ON/PUMP_ON gonderir
//               sonra "RESUME" gonderir
//    [Arduino]  RESUME alinca sonraki siyah banda kadar takibe devam eder
//
//  Iki haberlesme kanali:
//    1) Arduino  <-- seri (/dev/ttyUSB0, 9600) -->  main      (MARKER/RESUME/LASER/PUMP)
//    2) main     <-- unix socket (/tmp/robot_ipc.sock) -->  robot_server.py (CAPTURE/karar)
//
//  Calistirma:
//    Terminal 1:  source ~/agroai-env/bin/activate && python3 src/robot_server.py
//    Terminal 2:  ./pi/main                 (varsayilan port /dev/ttyUSB0)
//                 ./pi/main /dev/ttyUSB1     (port override)
//    Veya tek komut: ./run_robot.sh
//
//  Donanim yoksa (seri port acilamazsa) DEMO modu: [Enter] = MARKER simule eder.
//
//  CSE396 Group 9
// =====================================================================

#include <iostream>
#include <string>
#include <cstring>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <fcntl.h>
#include <termios.h>
#include <errno.h>

using namespace std;

static const char* ROBOT_SOCKET  = "/tmp/robot_ipc.sock";
static const char* DEFAULT_PORT  = "/dev/ttyUSB0";

// =====================================================================
// 1. DONANIM / ARDUINO SERI YONETICISI (cift yonlu)
// =====================================================================
class ArduinoLink {
    int fd;
    string rxbuf;                 // satir biriktirme tamponu
public:
    ArduinoLink(const char* port) {
        fd = open(port, O_RDWR | O_NOCTTY | O_NONBLOCK);
        if (fd < 0) {
            cerr << "[Donanim] UYARI: " << port
                 << " acilamadi (" << strerror(errno) << "). DEMO modu.\n";
            return;
        }
        termios tty{};
        tcgetattr(fd, &tty);
        cfsetospeed(&tty, B9600); cfsetispeed(&tty, B9600);
        tty.c_cflag = (tty.c_cflag & ~CSIZE) | CS8;
        tty.c_cflag |= (CLOCAL | CREAD);
        tty.c_cflag &= ~(PARENB | CSTOPB | CRTSCTS);
        tty.c_lflag = 0;                       // raw mode
        tty.c_iflag &= ~(IXON | IXOFF | IXANY | ICRNL);
        tty.c_oflag = 0;
        tty.c_cc[VMIN] = 0; tty.c_cc[VTIME] = 0;  // non-blocking read
        tcsetattr(fd, TCSANOW, &tty);

        usleep(2000000);                       // Arduino DTR reset bekle
        tcflush(fd, TCIOFLUSH);
        cout << "[Donanim] Arduino baglantisi BASARILI (" << port << ")\n";
    }
    ~ArduinoLink() { if (fd >= 0) close(fd); }

    bool connected() const { return fd >= 0; }

    void sendLine(const string& cmd) {
        if (fd < 0) { cout << "[Donanim] SIMULASYON: " << cmd << "\n"; return; }
        string msg = cmd + "\n";
        ssize_t w = write(fd, msg.c_str(), msg.size());
        (void)w;
        cout << "[Donanim] -> Arduino: " << cmd << "\n";
    }

    // Tamponlanmis satir okuma. Tam bir satir varsa true + out doldurur.
    bool readLine(string& out) {
        // Once mevcut tamponda satir var mi?
        size_t nl = rxbuf.find('\n');
        if (nl == string::npos && fd >= 0) {
            char buf[256];
            ssize_t n = read(fd, buf, sizeof(buf));
            if (n > 0) rxbuf.append(buf, n);
            nl = rxbuf.find('\n');
        }
        if (nl == string::npos) return false;

        out = rxbuf.substr(0, nl);
        rxbuf.erase(0, nl + 1);
        // satir sonu \r temizle
        while (!out.empty() && (out.back() == '\r' || out.back() == ' '))
            out.pop_back();
        return true;
    }

    // Belirli bir token iceren satiri timeout_ms sureyle bekle.
    bool waitFor(const string& token, int timeout_ms) {
        if (fd < 0) return false;
        int waited = 0;
        string line;
        while (waited < timeout_ms) {
            if (readLine(line)) {
                if (line.find(token) != string::npos) return true;
            } else {
                usleep(10000); waited += 10;   // 10 ms
            }
        }
        return false;
    }

    // --- yuksek seviye aktuator komutlari ---
    void activateLaser(int ms)  { sendLine("LASER_ON " + to_string(ms)); }
    void deactivateLaser()      { sendLine("LASER_OFF"); }
    void activatePump(int ms)   { sendLine("PUMP_ON " + to_string(ms)); }
    void deactivatePump()       { sendLine("PUMP_OFF"); }
    void resume()               { sendLine("RESUME"); }
};

// =====================================================================
// 2. BASIT JSON DEGER OKUYUCU (string + sayisal)
// =====================================================================
static string jsonValue(const string& json, const string& key) {
    string needle = "\"" + key + "\"";
    size_t k = json.find(needle);
    if (k == string::npos) return "";
    size_t colon = json.find(':', k + needle.size());
    if (colon == string::npos) return "";
    size_t i = colon + 1;
    while (i < json.size() && (json[i] == ' ' || json[i] == '\t')) i++;
    if (i < json.size() && json[i] == '"') {
        size_t end = json.find('"', i + 1);
        if (end == string::npos) return "";
        return json.substr(i + 1, end - (i + 1));
    }
    size_t end = i;
    while (end < json.size() && json[end] != ',' && json[end] != '}') end++;
    string v = json.substr(i, end - i);
    while (!v.empty() && (v.back()==' '||v.back()=='\n'||v.back()=='\r')) v.pop_back();
    return v;
}

// =====================================================================
// 3. BIRLESIK VISION SUNUCUSU CAGRISI (kamera + YOLO + VLM)
// =====================================================================
string analyzeScene() {
    int sock = socket(AF_UNIX, SOCK_STREAM, 0);
    if (sock < 0) return "";
    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, ROBOT_SOCKET, sizeof(addr.sun_path) - 1);
    if (connect(sock, (sockaddr*)&addr, sizeof(addr)) < 0) {
        cerr << "[C++] HATA: vision sunucusuna baglanilamadi "
             << "(robot_server.py calisiyor mu?)\n";
        close(sock);
        return "";
    }
    const string cmd = "CAPTURE";
    send(sock, cmd.c_str(), cmd.size(), 0);
    char buffer[4096] = {0};
    int n = read(sock, buffer, sizeof(buffer) - 1);
    close(sock);
    if (n <= 0) return "";
    return string(buffer, n);
}

// =====================================================================
// 4. BIR ISTASYONU DEGERLENDIR  (MARKER -> inspect -> act -> RESUME)
// =====================================================================
void processStation(ArduinoLink& arduino, int station) {
    cout << "\n========== ISTASYON #" << station << " ==========\n";
    cout << "[Sistem] Bant algilandi, robot durdu. Kamera+YOLO+VLM tetikleniyor...\n";
    // Not: 2 sn'lik stabilizasyon beklemesi Arduino tarafinda (MARKER gonderilmeden
    // once delay(2000)); MARKER bize ulastiginda robot zaten oturmus oluyor.

    string json = analyzeScene();
    if (json.empty()) {
        cerr << "[Sistem] Karar alinamadi — guvenli gecis (skip).\n";
        arduino.resume();
        return;
    }

    string status = jsonValue(json, "status");
    string action = jsonValue(json, "action");
    string conf   = jsonValue(json, "confidence");
    string diag   = jsonValue(json, "diagnosis");

    cout << "--- KARAR ---\n";
    cout << "  Durum   : " << status << "   Guven: " << conf << "\n";
    cout << "  Teshis  : " << diag   << "\n";
    cout << "  Aksiyon : " << action << "\n";

    if (action == "laser") {
        cout << "  -> Yabani ot! Lazer atesleniyor (3s)...\n";
        arduino.activateLaser(3000);
        sleep(3);
        arduino.deactivateLaser();
    } else if (action == "spray") {
        cout << "  -> Hastalikli bitki! Ilaclama (2s)...\n";
        arduino.activatePump(2000);
        sleep(2);
        arduino.deactivatePump();
    } else {
        cout << "  -> Saglikli/belirsiz bitki. Mudahale yok.\n";
    }

    // Degerlendirme bitti: Arduino sonraki banda kadar takibe devam etsin
    cout << "[Sistem] RESUME gonderiliyor — sonraki banda kadar takip.\n";
    arduino.resume();
    cout << "=====================================\n";
}

// =====================================================================
// 5. ANA DONGU
// =====================================================================
int main(int argc, char* argv[]) {
    const char* port = (argc > 1) ? argv[1] : DEFAULT_PORT;

    cout << "=========================================\n";
    cout << "   MODUL 4: ANA KONTROL SISTEMI BASLADI  \n";
    cout << "=========================================\n";

    ArduinoLink arduino(port);
    int station = 0;

    if (arduino.connected()) {
        // Arduino "READY" satirini gondermis olabilir — yutalim (zorunlu degil)
        arduino.waitFor("READY", 3000);

        // Baslangic sinyali: robot acilista WAITING'de durur, teker donmez.
        // Kullanici hazir olunca Enter'a basinca "START" gonderiyoruz.
        cout << "\n[Sistem] Robot hazir, bekliyor. Baslatmak icin ENTER'a bas...";
        cout.flush();
        { string dummy; getline(cin, dummy); }
        arduino.sendLine("START");

        cout << "[Sistem] Cizgi takibi basladi. Bant (MARKER) bekleniyor...\n"
             << "         (Cikis: Ctrl+C)\n";

        string line;
        while (true) {
            if (arduino.readLine(line)) {
                if (line.find("MARKER") != string::npos) {
                    processStation(arduino, ++station);
                }
                // diger satirlar (ACK/RESUMED/sensor debug) yok sayilir
            } else {
                usleep(10000);  // 10 ms — CPU'yu yorma
            }
        }
    } else {
        // ---- DEMO MODU (Arduino yok): Enter ile MARKER simule et ----
        cout << "\n[DEMO] Arduino yok. [Enter] = istasyon simule et, q = cikis\n";
        string in;
        while (true) {
            cout << "> " << flush;
            if (!getline(cin, in)) break;
            if (in == "q" || in == "Q") break;
            processStation(arduino, ++station);
        }
    }

    cout << "\n[Sistem] Kapandi.\n";
    return 0;
}
