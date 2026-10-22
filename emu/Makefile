CC      ?= gcc
CFLAGS  ?= -std=c11 -Wall -Wextra -Wshadow -Werror -O2 -g
TARGETS  = test_ptc test_x86

all: test

test: $(TARGETS)
	./test_ptc
	@echo
	./test_x86

test_ptc: test_ptc.c ptc.c ptc.h
	$(CC) $(CFLAGS) -o $@ test_ptc.c ptc.c

test_x86: test_x86_decode.c x86_decode.c x86_decode.h
	$(CC) $(CFLAGS) -o $@ test_x86_decode.c x86_decode.c

clean:
	rm -f $(TARGETS) *.o *.ptc *.ptc.tmp.*

.PHONY: all test clean
