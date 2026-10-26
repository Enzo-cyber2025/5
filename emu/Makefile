CC      ?= gcc
FIXTURE     ?= /tmp/emu_fixture.exe
FIXTURE_DLL ?= /tmp/emu_guest.dll
CFLAGS  ?= -std=c11 -Wall -Wextra -Wshadow -Werror -O2 -g
TARGETS  = test_ptc test_x86 test_pe test_sweep test_translate test_api test_emit_exec pe_info prewarm api_report

all: test

test: $(TARGETS)
	./test_ptc
	@echo
	./test_x86
	@echo
	./test_pe
	@echo
	./test_sweep
	@echo
	@# End to end: the guest image goes to disk and the driver has to report a
	@# percentage and a remaining-time estimate. Asserted, not just printed.
	@./test_sweep --write-fixture $(FIXTURE_DLL) --exports > /dev/null
	@./prewarm --idle-ms 1 --max-seconds 30 $(FIXTURE_DLL) > $(FIXTURE_DLL).prewarm
	@grep -q 'remaining ~' $(FIXTURE_DLL).prewarm
	@grep -q 'blocks discovered:' $(FIXTURE_DLL).prewarm
	@grep -q 'functions pre-translated:' $(FIXTURE_DLL).prewarm
	@# The ranked refusal list is the point of this milestone: a coverage number
	@# on its own is a dead end, and the same run has to say what is blocking.
	@grep -q 'What is blocking the rest' $(FIXTURE_DLL).prewarm
	@grep -q 'stopped at opcode FF' $(FIXTURE_DLL).prewarm
	@grep -q 'refused: unsupported-opcode' $(FIXTURE_DLL).prewarm
	@grep -q 'functions pre-translated:  *2  (66.67% of attempted)' $(FIXTURE_DLL).prewarm
	@# The entry-point diagnosis is what separates "not in code" into causes, so
	@# it is asserted too: a fixture whose three entry points are all real code has
	@# to report exactly that.
	@./prewarm --diagnose-entries --idle-ms 1 --max-seconds 30 $(FIXTURE_DLL) > $(FIXTURE_DLL).diag
	@grep -q 'total=3 in_code=3 no_section=0 not_executable=0 past_raw=0 zero_first_byte=0' $(FIXTURE_DLL).diag
	@grep -q '2 export(s)' $(FIXTURE_DLL).prewarm
	@echo "prewarm end to end: percentage and remaining time reported for a real file"
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
	./test_translate
	@echo
	./test_api
	@echo
	@# End to end: the classifier has to report a fixture's real import mix. This
	@# uses the PE fixture, not the sweep one - the sweep guest has no import table
	@# at all, so pointing the classifier at it produced an empty report and the
	@# assertion below failed for a reason that was not the classifier's fault.
	@./api_report $(FIXTURE) > $(FIXTURE).api
	@grep -q 'SUMMARY parsed=1' $(FIXTURE).api
	@grep -q 'windows-core' $(FIXTURE).api
	@grep -q 'window/present' $(FIXTURE).api
	@# These are the fixture's real shares: kernel32 contributes 3 of 5 imported
	@# functions and user32 the other 2. Asserting an invented percentage would
	@# have failed for a reason that was not the classifier's fault.
	@grep -q 'windows-core           3 func(s)   60.0%' $(FIXTURE).api
	@grep -q 'window/present         2 func(s)   40.0%' $(FIXTURE).api
	@grep -q 'code_bytes=80' $(FIXTURE).api
	@# The fixture imports GetProcAddress and LoadLibraryA, so the report must say
	@# the static surface is only a lower bound. That warning is the honest part.
	@grep -q 'LOWER BOUND' $(FIXTURE).api
	@grep -q 'dynamic=yes' $(FIXTURE).api
	@echo "api_report end to end: classified with percentages and flagged as a lower bound"
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

# The sweep links the decoder, the PE parser, the cache and the encoder seed:
# it is the first component that uses all of them together.
# The sweep drives the function translator, so it links the whole native core.
CORE = pe_load.c ptc.c x86_decode.c a64_emit.c translate.c
test_sweep: test_sweep.c sweep.c sweep.h $(CORE)
	$(CC) $(CFLAGS) -o $@ test_sweep.c sweep.c $(CORE)

# The pre-translation driver: sweeps real files and reports percentage plus
# remaining time, modelling the screen-off window as a resumable time budget.
prewarm: prewarm.c sweep.c $(CORE)
	$(CC) $(CFLAGS) -o $@ prewarm.c sweep.c $(CORE)

# The end-to-end pipeline: PE exe and DLL in, decoded, translated, resolved,
# emitted, executed on ARM64, persisted and reloaded from the cache.
test_translate: test_translate.c translate.c pe_load.c ptc.c x86_decode.c a64_emit.c
	$(CC) $(CFLAGS) -o $@ test_translate.c translate.c pe_load.c ptc.c \
	      x86_decode.c a64_emit.c

# Classification of a module's imported API surface: how much of what a binary
# needs from the host is Direct3D, how much is Vulkan, and how much is neither.
test_api: test_api_map.c api_map.c pe_load.c
	$(CC) $(CFLAGS) -o $@ test_api_map.c api_map.c pe_load.c

api_report: api_report.c api_map.c pe_load.c api_map.h
	$(CC) $(CFLAGS) -o $@ api_report.c api_map.c pe_load.c

# The emit-and-execute harness is ISA-guarded at compile time; on a non-aarch64
# host it still builds and checks the encodings, but runs nothing.
# Reads a PE from disk and reports it. Parsing only: it never maps the image,
# applies relocations, resolves an import or executes a byte of it.
pe_info: pe_info.c pe_load.c pe_load.h
	$(CC) $(CFLAGS) -o $@ pe_info.c pe_load.c

test_emit_exec: test_emit_exec.c
	$(CC) $(CFLAGS) -o $@ test_emit_exec.c

clean:
	rm -f $(TARGETS) *.o *.ptc *.ptc.tmp.* $(FIXTURE) $(FIXTURE).report \
	      $(FIXTURE_DLL) $(FIXTURE_DLL).prewarm $(FIXTURE_DLL).diag $(FIXTURE).api

.PHONY: all test clean
