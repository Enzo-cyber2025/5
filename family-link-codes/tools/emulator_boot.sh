#!/usr/bin/env bash
# Boot an Android emulator (QEMU) and leave it running for the next step.
#
#   tools/emulator_boot.sh --work /tmp/emu --api 30 --tag google_apis_playstore
#
# Exports the coordinates on stdout and writes them to $WORK/boot-env.sh:
#   ANDROID_SERIAL, EMULATOR_PID, EMULATOR_LOG
set -uo pipefail

WORK="${WORK:-/tmp/flcodes-emu}"
API="30"
TAG="default"
ABI="x86_64"
ACCEL="auto"
BOOT_TIMEOUT="${BOOT_TIMEOUT:-900}"
SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-/usr/local/lib/android/sdk}}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --work) WORK="$2"; shift 2 ;;
    --api) API="$2"; shift 2 ;;
    --tag) TAG="$2"; shift 2 ;;
    --abi) ABI="$2"; shift 2 ;;
    --accel) ACCEL="$2"; shift 2 ;;
    --timeout) BOOT_TIMEOUT="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$WORK"
export PATH="$SDK/platform-tools:$SDK/emulator:$SDK/cmdline-tools/latest/bin:$PATH"
export ANDROID_AVD_HOME="${ANDROID_AVD_HOME:-$WORK/avd}"
mkdir -p "$ANDROID_AVD_HOME"

SDKMANAGER="$(command -v sdkmanager || true)"
AVDMANAGER="$(command -v avdmanager || true)"
EMULATOR="$(command -v emulator 2>/dev/null || find "$SDK" -maxdepth 3 -type f -name emulator 2>/dev/null | head -1)"

if [[ ! -x "$EMULATOR" && -n "$SDKMANAGER" ]]; then
  yes | "$SDKMANAGER" --licenses >/dev/null 2>&1 || true
  "$SDKMANAGER" --install "platform-tools" "emulator" > "$WORK/sdkmanager.log" 2>&1 || true
  EMULATOR="$SDK/emulator/emulator"
fi
[[ -x "$EMULATOR" ]] || { echo "no emulator binary" >&2; exit 1; }

if [[ ! -d "$SDK/system-images/android-$API/$TAG/$ABI" ]]; then
  echo "installing system-images;android-$API;$TAG;$ABI"
  yes | "$SDKMANAGER" --licenses >/dev/null 2>&1 || true
  "$SDKMANAGER" "system-images;android-$API;$TAG;$ABI" > "$WORK/system-image.log" 2>&1 \
    || { tail -20 "$WORK/system-image.log" >&2; exit 1; }
fi

AVD="flcodes-$API-$TAG"
echo no | "$AVDMANAGER" create avd -n "$AVD" \
  -k "system-images;android-$API;$TAG;$ABI" -d pixel \
  -p "$ANDROID_AVD_HOME/$AVD.avd" --force > "$WORK/avdmanager.log" 2>&1 \
  || { tail -20 "$WORK/avdmanager.log" >&2; exit 1; }

# a Play Store image needs more RAM than the default
RAM=2048; [[ "$TAG" == *playstore* ]] && RAM=3072
# an ARM guest on an x86 host has no KVM: it runs under TCG, which is slow
if [[ "$ABI" == arm* && "$ACCEL" == "auto" ]]; then ACCEL="off"; fi
[[ "$ABI" == arm* ]] && RAM=3072
echo "boot: abi $ABI, accel $ACCEL, ram $RAM"

"$EMULATOR" -avd "$AVD" -no-window -no-audio -no-boot-anim -no-snapshot \
  -gpu swiftshader_indirect -camera-back none -camera-front none \
  -accel "$ACCEL" -memory "$RAM" -cores 4 -wipe-data \
  > "$WORK/emulator.log" 2>&1 &
EMULATOR_PID=$!
echo "boot: pid $EMULATOR_PID, avd $AVD, image android-$API;$TAG;$ABI"

deadline=$(( $(date +%s) + BOOT_TIMEOUT ))
until [[ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; do
  if ! kill -0 "$EMULATOR_PID" 2>/dev/null; then
    echo "the emulator died:" >&2; tail -30 "$WORK/emulator.log" >&2; exit 1
  fi
  if [[ $(date +%s) -gt $deadline ]]; then
    echo "boot timeout" >&2; tail -30 "$WORK/emulator.log" >&2; exit 1
  fi
  sleep 10
done
# let the launcher settle
for _ in $(seq 1 30); do
  [[ "$(adb shell dumpsys window 2>/dev/null | grep -c mDreamingLockscreen)" == "0" ]] && break
  sleep 2
done

SERIAL="$(adb devices | awk 'NR>1 && $2=="device" {print $1; exit}')"
cat > "$WORK/boot-env.sh" <<EOF
export ANDROID_SERIAL="$SERIAL"
export EMULATOR_PID="$EMULATOR_PID"
export EMULATOR_LOG="$WORK/emulator.log"
EOF
echo "boot: serial $SERIAL, android $(adb shell getprop ro.build.version.release | tr -d '\r') (API $(adb shell getprop ro.build.version.sdk | tr -d '\r'))"
echo "boot: product $(adb shell getprop ro.product.name | tr -d '\r') / $(adb shell getprop ro.build.type | tr -d '\r')"
echo "BOOTED"
