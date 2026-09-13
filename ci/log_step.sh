#!/usr/bin/env bash
# Preserve the original exit code and expose bounded diagnostics via Checks API.
# Actions log downloads are not reachable from all clients; annotations are.
set -uo pipefail
label="$1"
shift
mkdir -p .cache/ci-logs
logfile=".cache/ci-logs/${label//[^a-zA-Z0-9_-]/_}.log"
"$@" 2>&1 | tee "$logfile"
status=${PIPESTATUS[0]}
python3 - "$label" "$status" "$logfile" <<'PY'
from pathlib import Path
import sys
label, status, filename = sys.argv[1:]
text = Path(filename).read_text(errors='replace')
# Never publish runner masking directives (which contain the unmasked value).
text = '\n'.join(line for line in text.splitlines() if '::add-mask::' not in line)
if label == 'emulator':
    commands = Path('evidence/commands.log')
    if commands.exists():
        text += '\n--- Last ADB commands ---\n' + commands.read_text(errors='replace')[-10000:]
text = f'exit={status}\n' + text[-20000:]
text = text.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
level = 'notice' if status == '0' else 'error'
print(f'::{level} title=GGUF {label}::{text}')
PY
exit "$status"
