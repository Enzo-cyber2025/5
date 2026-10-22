#!/usr/bin/env bash
# Boot an Android x86_64 emulator (QEMU) and run the no-root pipeline on it.
#
# Written for CI, but works locally with an Android SDK. Every step is logged to
# $WORK/run.log, so a failure can be read back without the raw job log:
#
#   tools/android_emulator_ci.sh --apk /path/app.apk --package com.example --expect AIte
#
# with --apk it installs that APK (the real Family Link, or the selftest app);
# without it, it builds the selftest APK first.
set -uo pipefail

WORK="${WORK:-$PWD/emulator-work}"
APK=""
PACKAGE="com.flcodes.selftest"
EXPECT="AIte"
API="30"
TAG="default"
ABI="x86_64"
BUILD_SELFTEST="1"
BOOT_TIMEOUT="${BOOT_TIMEOUT:-900}"
SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-/usr/local/lib/android/sdk}}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apk) APK="$2"; BUILD_SELFTEST="0"; shift 2 ;;
    --package) PACKAGE="$2"; shift 2 ;;
    --expect) EXPECT="$2"; shift 2 ;;
    --api) API="$2"; shift 2 ;;
    --work) WORK="$2"; shift 2 ;;
    --sdk) SDK="$2"; shift 2 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$WORK"
LOG="$WORK/run.log"
exec > >(tee -a "$LOG") 2>&1

export ANDROID_SDK_ROOT="$SDK"
export ANDROID_HOME="$SDK"
export PATH="$SDK/platform-tools:$SDK/emulator:$SDK/cmdline-tools/latest/bin:$PATH"
# let avdmanager use its default location (~/.android/avd); pointing
# ANDROID_AVD_HOME somewhere else makes the emulator look for a .ini that
# avdmanager never writes there
export ANDROID_AVD_HOME="$WORK/avd"
mkdir -p "$ANDROID_AVD_HOME"

HERE="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}"
export FLCODES_HOME="$WORK/home"
export FLCODES_PASSPHRASE="${FLCODES_PASSPHRASE:-emulator}"

fail() { echo "FAILED: $*"; exit 1; }
step() { echo; echo "===== $* ====="; }

trap 'status=$?; echo "--- exit $status ---"; ls -la "$WORK" 2>/dev/null | head -30; tail -25 "$WORK/emulator.log" 2>/dev/null' EXIT

step "0. environment"
if [[ -n "${CI:-}" ]] && command -v apt-get >/dev/null; then
  echo "installing the libraries the bundled QEMU needs"
  sudo apt-get update -qq >/dev/null 2>&1 || true
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
    libpulse0 libnss3 libx11-6 libxcomposite1 libxcursor1 libxi6 libxtst6 \
    libasound2 libgbm1 libxdamage1 libxrandr2 libglu1-mesa >/dev/null 2>&1 \
    || echo "(apt install had errors; continuing)"
fi
ls "$SDK" || fail "no SDK at $SDK"
SDKMANAGER="$(command -v sdkmanager || find "$SDK" -maxdepth 5 -type f -name sdkmanager | head -1)"
AVDMANAGER="$(command -v avdmanager || find "$SDK" -maxdepth 5 -type f -name avdmanager | head -1)"
[[ -x "$SDKMANAGER" ]] || fail "no sdkmanager (install cmdline-tools)"
EMULATOR="$(command -v emulator 2>/dev/null || find "$SDK" -maxdepth 3 -type f -name emulator 2>/dev/null | head -1)"
if [[ ! -x "$EMULATOR" ]]; then
  echo "the emulator package is not installed; installing it"
  yes | "$SDKMANAGER" --licenses >/dev/null 2>&1 || true
  "$SDKMANAGER" --install "platform-tools" "emulator" > "$WORK/sdkmanager.log" 2>&1 \
    || { tail -20 "$WORK/sdkmanager.log"; fail "cannot install the emulator package"; }
  EMULATOR="$SDK/emulator/emulator"
fi
echo "emulator=$EMULATOR"; echo "avdmanager=$AVDMANAGER"; echo "sdkmanager=$SDKMANAGER"
[[ -x "$EMULATOR" ]] || fail "no emulator binary"
"$EMULATOR" -version 2>&1 | head -3
adb version | head -2
ls /dev/kvm 2>&1 || echo "no /dev/kvm (software emulation, slow)"

step "1. system image"
if [[ ! -d "$SDK/system-images/android-$API/$TAG/$ABI" ]]; then
  yes | "$SDKMANAGER" --licenses >/dev/null 2>&1 || true
  "$SDKMANAGER" "system-images;android-$API;$TAG;$ABI" >/dev/null || fail "cannot install the system image"
fi
ls "$SDK/system-images/android-$API/$TAG/$ABI" | head -5

step "2. create the AVD"
echo no | "$AVDMANAGER" create avd -n ciflcodes \
  -k "system-images;android-$API;$TAG;$ABI" -d pixel \
  -p "$ANDROID_AVD_HOME/ciflcodes.avd" --force || fail "avdmanager failed"
echo "avd dir: $(ls -d "$ANDROID_AVD_HOME"/* 2>/dev/null)"
AVD_INI="$(find "$ANDROID_AVD_HOME" "$HOME/.android/avd" -maxdepth 2 -name '*.ini' 2>/dev/null | head -3)"
echo "avd ini files: ${AVD_INI:-none}"
"$EMULATOR" -list-avds || true
[[ -d "$ANDROID_AVD_HOME/ciflcodes.avd" ]] || fail "the AVD directory was not created"

step "3. boot the emulator (QEMU)"
"$EMULATOR" -avd ciflcodes -no-window -no-audio -no-boot-anim \
  -no-snapshot -gpu swiftshader_indirect -camera-back none -camera-front none \
  -accel auto -memory 2048 -cores 2 -wipe-data > "$WORK/emulator.log" 2>&1 &
EMULATOR_PID=$!
echo "emulator pid $EMULATOR_PID (log: $WORK/emulator.log)"

deadline=$(( $(date +%s) + BOOT_TIMEOUT ))
until [[ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; do
  if ! kill -0 "$EMULATOR_PID" 2>/dev/null; then
    tail -40 "$WORK/emulator.log"
    fail "the emulator process died"
  fi
  if [[ $(date +%s) -gt $deadline ]]; then
    tail -40 "$WORK/emulator.log"; adb devices
    fail "boot timeout (${BOOT_TIMEOUT}s)"
  fi
  sleep 10
done
adb devices
adb shell getprop ro.build.version.release
adb shell getprop ro.build.version.sdk
adb shell wm size

step "4. the APK"
if [[ "$BUILD_SELFTEST" == "1" ]]; then
  bash "$HERE/tools/build_test_apk.sh" --out "$WORK/selftest.apk" \
       --secret "AItest-only-emulator-key" || fail "the selftest APK did not build"
  APK="$WORK/selftest.apk"
fi
[[ -s "$APK" ]] || fail "no APK at $APK"
ls -l "$APK"
sha256sum "$APK"
"$SDK/build-tools/"*/aapt2 dump packagename "$APK" 2>/dev/null | head -1 || true

step "5. install and launch (no root)"
adb install -r -g "$APK" || fail "install failed"
adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1 2>&1 | tail -3 || true
sleep 15
adb shell dumpsys package "$PACKAGE" | grep -E "versionName|dataDir|flags=\[" | head -5 || true
adb shell pidof "$PACKAGE" || echo "(app is not running; that is fine for the backup)"

step "6. where the app keeps its data (REA, static and on-device)"
python3 -m flcodes device info --json | tee "$WORK/device-info.json"
python3 -m flcodes device apk --package "$PACKAGE" --out "$WORK/apk" | tee "$WORK/device-apk.txt" \
  || echo "pull failed (some packages are protected); continuing"
BASE_APK="$WORK/apk/base.apk"
[[ -s "$BASE_APK" ]] || BASE_APK="$APK"
python3 -m flcodes apk scan "$BASE_APK" | tee "$WORK/apk-scan.txt"
adb shell ls -la "/data/data/$PACKAGE" 2>&1 | tee "$WORK/private-dir.txt" || true
adb shell ls -la "/data/data/$PACKAGE/shared_prefs" 2>&1 | tee "$WORK/shared-prefs.txt" || true

step "7. adb backup (the device writes it; the dialog is accepted on screen)"
AB="$WORK/$PACKAGE.ab"
rm -f "$AB"
adb backup -f "$AB" -noapk "$PACKAGE" > "$WORK/backup-cmd.log" 2>&1 &
BACKUP_PID=$!
for i in $(seq 1 40); do
  [[ -s "$AB" ]] && break
  python3 "$HERE/tools/accept_backup_dialog.py" --retries 1 --interval 1 >/dev/null 2>&1 || true
  sleep 2
done
wait $BACKUP_PID 2>/dev/null || true
ls -l "$AB" 2>&1 | tee "$WORK/backup-size.txt"
[[ -s "$AB" ]] || { cat "$WORK/backup-cmd.log"; fail "empty backup (dialog not accepted or allowBackup=false)"; }

step "8. extract the container and hunt for the key"
python3 -m flcodes abe info "$AB" | tee "$WORK/abe-info.txt"
python3 -m flcodes abe extract "$AB" --out "$WORK/extracted" | tee "$WORK/abe-extract.txt" \
  || fail "extraction failed"
find "$WORK/extracted" -type f | sed "s|$WORK/extracted/||" | head -40 | tee "$WORK/tree.txt"
python3 -m flcodes abe scan "$AB" --save --label emulator | tee "$WORK/abe-scan.txt"

step "9. verdict"
if grep -q "^\[android\]" "$WORK/abe-scan.txt"; then
  grep -q "$EXPECT" "$WORK/abe-scan.txt" || fail "a key was found but it is not the expected one"
  echo "PASS: the shared secret was recovered from a real Android device without root"
  python3 -m flcodes keys list
  python3 -m flcodes gen --label emulator --json | tee "$WORK/code.json"
  exit 0
fi

step "note: no secret in the container"
echo "This is expected when the app has never been signed in (the real Family"
echo "Link writes its config only after the parent logs in), or when the app"
echo "declares android:allowBackup=false."
grep -iE "allowBackup|dataExtractionRules" "$WORK/apk-scan.txt" || true
exit 3
