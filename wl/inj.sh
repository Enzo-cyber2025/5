#!/bin/bash
set -e
OUT=$1
PE=$(cd "$(dirname "$0")" && pwd)/patch.sh
isshell() {
  local f="$1"
  case "$f" in
    *.sh) return 0;;
  esac
  head -c 2 "$f" 2>/dev/null | grep -q '#!' && return 0
  return 1
}
inject() {
  local f="$1"
  echo "-> inject $f"
  if head -1 "$f" | grep -q '^#!'; then
    { head -1 "$f"; echo; cat "$PE"; echo; tail -n +2 "$f"; } > "$f.new"
  else
    { cat "$PE"; echo; cat "$f"; } > "$f.new"
  fi
  mv "$f.new" "$f"; chmod +x "$f" 2>/dev/null || true
}
# 1. Nomes conhecidos
for t in start_box64.sh start_wow64.sh start_wine.sh start_box64_32.sh bootstrap.sh box64_start.sh wow64_start.sh setup_box64.sh; do
  find "$OUT" -type f -name "$t" 2>/dev/null | while read -r f; do inject "$f"; done
done
# 2. Procura em res/raw e assets por scripts que chamem box64/wine e que sejam shell
find "$OUT" \( -path "*/res/raw/*" -o -path "*/assets/*" \) -type f 2>/dev/null | while read -r f; do
  isshell "$f" || continue
  head -c 4096 "$f" 2>/dev/null | grep -q "box64\|BOX64\|wine\|WINEPREFIX" || continue
  grep -q "BOX64_DYNAREC_PERSISTENT=1" "$f" && { echo "ja patcheado: $f"; continue; }
  inject "$f"
done
# 3. Também injeta no default.box64rc (formato rc, nao shell; escreve linhas sem shebang handling)
find "$OUT" -type f -name "*.box64rc" 2>/dev/null | while read -r f; do
  grep -q "DYNAREC_PERSISTENT=1" "$f" && { echo "rc ja tem: $f"; continue; }
  echo "-> rc $f"
  # Extrai do patch.sh so as linhas BOX64_* de configuracao (sem export, sem mkdir)
  grep -E "^export BOX64|^export BOX86" "$PE" | sed 's/^export //' >> "$f"
done
echo "injection ok"
