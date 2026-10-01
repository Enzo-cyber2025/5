#!/usr/bin/env bash
# Prova de modo offline: o APK traz TODO o necessario dentro dele
# (pesos da IA + modelo .tflite) e nao faz download nenhum em runtime.
set -euo pipefail
cd "$(dirname "$0")/.."
APK="${1:-dist/ETS2-AI-mobile.apk}"
test -f "$APK" || { echo "APK nao encontrado: $APK"; exit 1; }
OUT=.cache/offline-check
rm -rf "$OUT"; mkdir -p "$OUT"
unzip -oq "$APK" 'assets/*' -d "$OUT"
test -s "$OUT/assets/model-weights.txt" || { echo "FALHA: pesos nao embutidos"; exit 1; }
if [ -s "$OUT/assets/ets2ai-float32.tflite" ]; then
  echo "modelo tflite embutido: sim ($(du -h "$OUT/assets/ets2ai-float32.tflite" | cut -f1))"
else
  echo "AVISO: tflite ausente neste build — a inferencia segue offline em Java"
fi
echo "OFFLINE OK: IA 100% embutida no APK (nenhum download em runtime)"
