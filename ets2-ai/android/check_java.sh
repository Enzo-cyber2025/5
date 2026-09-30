#!/usr/bin/env bash
# Java parity gate: the pure-Java inference used inside the APK must match
# the numpy reference bit-close (< 1e-4) and drive in-lane in the Java world
# port. Runs on the CI (needs javac + java; no Android SDK required).
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=.cache/java-check
mkdir -p "$OUT/classes"
rm -rf "$OUT/classes"/*

javac -encoding UTF-8 -d "$OUT/classes" \
    android/src/com/enzo/ets2ai/NeuralNet.java \
    android/src/com/enzo/ets2ai/SimWorld.java \
    android/src/com/enzo/ets2ai/Dispatcher.java \
    android/tools/JavaCheck.java

{ java -cp "$OUT/classes" JavaCheck android/assets/model-weights.txt 2>&1; echo "JAVACHECK_EXIT=$?"; } | tee "$OUT/java-check.log"
grep -q "JAVA_FORWARD_END" "$OUT/java-check.log" || { echo "JavaCheck nao rodou ate o fim"; exit 3; }
grep -q "JAVA_MISSION_OK" "$OUT/java-check.log" || { echo "Missao Java nao concluiu"; exit 4; }

python3 - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, ".")
import numpy as np
from ets2ai.contract import load_weights
from ets2ai.model import forward

probes = [
    [0.60, -0.5714, 0.0833, 0.0, 0.02, 0.04, 0.05, 0.0, 1.0, 0.80, 0.10, 0.05, 0.92],
    [0.85, 0.2857, -0.1667, 0.03, -0.03, 0.0, 0.0, 0.0, 1.0, 0.55, 0.40, 0.30, 0.10],
    [1.30, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.95, 0.75, 0.80, 0.50],
    [0.95, 0.8571, 0.2500, -0.04, -0.06, -0.08, -0.02, 0.0, 1.0, 0.30, 0.05, 0.02, 0.05],
    [0.10, -0.2857, 0.4167, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.50, 0.20, 0.60, 0.80],
]
layers, _ = load_weights("artifacts/model-weights.json")

log = Path(".cache/java-check/java-check.log").read_text()
block = log.split("JAVA_FORWARD_BEGIN")[1].split("JAVA_FORWARD_END")[0].strip().splitlines()
assert len(block) == len(probes), f"esperava {len(probes)} linhas, veio {len(block)}"
worst = 0.0
for probe, line in zip(probes, block):
    vals = [float(v) for v in line.split(",")]
    ref = forward(np.array(probe, dtype=np.float32), layers)[0]
    for got, want in zip(vals[:3], ref):
        worst = max(worst, abs(got - float(want)))
print(f"paridade Java x numpy: pior delta = {worst:.2e}")
assert worst < 1e-4, "Java divergiu do numpy"
assert "JAVA_LOOP_OK" in log, "loop fechado Java falhou"
print("JAVA PARITY OK")
PY
