#!/usr/bin/env bash
# Download Family Link from the Play Store inside the emulator and take it apart
# without root.
#
#   FLCODES_GPLAY_EMAIL=... FLCODES_GPLAY_PASSWORD=... \
#   tools/play_store_reap.sh --work /tmp/store --api 30
#
# What it does, in order:
#   1. boots an emulator with the Google APIs *Play Store* image;
#   2. signs the Play Store into the account given in the environment
#      (uiautomator drives the real UI: email, password, "I agree");
#   3. installs com.google.android.apps.familylink from the store;
#   4. extracts the installed APK *without root* using `adb backup -apk`,
#      because the Play Store's /data/app copy is not readable to adb;
#   5. runs `flcodes apk scan` on the real, newest APK.
#
# Exit codes: 0 downloaded and scanned, 3 installed but not extractable,
#             4 no credentials (nothing is attempted), 1 anything else.
set -uo pipefail

WORK="${WORK:-/tmp/flcodes-store}"
API="30"
TAG="google_apis_playstore"
PACKAGE="com.google.android.apps.familylink"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}"
export FLCODES_HOME="${FLCODES_HOME:-$WORK/home}"
export FLCODES_PASSPHRASE="${FLCODES_PASSPHRASE:-store}"
mkdir -p "$WORK"
LOG="$WORK/store.log"
exec > >(tee -a "$LOG") 2>&1

step() { echo; echo "===== $* ====="; }
die() { echo "FAILED: $*"; exit 1; }

if [[ -z "${FLCODES_GPLAY_EMAIL:-}" || -z "${FLCODES_GPLAY_PASSWORD:-}" ]]; then
  echo "no Play Store credentials."
  echo "Set FLCODES_GPLAY_EMAIL and FLCODES_GPLAY_PASSWORD (repository secrets)"
  echo "to a throwaway Google account. Without a signed-in store the app cannot"
  echo "be downloaded, and Google blocks anonymous sessions."
  exit 4
fi

step "1. boot the Play Store image"
bash "$HERE/tools/emulator_boot.sh" --work "$WORK" --api "$API" --tag "$TAG" || exit 1
export ANDROID_SERIAL="$(adb devices | awk 'NR>1 && $2=="device" {print $1; exit}')"
echo "serial: $ANDROID_SERIAL"
adb shell pm list packages | grep -c vending || die "no Play Store app on this image"

ui() { python3 "$HERE/tools/ui.py" "$@"; }
shot() { ui shot "$WORK/screen-$1.png" >/dev/null 2>&1 || true; ui dump > "$WORK/ui-$1.xml" 2>/dev/null || true; }

step "2. sign in"
adb shell pm clear com.android.vending >/dev/null 2>&1 || true
adb shell am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER \
  -n com.android.vending/com.google.android.finsky.activities.MainActivity >/dev/null 2>&1
sleep 8
shot 01-store-start

# first-run dialogs
for pattern in "Accept" "I agree" "Got it" "OK" "Next"; do
  ui find "$pattern" --clickable-only --click >/dev/null 2>&1 && { echo "dismissed: $pattern"; sleep 3; }
done

if ! ui wait "Sign in" --timeout 60 --click >/dev/null 2>&1; then
  shot 02-no-signin
  die "the 'Sign in' button was not found (see $WORK/ui-02-no-signin.xml)"
fi
echo "sign in: tapped"
sleep 8
shot 03-account-picker

ui wait "Add another account|Use another account" --timeout 30 --click >/dev/null 2>&1 \
  && { echo "sign in: add another account"; sleep 4; }

if ! ui find "Email|phone|identifier" --clickable-only >/dev/null 2>&1; then
  # the identifier field is usually the focused input
  ui find "identifierId|Email or phone" >/dev/null 2>&1 || shot 04-before-email
fi
ui find "Email or phone|identifierId|Email" --click >/dev/null 2>&1 || shot 04-email-field
ui type "$FLCODES_GPLAY_EMAIL"
sleep 1
ui key KEYCODE_ENTER
sleep 6
shot 05-after-email

if ! ui wait "password|Enter your password" --timeout 60 >/dev/null 2>&1; then
  shot 06-no-password
  die "the password field never appeared (2FA, wrong address, or a block screen)"
fi
ui find "password|Enter your password" --click >/dev/null 2>&1
ui type "$FLCODES_GPLAY_PASSWORD"
sleep 1
ui key KEYCODE_ENTER
sleep 10
shot 07-after-password

for pattern in "I agree" "Accept" "Next" "Got it" "No thanks" "Skip"; do
  ui find "$pattern" --clickable-only --click >/dev/null 2>&1 && { echo "accepted: $pattern"; sleep 3; }
done
shot 08-after-signin

step "3. install Family Link from the Play Store"
adb shell am start -a android.intent.action.VIEW -d "market://details?id=$PACKAGE" >/dev/null 2>&1
sleep 10
shot 09-store-page
if ! ui wait "Install|Update" --timeout 90 --click >/dev/null 2>&1; then
  shot 10-no-install
  die "the Install button was not found (store page not loaded?)"
fi
echo "install: tapped, waiting for the package"
for _ in $(seq 1 90); do
  if adb shell pm path "$PACKAGE" 2>/dev/null | grep -q package:; then break; fi
  sleep 10
done
adb shell pm path "$PACKAGE" | tee "$WORK/pm-path.txt"
grep -q package: "$WORK/pm-path.txt" || die "the package never installed"
adb shell dumpsys package "$PACKAGE" | grep -E "versionName|firstInstallTime" | tee "$WORK/version.txt"
shot 11-installed

step "4. extract the APK without root (adb backup -apk)"
AB="$WORK/$PACKAGE.ab"
rm -f "$AB"
( adb backup -f "$AB" -apk "$PACKAGE" > "$WORK/backup-cmd.log" 2>&1 ) &
BACKUP_PID=$!
for _ in $(seq 1 60); do
  [[ -s "$AB" ]] && break
  python3 "$HERE/tools/accept_backup_dialog.py" --serial "$ANDROID_SERIAL" \
    --retries 1 --interval 1 >/dev/null 2>&1 || true
  sleep 2
done
wait $BACKUP_PID 2>/dev/null || true
ls -l "$AB" 2>&1 | tee "$WORK/backup-size.txt"
if [[ ! -s "$AB" ]]; then
  cat "$WORK/backup-cmd.log"
  echo "the backup is empty: the app may set allowBackup=false, or the dialog was not accepted"
  exit 3
fi

python3 -m flcodes abe info "$AB" | tee "$WORK/abe-info.txt"
rm -rf "$WORK/extracted"
python3 -m flcodes abe extract "$AB" --out "$WORK/extracted" | tee "$WORK/abe-extract.txt" || exit 3
find "$WORK/extracted" -name '*.apk' | tee "$WORK/apks.txt"
BASE="$(find "$WORK/extracted" -name 'base.apk' | head -1)"
[[ -n "$BASE" ]] || BASE="$(find "$WORK/extracted" -name '*.apk' -printf '%s %p\n' | sort -rn | head -1 | cut -d' ' -f2-)"
[[ -s "$BASE" ]] || { echo "no APK inside the container"; exit 3; }

cp -f "$BASE" "$WORK/familylink-store.apk"
sha256sum "$WORK/familylink-store.apk" | tee "$WORK/apk-sha256.txt"
echo "$WORK/familylink-store.apk" > "$WORK/apk-path.txt"

step "5. unpack the real APK (REA, static)"
python3 -m flcodes apk scan "$WORK/familylink-store.apk" | tee "$WORK/apk-scan.txt"
echo
echo "PASS: the newest Family Link APK was downloaded from the Play Store and"
echo "      extracted from the device without root: $WORK/familylink-store.apk"
