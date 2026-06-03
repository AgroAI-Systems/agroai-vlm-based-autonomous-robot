CXX      = g++
CXXFLAGS = -std=c++17 -O2 -Wall

.PHONY: all clean

all: main controller

# Birlesik orkestrator (robot_server.py ile tek socket uzerinden konusur)
main: main.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

# Detect.py'nin kullandigi seri-port middleware (alternatif standalone yol)
controller: controller.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

clean:
	rm -f main controller
