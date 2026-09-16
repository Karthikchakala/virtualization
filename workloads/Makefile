CC ?= gcc
CFLAGS ?= -O2 -Wall -Wextra -pthread -std=c99 -fno-omit-frame-pointer -static
LDFLAGS ?= -lm -pthread

SRC_DIR = src
DIST_DIR = dist

TARGETS = $(DIST_DIR)/cpu_workload $(DIST_DIR)/memory_workload $(DIST_DIR)/syscall_workload $(DIST_DIR)/scheduling_workload

all: $(DIST_DIR) $(TARGETS) package

$(DIST_DIR):
	mkdir -p $(DIST_DIR)

$(DIST_DIR)/cpu_workload: $(SRC_DIR)/cpu_workload.c $(SRC_DIR)/common_workload.h
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

$(DIST_DIR)/memory_workload: $(SRC_DIR)/memory_workload.c $(SRC_DIR)/common_workload.h
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

$(DIST_DIR)/syscall_workload: $(SRC_DIR)/syscall_workload.c $(SRC_DIR)/common_workload.h
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

$(DIST_DIR)/scheduling_workload: $(SRC_DIR)/scheduling_workload.c $(SRC_DIR)/common_workload.h
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

package: $(TARGETS)
	chmod +x $(DIST_DIR)/run_workload.sh 2>/dev/null || true
	python3 build_package.py

clean:
	rm -rf $(DIST_DIR)/cpu_workload $(DIST_DIR)/memory_workload $(DIST_DIR)/syscall_workload $(DIST_DIR)/scheduling_workload MANIFEST.json

test: all
	$(DIST_DIR)/cpu_workload --size 100 --iterations 2
	$(DIST_DIR)/memory_workload --buffer-mb 32 --passes 2
	$(DIST_DIR)/syscall_workload --iterations 10000 --warmup 1000
	$(DIST_DIR)/scheduling_workload --iterations 5000 --warmup 500

.PHONY: all clean test package
