CXX      = g++
CXXFLAGS = -std=c++17 -O2 -Wall

.PHONY: all clean

all: controller

controller: controller.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

clean:
	rm -f controller
