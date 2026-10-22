CC      ?= gcc
FIXTURE ?= /tmp/emu_fixture.exe
CFLAGS  ?= -std=c11 -Wall -Wextra -Wshadow -Werror -O2 -g
TARGETS  = test_ptc test_x86 test_pe test_emit_exec pe_info

all: test

test: $(TARGETS)
	./test_ptc
	@echo
	./test_x86
	@echo
	./test_pe
	@echo
	@# End to end: the fixture goes to disk and the CLI has to report what is in
	@# it. Asserted rather than printed, so a broken pe_info fails the suite.
	@./test_pe --write-fixture $(FIXTURE) > /dev/null
	@./pe_info $(FIXTURE) > $(FIXTURE).report
	@grep -q 'x64 (AMD64)' $(FIXTURE).report
	@grep -q 'kernel32.dll' $(FIXTURE).report
	@grep -q 'user32.dll' $(FIXTURE).report
	@grep -q 'GetProcAddress' $(FIXTURE).report
	@echo "pe_info end to end: fixture parsed, kernel32.dll and user32.dll imports reported"
	@echo
	./test_emit_exec

test_ptc: test_ptc.c ptc.c ptc.h
	$(CC) $(CFLAGS) -o $@ test_ptc.c ptc.c

test_x86: test_x86_decode.c x86_decode.c x86_decode.h
	$(CC) $(CFLAGS) -o $@ test_x86_decode.c x86_decode.c

# The PE parser is pure C over a memory buffer with no host-specific code, so it
# builds and runs identically on x86-64 and aarch64.
test_pe: test_pe_load.c pe_load.c pe_load.h
	$(CC) $(CFLAGS) -o $@ test_pe_load.c pe_load.c

# The emit-and-execute harness is ISA-guarded at compile time; on a non-aarch64
# host it still builds and checks the encodings, but runs nothing.
# Reads a PE from disk and reports it. Parsing only: it never maps the image,
# applies relocations, resolves an import or executes a byte of it.
pe_info: pe_info.c pe_load.c pe_load.h
	$(CC) $(CFLAGS) -o $@ pe_info.c pe_load.c

test_emit_exec: test_emit_exec.c
	$(CC) $(CFLAGS) -o $@ test_emit_exec.c

clean:
	rm -f $(TARGETS) *.o *.ptc *.ptc.tmp.* $(FIXTURE) $(FIXTURE).report

.PHONY: all test clean
