#!/usr/bin/env bash
# End-to-end no-root test inside a booted Android emulator.
#
# Run this from the emulator job (or locally with a device attached):
#
#   tools/emulator_no_root_test.sh --package com.flcodes.selftest --expect AItest-only
#
# Steps, all without root:
#   1. `flcodes device info`      - props and packages
#   2. `flcodes device apk`       - pull the installed APK (world readable)
#   3. `flcodes apk scan`         - where the app keeps its private data
#   4. `flcodes device backup`    - adb backup, accepting the on-screen dialog
#   5. `flcodes abe scan`         - extract the secret and save it
#   6. `flcodes gen/verify`       - the saved key produces the expected code
#
set -euo pipefail

PACKAGE="com.flcodes.selftest"
EXPECT="AItest-only"
WORK="${WORKDIR:-/tmp/flcodes-emulator}"
SERIAL="${ANDROID_SERIAL:-}"
BOOT_TIMEOUT="${BOOT_TIMEOUT:-600}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --package) PACKAGE="$2"; shift 2 ;;
    --expect) EXPECT="$2"; shift 2 ;;
    --work) WORK="$2"; shift 2 ;;
    --serial) SERIAL="$2"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}"
export FLCODES_HOME="${FLCODES_HOME:-$WORK/home}"
export FLCODES_PASSPHRASE="${FLCODES_PASSPHRASE:-emulator}"
mkdir -p "$WORK"

adb_cmd() { adb ${SERIAL:+-s "$SERIAL"} "$@"; }
flc() { python3 -m flcodes "$@"; }

echo "== 0. wait for the device to finish booting (up to ${BOOT_TIMEOUT}s)"
deadline=$(( $(date +%s) + BOOT_TIMEOUT ))
until [[ "$(adb_cmd shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; do
  [[ $(date +%s) -lt $deadline ]] || { echo "device never booted" >&2; adb_cmd devices; exit 1; }
  sleep 5
done
adb_cmd shell getprop ro.build.version.release
adb_cmd shell getprop ro.build.version.sdk

echo
echo "== 1. device info (no root)"
flc device info ${SERIAL:+--serial "$SERIAL"}

echo
echo "== 2. pull the installed APK (world readable, no root)"
flc device apk ${SERIAL:+--serial "$SERIAL"} --package "$PACKAGE" --out "$WORK/apk"

echo
echo "== 3. where does it keep the private data? (static REA)"
flc apk scan "$WORK/apk/base.apk" | tee "$WORK/apk-scan.txt"
grep -q "private-dir" "$WORK/apk-scan.txt" || { echo "no private dir found in the APK" >&2; exit 1; }

echo
echo "== 4. adb backup, accepting the confirmation dialog"
rm -f "$WORK/$PACKAGE.ab"
adb_cmd backup -f "$WORK/$PACKAGE.ab" -noapk "$PACKAGE" >"$WORK/backup.log" 2>&1 &
backup_pid=$!
for attempt in $(seq 1 30); do
  if [[ -s "$WORK/$PACKAGE.ab" ]]; then break; fi
  if ! kill -0 "$backup_pid" 2>/dev/null && [[ ! -s "$WORK/$PACKAGE.ab" ]]; then
    # the command finished without producing a container: retry once the dialog is tapped
    sleep 2
  fi
  python3 "$HERE/tools/accept_backup_dialog.py" ${SERIAL:+--serial "$SERIAL"} \
      --retries 1 --interval 1 >/dev/null 2>&1 || true
  sleep 2
done
wait "$backup_pid" || true
ls -l "$WORK/$PACKAGE.ab" || { echo "no backup file" >&2; exit 1; }
if [[ ! -s "$WORK/$PACKAGE.ab" ]]; then
  echo "backup is empty: the dialog was not accepted or allowBackup=false" >&2
  cat "$WORK/backup.log" >&2 || true
  exit 1
fi

echo
echo "== 5. extract and hunt for the key (no root, no app cooperation)"
flc abe info "$WORK/$PACKAGE.ab"
flc abe scan "$WORK/$PACKAGE.ab" --save --label emulator | tee "$WORK/abe-scan.txt"
grep -q "\[android\]" "$WORK/abe-scan.txt" || { echo "no secret extracted" >&2; exit 1; }
grep -q "$EXPECT" "$WORK/abe-scan.txt" || { echo "unexpected secret" >&2; exit 1; }

echo
echo "== 6. the saved key generates a code"
flc keys list
flc gen --label emulator --json | tee "$WORK/code.json"
python3 - <<'PY'
import json, pathlib
record = json.loads(pathlib.Path("/tmp/flcodes-emulator/code.json").read_text().strip().splitlines()[-1])
assert len(record["code"]) == 6 and record["code"].isdigit(), record
assert record["validity"] == 600, record
print(f"code {record['code']} valid until {record['valid_to_utc']} (ttl {record['validity']}s)")
PY

echo
echo "PASS: key recovered from a real Android device without root"
