#!/usr/bin/env bash
# Build a minimal APK used to test the no-root acquisition on a real Android.
#
# The app does one thing: on launch it writes the Family Link shaped config
# (shared secret + TTL) into its own SharedPreferences. It declares
# android:allowBackup="true", so `adb backup` can copy exactly the private file
# that the real Family Link app keeps — which is what `flcodes abe scan` looks
# for. The secret is fictitious.
#
# Requires an Android SDK (ANDROID_HOME/ANDROID_SDK_ROOT) with build-tools and
# at least one platform, plus a JDK. No Gradle, no network.
#
#   tools/build_test_apk.sh --out /tmp/selftest.apk
#
set -euo pipefail

OUT="selftest.apk"
SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-/usr/local/lib/android/sdk}}"
PACKAGE="com.flcodes.selftest"
SECRET="${FLCODES_TEST_SECRET:-AItest-only-emulator-key}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --sdk) SDK="$2"; shift 2 ;;
    --secret) SECRET="$2"; shift 2 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -d "$SDK" ]] || { echo "no Android SDK at $SDK (set ANDROID_HOME)" >&2; exit 2; }
BUILD_TOOLS="$(find "$SDK/build-tools" -maxdepth 1 -mindepth 1 -type d | sort -V | tail -1)"
PLATFORM="$(find "$SDK/platforms" -maxdepth 1 -mindepth 1 -type d -name 'android-*' | sort -V | tail -1)"
[[ -n "$BUILD_TOOLS" && -n "$PLATFORM" ]] || {
  echo "SDK is missing build-tools or platforms (looked in $SDK)" >&2; exit 2; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
SRC="$WORK/src/com/flcodes/selftest"
mkdir -p "$SRC" "$WORK/classes" "$WORK/dex"

cat > "$WORK/AndroidManifest.xml" <<XML
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="$PACKAGE"
    android:versionCode="1"
    android:versionName="1.0">
    <uses-sdk android:minSdkVersion="21" android:targetSdkVersion="30" />
    <application
        android:label="flcodes selftest"
        android:allowBackup="true"
        android:fullBackupContent="true">
        <activity android:name=".Main" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
XML

cat > "$SRC/Main.java" <<'JAVA'
package com.flcodes.selftest;

import android.app.Activity;
import android.content.SharedPreferences;
import android.os.Bundle;

/**
 * Writes the Family Link shaped config into this app's private prefs, so the
 * no-root pipeline (adb backup -> flcodes abe scan) has something real to find.
 */
public class Main extends Activity {
    private static final String SECRET = "__SECRET__";
    private static final String CONFIG =
        "{\"parentAccessCode\":{\"sharedSecret\":\"" + SECRET + "\","
        + "\"accessCodeTtl\":600,\"clockDriftTolerance\":300}}";

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        SharedPreferences prefs = getSharedPreferences("familylink_preferences", MODE_PRIVATE);
        prefs.edit().putString("family_link_app_config", CONFIG).commit();
        System.out.println("flcodes-selftest: secret written");
        finish();
    }
}
JAVA
python3 - "$SRC/Main.java" "$SECRET" <<'PY'
import sys, pathlib
path = pathlib.Path(sys.argv[1])
path.write_text(path.read_text().replace("__SECRET__", sys.argv[2]))
PY

javac --release 8 -bootclasspath "$PLATFORM/android.jar" -d "$WORK/classes" \
      "$SRC/Main.java" 2>&1 | grep -v "bootstrap class path" || true
[[ -f "$WORK/classes/com/flcodes/selftest/Main.class" ]] || { echo "javac failed" >&2; exit 1; }

"$BUILD_TOOLS/d8" --lib "$PLATFORM/android.jar" --min-api 21 \
    --output "$WORK/dex" $(find "$WORK/classes" -name '*.class')

APK="$WORK/base.apk"
if [[ -x "$BUILD_TOOLS/aapt2" ]]; then
  "$BUILD_TOOLS/aapt2" link -o "$APK" -I "$PLATFORM/android.jar" \
      --manifest "$WORK/AndroidManifest.xml" \
      --min-sdk-version 21 --target-sdk-version 30
else
  "$BUILD_TOOLS/aapt" package -f -M "$WORK/AndroidManifest.xml" \
      -I "$PLATFORM/android.jar" -F "$APK"
fi
(cd "$WORK/dex" && zip -q -X "$APK" classes.dex)

"$BUILD_TOOLS/zipalign" -f 4 "$APK" "$WORK/aligned.apk"
if [[ ! -f "$WORK/debug.keystore" ]]; then
  keytool -genkeypair -keystore "$WORK/debug.keystore" -alias androiddebugkey \
      -storepass android -keypass android -keyalg RSA -keysize 2048 -validity 10000 \
      -dname "CN=flcodes selftest, O=experiment, C=BR" >/dev/null 2>&1
fi
"$BUILD_TOOLS/apksigner" sign --ks "$WORK/debug.keystore" --ks-pass pass:android \
    --key-pass pass:android --out "$OUT" "$WORK/aligned.apk"
"$BUILD_TOOLS/apksigner" verify "$OUT"
echo "built $OUT"
"$BUILD_TOOLS/aapt2" dump packagename "$OUT" 2>/dev/null || true
echo "package=$PACKAGE secret=$SECRET"
