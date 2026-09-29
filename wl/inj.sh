#!/bin/bash
set -e
OUT=$1
PE=$(cd "$(dirname "$0")" && pwd)/patch.sh
find "$OUT/res/raw" -type f \( -name "start_box64.sh" -o -name "start_wow64.sh" \) -print | while read -r f; do
  echo "-> $f"
  if head -1 "$f" | grep -q '^#!'; then
    { head -1 "$f"; echo; cat "$PE"; echo; tail -n +2 "$f"; } > "$f.new"
  else
    { cat "$PE"; echo; cat "$f"; } > "$f.new"
  fi
  mv "$f.new" "$f"; chmod +x "$f"
done
