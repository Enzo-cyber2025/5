#!/usr/bin/env bash
# Build the ETS2-AI demo APK with the repo's Gradle-free pipeline
# (aapt2 -> javac -> d8 -> apksigner), same pattern as scripts/build_test_input.sh.
#
# Requires: ANDROID_HOME with build-tools + one platform jar; javac; zip; curl.
# Optional:
#   TFLITE_MODEL=<path/ets2ai-float32.tflite>  embeds the TFLite model (asset)
#   TFLITE_AAR=1                               also embeds the TFLite runtime
#                                              (classes + arm64/armeabi jniLibs)
# Both degrade gracefully: without them the app runs the pure-Java backend.
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
rm -rf "$OUT/classes"/* "$OUT/dex"/* "$OUT/tflite" "$OUT/apklib"

# 1. resources (+ optional model asset)
if [ -n "${TFLITE_MODEL:-}" ] && [ -f "${TFLITE_MODEL:-}" ]; then
  cp "$TFLITE_MODEL" "$SRC/assets/ets2ai-float32.tflite"
  echo "asset extra: ets2ai-float32.tflite ($(du -h "$SRC/assets/ets2ai-float32.tflite" | cut -f1))"
fi
"$BT/aapt2" compile --dir "$SRC/res" -o "$OUT/resources.zip"

# 2. link (assets included via -A)
"$BT/aapt2" link -I "$JAR" --manifest "$SRC/AndroidManifest.xml" \
    -A "$SRC/assets" -o "$OUT/base.apk" "$OUT/resources.zip"

# 3. java -> class -> dex
javac -source 8 -target 8 -encoding UTF-8 -Xlint:none \
    -classpath "$JAR" -d "$OUT/classes" \
    $(find "$SRC/src" -name '*.java')
D8_INPUTS=$(find "$OUT/classes" -name '*.class')

# 3b. optional TFLite runtime (reflection-based in app; never fails the build)
if [ "${TFLITE_AAR:-0}" = "1" ]; then
  mkdir -p "$OUT/tflite" "$OUT/apklib/lib/arm64-v8a" "$OUT/apklib/lib/armeabi-v7a"
  if curl -fsSL --retry 3 --max-time 180 -o "$OUT/tflite/tflite.aar" \
      https://repo1.maven.org/maven2/org/tensorflow/tensorflow-lite/2.14.0/tensorflow-lite-2.14.0.aar \
     && curl -fsSL --retry 3 --max-time 180 -o "$OUT/tflite/tflite-gpu.aar" \
      https://repo1.maven.org/maven2/org/tensorflow/tensorflow-lite-gpu/2.14.0/tensorflow-lite-gpu-2.14.0.aar; then
    ok=1
    (cd "$OUT/tflite" && unzip -oq tflite.aar classes.jar -d core) || ok=0
    (cd "$OUT/tflite" && unzip -oq tflite-gpu.aar classes.jar -d gpu) || ok=0
    (cd "$OUT/tflite" && unzip -oq tflite.aar 'jni/arm64-v8a/*' 'jni/armeabi-v7a/*') || true
    if [ "$ok" = "1" ] && [ -f "$OUT/tflite/core/classes.jar" ] \
       && [ -f "$OUT/tflite/gpu/classes.jar" ] && [ -d "$OUT/tflite/jni/arm64-v8a" ]; then
      cp "$OUT/tflite/core/classes.jar" "$OUT/tflite/tensorflow-lite.jar"
      cp "$OUT/tflite/gpu/classes.jar" "$OUT/tflite/tensorflow-lite-gpu.jar"
      cp "$OUT/tflite"/jni/arm64-v8a/*.so "$OUT/apklib/lib/arm64-v8a/" 2>/dev/null || true
      cp "$OUT/tflite"/jni/armeabi-v7a/*.so "$OUT/apklib/lib/armeabi-v7a/" 2>/dev/null || true
      (cd "$OUT/apklib" && zip -q "$OLDPWD/$OUT/base.apk" lib/*/*.so) || true
      D8_INPUTS="$D8_INPUTS $OUT/tflite/tensorflow-lite.jar $OUT/tflite/tensorflow-lite-gpu.jar"
      echo "runtime TFLite embutido (classes + jniLibs)"
    else
      echo "AVISO: AAR incompleto — seguindo sem runtime TFLite (Java puro)"
    fi
  else
    echo "AVISO: Maven Central indisponivel — APK sem runtime TFLite (Java puro)"
  fi
fi

"$BT/d8" --lib "$JAR" --min-api 26 --output "$OUT/dex" $D8_INPUTS

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
