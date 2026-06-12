// =====================================================================
//  AgroAI Robot — Cizgi Takip + Istasyon Durma + Donanim Kontrol
//  CSE396 Group 9 — Arduino (motor surucu + IR sensor + lazer/pompa)
//
//  AKIS:
//    1) Robot cizgiyi takip eder (3 IR sensor).
//    2) SOL sensor siyah bandi (istasyon isareti) okuyunca DURUR ve
//       Raspberry Pi'ye seri porttan "MARKER" gonderir.
//    3) Pi degerlendirmeyi yapar (kamera + YOLO + VLM) ve karara gore
//       "LASER_ON/OFF" veya "PUMP_ON/OFF" komutlarini gonderir.
//    4) Pi isi bitince "RESUME" gonderir; robot banttan ayrilip bir
//       SONRAKI siyah banda kadar tekrar cizgi takibine devam eder.
//
//  SERI PROTOKOL (9600 baud, satir = '\n'):
//    Arduino -> Pi :  "MARKER"        istasyona varildi, duruldu
//                     "RESUMED"       takibe devam edildi
//                     "ACK <cmd>"     lazer/pompa komutu uygulandi
//    Pi -> Arduino :  "LASER_ON <ms>" / "LASER_OFF"
//                     "PUMP_ON <ms>"  / "PUMP_OFF"
//                     "RESUME"        degerlendirme bitti, devam et
// =====================================================================

// ---- SENSOR PINLERI ----
#define solSensor 10
#define ortaSensor 11
#define sagSensor 12

// ---- SAG MOTOR PINLERI ----
#define motorSag1 6
#define motorSag2 7
#define ENA 9

// ---- SOL MOTOR PINLERI ----
#define motorSol1 5
#define motorSol2 4
#define ENB 3

// ---- DONANIM (LAZER / POMPA) PINLERI ----
// Bos dijital pinler. Roleyi/MOSFET'i baska pine baglarsan burayi guncelle.
#define LASER_PIN 2
#define PUMP_PIN  8   // 13 = onboard LED ile ayni, gorsel geri bildirim verir

// Aktif seviye: rolelerin cogu LOW-tetikli. HIGH-tetikli ise true yap.
#define ACTUATOR_ACTIVE_HIGH true

// ---- HIZ AYARLARI ----
#define SOL_MOTOR_HIZI 64
#define SAG_MOTOR_HIZI 58
#define HAFIF_ARTIS 8

// ---- ISTASYON ISARETI (SIYAH BANT) POLARITESI ----
// ONEMLI: Normal cizgi takibinde sol sensor LOW(0) okuyor (followLine'da
// ileri gitmenin sarti solDeger==0). Demek ki MARKER_LEVEL'i LOW yaparsan
// markerRaw() normal suruste de surekli true olur -> banda gelmeden SAHTE
// MARKER atar, sonra markerArmed bir daha LOW'dan cikamadigi icin kilitlenir.
// Bu donanimda siyah bant sol sensorde HIGH(1) okutuyor; normal zemin LOW.
// Bu yuzden istasyon isareti = sol sensor HIGH. Ters olursa LOW yap.
// NE OLDUGUNU BILMIYORSAN: "DEBUG_ON" gonder, bandi sol sensorun altina koy,
// hangi degerin ciktigini gor, MARKER_LEVEL'i ona gore ayarla.
#define MARKER_LEVEL HIGH   // Siyah bant sol sensorde HIGH okunur; normal suruste LOW

// Marker debounce: bandi GERCEK saymak icin kac ARDISIK okuma gereksin.
// Anlik sapma/gurultunun yanlis "MARKER" uretmesini onler. ~3 = guvenli.
#define MARKER_DEBOUNCE 3

// ---- DURUM MAKINESI ----
// WAITING:   acilista burada bekler, motorlar KAPALI. "START"/"GO" gelene kadar
//            cizgi takibine baslamaz (acar acmaz teker donmesin diye).
// FOLLOWING: cizgi takibi + istasyon (marker) algilama.
// AT_MARKER: istasyonda durup Pi'nin kararini (RESUME) bekler.
// LEAVING:   RESUME sonrasi bandi gecer; sol sensor KESINTISIZ 3 sn beyaz gorene
//            kadar yeni marker okumaz (ayni istasyonu tekrar okumayi onler).
enum RobotState { WAITING, FOLLOWING, AT_MARKER, LEAVING };
RobotState state = WAITING;

// Ayni bant uzerinde tekrar tetiklenmeyi onlemek icin "silah" bayragi:
// RESUME sonrasi bant terk edilene kadar yeni MARKER uretilmez.
bool markerArmed = true;

// Debounce sayaci: sol sensor ust uste kac kez bant gordu
int markerCount = 0;

// LEAVING: istasyon islendikten sonra robot bandi gecip sol sensor KESINTISIZ
// bu kadar sure beyaz gorene kadar yeni MARKER okumaz.
#define LEAVE_WHITE_MS 3000          // 3 sn kesintisiz beyaz
unsigned long leaveWhiteStart = 0;   // beyazin baslama ani (0 = henuz beyaz yok)

// DEBUG: "DEBUG_ON" komutuyla acilir, ham sensor degerlerini seri'ye yazar.
// Kalibrasyon icin (MARKER_LEVEL'i bulmak, bant yerlesimini test etmek).
bool debugSensors = false;

// Lazer/pompa guvenlik oto-kapatma zamanlari (millis). 0 = oto-kapatma yok.
unsigned long laserOffAt = 0;
unsigned long pumpOffAt  = 0;

// Seri satir tamponu
char lineBuf[48];
uint8_t lineLen = 0;

// ---- FONKSIYON PROTOTIPLERI ----
// (Arduino IDE otomatik uretir; saf C++/derleyici uyumu icin acikca yaziyoruz)
void ileriGit();
void solHafifHizlan();
void sagHafifHizlan();
void dur();
void followLine(int solDeger, int ortaDeger, int sagDeger);
void actuatorOn(int pin);
void actuatorOff(int pin);
bool markerRaw();
void handleCommand(char* cmd);
void pollSerial();
void printSensors(int s, int o, int g);

// ---------------------------------------------------------------------
void setup() {
  pinMode(solSensor,  INPUT_PULLUP);
  pinMode(ortaSensor, INPUT_PULLUP);
  pinMode(sagSensor,  INPUT_PULLUP);

  pinMode(motorSag1, OUTPUT);
  pinMode(motorSag2, OUTPUT);
  pinMode(motorSol1, OUTPUT);
  pinMode(motorSol2, OUTPUT);
  pinMode(ENA, OUTPUT);
  pinMode(ENB, OUTPUT);

  pinMode(LASER_PIN, OUTPUT);
  pinMode(PUMP_PIN,  OUTPUT);
  actuatorOff(LASER_PIN);
  actuatorOff(PUMP_PIN);

  Serial.begin(9600);
  Serial.println("READY");   // Pi bu satiri gorunce Arduino acildi anlar
  // Not: Burada bekleme YOK. Robot WAITING durumunda durur; "START" sinyali
  //      gelene kadar teker donmez.
}

// =====================================================================
// MOTOR FONKSIYONLARI  (orijinal ir_sensor_test2.ino mantigi korunmustur)
// =====================================================================
void ileriGit() {
  analogWrite(ENA, SAG_MOTOR_HIZI);
  analogWrite(ENB, SOL_MOTOR_HIZI);
  digitalWrite(motorSag1, HIGH); digitalWrite(motorSag2, LOW);
  digitalWrite(motorSol1, HIGH); digitalWrite(motorSol2, LOW);
}
void solHafifHizlan() {
  analogWrite(ENA, SAG_MOTOR_HIZI + HAFIF_ARTIS);
  analogWrite(ENB, SOL_MOTOR_HIZI);
  digitalWrite(motorSag1, HIGH); digitalWrite(motorSag2, LOW);
  digitalWrite(motorSol1, HIGH); digitalWrite(motorSol2, LOW);
}
void sagHafifHizlan() {
  analogWrite(ENA, SAG_MOTOR_HIZI);
  analogWrite(ENB, SOL_MOTOR_HIZI + HAFIF_ARTIS);
  digitalWrite(motorSag1, HIGH); digitalWrite(motorSag2, LOW);
  digitalWrite(motorSol1, HIGH); digitalWrite(motorSol2, LOW);
}
void dur() {
  analogWrite(ENA, 0); analogWrite(ENB, 0);
  digitalWrite(motorSag1, LOW); digitalWrite(motorSag2, LOW);
  digitalWrite(motorSol1, LOW); digitalWrite(motorSol2, LOW);
}

// Tek adim cizgi takibi (sadece motorlari surer, durum yonetmez).
void followLine(int solDeger, int ortaDeger, int sagDeger) {
  if (solDeger == 0 && ortaDeger == 1 && sagDeger == 1)        ileriGit();
  else if (solDeger == 0 && ortaDeger == 1 && sagDeger == 0)   sagHafifHizlan();
  else if (solDeger == 0 && ortaDeger == 0 && sagDeger == 1)   solHafifHizlan();
  else                                                         dur();
}

// =====================================================================
// DONANIM (AKTUATOR) YARDIMCILARI
// =====================================================================
void actuatorOn(int pin)  { digitalWrite(pin, ACTUATOR_ACTIVE_HIGH ? HIGH : LOW); }
void actuatorOff(int pin) { digitalWrite(pin, ACTUATOR_ACTIVE_HIGH ? LOW : HIGH); }

// =====================================================================
// SIYAH BANT (ISTASYON) ALGILAMA — sadece sol sensor
// =====================================================================
// markerRaw(): sol sensor SU AN bant goruyor mu (debounce'suz, ham).
// Gercek "MARKER" karari loop() icinde MARKER_DEBOUNCE ile verilir.
bool markerRaw() {
  return digitalRead(solSensor) == MARKER_LEVEL;
}

// Kalibrasyon ciktisi: ham sensor degerleri (DEBUG_ON ile acilir)
void printSensors(int s, int o, int g) {
  Serial.print("DBG sol="); Serial.print(s == 1 ? "1" : "0");
  Serial.print(" orta=");   Serial.print(o == 1 ? "1" : "0");
  Serial.print(" sag=");    Serial.print(g == 1 ? "1" : "0");
  Serial.println(s == MARKER_LEVEL ? "  <-- BANT (sol=MARKER_LEVEL)" : "");
}

// =====================================================================
// SERI KOMUT ISLEME (Pi -> Arduino)
// =====================================================================
void handleCommand(char* cmd) {
  if (strncmp(cmd, "LASER_ON", 8) == 0) {
    actuatorOn(LASER_PIN);
    long ms = atol(cmd + 8);                  // "LASER_ON 3000" -> 3000
    laserOffAt = (ms > 0) ? millis() + ms : 0; // guvenlik oto-kapatma
    Serial.println("ACK LASER_ON");
  }
  else if (strncmp(cmd, "LASER_OFF", 9) == 0) {
    actuatorOff(LASER_PIN); laserOffAt = 0;
    Serial.println("ACK LASER_OFF");
  }
  else if (strncmp(cmd, "PUMP_ON", 7) == 0) {
    actuatorOn(PUMP_PIN);
    long ms = atol(cmd + 7);
    pumpOffAt = (ms > 0) ? millis() + ms : 0;
    Serial.println("ACK PUMP_ON");
  }
  else if (strncmp(cmd, "PUMP_OFF", 8) == 0) {
    actuatorOff(PUMP_PIN); pumpOffAt = 0;
    Serial.println("ACK PUMP_OFF");
  }
  else if (strncmp(cmd, "RESUME", 6) == 0) {
    // Degerlendirme bitti: guvenlik icin aktuatorleri kapat, takibe don.
    actuatorOff(LASER_PIN); actuatorOff(PUMP_PIN);
    laserOffAt = pumpOffAt = 0;
    state = LEAVING;         // bandi gec + 3 sn kesintisiz beyaz gor, sonra FOLLOWING
    markerArmed = false;
    markerCount = 0;
    leaveWhiteStart = 0;
    Serial.println("RESUMED");
  }
  else if (strncmp(cmd, "START", 5) == 0 || strncmp(cmd, "GO", 2) == 0) {
    // Baslangic sinyali: WAITING'den cik, cizgi takibine basla.
    state = FOLLOWING;
    markerArmed = true;
    markerCount = 0;
    Serial.println("STARTED");
  }
  else if (strncmp(cmd, "DEBUG_ON", 8) == 0) {
    debugSensors = true;  Serial.println("ACK DEBUG_ON");
  }
  else if (strncmp(cmd, "DEBUG_OFF", 9) == 0) {
    debugSensors = false; Serial.println("ACK DEBUG_OFF");
  }
}

// Seri porttan satir biriktir, '\n' gelince isle.
void pollSerial() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineLen > 0) {
        lineBuf[lineLen] = '\0';
        handleCommand(lineBuf);
        lineLen = 0;
      }
    } else if (lineLen < sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = c;
    }
  }
}

// =====================================================================
// ANA DONGU
// =====================================================================
void loop() {
  pollSerial();   // Pi'den gelen komutlari her zaman dinle

  // Guvenlik oto-kapatma (OFF mesaji kaybolursa aktuator sonsuza dek acik kalmasin)
  if (laserOffAt && millis() >= laserOffAt) { actuatorOff(LASER_PIN); laserOffAt = 0; }
  if (pumpOffAt  && millis() >= pumpOffAt)  { actuatorOff(PUMP_PIN);  pumpOffAt  = 0; }

  int solDeger  = digitalRead(solSensor);
  int ortaDeger = digitalRead(ortaSensor);
  int sagDeger  = digitalRead(sagSensor);

  if (debugSensors) printSensors(solDeger, ortaDeger, sagDeger);

  switch (state) {
    case WAITING:
      // Baslangic sinyali ("START"/"GO") gelene kadar dur, hicbir sey yapma.
      dur();
      break;

    case FOLLOWING:
      // Istasyon isareti algilama — DEBOUNCE'li.
      // (Bant terk etme / yeniden silahlanma artik LEAVING durumunda yapilir.)
      if (markerArmed && markerRaw()) {
        markerCount++;
        if (markerCount >= MARKER_DEBOUNCE) {
          // Yeterince ardisik okuma -> gercek bant. DUR, 2 sn bekle, sonra haber ver.
          dur();
          delay(2000);           // istasyonda 2 sn dur: robot otursun/titresim bitsin
          state = AT_MARKER;
          markerCount = 0;
          markerArmed = false;   // EDGE LATCH: siyahi gorduk, kilitle. Beyaz
                                 // gorulene kadar (yukaridaki 1. madde) tekrar
                                 // MARKER atilmaz -> ayni istasyonda tek durus.
          Serial.println("MARKER");
        } else {
          // Henuz emin degiliz; takibe devam et (birkac ms surer)
          followLine(solDeger, ortaDeger, sagDeger);
        }
      } else {
        // Bant yok -> sayaci sifirla, normal cizgi takibi
        markerCount = 0;
        followLine(solDeger, ortaDeger, sagDeger);
      }
      break;

    case LEAVING:
      // Istasyonu isledik; bandi terk et. Sol sensor SIYAH iken (bant uzerinde)
      // duz ileri git ve beyaz sayacini sifirla. BEYAZ gorunce cizgiyi takip et
      // ve beyaz suresini say. KESINTISIZ 3 sn beyaz gorulunce yeniden silahlan
      // ve normal takibe (FOLLOWING) don.
      if (markerRaw()) {                 // hala bant (siyah) -> duz gec
        ileriGit();
        leaveWhiteStart = 0;             // beyaz kesildi, sayaci sifirla
      } else {                           // beyaz -> takip et + sure say
        followLine(solDeger, ortaDeger, sagDeger);
        if (leaveWhiteStart == 0) {
          leaveWhiteStart = millis();    // beyaz yeni basladi
        } else if (millis() - leaveWhiteStart >= LEAVE_WHITE_MS) {
          markerArmed = true;            // 3 sn kesintisiz beyaz -> hazir
          markerCount = 0;
          state = FOLLOWING;
        }
      }
      break;

    case AT_MARKER:
      // Degerlendirme suruyor: dur ve Pi'nin komutlarini bekle.
      // (Lazer/pompa ve RESUME pollSerial() icinde islenir.)
      dur();
      break;
  }
}
