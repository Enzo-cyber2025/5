#!/usr/bin/env bash
# Isolated host-built APK, never added to the production app.
set -euo pipefail
SDK="${ANDROID_HOME:?Android SDK required}"
BT=$(find "$SDK/build-tools" -mindepth 1 -maxdepth 1 -type d | sort -V | tail -1)
JAR="$SDK/platforms/android-35/android.jar"
OUT=.cache/test-input
SRC=tests/android-input
mkdir -p "$OUT/classes" "$OUT/dex"
"$BT/aapt2" compile --dir "$SRC/res" -o "$OUT/resources.zip"
"$BT/aapt2" link -I "$JAR" --manifest "$SRC/AndroidManifest.xml" -o "$OUT/input.apk" "$OUT/resources.zip"
javac -source 8 -target 8 -classpath "$JAR" -d "$OUT/classes" "$SRC/src/com/ggufchat/testinput/InputBridge.java"
"$BT/d8" --lib "$JAR" --min-api 28 --output "$OUT/dex" $(find "$OUT/classes" -name '*.class')
(cd "$OUT/dex" && zip -q ../input.apk classes.dex)
if [ ! -f "$OUT/test.p12" ]; then
  keytool -genkeypair -keystore "$OUT/test.p12" -storepass android -keypass android -alias test -keyalg RSA -keysize 2048 -validity 30 -dname 'CN=Disposable emulator test input'
fi
"$BT/apksigner" sign --ks "$OUT/test.p12" --ks-key-alias test --ks-pass pass:android "$OUT/input.apk"
"$BT/apksigner" verify "$OUT/input.apk"
