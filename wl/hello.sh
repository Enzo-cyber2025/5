#!/bin/bash
set -eux
echo "token len: ${#GITHUB_TOKEN}"
echo "repo: $GITHUB_REPOSITORY"
python3 -c "
import json, os
json.dump({'body': 'hello wlh run='+os.environ['GITHUB_RUN_ID']+' sha='+os.environ['GITHUB_SHA'][:8]+' ts='+os.popen('date -u +%H:%M:%SZ').read().strip()}, open('/tmp/body.json','w'))
"
curl -sS -X POST \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" \
  -d @/tmp/body.json \
  -w "\nHTTP=%{http_code}\n" \
  "https://api.github.com/repos/$GITHUB_REPOSITORY/issues/7/comments" -o /tmp/resp.txt
cat /tmp/resp.txt
cp /tmp/resp.txt wlh-resp.txt
