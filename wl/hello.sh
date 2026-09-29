#!/bin/bash
set -eux
echo "token len: ${#GITHUB_TOKEN}"
echo "repo: $GITHUB_REPOSITORY"
SHA8=$(echo "$GITHUB_SHA" | cut -c1-8)
BODY="hello wlh run=$GITHUB_RUN_ID sha=$SHA8 ts=$(date -u +%H:%M:%SZ)"
echo "$BODY"
python3 -c "
import json, os, subprocess
body = {'body': 'hello wlh run='+os.environ['GITHUB_RUN_ID']+' sha='+os.environ['GITHUB_SHA'][:8]+' ts='+subprocess.check_output(['date','-u','+%H:%M:%SZ']).decode().strip()}
open('wlh-body.json','w').write(json.dumps(body))
"
curl -sS -X POST \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" \
  -d @wlh-body.json \
  -w "\nHTTP=%{http_code}\n" \
  "https://api.github.com/repos/$GITHUB_REPOSITORY/issues/7/comments" -o wlh-resp.txt
cat wlh-resp.txt
echo
