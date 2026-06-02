/*
 * Weed Robot — Arduino Firmware
 * Receives commands over USB serial (9600 baud) from the Pi.
 *
 * Wiring:
 *   Pin  7  → relay/driver IN → Laser module
 *   Pin  8  → relay/driver IN → Water pump
 *   Pin  9  → Tilt servo signal
 *   Pin 10  → Pan  servo signal
 *
 * NOTE: The Servo library uses Timer1 (pins 9 & 10 lose PWM but stay digital).
 *       Laser and pump only need digital HIGH/LOW so this is fine.
 *
 * NOTE: Most relay modules are active-LOW. If your relay clicks ON at boot,
 *       swap RELAY_ON = LOW and RELAY_OFF = HIGH.
 *
 * Commands (newline-terminated):
 *   LASER_ON [ms]      — fire laser; auto-off after ms (omit = manual off)
 *   LASER_OFF          — cut laser immediately
 *   PUMP_ON  [ms]      — run pump;  auto-off after ms (omit = manual off)
 *   PUMP_OFF           — stop pump immediately
 *   SERVO pan tilt     — move pan+tilt to angles 0-180; waits for settle, then ACKs
 */

#include <Servo.h>

// --- Pin assignments ---
static const int LASER_PIN = 7;
static const int PUMP_PIN  = 8;
static const int TILT_PIN  = 9;
static const int PAN_PIN   = 10;

// --- Relay logic ---
static const int RELAY_ON  = HIGH;
static const int RELAY_OFF = LOW;

// --- Servo settle time (ms) — SG90 moves ~60°/sec, allow up to 90° travel ---
static const unsigned long SERVO_SETTLE_MS = 600;

// --- Actuator state ---
bool          laserState = false;
bool          pumpState  = false;
unsigned long laserOffAt = 0;
unsigned long pumpOffAt  = 0;

// --- Servo objects ---
Servo panServo;
Servo tiltServo;

int currentPan  = 90;
int currentTilt = 90;

// ---------------------------------------------------------------------------

void setLaser(bool on)
{
    laserState = on;
    digitalWrite(LASER_PIN, on ? RELAY_ON : RELAY_OFF);
}

void setPump(bool on)
{
    pumpState = on;
    digitalWrite(PUMP_PIN, on ? RELAY_ON : RELAY_OFF);
}

void moveServos(int pan, int tilt)
{
    pan  = constrain(pan,  0, 180);
    tilt = constrain(tilt, 0, 180);
    panServo.write(pan);
    currentPan = pan;
    delay(SERVO_SETTLE_MS);   // pan settles before tilt starts
    tiltServo.write(tilt);
    currentTilt = tilt;
    delay(SERVO_SETTLE_MS);   // tilt settles before ACK
}

void handleCommand(const String& raw)
{
    String cmd = raw;
    cmd.trim();
    if (cmd.length() == 0) return;

    if (cmd.startsWith("LASER_ON")) {
        unsigned long ms = 0;
        if (cmd.length() > 9) ms = (unsigned long)cmd.substring(9).toInt();
        setLaser(true);
        laserOffAt = (ms > 0) ? millis() + ms : 0;
        Serial.println("ACK LASER_ON");
    }
    else if (cmd == "LASER_OFF") {
        setLaser(false);
        laserOffAt = 0;
        Serial.println("ACK LASER_OFF");
    }
    else if (cmd.startsWith("PUMP_ON")) {
        unsigned long ms = 0;
        if (cmd.length() > 8) ms = (unsigned long)cmd.substring(8).toInt();
        setPump(true);
        pumpOffAt = (ms > 0) ? millis() + ms : 0;
        Serial.println("ACK PUMP_ON");
    }
    else if (cmd == "PUMP_OFF") {
        setPump(false);
        pumpOffAt = 0;
        Serial.println("ACK PUMP_OFF");
    }
    else if (cmd.startsWith("SERVO")) {
        int pan = currentPan, tilt = currentTilt;
        sscanf(cmd.c_str(), "SERVO %d %d", &pan, &tilt);
        moveServos(pan, tilt);
        Serial.print("ACK SERVO ");
        Serial.print(currentPan);
        Serial.print(" ");
        Serial.println(currentTilt);
    }
    else {
        Serial.print("ERR unknown: ");
        Serial.println(cmd);
    }
}

// ---------------------------------------------------------------------------

void setup()
{
    pinMode(LASER_PIN, OUTPUT);
    pinMode(PUMP_PIN,  OUTPUT);
    setLaser(false);
    setPump(false);

    panServo.attach(PAN_PIN);
    tiltServo.attach(TILT_PIN);
    moveServos(90, 90);   // home position

    Serial.begin(9600);
    Serial.println("READY");
}

void loop()
{
    unsigned long now = millis();

    if (laserState && laserOffAt > 0 && now >= laserOffAt) {
        setLaser(false);
        laserOffAt = 0;
        Serial.println("AUTO LASER_OFF");
    }
    if (pumpState && pumpOffAt > 0 && now >= pumpOffAt) {
        setPump(false);
        pumpOffAt = 0;
        Serial.println("AUTO PUMP_OFF");
    }

    if (Serial.available()) {
        String cmd = Serial.readStringUntil('\n');
        handleCommand(cmd);
    }
}
