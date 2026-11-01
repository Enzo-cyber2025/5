#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$HOME/text-binary"
cd "$ROOT"
mkdir -p classes dex out
: "${ANDROID_JAR:=$ROOT/android.jar}"
test -s "$ANDROID_JAR"
command -v javac >/dev/null
command -v aapt2 >/dev/null
command -v d8 >/dev/null
command -v apksigner >/dev/null

javac -source 8 -target 8 -bootclasspath "$ANDROID_JAR" -d classes MainActivity.java
aapt2 link --manifest AndroidManifest.xml -I "$ANDROID_JAR" \
  --min-sdk-version 23 --target-sdk-version 35 \
  --version-code 1 --version-name 1.0 \
  -o out/base.apk
d8 --lib "$ANDROID_JAR" --output dex classes
cp out/base.apk out/unsigned.apk
jar uf out/unsigned.apk -C dex classes.dex
if [ ! -s out/debug.keystore ]; then
  keytool -genkeypair -keystore out/debug.keystore -storetype JKS \
    -storepass android -keypass android -alias textbinary \
    -keyalg RSA -keysize 2048 -validity 3650 \
    -dname 'CN=Text Binary Test, O=Disposable CI'
fi
apksigner sign --ks out/debug.keystore --ks-key-alias textbinary \
  --ks-pass pass:android --key-pass pass:android \
  --out out/TextToBinary.apk out/unsigned.apk
apksigner verify --verbose out/TextToBinary.apk
stat -c 'apk_bytes=%s' out/TextToBinary.apk
sha256sum out/TextToBinary.apk
