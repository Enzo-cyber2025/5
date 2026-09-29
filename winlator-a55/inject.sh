#!/usr/bin/env bash
set -euo pipefail
OUT=$1
for f in start_box64.sh start_wow64.sh; do
  p=$(find "$OUT" -name "$f" -path "*/res/raw/*" | head -1)
  if [ -n "$p" ]; then
    echo "patching $p"
    cat winlator-a55/assets/start_box64.sh > "$p"
  fi
done
echo "injeção concluída"
