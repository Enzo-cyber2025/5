#!/data/data/com.termux/files/usr/bin/bash
ROOT="$HOME/text-binary"
printf 'started\n' > "$ROOT/build.started"
# Select the official Termux Cloudflare endpoint instead of accepting an
# arbitrary stale mirror snapshot: older aapt2 builds rejected API 35 android.jar.
printf 'deb https://packages-cf.termux.dev/apt/termux-main stable main\n' > "$PREFIX/etc/apt/sources.list"
rm -f "$PREFIX"/var/lib/apt/lists/*
pkg update -y > "$ROOT/build-tools-install.log" 2>&1
status=$?
if [ "$status" -eq 0 ]; then
    pkg install -y openjdk-21 libc++ aapt2 d8 apksigner >> "$ROOT/build-tools-install.log" 2>&1
    status=$?
fi
if [ "$status" -eq 0 ]; then
    bash "$ROOT/build-termux.sh" > "$ROOT/build.log" 2>&1
    status=$?
fi
printf '%s\n' "$status" > "$ROOT/build.exit"
exit "$status"
