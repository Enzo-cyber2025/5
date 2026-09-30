#!/bin/bash
set -ux
# Posta wlh.log numa pasta no branch wl-logs
git config user.email "ci@local"
git config user.name "ci"
git fetch origin wl-logs 2>/dev/null && git checkout -B wl-logs origin/wl-logs || git checkout --orphan wl-logs
# Limpa arquivos do branch de build (nao queremos a arvore completa)
git rm -rf --ignore-unmatch . 2>/dev/null || true
# Copia o log
mkdir -p _logs
cp wlh.log _logs/wlh.log 2>/dev/null || echo "no wlh.log"
[ -f wlh.log ] && cp wlh.log _logs/wlh.log
# Metadata
echo "run_id=${RUN_ID:-unknown} date=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > _logs/meta.txt
git add _logs/wlh.log _logs/meta.txt
git commit -m "wl log $(date -u +%Y-%m-%dT%H:%M:%SZ)" 2>&1 | tail -3 || echo "nothing to commit"
# Push com o token do actions (tem permissao write-all)
git push -f origin wl-logs 2>&1 | tail -5
