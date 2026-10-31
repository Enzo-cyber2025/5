#!/usr/bin/env bash
# Reproducible build for the Pré-Tradutor EXE prototype APK.
#
# Does not use the official Android SDK (aapt2 is pulled from an npm package
# that bundles upstream Google binaries; apktool/apksigner come from an npm
# package that bundles the upstream jars; the JDK comes from PyPI). Everything
# is fetched from registry.npmjs.org / pypi.org, which are allow-listed in
# this workspace. No handwritten dex/zip signing implementation is used:
# apksigner (Google's own tool) does the signing.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
CACHE="$ROOT/.cache"
mkdir -p "$CACHE/tools"

# 1. JDK (provides java/keytool) ---------------------------------------------
if [ ! -x "$ROOT/.venv_jdk/bin/python3" ]; then
  python3 -m venv "$ROOT/.venv_jdk"
  "$ROOT/.venv_jdk/bin/pip" install --quiet jdk4py
fi
JAVA_HOME_DIR=$("$ROOT/.venv_jdk/bin/python3" -c "import jdk4py; print(jdk4py.JAVA_HOME)")
JAVA="$JAVA_HOME_DIR/bin/java"
KEYTOOL="$JAVA_HOME_DIR/bin/keytool"

# 2. apktool.jar + apksigner.jar (smali assembler + official signer) --------
if [ ! -f "$CACHE/tools/apktool.jar" ]; then
  (cd "$CACHE/tools" && npm pack @postar/apktool-node@0.3.4 --ignore-scripts --silent
   tar -xzf postar-apktool-node-0.3.4.tgz package/lib/apktool.jar package/lib/apksigner.jar
   mv package/lib/apktool.jar . && mv package/lib/apksigner.jar .
   rm -rf package postar-apktool-node-0.3.4.tgz)
fi

# 3. aapt2 (official Google resource/manifest compiler, Linux x64 build) ----
if [ ! -f "$CACHE/tools/aapt2" ]; then
  (cd "$CACHE/tools" && npm pack aaptjs3 --ignore-scripts --silent
   tar -xzf aaptjs3-*.tgz package/bin/x64/linux/aapt2
   mv package/bin/x64/linux/aapt2 . && chmod +x aapt2
   rm -rf package aaptjs3-*.tgz)
fi

# 4. Assemble the unsigned APK from source (manifest + hand-written smali) --
PROJECT="$CACHE/project"
rm -rf "$PROJECT"
mkdir -p "$PROJECT/smali"
cp src/AndroidManifest.xml "$PROJECT/"
cp -r src/smali/* "$PROJECT/smali/"
if [ -d src/assets ]; then
  mkdir -p "$PROJECT/assets"
  cp -r src/assets/* "$PROJECT/assets/"
fi
cat > "$PROJECT/apktool.yml" <<'EOF'
!!brut.androlib.meta.MetaInfo
version: 2.9.3
apkFileName: pretradutor.apk
isFrameworkApk: false
usesFramework:
  ids:
  - 1
sdkInfo:
  minSdkVersion: '26'
  targetSdkVersion: '34'
packageInfo:
  forcedPackageId: '127'
versionInfo:
  versionCode: '1'
  versionName: '1.0'
compressionType: false
doNotCompress: []
EOF

mkdir -p release
"$JAVA" -jar "$CACHE/tools/apktool.jar" b "$PROJECT" -o "$CACHE/unsigned.apk" --aapt "$CACHE/tools/aapt2"

# 5. Sign it -----------------------------------------------------------------
mkdir -p "$ROOT/../.signing"
KS="$ROOT/../.signing/pretradutor-exe.keystore"
if [ ! -f "$KS" ]; then
  "$KEYTOOL" -genkeypair -v -keystore "$KS" -alias pretradutor \
    -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass "${PRETRADUTOR_KEYSTORE_PASSWORD:-PreTradutorExe2026}" \
    -keypass "${PRETRADUTOR_KEYSTORE_PASSWORD:-PreTradutorExe2026}" \
    -dname "CN=Pre-Tradutor EXE, OU=Prototipo, O=Local, L=Barbacena, S=MG, C=BR"
fi
"$JAVA" -jar "$CACHE/tools/apksigner.jar" sign \
  --ks "$KS" --ks-pass "pass:${PRETRADUTOR_KEYSTORE_PASSWORD:-PreTradutorExe2026}" --ks-key-alias pretradutor \
  --out release/PreTradutorEXE.apk "$CACHE/unsigned.apk"

sha256sum release/PreTradutorEXE.apk | tee release/PreTradutorEXE.apk.sha256
echo "Built release/PreTradutorEXE.apk"
