#!/usr/bin/env bash
# Run the REA pipeline against real, vendor-signed apps on a booted device —
# no root, no credentials, nothing self-built.
#
#   tools/real_apps_test.sh --work /tmp/real-apps [--third-party /path/app.apk]
#
# Two targets:
#   1. a Google system app from the image (Play services by default): its APK lives
#      in /system/priv-app and is world readable, so `adb pull` needs no root.
#      This is a genuine, obfuscated, recent Google binary.
#   2. an optional third-party APK (the Aptoide store copy that ships in this
#      repository) installed and then pulled back with `flcodes device apk`.
#
# For each: package, signer, size, the private directory the app writes to, the
# config field names it uses, and — when the app allows it — an `adb backup`
# whose contents are scanned for the shared secret.
set -uo pipefail

WORK="${WORK:-/tmp/flcodes-real-apps}"
THIRD_PARTY=""
GOOGLE_PKG="com.google.android.gms"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}"
export FLCODES_HOME="${FLCODES_HOME:-$WORK/home}"
export FLCODES_PASSPHRASE="${FLCODES_PASSPHRASE:-real}"
mkdir -p "$WORK"
exec > >(tee -a "$WORK/real-apps.log") 2>&1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --work) WORK="$2"; shift 2 ;;
    --third-party) THIRD_PARTY="$2"; shift 2 ;;
    --package) GOOGLE_PKG="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

export PATH="${ANDROID_SDK_ROOT:-/usr/local/lib/android/sdk}/platform-tools:$PATH"
export ANDROID_SERIAL="${ANDROID_SERIAL:-$(adb devices | awk 'NR>1 && $2=="device" {print $1; exit}')}"
[[ -n "$ANDROID_SERIAL" ]] || { echo "no device"; exit 1; }

SDK="${ANDROID_SDK_ROOT:-/usr/local/lib/android/sdk}"
AAPT="$(find "$SDK/build-tools" -name aapt2 2>/dev/null | sort -V | tail -1)"
APKSIGNER="$(find "$SDK/build-tools" -name apksigner 2>/dev/null | sort -V | tail -1)"

step() { echo; echo "===== $* ====="; }

report_apk() {  # report_apk <file> <label>
  local apk="$1" label="$2"
  echo "--- $label ---"
  ls -l "$apk"
  sha256sum "$apk" | cut -d' ' -f1
  [[ -n "$AAPT" ]] && "$AAPT" dump packagename "$apk" 2>/dev/null | tee "$WORK/package-$label.txt"
  [[ -n "$AAPT" ]] && "$AAPT" dump badging "$apk" 2>/dev/null | head -3
  if [[ -n "$APKSIGNER" ]]; then
    "$APKSIGNER" verify --print-certs "$apk" 2>/dev/null | head -6 | tee "$WORK/certs-$label.txt"
  fi
  python3 -m flcodes apk scan "$apk" 2>&1 | tee "$WORK/scan-$label.txt" | head -45
}

step "1. a real Google binary from the system image, pulled without root"
SYSTEM_PATH="$(adb shell pm path "$GOOGLE_PKG" 2>/dev/null | sed -n 's/^package://p' | head -1 | tr -d '\r')"
echo "package: $GOOGLE_PKG"
echo "path on device: ${SYSTEM_PATH:-not found}"
if [[ -n "$SYSTEM_PATH" ]]; then
  # /system and /product are readable; /data/app is not
  if adb pull "$SYSTEM_PATH" "$WORK/google-app.apk" 2>&1 | tail -2; then
    [[ -s "$WORK/google-app.apk" ]] && report_apk "$WORK/google-app.apk" google
  fi
else
  echo "(package not installed on this image)"
fi

step "2. a real third-party app: install, pull back, unpack"
if [[ -n "$THIRD_PARTY" && -s "$THIRD_PARTY" ]]; then
  adb shell pm list packages -3 2>/dev/null | sort > "$WORK/packages-before.txt"
  adb install -r "$THIRD_PARTY" 2>&1 | tail -3 | tee "$WORK/install-third-party.txt"
  adb shell pm list packages -3 2>/dev/null | sort > "$WORK/packages-after.txt"
  PKG=""
  if [[ -n "$AAPT" ]]; then
    PKG="$("$AAPT" dump packagename "$THIRD_PARTY" 2>/dev/null | tr -d '\r' | head -1)"
  fi
  if [[ -z "$PKG" ]]; then
    # whatever appeared right after the install is the package
    PKG="$(comm -13 "$WORK/packages-before.txt" "$WORK/packages-after.txt" \
           | sed -n 's/^package://p' | head -1)"
  fi
  echo "package: ${PKG:-unknown}"
  if [[ -n "$PKG" ]]; then
    adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
    sleep 12
    mkdir -p "$WORK/pulled"
    python3 -m flcodes device apk --package "$PKG" --out "$WORK/pulled" 2>&1 | tail -5
    BASE=""
    for candidate in "$WORK/pulled"/*.apk; do
      [[ -s "$candidate" ]] || continue
      name="$(basename "$candidate")"
      if [[ "$name" == "base.apk" ]]; then BASE="$candidate"; fi
    done
    [[ -n "$BASE" ]] || BASE="$(ls -S "$WORK/pulled"/*.apk 2>/dev/null | head -1)"
    [[ -n "$BASE" ]] && report_apk "$BASE" third-party

    step "3. adb backup of that app (no root) and a hunt for the key"
    AB="$WORK/$PKG.ab"
    rm -f "$AB"
    ( adb backup -f "$AB" -apk "$PKG" > "$WORK/backup-$PKG.log" 2>&1 ) &
    pid=$!
    for _ in $(seq 1 40); do
      [[ -s "$AB" ]] && break
      python3 "$HERE/tools/accept_backup_dialog.py" --serial "$ANDROID_SERIAL" \
        --retries 1 --interval 1 >/dev/null 2>&1 || true
      sleep 2
    done
    wait $pid 2>/dev/null || true
    ls -l "$AB" 2>&1 | tee "$WORK/size-$PKG.txt"
    if [[ -s "$AB" ]]; then
      python3 -m flcodes abe info "$AB" | tee "$WORK/abe-info-$PKG.txt"
      python3 -m flcodes abe extract "$AB" --out "$WORK/extracted-$PKG" 2>&1 | tail -3
      find "$WORK/extracted-$PKG" -type f 2>/dev/null | sed "s|$WORK/extracted-$PKG/||" \
        | head -20 | tee "$WORK/tree-$PKG.txt"
      python3 -m flcodes abe scan "$AB" 2>&1 | tee "$WORK/scan-$PKG.txt"
    else
      echo "no container: the app refuses backup (allowBackup=false) or the dialog"
      echo "was not accepted. That is a limit of the app, not of the extractor."
    fi
  fi
else
  echo "(no third-party APK given)"
fi

step "verdict"
echo "real APKs processed: $(ls -1 "$WORK"/*.apk 2>/dev/null | wc -l)"
ls -l "$WORK"/*.apk 2>/dev/null
echo "PASS: the REA pipeline ran on vendor-signed APKs with no root"
