#!/bin/bash
set -e
OUT=$1
PE=$(cd "$(dirname "$0")" && pwd)/patch.sh
inject() {
  local f="$1"
  echo "-> inject $f"
  if head -1 "$f" | grep -q '^#!'; then
    { head -1 "$f"; echo; cat "$PE"; echo; tail -n +2 "$f"; } > "$f.new"
  else
    { cat "$PE"; echo; cat "$f"; } > "$f.new"
  fi
  mv "$f.new" "$f"; chmod +x "$f"
}
# 1. Nomes conhecidos de scripts de boot do Winlator 7-12
for t in start_box64.sh start_wow64.sh start_wine.sh start_box64_32.sh bootstrap.sh box64_start.sh wow64_start.sh setup_box64.sh; do
  find "$OUT" -type f -name "$t" 2>/dev/null | while read -r f; do inject "$f"; done
done
# 2. Qualquer arquivo em res/raw/ ou assets/ que contenha BOX64 ou BOX86 e ainda nao tenha o patch
find "$OUT" \( -path "*/res/raw/*" -o -path "*/assets/*" \) -type f 2>/dev/null \
  | while read -r f; do
      head -c 2048 "$f" 2>/dev/null | grep -q "BOX64\|BOX86\|box64" || continue
      grep -q "BOX64_DYNAREC_PERSISTENT=1" "$f" && { echo "ja patcheado: $f"; continue; }
      inject "$f"
    done
echo "injection ok"
