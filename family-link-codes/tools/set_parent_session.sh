#!/usr/bin/env bash
# Put a *parent session* into the repository secrets, from your terminal.
#
#   bash family-link-codes/tools/set_parent_session.sh
#
# What a parent session is: the SAPISID cookie of the Google account that is the
# parent in Family Link. It is not a password, it does not create any account,
# and it expires when you sign out — revoke it from
# https://myaccount.google.com/deviceactivity at any time.
#
# Where to get it, once:
#   Chrome -> familylink.google.com (signed in as the parent) -> DevTools (F12)
#   -> Application -> Cookies -> https://accounts.google.com -> copy SAPISID
#
# The value is read with `read -rs` (not echoed, not in your shell history),
# checked for shape, and piped straight into `gh secret set`. It never touches
# disk, a log, or a chat window.
#
# After that, the `parent-session` job in flcodes-emulator.yml harvests the
# config, extracts the shared secret and generates a code by itself.
set -uo pipefail

REPO="${FLCODES_REPO:-}"
TRIGGER=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="${2:-}"; shift 2 ;;
    --no-trigger) TRIGGER=0; shift ;;
    -h|--help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
die() { printf 'FAILED: %s\n' "$*" >&2; exit 1; }

command -v gh >/dev/null 2>&1 || die "gh is not installed"
gh auth status >/dev/null 2>&1 || die "gh is not authenticated (run: gh auth login)"
[[ -n "$REPO" ]] || REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)"
[[ -n "$REPO" ]] || die "cannot work out the repository; pass --repo owner/name"

say "repository: $REPO"
say ""
say "Paste the SAPISID cookie of the PARENT account (input hidden), then Enter:"
if [[ -n "${FLCODES_SAPISID:-}" ]]; then
  SESSION="$FLCODES_SAPISID"
  say "(using FLCODES_SAPISID from the environment)"
else
  read -rs SESSION
  echo
fi

SESSION="$(printf '%s' "$SESSION" | tr -d '[:space:]')"
[[ -n "$SESSION" ]] || die "nothing was pasted"

if [[ ${#SESSION} -lt 20 ]]; then
  die "that does not look like a SAPISID (${#SESSION} characters; usually ~40)"
fi
if [[ "$SESSION" == *"="* && "$SESSION" == SAPISID* ]]; then
  SESSION="${SESSION#SAPISID=}"
fi
say "session: ${#SESSION} characters (not printed)"

if ! printf '%s' "$SESSION" | gh secret set FLCODES_SAPISID --repo "$REPO"; then
  die "gh secret set failed (the token needs secrets:write; the web UI works too)"
fi
say "published: FLCODES_SAPISID"

[[ "$TRIGGER" -eq 1 ]] || { say "not triggering (--no-trigger)"; exit 0; }

say ""
say "triggering the parent-session job…"
if ! gh workflow run flcodes-emulator.yml --repo "$REPO" >/dev/null 2>&1; then
  say "this token cannot dispatch workflows; push any commit under family-link-codes/"
  say "or use the Actions tab -> flcodes emulator -> Run workflow."
  exit 0
fi
sleep 10
RUN="$(gh run list --repo "$REPO" --limit 1 --json databaseId -q '.[0].databaseId' 2>/dev/null || true)"
[[ -n "$RUN" ]] && say "run: https://github.com/$REPO/actions/runs/$RUN" \
  && say "watch: gh run watch $RUN --repo $REPO"
