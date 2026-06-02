/*
 * Weed Robot — Serial Controller (middleware)
 *
 * Reads commands from stdin (piped from detect.py), forwards them
 * to the Arduino over /dev/ttyUSB0 at 9600 baud, and prints an
 * acknowledgment line to stdout for each command.
 *
 * Supported commands (passed through verbatim to Arduino):
 *   LASER_ON [ms]
 *   LASER_OFF
 *   PUMP_ON [ms]
 *   PUMP_OFF
 *
 * Build:  make
 * Run:    ./controller          (normally spawned by detect.py)
 *         ./controller /dev/ttyUSB1   (override port)
 */

#include <iostream>
#include <string>
#include <cstring>
#include <fcntl.h>
#include <termios.h>
#include <unistd.h>

static const char* DEFAULT_PORT = "/dev/ttyUSB0";
static const int   ARDUINO_RESET_DELAY_US = 2'000'000; // 2 s

static int openSerial(const char* port)
{
    int fd = open(port, O_RDWR | O_NOCTTY | O_SYNC);
    if (fd < 0) {
        std::cerr << "[controller] ERROR: cannot open " << port
                  << ": " << strerror(errno) << "\n";
        return -1;
    }

    termios tty{};
    tcgetattr(fd, &tty);
    cfsetospeed(&tty, B9600);
    cfsetispeed(&tty, B9600);

    tty.c_cflag = (tty.c_cflag & ~CSIZE) | CS8;
    tty.c_cflag |=  (CLOCAL | CREAD);
    tty.c_cflag &= ~(PARENB | CSTOPB | CRTSCTS);
    tty.c_lflag  =  0;
    tty.c_iflag &= ~(IXON | IXOFF | IXANY | ICRNL);
    tty.c_oflag  =  0;
    tty.c_cc[VMIN]  = 0;
    tty.c_cc[VTIME] = 10; // 1 s read timeout

    tcsetattr(fd, TCSANOW, &tty);

    // Arduino resets on DTR toggle when serial opens — wait for it to boot
    usleep(ARDUINO_RESET_DELAY_US);
    tcflush(fd, TCIOFLUSH);

    std::cerr << "[controller] Serial open: " << port << " @ 9600\n";
    return fd;
}

static void sendLine(int fd, const std::string& cmd)
{
    std::string msg = cmd + "\n";
    write(fd, msg.c_str(), msg.size());
}

int main(int argc, char* argv[])
{
    const char* port = (argc > 1) ? argv[1] : DEFAULT_PORT;

    int fd = openSerial(port);
    if (fd < 0) {
        std::cerr << "[controller] Running in demo mode (no serial)\n";
    }

    // Line-buffer stdout so Python readline() doesn't block
    std::cout << std::unitbuf;

    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;

        if (fd >= 0) {
            sendLine(fd, line);
        }
        std::cout << "OK: " << line << "\n";
    }

    if (fd >= 0) close(fd);
    return 0;
}
