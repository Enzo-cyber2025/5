#!/usr/bin/env bash
# Publish only bounded reports/screenshots to THIS session branch. No other branch,
# no model, APK, private key or token. This runs only on a disposable CI emulator.
set -euo pipefail
BRANCH=arena/01a09b42-5
[[ "${GITHUB_REF:-}" == "refs/heads/$BRANCH" ]]
[[ "$(git branch --show-current)" == "$BRANCH" ]]
DEST="ci-results/${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}"
mkdir -p "$DEST"
python3 - "$DEST" <<'PY'
import os
from pathlib import Path
import shutil
import sys
source, dest = Path('evidence'), Path(sys.argv[1])
for name in ('normal-no-eye.png', 'unified-after-delete.json', 'unified-after-delete.png', 'smolvlm-logcat.txt', 'smolvlm-chats.json', 'smolvlm-1-reply.txt', 'smolvlm-2-reply.txt', 'smolvlm-1-reply.png', 'smolvlm-2-reply.png', 'smollm2-logcat.txt', 'smollm2-chats.json', 'smollm2-1-reply.txt', 'smollm2-2-reply.txt', 'smollm2-1-reply.png', 'smollm2-2-reply.png', 'saf-two-selected.png', 'mobile-reimport-models.json', 'reimport.png', 'failure-context.txt', 'mobile-models.json', 'mobile-logcat.txt', 'mobile-chats.json', 'mobile-reply.txt', 'mobile-reply.png', 'tools-collapsed.png', 'tools-expanded.png', 'runtime-regression.json', 'runtime-provenance.json', 'vulkan-crash-diagnostic.txt', 'host-vulkan.txt', 'vulkan-capabilities.json', 'vulkan-device.json', 'vulkan-features.txt', 'graphics-properties.txt', 'vulkan-backend.txt', 'vulkan-logcat.txt', 'vulkan-final-logcat.txt', 'vulkan-chats.json', 'vulkan-reply.txt', 'vulkan-reply.png', 'apk-payload.json', 'cpu-logcat.txt', 'cpu-second-logcat.txt', 'summary.json', 'launch.png', 'import.png', 'cpu-reply.png', 'cpu-second-reply.png', 'cpu-reply.txt', 'cpu-second-reply.txt', 'cpu-chats.json', 'cpu-second-chats.json', 'final-screen.png'):
    p = source / name
    if p.is_file() and p.stat().st_size < 2_000_000:
        shutil.copyfile(p, dest / name)
# Bounded attachment UI/reports only; never copy fixture bytes or private files.
for p in list(source.glob('attachments-*'))+list(source.glob('inference-*'))+list(source.glob('physical-*'))+list(source.glob('system-*')):
    if p.suffix in ('.png', '.json', '.txt') and p.is_file() and p.stat().st_size < 2_000_000:
        shutil.copyfile(p, dest / p.name)
(dest / 'run.txt').write_text('https://github.com/Enzo-cyber2025/5/actions/runs/' + os.environ['GITHUB_RUN_ID'] + '\n')
PY
git config user.name 'GGUF CI evidence'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git add -- "$DEST"
if ! git diff --cached --quiet; then
  git commit -m "Record Android emulator evidence ${GITHUB_RUN_ID} [skip ci]"
  # Rebase this evidence-only commit if another repair advanced the SAME branch.
  git pull --rebase origin "$BRANCH"
  git push origin "$BRANCH"
fi
