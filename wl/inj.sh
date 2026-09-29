#!/usr/bin/env bash
set -euo pipefail
OUT=$1
: > /tmp/tt
find "$OUT" -type f \( -name "start_box64.sh" -o -name "start_wow64.sh" -o -name "start.sh" -o -name "wine.sh" \) -path "*/res/raw/*" -print >> /tmp/tt
mapfile -t STARTS < <(sort -u /tmp/tt)
echo "scripts encontrados:"; printf '  %s\n' "${STARTS[@]}"
for p in "${STARTS[@]}"; do
  if head -1 "$p" | grep -q '^#!'; then
    { head -1 "$p"; echo; cat winlator-a55/assets/patch-env.sh; echo; tail -n +2 "$p"; } > "$p.new"
  else
    { cat winlator-a55/assets/patch-env.sh; echo; cat "$p"; } > "$p.new"
  fi
  mv "$p.new" "$p"
  chmod +x "$p" 2>/dev/null || true
done
