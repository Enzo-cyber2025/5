# NovaLinux host-side build
CFLAGS ?= -march=goldmont-plus -mtune=goldmont-plus -O3 -pipe -flto=auto -static
CC ?= gcc
SRC := src

.PHONY: all userspace clean

all: userspace

userspace: out/novashell out/novapkg out/novafetch out/nova-oom out/nova-preload out/autologin out/sudo

out:
	mkdir -p out

out/novashell: src/novashell/novashell.c src/include/nova.h src/include/novafont.h | out
	$(CC) $(CFLAGS) -o $@ src/novashell/novashell.c -lm -lutil

out/novapkg: src/novapkg/novapkg.c | out
	$(CC) $(CFLAGS) -o $@ src/novapkg/novapkg.c

out/novafetch: src/novafetch/novafetch.c | out
	$(CC) $(CFLAGS) -o $@ src/novafetch/novafetch.c

out/nova-oom: src/nova-oom/nova-oom.c | out
	$(CC) $(CFLAGS) -o $@ src/nova-oom/nova-oom.c

out/nova-preload: src/nova-preload/nova-preload.c | out
	$(CC) $(CFLAGS) -o $@ src/nova-preload/nova-preload.c

out/autologin: src/autologin/autologin.c | out
	$(CC) $(CFLAGS) -o $@ src/autologin/autologin.c

out/sudo: src/sudo/sudo.c | out
	$(CC) $(CFLAGS) -o $@ src/sudo/sudo.c

clean:
	rm -rf out
