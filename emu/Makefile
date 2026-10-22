CC      ?= gcc
CFLAGS  ?= -std=c11 -Wall -Wextra -Wshadow -Werror -O2 -g
TARGET   = test_ptc

all: test

test: $(TARGET)
	./$(TARGET)

$(TARGET): test_ptc.c ptc.c ptc.h
	$(CC) $(CFLAGS) -o $@ test_ptc.c ptc.c

clean:
	rm -f $(TARGET) *.ptc *.tmp.*

.PHONY: all test clean
