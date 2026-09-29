#!/usr/bin/env bash
set -euo pipefail
OUT=$1
echo "== procurando scripts de boot do Box64 em $OUT =="
mapfile -t STARTS < <(find "$OUT" -type f \( -name "start_box64.sh" -o -name "start_wow64.sh" -o -name "start.sh" -o -name "start_wine.sh" \) -path "*/res/raw/*")
echo "encontrados: ${#STARTS[@]}"
for p in "${STARTS[@]}"; do
  echo "-> $p"
  # Insere o bloco pre-AOT DEPOIS do shebang se existir, no topo caso contrário.
  if head -1 "$p" | grep -q '^#!'; then
    { head -1 "$p"; echo; cat winlator-a55/assets/patch-env.sh; tail -n +2 "$p"; } > "$p.new"
    mv "$p.new" "$p"
  else
    { cat winlator-a55/assets/patch-env.sh; echo; cat "$p"; } > "$p.new"
    mv "$p.new" "$p"
  fi
done
# Garante permissões de execução (apktool perde +x às vezes)
chmod +x "${STARTS[@]}" 2>/dev/null || true
# Confere se realmente tem PERSISTENT:
grep -l "BOX64_DYNAREC_PERSISTENT=1" "${STARTS[@]}" | head
echo "injeção feita"
