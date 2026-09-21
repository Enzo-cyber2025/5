#!/usr/bin/env bash
# Bounded retry ONLY for concurrent fast-forward races. Never force a push,
# change branches, retry credentials failures, or resolve conflicts silently.
set -euo pipefail
BRANCH=arena/01a09b42-5
[[ "${GITHUB_REF:-}" == "refs/heads/$BRANCH" ]]
[[ "$(git branch --show-current)" == "$BRANCH" ]]
log=$(mktemp)
trap 'rm -f "$log"' EXIT
for attempt in 1 2 3 4; do
  git pull --rebase origin "$BRANCH"
  if git push origin "$BRANCH" >"$log" 2>&1; then
    cat "$log"
    exit 0
  fi
  cat "$log" >&2
  if ! grep -Eq '\[rejected\].*(fetch first|non-fast-forward)' "$log"; then
    exit 1
  fi
  if [[ "$attempt" == 4 ]]; then
    echo 'Concurrent evidence publication still racing after four attempts; refusing force push.' >&2
    exit 1
  fi
  sleep "$attempt"
done
