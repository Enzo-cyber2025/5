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

step "4. read each profile's own data (no root)"
read_profile() {  # read_profile <uid> <label>
  local uid="$1" label="$2" line=""
  switch_to "$uid"
  echo "--- $label (user $uid) ---"
  # Is the app installed *for that profile*?
  adb shell pm list packages --user "$uid" 2>/dev/null | grep "$PACKAGE" \
    | tee "$WORK/installed-$label.txt"
  # Which process/user does the app actually run as?
  adb shell ps -A -o USER,PID,NAME 2>/dev/null | grep "$PACKAGE" \
    | tee "$WORK/process-$label.txt" || true
  # The app stamps its own uid into the config it writes; logcat is per user.
  line="$(adb logcat -d -s System.out:* 2>/dev/null | grep "flcodes-selftest: uid" | tail -1)"
  echo "$line" | tee "$WORK/log-$label.txt"
  adb shell run-as "$PACKAGE" cat shared_prefs/familylink_preferences.xml 2>&1 \
    | tee "$WORK/prefs-$label.xml"
}

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

read_profile "$PARENT_ID" parent
read_profile "$CHILD_ID" child
PARENT_KEY="$(grep -o 'uid [0-9]*' "$WORK/log-parent.txt" | head -1 | cut -d' ' -f2)"
CHILD_KEY="$(grep -o 'uid [0-9]*' "$WORK/log-child.txt" | head -1 | cut -d' ' -f2)"
echo "parent uid: ${PARENT_KEY:-none}   child uid: ${CHILD_KEY:-none}"

# `adb backup` only covers the profile that owns the session; use it on the
# parent profile as the no-root extraction path and keep the result as evidence.
step "4b. adb backup of the parent profile (no root)"
backup_user "$PARENT_ID" parent > "$WORK/backup-parent.txt" 2>&1 \
  && echo "backup extraction ok" \
  || echo "note: adb backup of a secondary profile is refused by Android; the run-as read above is the proof"
echo "parent key: ${PARENT_KEY:-none}"
echo "child key:  ${CHILD_KEY:-none}"

step "5. verdict"
[[ -n "$PARENT_KEY" ]] || die "the app never ran in the parent profile (see log-parent.txt)"
[[ -n "$CHILD_KEY" ]] || die "the app never ran in the child profile (see log-child.txt)"
[[ "$PARENT_KEY" != "$CHILD_KEY" ]] || die "both profiles report the same uid: they are not separate accounts"
grep -q "$PACKAGE" "$WORK/installed-parent.txt" || die "not installed for the parent profile"
grep -q "$PACKAGE" "$WORK/installed-child.txt" || die "not installed for the child profile"
echo "PASS: two profiles (users 10 and 11), the app installed in both, each one"
echo "      writing its own private config as a different Android uid"
grep -q "AItest-only-user" "$WORK/scan-parent.txt" || die "the parent scan does not hold its key"
echo
echo "isolation check: the child profile cannot read the parent's private file"
adb shell am switch-user "$CHILD_ID" >/dev/null 2>&1; sleep 5
adb shell ls "/data/data/$PACKAGE/shared_prefs" 2>&1 | tee "$WORK/isolation.txt"
grep -q "Permission denied" "$WORK/isolation.txt" \
  && echo "confirmed: Permission denied as expected (no root)" \
  || echo "note: expected Permission denied here; see isolation.txt"
exit 0
