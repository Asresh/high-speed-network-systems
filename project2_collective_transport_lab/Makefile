CXX ?= c++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror -pthread

.PHONY: build test demo clean

build: build/ring_allreduce

build/ring_allreduce: src/ring_allreduce.cpp
	mkdir -p build
	$(CXX) $(CXXFLAGS) $< -o $@

test:
	python3 -m unittest discover -s tests -v

demo:
	python3 scripts/run_local.py --world-size 3 --elements 11

clean:
	rm -rf build
