#!/bin/bash
set -eux
echo "Token prefix: ${GITHUB_TOKEN:0:8}..."
echo "Token length: ${#GITHUB_TOKEN}"
# Usa o GITHUB_TOKEN do runner para comentar. O gh já autentica com ele por padrão.
# Teste 1: curl com GITHUB_TOKEN
BODY="hello from wlh (curl+GITHUB_TOKEN) run=$GITHUB_RUN_ID"
curl -sS -X POST \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" \
  -d "{\"body\":\"$BODY\"}" \
  -w "\nHTTP=%{http_code}\n" \
  "https://api.github.com/repos/$GITHUB_REPOSITORY/issues/8/comments"
