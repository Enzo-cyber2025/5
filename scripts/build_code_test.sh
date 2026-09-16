#!/usr/bin/env bash
set -euo pipefail
SDK="${ANDROID_HOME:?}"
BT=$(find "$SDK/build-tools" -mindepth 1 -maxdepth 1 -type d | sort -V | tail -1)
JAR="$SDK/platforms/android-35/android.jar"
OUT=.cache/code-test
mkdir -p "$OUT/classes" "$OUT/dex"
"$BT/aapt2" link -I "$JAR" --manifest tests/android-code/AndroidManifest.xml -o "$OUT/test.apk"
javac -source 8 -target 8 -classpath "$JAR" -d "$OUT/classes" tests/android-code/src/com/ggufchat/codetest/CodeActivity.java
"$BT/d8" --lib "$JAR" --min-api 28 --output "$OUT/dex" $(find "$OUT/classes" -name '*.class')
(cd "$OUT/dex" && zip -q ../test.apk classes.dex)
keytool -genkeypair -keystore "$OUT/test.p12" -storepass android -alias test -keyalg RSA -keysize 2048 -validity 30 -dname 'CN=Disposable code renderer test'
"$BT/apksigner" sign --ks "$OUT/test.p12" --ks-pass pass:android "$OUT/test.apk"
