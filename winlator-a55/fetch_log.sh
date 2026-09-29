#!/bin/bash
set -e
mkdir -p wl-logs
RID=${{ github.event.inputs.rid || '36595103403' }}
# tenta baixar os artefatos
gh run download "$RID" -D wl-logs/ 2>&1 | tee wl-logs/download.log
# lista job steps
gh api "repos/Enzo-cyber2025/5/actions/runs/$RID/jobs" > wl-logs/jobs.json
for jid in $(python3 -c "import json;[print(j['id']) for j in json.load(open('wl-logs/jobs.json'))['jobs']]"); do
  curl -sSL -H "Authorization: Bearer ${{ github.token }}" -H "Accept: application/vnd.github+json" -L \
    "$(gh api "repos/Enzo-cyber2025/5/actions/jobs/$jid/logs" -i | grep -i '^location:' | awk '{print $2}' | tr -d '\r')" \
    -o wl-logs/job-$jid.txt 2>&1 || true
done
ls -la wl-logs/
