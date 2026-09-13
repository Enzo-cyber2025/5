#!/usr/bin/env bash
# Run on an already booted, disposable Google APIs x86_64 emulator (not Play Store).
# Emulator lifecycle belongs to the runner; never hide the suite's exit status.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_SERIAL:?Specify the emulator serial}"
[[ "$(adb -s "$ANDROID_SERIAL" shell getprop sys.boot_completed | tr -d '\r')" == 1 ]]
[[ "$(adb -s "$ANDROID_SERIAL" shell getprop ro.product.cpu.abi | tr -d '\r')" == x86_64 ]]
exec bash .github/emu-test.sh
