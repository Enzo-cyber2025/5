#!/data/data/com.termux/files/usr/bin/bash
ROOT="$HOME/text-binary"
printf 'started\n' > "$ROOT/build.started"
pkg install -y openjdk-21 libc++ aapt2 d8 apksigner > "$ROOT/build-tools-install.log" 2>&1
status=$?
if [ "$status" -eq 0 ]; then
    bash "$ROOT/build-termux.sh" > "$ROOT/build.log" 2>&1
    status=$?
fi
printf '%s\n' "$status" > "$ROOT/build.exit"
exit "$status"
