CC      ?= gcc
CFLAGS  ?= -std=c11 -Wall -Wextra -Wshadow -Werror -O2 -g
TARGETS  = test_ptc test_x86 test_emit_exec

all: test

test: $(TARGETS)
	./test_ptc
	@echo
	./test_x86
	@echo
	./test_emit_exec

test_ptc: test_ptc.c ptc.c ptc.h
	$(CC) $(CFLAGS) -o $@ test_ptc.c ptc.c

test_x86: test_x86_decode.c x86_decode.c x86_decode.h
	$(CC) $(CFLAGS) -o $@ test_x86_decode.c x86_decode.c

# The emit-and-execute harness is ISA-guarded at compile time; on a non-aarch64
# host it still builds and checks the encodings, but runs nothing.
test_emit_exec: test_emit_exec.c
	$(CC) $(CFLAGS) -o $@ test_emit_exec.c

clean:
	rm -f $(TARGETS) *.o *.ptc *.ptc.tmp.*

.PHONY: all test clean
