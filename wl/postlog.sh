#!/bin/bash
set -ux
git config user.email "ci@local"
git config user.name "ci"
# Cria branch de logs a partir de HEAD para nao conflitar
git checkout -B wl-logs || git checkout wl-logs
cp wlh.log wlh.log.last 2>/dev/null || echo "no wlh.log"
git add -f wlh.log wlh.log.last 2>/dev/null
git commit -m "wl log $(date -u +%Y-%m-%dT%H:%M:%SZ)" || echo "nothing to commit"
git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
git push -f origin wl-logs 2>&1 | tail -10
