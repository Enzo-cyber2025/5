#!/usr/bin/env bash
# =============================================================================
#  Executa o código REAL do APK (classes.dex -> bytecode JVM) num JVM comum
#  e reproduz o crash de abertura ("crasha antes mesmo de abrir").
#
#  Pré-requisitos resolvidos automaticamente:
#   - JVM:      /tmp/venv via `pip install jdk4py`  (OpenJDK Temurin 25)
#   - ecj.jar:  compilador Eclipse baixado de um blob real do GitHub (qmole)
#   - org.json: clone de https://github.com/stleary/JSON-java (implementação real)
#   - app:      /tmp/app-enjarify.jar (enjarify sobre o classes.dex do APK REAL)
# =============================================================================
set -euo pipefail

VENV=/tmp/venv
JAVA_HOME="$( $VENV/bin/python -c 'import jdk4py; print(jdk4py.JAVA_HOME)' )"
JAVA="$JAVA_HOME/bin/java"
ECJ=/tmp/ecj.jar
ECJ_BLOB_SHA=ea8203121f394f21edcf863059468c6081952011
ECJ_REPO=chriskmanx/qmole-packages
APP_JAR=/tmp/app-enjarify.jar
OUT=/tmp/jvm-harness-out

mkdir -p "$OUT"

# 1) ecj.jar (compilador Eclipse; jdk4py é só JRE, não tem javac)
if [ ! -s "$ECJ" ]; then
  echo "[1/5] baixando ecj.jar (blob real do GitHub)..."
  gh api "repos/$ECJ_REPO/git/blobs/$ECJ_BLOB_SHA" --jq '.content' | tr -d '\n' | base64 -d > "$ECJ"
fi
"$JAVA" -jar "$ECJ" -version 2>&1 | head -1 || true

# 2) org.json real
if [ ! -d /tmp/jsonjava ]; then
  echo "[2/5] clonando JSON-java (org.json real)..."
  git clone --depth 1 https://github.com/stleary/JSON-java /tmp/jsonjava >/dev/null 2>&1
fi

# 3) converter o classes.dex do APK REAL para bytecode JVM (enjarify)
if [ ! -s "$APP_JAR" ]; then
  echo "[3/5] enjarify: classes.dex -> bytecode JVM..."
  cd /tmp
  unzip -o -q /home/user/5/GGUF-Chat.apk classes.dex -d /tmp/dexwork
  PYTHONPATH=/tmp/enjarify "$VENV/bin/python" -O -m enjarify.main \
    /tmp/dexwork/classes.dex -o "$APP_JAR" >/dev/null 2>&1
fi
echo "[3/5] APK bytecode: $APP_JAR ($(stat -c%s "$APP_JAR") bytes)"

# 4) compilar org.json + stub Context + driver (ecj, target Java 8)
echo "[4/5] compilando..."
rm -rf "$OUT/classes" && mkdir -p "$OUT/classes"
"$JAVA" -jar "$ECJ" -source 1.8 -target 1.8 -nowarn -proc:none \
  -cp "$APP_JAR" \
  -d "$OUT/classes" \
  $(find /tmp/jsonjava/src/main/java -name '*.java') \
  /home/user/5/apk-real-host-run/jvm-harness/src/android/content/Context.java \
  /home/user/5/apk-real-host-run/jvm-harness/src/LaunchRepro.java

# 5) executar o código REAL do APK
echo "[5/5] executando o bytecode REAL do APK..."
"$JAVA" -cp "$OUT/classes:$APP_JAR" LaunchRepro
