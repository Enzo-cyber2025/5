#!/bin/bash
set -e
OUT=$1
PE=$(cd "$(dirname "$0")" && pwd)/patch.sh
for t in start_box64.sh start_wow64.sh; do
  find "$OUT" -type f -path "*/res/raw/*" -name "$t" 2>/dev/null | while read -r f; do
    echo "-> $f"
    if head -1 "$f" | grep -q '^#!'; then
      { head -1 "$f"; echo; cat "$PE"; echo; tail -n +2 "$f"; } > "$f.new"
    else
      { cat "$PE"; echo; cat "$f"; } > "$f.new"
    fi
    mv "$f.new" "$f"; chmod +x "$f"
  done
done
# Procura qualquer outro script de boot se start_box64.sh nao existir (no v11 pode ter outro nome)
grep -rl "BOX64" "$OUT/res/raw" 2>/dev/null | head -5 | while read -r f; do
  grep -q "BOX64_DYNAREC_PERSISTENT=1" "$f" && { echo "ja tem patch: $f"; continue; }
  echo "injetando em $f"
  if head -1 "$f" | grep -q '^#!'; then
    { head -1 "$f"; echo; cat "$PE"; echo; tail -n +2 "$f"; } > "$f.new"
  else
    { cat "$PE"; echo; cat "$f"; } > "$f.new"
  fi
  mv "$f.new" "$f"; chmod +x "$f"
done
echo "injection ok"
