#!/usr/bin/env bash
# Bounded evidence for the session branch that triggered this run, and nothing else.
# No APK, model, private key or token is ever committed; the job only runs on a
# disposable CI emulator and the push is retried ONLY for fast-forward races.
set -euo pipefail
: "${GITHUB_RUN_ID:?}"
BRANCH="$(git branch --show-current)"
[[ "${GITHUB_REF:-}" == "refs/heads/$BRANCH" ]]
[[ "$BRANCH" == arena/* ]]
DEST="ci-results/${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT:?}-${GGUF_EVIDENCE_VARIANT:-text-ui}"
mkdir -p "$DEST"
python3 - "$DEST" <<'PY'
import os, shutil, sys
from pathlib import Path
source, dest = Path('evidence'), Path(sys.argv[1])
names = ('summary.json', 'failure-context.txt', 'mobile-reply.txt', 'mobile-reply.png',
         'smollm2-logcat.txt', 'smollm2-chats.json', 'smollm2-1-reply.txt', 'smollm2-1-reply.png',
         'vulkan-capabilities.json', 'vulkan-device.json', 'vulkan-backend.txt',
         'apk-payload.json', 'host-vulkan.txt', 'launch.png', 'final-screen.png',
         'physical-text-ui.json', 'physical-text.png', 'physical-text-logcat.txt',
         'physical-text-start.txt', 'physical-code-ui.json', 'physical-code-stream.png',
         'text-ui-device-state.txt', 'attachments-detach.json', 'performance.json',
         'cpu-logcat.txt', 'vulkan-logcat.txt', 'vulkan-policy-default-logcat.txt',
         'cpu-threads-auto-logcat.txt', 'local-gates.txt')
for name in names:
    p = source / name
    if p.is_file() and p.stat().st_size < 2_000_000:
        shutil.copyfile(p, dest / name)
for pattern in ('attachments-*', 'inference-*', 'physical-*', 'system-*', 'text-*', '*-perf.json'):
    for p in source.glob(pattern):
        if p.suffix in ('.png', '.json', '.txt') and p.is_file() and p.stat().st_size < 2_000_000:
            shutil.copyfile(p, dest / p.name)
(dest / 'run.txt').write_text('https://github.com/Enzo-cyber2025/5/actions/runs/' + os.environ['GITHUB_RUN_ID'] + '\n')
(dest / 'branch.txt').write_text(os.environ['GITHUB_REF'] + '\n')
PY
git config user.name 'GGUF CI evidence'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git add -- "$DEST"
if git diff --cached --quiet; then
  echo 'No evidence changes to publish.'
  exit 0
fi
git commit -m "Record Android text UI evidence ${GITHUB_RUN_ID} [skip ci]"
log=$(mktemp)
trap 'rm -f "$log"' EXIT
for attempt in 1 2 3 4; do
  git pull --rebase origin "$BRANCH"
  if git push origin "$BRANCH" >"$log" 2>&1; then
    cat "$log"
    exit 0
  fi
  cat "$log" >&2
  grep -Eq '\[rejected\].*(fetch first|non-fast-forward)' "$log" || exit 1
  [[ "$attempt" != 4 ]] || { echo 'Evidence publication kept racing; refusing a force push.' >&2; exit 1; }
  sleep "$attempt"
done
