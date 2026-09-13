#!/usr/bin/env bash
# Executes real repaired APK classes translated to JVM bytecode, with explicit
# Native/JSONObject test doubles. Does NOT run Android or native inference.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${APKTOOL_JAR:?Run scripts/fetch_tools.sh and export APKTOOL_JAR}"
PYTHON="${PYTHON:-.venv/bin/python}"
APK="${1:-dist/GGUF-Chat-repaired.apk}"
CACHE="$PWD/.cache/host-tests"
ENJARIFY="${ENJARIFY_DIR:-$PWD/.cache/gguf/enjarify}"
PIN=f2db0563aa83885ce6e6acd5b7dc9a8a1a1e1987
mkdir -p "$CACHE"
if [[ ! -d "$ENJARIFY" ]]; then
  git clone https://github.com/google/enjarify.git "$ENJARIFY"
fi
# Check the dependency tree without changing any branch (including its branch).
[[ "$(git -C "$ENJARIFY" rev-parse HEAD)" == "$PIN" ]] || {
  echo "Enjarify must be at pinned commit $PIN" >&2; exit 1;
}
export GGUF_TEST_DOUBLES_DEX="$CACHE/test-doubles.dex"
"$PYTHON" - <<'PY'
import os, sys
sys.path.insert(0, 'apk-fix')
from build_apk import tool
import jpype, jdk4py
jpype.startJVM(str(jdk4py.JAVA_HOME / 'lib/server/libjvm.so'), classpath=[tool('APKTOOL_JAR')])
jpype.JClass('brut.androlib.src.SmaliBuilder').build(
    jpype.JClass('brut.directory.ExtFile')('tests/fixtures'),
    jpype.JClass('java.io.File')(os.environ['GGUF_TEST_DOUBLES_DEX']), 24)
PY
export PYTHONPATH="$ENJARIFY${PYTHONPATH:+:$PYTHONPATH}"
"$PYTHON" -m enjarify.main "$GGUF_TEST_DOUBLES_DEX" -o "$CACHE/test-doubles.jar" -f
"$PYTHON" -m enjarify.main "$APK" -o "$CACHE/application.jar" -f
export GGUF_TEST_JAR="$CACHE/application.jar"
export GGUF_TEST_DOUBLES_JAR="$CACHE/test-doubles.jar"
"$PYTHON" -m pytest -q tests/test_jvm_regressions.py
