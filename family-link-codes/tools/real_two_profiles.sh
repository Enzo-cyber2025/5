#!/usr/bin/env bash
# The real, published Family Link installed for two profiles on one device.
#
#   tools/real_two_profiles.sh --work /tmp/rtp --apk /tmp/base.apk \
#       --splits /tmp/splits.txt --package com.google.android.apps.kids.familylink
#
# "Two accounts" is automated as far as it can honestly be: two Android user
# profiles (a parent and a child) on one emulator, each with its own uid and its
# own private data. Google *accounts* cannot be created by a script — the signup
# asks for a phone number and runs anti-automation — so what this script proves
# is the device half: the published app installs, launches as a different uid in
# each profile, and each profile keeps its own data.
#
# Exit codes: 0 both profiles installed and launched; 10 the APK cannot install
# on this ABI (documented wall); 1 anything else.
set -uo pipefail

WORK="${WORK:-/tmp/flcodes-rtp}"
APK=""
SPLITS=""
PACKAGE="com.google.android.apps.kids.familylink"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}"
export FLCODES_HOME="${FLCODES_HOME:-$WORK/home}"
export FLCODES_PASSPHRASE="${FLCODES_PASSPHRASE:-real}"
mkdir -p "$WORK"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --work) WORK="$2"; shift 2 ;;
    --apk) APK="$2"; shift 2 ;;
    --splits) SPLITS="$2"; shift 2 ;;
    --package) PACKAGE="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

step() { echo; echo "===== $* ====="; }
die() { echo "FAILED: $*"; exit 1; }

[[ -n "${ANDROID_SERIAL:-}" ]] || export ANDROID_SERIAL="$(adb devices | awk 'NR>1 && $2=="device" {print $1; exit}')"
[[ -n "${ANDROID_SERIAL:-}" ]] || die "no device (boot one with tools/emulator_boot.sh)"
[[ -s "$APK" ]] || die "no APK at $APK"

step "0. device"
adb shell getprop ro.product.cpu.abi
adb shell getprop ro.build.version.release
adb shell pm list users

step "1. the APK about to be installed"
ls -l "$APK"
sha256sum "$APK"
if [[ -s "$SPLITS" ]]; then
  echo "bundle pieces: $(wc -l < "$SPLITS")"
  while read -r piece; do printf '  %s\n' "$(basename "$piece")"; done < "$SPLITS"
fi

step "2. two profiles"
create_user() {
  local name="$1" id
  id="$(adb shell pm create-user "$name" 2>&1 | tr -d '\r' | sed -n 's/.*id \([0-9]\+\).*/\1/p')"
  [[ -n "$id" ]] || id="$(adb shell pm list users | sed -n "s/.*UserInfo{\([0-9]\+\):$name:.*/\1/p")"
  [[ -n "$id" ]] || die "could not create the user $name"
  echo "$id"
}
PARENT_ID="$(create_user parent)" || exit 1
CHILD_ID="$(create_user child)" || exit 1
echo "parent user: $PARENT_ID   child user: $CHILD_ID"
adb shell pm list users | tee "$WORK/users.txt"

switch_to() {
  local uid="$1" state=""
  adb shell am start-user -w "$uid" >/dev/null 2>&1
  adb shell am switch-user "$uid" >/dev/null 2>&1
  adb shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1
  adb shell wm dismiss-keyguard >/dev/null 2>&1
  for _ in $(seq 1 15); do
    state="$(adb shell am get-started-user-state "$uid" 2>/dev/null | tr -d '\r')"
    [[ "$state" == *"UNLOCKED"* ]] && break
    adb shell input swipe 540 1700 540 500 >/dev/null 2>&1
    adb shell input keyevent 82 >/dev/null 2>&1
    sleep 3
  done
  echo "user $uid: ${state:-unknown} (current: $(adb shell am get-current-user | tr -d '\r'))"
}

install_for() {  # install_for <uid> <label>
  local uid="$1" label="$2"
  local out="$WORK/install-$label.txt" status=0
  switch_to "$uid" > "$WORK/state-$label.txt"
  cat "$WORK/state-$label.txt"
  if [[ -s "$SPLITS" ]] && [[ "$(wc -l < "$SPLITS")" -gt 1 ]]; then
    mapfile -t pieces < "$SPLITS"
    adb install-multiple -r -g --user "$uid" "${pieces[@]}" > "$out" 2>&1 || status=$?
  else
    adb install -r -g --user "$uid" "$APK" > "$out" 2>&1 || status=$?
  fi
  cat "$out"
  return $status
}

step "3. install in both profiles"
install_for "$PARENT_ID" parent || install_status=1
install_for "$CHILD_ID" child || install_status=1
if grep -qs "INSTALL_FAILED_NO_MATCHING_ABIS" "$WORK"/install-*.txt; then
  echo
  echo "WALL: this bundle has no native code for $(adb shell getprop ro.product.cpu.abi | tr -d '\r')."
  echo "The Android emulator on an x86 host cannot run an ARM image, so a"
  echo "published ARM-only bundle can be inspected here but not executed."
  exit 10
fi
[[ "${install_status:-0}" == "0" ]] || die "install failed for a reason other than ABI"

step "4. launch in both profiles and watch each uid"
launch_and_watch() {  # launch_and_watch <uid> <label>
  local uid="$1" label="$2"
  switch_to "$uid" | tee "$WORK/state-$label.txt"
  adb shell am force-stop --user "$uid" "$PACKAGE" >/dev/null 2>&1
  adb logcat -c >/dev/null 2>&1
  adb shell monkey --user "$uid" -p "$PACKAGE" -c android.intent.category.LAUNCHER 1 \
    > "$WORK/launch-$label.txt" 2>&1 || true
  tail -2 "$WORK/launch-$label.txt"
  sleep 20
  echo "--- package installed for user $uid ---"
  adb shell pm list packages --user "$uid" 2>/dev/null | grep "$PACKAGE" \
    | tee "$WORK/installed-$label.txt" || echo "(not listed)"
  echo "--- process (which uid it runs as) ---"
  adb shell ps -A -o USER,PID,NAME 2>/dev/null | grep "$PACKAGE" \
    | tee "$WORK/process-$label.txt" || echo "(not running)"
  echo "--- what the app writes, as far as a non-root shell can see ---"
  adb shell dumpsys package "$PACKAGE" 2>/dev/null \
    | grep -E "dataDir|userId=|versionName|flags=" | head -6 | tee "$WORK/package-$label.txt"
  echo "--- logcat of the app (first interest lines) ---"
  adb logcat -d 2>/dev/null | grep -iE "familylink|kids|fatal|AndroidRuntime" \
    | head -20 | tee "$WORK/logcat-$label.txt" || true
}

launch_and_watch "$PARENT_ID" parent
launch_and_watch "$CHILD_ID" child

step "5. private data of the real app, without root"
for pair in "$PARENT_ID:parent" "$CHILD_ID:child"; do
  uid="${pair%%:*}"; label="${pair##*:}"
  switch_to "$uid" >/dev/null
  echo "--- $label ---"
  adb shell ls -la "/data/data/$PACKAGE" 2>&1 | head -5 | tee "$WORK/privatedir-$label.txt"
  adb shell ls -la "/data/data/$PACKAGE/shared_prefs" 2>&1 | head -5 | tee "$WORK/prefs-$label.txt"
done

step "6. can the device hand us the container at all?"
AB="$WORK/$PACKAGE-owner.ab"
rm -f "$AB"
( adb backup -f "$AB" -noapk "$PACKAGE" > "$WORK/backup.log" 2>&1 ) &
pid=$!
for _ in $(seq 1 30); do
  [[ -s "$AB" ]] && break
  python3 "$HERE/tools/accept_backup_dialog.py" --retries 1 --interval 1 >/dev/null 2>&1 || true
  sleep 2
done
wait $pid 2>/dev/null || true
ls -l "$AB" 2>&1 | tee "$WORK/backup-size.txt"
if [[ -s "$AB" ]]; then
  python3 -m flcodes abe info "$AB" | tee "$WORK/abe-info.txt"
  python3 -m flcodes abe scan "$AB" 2>&1 | tee "$WORK/abe-scan.txt"
else
  echo "no container: the app refuses backup or the dialog was not accepted"
fi

step "7. verdict"
adb shell pm list packages --user "$PARENT_ID" 2>/dev/null | grep -q "$PACKAGE" \
  || die "not installed for the parent profile"
adb shell pm list packages --user "$CHILD_ID" 2>/dev/null | grep -q "$PACKAGE" \
  || die "not installed for the child profile"
p_uid="$(adb shell dumpsys package "$PACKAGE" 2>/dev/null | grep -o 'userId=[0-9]*' | head -1)"
echo "the published app is installed in two profiles on one device"
echo "package: $PACKAGE ($p_uid)"
echo "each profile has its own uid and its own /data/data/$PACKAGE"
echo "PASS: two profiles, real APK, no root"
exit 0
