#!/bin/bash
set -eux
IN=$1; OUT=$2
KS=/tmp/debug.keystore
if [ ! -f "$KS" ]; then
  keytool -genkeypair -v -keystore "$KS" -storepass android -alias androiddebugkey \
    -keypass android -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Debug,O=Debug,C=BR" 2>&1 | tail -3
fi
# zipalign é opcional (está no uber jar); sem ele o apk instala mas com tamanho maior.
# Usa jarsigner direto
jarsigner -verbose -sigalg SHA256withRSA -digestalg SHA-256 -keystore "$KS" \
  -storepass android -keypass android "$IN" androiddebugkey 2>&1 | tail -10
# zipalign manual: usa a ferramenta do Android SDK build-tools se presente, senão o uber jar embutido
if command -v zipalign >/dev/null; then
  zipalign -f 4 "$IN" "$OUT"
else
  # Fallback: copia e confia que jarsigner já alinhou
  cp "$IN" "$OUT"
fi
# Verifica
jarsigner -verify "$OUT" 2>&1 | tail -3
