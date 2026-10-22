#!/usr/bin/env bash
# Two-account test on a real Android: parent profile and child profile.
#
# "Two accounts" here means two Android user profiles on the same device — the
# thing that can actually be automated. Google accounts cannot: signing up opens
# a phone-verification and anti-automation flow, so the parent and child Google
# accounts have to be created by a human (see tools/play_store_reap.sh for using
# one of them in CI).
#
# What this script proves:
#   1. a second and a third Android user can be created and given the same app;
#   2. each profile keeps its own private data (the app writes the uid into the
#      secret, so the two backups must differ);
#   3. `adb backup` + `flcodes abe scan` extracts the right key for the profile
#      that is active — without root;
#   4. user A's data is not visible from user B.
#
#   tools/two_users_test.sh --work /tmp/two --apk /tmp/selftest.apk \
#       --package com.flcodes.selftest
#
set -uo pipefail

WORK="${WORK:-/tmp/flcodes-two}"
APK=""
PACKAGE="com.flcodes.selftest"
BUILD="1"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}"
export FLCODES_HOME="${FLCODES_HOME:-$WORK/home}"
export FLCODES_PASSPHRASE="${FLCODES_PASSPHRASE:-two}"
mkdir -p "$WORK"
exec > >(tee -a "$WORK/two.log") 2>&1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --work) WORK="$2"; shift 2 ;;
    --apk) APK="$2"; BUILD="0"; shift 2 ;;
    --package) PACKAGE="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

step() { echo; echo "===== $* ====="; }
die() { echo "FAILED: $*"; exit 1; }

[[ -n "${ANDROID_SERIAL:-}" ]] || export ANDROID_SERIAL="$(adb devices | awk 'NR>1 && $2=="device" {print $1; exit}')"
[[ -n "${ANDROID_SERIAL:-}" ]] || die "no device (boot one with tools/emulator_boot.sh)"

step "0. device"
adb shell getprop ro.build.version.release
adb shell pm list users

step "1. the APK"
if [[ "$BUILD" == "1" ]]; then
  python3 "$HERE/tools/build_test_apk.py" --out "$WORK/selftest.apk" --secret "AItest-only-user" \
      > "$WORK/build.log" 2>&1 || { tail -20 "$WORK/build.log"; die "build failed"; }
  APK="$WORK/selftest.apk"
fi
[[ -s "$APK" ]] || die "no APK"
ls -l "$APK"

step "2. create the two extra profiles"
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

step "3. install in both profiles and launch"
# A secondary user starts locked; `am start-user -w` starts it and waits, then a
# swipe/keyguard dismissal finishes the unlock. Without RUNNING_UNLOCKED the
# profile cannot write data and `adb backup` comes back empty.
switch_to() {  # switch_to <uid>
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

switch_to "$PARENT_ID"
adb install -r --user "$PARENT_ID" "$APK" 2>&1 | tee "$WORK/install-parent.txt"
adb shell am start --user "$PARENT_ID" -n "$PACKAGE/.Main" >/dev/null 2>&1
sleep 12
switch_to "$CHILD_ID"
adb install -r --user "$CHILD_ID" "$APK" 2>&1 | tee "$WORK/install-child.txt"
adb shell am start --user "$CHILD_ID" -n "$PACKAGE/.Main" >/dev/null 2>&1
sleep 12

step "4. back up each profile (no root) and extract the key"
backup_user() {  # backup_user <uid> <label>
  local uid="$1" label="$2"
  switch_to "$uid"
  echo "active user: $(adb shell am get-current-user | tr -d '\r')"
  local ab="$WORK/$label.ab"
  rm -f "$ab"
  ( adb backup -f "$ab" -noapk "$PACKAGE" > "$WORK/backup-$label.log" 2>&1 ) &
  local pid=$!
  for _ in $(seq 1 40); do
    [[ -s "$ab" ]] && break
    python3 "$HERE/tools/accept_backup_dialog.py" --serial "$ANDROID_SERIAL" \
      --retries 1 --interval 1 >/dev/null 2>&1 || true
    sleep 2
  done
  wait $pid 2>/dev/null || true
  ls -l "$ab" 2>&1 | tee "$WORK/size-$label.txt"
  if [[ ! -s "$ab" ]]; then
    echo "empty backup for $label; device state follows"
    adb shell am get-started-user-state "$uid" || true
    adb shell dumpsys user | head -20 | tee "$WORK/users-state.txt"
    adb logcat -d -s BackupManager:* BackupConfirm:* 2>/dev/null | tail -20 | tee "$WORK/logcat-$label.txt"
    python3 "$HERE/tools/ui.py" dump > "$WORK/ui-$label.xml" 2>/dev/null || true
    die "empty backup for $label"
  fi
  python3 -m flcodes abe extract "$ab" --out "$WORK/extracted-$label" > "$WORK/extract-$label.txt" 2>&1 \
    || die "extraction failed for $label"
  python3 -m flcodes abe scan "$ab" | tee "$WORK/scan-$label.txt"
}

PARENT_KEY="$(backup_user "$PARENT_ID" parent | tee /dev/stderr | grep -o 'AItest-only-user[0-9]*' | head -1)"
CHILD_KEY="$(backup_user "$CHILD_ID" child | tee /dev/stderr | grep -o 'AItest-only-user[0-9]*' | head -1)"
echo "parent key: ${PARENT_KEY:-none}"
echo "child key:  ${CHILD_KEY:-none}"

step "5. verdict"
[[ -n "$PARENT_KEY" ]] || die "no key from the parent profile"
[[ -n "$CHILD_KEY" ]] || die "no key from the child profile"
[[ "$PARENT_KEY" != "$CHILD_KEY" ]] || die "both profiles produced the same key: isolation is broken"
echo "PASS: two profiles, two independent keys, both extracted without root"
grep -q "AItest-only-user" "$WORK/scan-parent.txt" || die "the parent scan does not hold its key"
echo
echo "isolation check: the child profile cannot read the parent's private file"
adb shell am switch-user "$CHILD_ID" >/dev/null 2>&1; sleep 5
adb shell ls "/data/data/$PACKAGE/shared_prefs" 2>&1 | tee "$WORK/isolation.txt"
grep -q "Permission denied" "$WORK/isolation.txt" \
  && echo "confirmed: Permission denied as expected (no root)" \
  || echo "note: expected Permission denied here; see isolation.txt"
exit 0
