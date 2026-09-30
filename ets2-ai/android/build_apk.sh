#!/usr/bin/env bash
# Build the ETS2-AI demo APK with the repo's Gradle-free pipeline
# (aapt2 -> javac -> d8 -> apksigner), same pattern as scripts/build_test_input.sh.
# Requires: ANDROID_HOME with build-tools + one platform jar; javac; zip.
set -euo pipefail
cd "$(dirname "$0")/.."

SDK="${ANDROID_HOME:?export ANDROID_HOME antes}"
BT=$(find "$SDK/build-tools" -mindepth 1 -maxdepth 1 -type d | sort -V | tail -1)
JAR=$(ls -d "$SDK"/platforms/android-* | sort -V | tail -1)/android.jar
test -f "$JAR"
echo "build-tools: $BT"
echo "platform:    $JAR"

SRC=android
OUT=.cache/android-build
DIST=dist
mkdir -p "$OUT/classes" "$OUT/dex" "$DIST"
rm -rf "$OUT/classes"/* "$OUT/dex"/* 

# 1. resources
"$BT/aapt2" compile --dir "$SRC/res" -o "$OUT/resources.zip"

# 2. link (assets included via -A)
"$BT/aapt2" link -I "$JAR" --manifest "$SRC/AndroidManifest.xml" \
    -A "$SRC/assets" -o "$OUT/base.apk" "$OUT/resources.zip"

# 3. java -> class -> dex
javac -source 8 -target 8 -encoding UTF-8 \
    -classpath "$JAR" -d "$OUT/classes" \
    $(find "$SRC/src" -name '*.java')
"$BT/d8" --lib "$JAR" --min-api 26 --output "$OUT/dex" \
    $(find "$OUT/classes" -name '*.class')

# 4. pack + sign
(cd "$OUT/dex" && zip -q "$OLDPWD/$OUT/base.apk" classes.dex)
if [ ! -f "$OUT/release.p12" ]; then
    keytool -genkeypair -keystore "$OUT/release.p12" -storepass ets2ai \
        -keypass ets2ai -alias ets2ai -keyalg RSA -keysize 2048 -validity 10950 \
        -dname 'CN=ETS2-AI demo'
fi
"$BT/apksigner" sign --ks "$OUT/release.p12" --ks-key-alias ets2ai \
    --ks-pass pass:ets2ai --key-pass pass:ets2ai \
    --out "$DIST/ETS2-AI-mobile.apk" "$OUT/base.apk"
"$BT/apksigner" verify "$DIST/ETS2-AI-mobile.apk"

SIZE=$(du -h "$DIST/ETS2-AI-mobile.apk" | cut -f1)
echo "OK -> $DIST/ETS2-AI-mobile.apk ($SIZE)"
