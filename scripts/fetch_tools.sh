#!/usr/bin/env bash
# Fetch pinned tooling without executing npm lifecycle scripts.
set -euo pipefail
cd "$(dirname "$0")/.."
DEST="$PWD/.cache/tools"
mkdir -p "$DEST"
cd "$DEST"
npm pack @postar/apktool-node@0.3.4 --ignore-scripts --silent
python3 - <<'PY'
import base64, hashlib
from pathlib import Path
p = Path('postar-apktool-node-0.3.4.tgz')
expected = 'r+u5L/4a4ZXrmGQImEtiu8Y+6d4/MFBmgTGdctu8trNo5dodiwiKPp//8qwDNO45JpLYYx00aW9THwM7prHm1w=='
if base64.b64encode(hashlib.sha512(p.read_bytes()).digest()).decode() != expected:
    raise SystemExit('Hash do pacote de ferramentas não confere.')
PY
tar -xzf postar-apktool-node-0.3.4.tgz package/lib/apktool.jar package/lib/apksigner.jar
printf '\nExporte antes de compilar:\nexport APKTOOL_JAR="%s/package/lib/apktool.jar"\nexport APKSIGNER_JAR="%s/package/lib/apksigner.jar"\n' "$DEST" "$DEST"
