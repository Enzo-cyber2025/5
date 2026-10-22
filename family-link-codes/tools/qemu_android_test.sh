#!/usr/bin/env bash
# Boot an Android image under QEMU and run the no-root pipeline against it.
#
# This is the device-side test that cannot run inside the development sandbox
# (no qemu binary, no system image, no /dev/kvm). On a machine with QEMU and an
# Android x86_64 image it does, end to end:
#
#   1. boots the image headless with adb forwarded over TCP;
#   2. waits for `adb devices` to report the guest;
#   3. runs `flcodes device info` (props + packages, no root);
#   4. pulls the installed APK splits with `flcodes device apk` (world readable);
#   5. runs `adb backup` from inside the guest and extracts it with
#      `flcodes abe scan`, asserting that the shared secret came out.
#
# Requirements:
#   * qemu-system-x86_64 (apt install qemu-system-x86)
#   * adb (android platform-tools)
#   * an Android x86_64 disk image that exposes adbd on TCP 5555
#     (Android-x86 installed to a qcow2, BlissOS, or an AVD image)
#   * a package to test, ideally with `android:allowBackup="true"`
#
# Usage:
#   tools/qemu_android_test.sh --image /path/android-x86.qcow2 \
#       --package com.google.android.apps.familylink --mem 4096
#
# Exit codes: 0 all steps passed, 1 a step failed, 2 prerequisites missing.

set -euo pipefail

IMAGE=""
PORT="5555"
PACKAGE="com.google.android.apps.familylink"
MEM="3072"
CPUS="2"
BOOT_TIMEOUT="900"
ADB_TIMEOUT="300"
WORKDIR="${TMPDIR:-/tmp}/flcodes-qemu"
KEEP="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image) IMAGE="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --package) PACKAGE="$2"; shift 2 ;;
    --mem) MEM="$2"; shift 2 ;;
    --cpus) CPUS="$2"; shift 2 ;;
    --boot-timeout) BOOT_TIMEOUT="$2"; shift 2 ;;
    --workdir) WORKDIR="$2"; shift 2 ;;
    --keep) KEEP="1"; shift ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1" >&2; exit 2; }; }
need qemu-system-x86_64
need adb
[[ -n "$IMAGE" ]] || { echo "missing --image (Android x86_64 disk image)" >&2; exit 2; }
[[ -f "$IMAGE" ]] || { echo "no such image: $IMAGE" >&2; exit 2; }

HERE="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}"
FLCODES=(python3 -m flcodes)
mkdir -p "$WORKDIR"

ACCEL=()
if [[ -r /dev/kvm ]]; then
  ACCEL=(-enable-kvm -cpu host)
  echo "== accel: KVM"
else
  ACCEL=(-accel tcg,thread=multi)
  echo "== accel: TCG (no /dev/kvm: expect 5-20x slower boot)"
fi

QEMU_PID=""
cleanup() {
  adb disconnect "127.0.0.1:$PORT" >/dev/null 2>&1 || true
  if [[ -n "$QEMU_PID" ]] && kill -0 "$QEMU_PID" 2>/dev/null; then
    kill "$QEMU_PID" 2>/dev/null || true
    wait "$QEMU_PID" 2>/dev/null || true
  fi
  [[ "$KEEP" == "1" ]] || rm -rf "$WORKDIR/tmp"
}
trap cleanup EXIT

echo "== 1. boot $IMAGE (headless, adb on 127.0.0.1:$PORT)"
qemu-system-x86_64 \
  "${ACCEL[@]}" \
  -m "$MEM" -smp "$CPUS" \
  -drive file="$IMAGE",if=virtio,format=qcow2 \
  -netdev "user,id=net0,hostfwd=tcp:127.0.0.1:$PORT-:5555" \
  -device e1000,netdev=net0 \
  -display none -serial "file:$WORKDIR/serial.log" \
  -monitor "unix:$WORKDIR/monitor.sock,server,nowait" \
  -daemonize -pidfile "$WORKDIR/qemu.pid"
QEMU_PID="$(cat "$WORKDIR/qemu.pid")"

echo "== 2. wait for adb (up to ${ADB_TIMEOUT}s)"
deadline=$(( $(date +%s) + ADB_TIMEOUT ))
until adb connect "127.0.0.1:$PORT" 2>/dev/null | grep -q "connected"; do
  [[ $(date +%s) -lt $deadline ]] || { echo "adb never connected; see $WORKDIR/serial.log" >&2; exit 1; }
  sleep 5
done
adb -s "127.0.0.1:$PORT" wait-for-device
until [[ "$(adb -s "127.0.0.1:$PORT" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; do
  [[ $(date +%s) -lt $(( deadline + BOOT_TIMEOUT )) ]] || { echo "boot did not complete" >&2; exit 1; }
  sleep 5
done

export FLCODES_HOME="$WORKDIR/home"
export FLCODES_PASSPHRASE="${FLCODES_PASSPHRASE:-qemu-test}"
export ANDROID_SERIAL="127.0.0.1:$PORT"

echo "== 3. device info (no root)"
"${FLCODES[@]}" device info --serial "$ANDROID_SERIAL" | tee "$WORKDIR/device-info.txt"

echo "== 4. pull the APK splits (world readable, no root)"
"${FLCODES[@]}" device apk --serial "$ANDROID_SERIAL" --package "$PACKAGE" --out "$WORKDIR/apk" || true

echo "== 5. adb backup + extraction + key hunt"
"${FLCODES[@]}" device backup \
  --serial "$ANDROID_SERIAL" \
  --package "$PACKAGE" \
  --out "$WORKDIR/familylink.ab" \
  --scan --save --label qemu |
  tee "$WORKDIR/backup.txt"

if grep -qE '^\[android\]' "$WORKDIR/backup.txt"; then
  echo "== PASS: the shared secret came out of the backup without root"
  "${FLCODES[@]}" keys list
  exit 0
fi

echo "== FAIL: no candidate extracted."
echo "   * did you accept the backup dialog on the emulator screen?"
echo "   * does the package set android:allowBackup=\\"false\\"?"
echo "   * is the package actually installed and used at least once?"
exit 1
