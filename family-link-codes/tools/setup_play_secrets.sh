#!/usr/bin/env bash
# Put the throwaway Play Store identity into the repository secrets — from your
# own terminal, without the password ever touching a shell history, a log or a
# chat window.
#
#   read -rs FLCODES_GPLAY_EMAIL;    export FLCODES_GPLAY_EMAIL      # or
#   export FLCODES_GPLAY_EMAIL=you@example.com
#   read -rs FLCODES_GPLAY_PASSWORD; export FLCODES_GPLAY_PASSWORD
#   bash family-link-codes/tools/setup_play_secrets.sh --dry-run
#   bash family-link-codes/tools/setup_play_secrets.sh
#
# What it checks before writing anything:
#   * both variables are set and the email has the shape of an address;
#   * the password is not a placeholder and is long enough for Google;
#   * every shell metacharacter is quoted correctly (a `$` in a password is the
#     number one reason a working account fails to sign in from CI);
#   * `gh` is authenticated and points at a repo you can write to.
# Exit codes: 0 secrets written, 2 nothing to do (missing/!usable credentials),
#             1 gh failed.
set -uo pipefail

DRY_RUN=0
REPO="${FLCODES_REPO:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --repo) REPO="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

EMAIL="${FLCODES_GPLAY_EMAIL:-}"
PASSWORD="${FLCODES_GPLAY_PASSWORD:-}"

say() { printf '%s\n' "$*"; }
fail() { printf '[FAIL] %s\n' "$*" >&2; }

if [[ -z "$EMAIL" || -z "$PASSWORD" ]]; then
  fail "FLCODES_GPLAY_EMAIL and/or FLCODES_GPLAY_PASSWORD are empty."
  say ""
  say "export them first (read -rs keeps the password out of your shell history):"
  say "  read -r  FLCODES_GPLAY_EMAIL;  export FLCODES_GPLAY_EMAIL"
  say "  read -rs FLCODES_GPLAY_PASSWORD; export FLCODES_GPLAY_PASSWORD"
  exit 2
fi

case "$EMAIL" in
  *@*.*) ;;
  *) fail "the email does not look like an address: $EMAIL"; exit 2 ;;
esac

if [[ ${#PASSWORD} -lt 8 ]]; then
  fail "the password is shorter than 8 characters — no Google account accepts it."
  fail "if you copied it by hand, check for a truncated paste."
  exit 2
fi

if ! command -v gh >/dev/null 2>&1; then
  fail "gh is not installed; install it or set the secrets in the web UI."
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  fail "gh is not authenticated. Run: gh auth login"
  exit 1
fi

if [[ -z "$REPO" ]]; then
  REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)"
fi
if [[ -z "$REPO" ]]; then
  fail "cannot work out the repository; pass --repo owner/name"
  exit 1
fi

say "repository: $REPO"
say "email:      $EMAIL"
say "password:   ${#PASSWORD} characters (not printed)"
if printf '%s' "$PASSWORD" | grep -q '[$`\\]'; then
  say "[warn] the password contains \$ \` or \\ — make sure it is what you think it"
  say "       is: quote it with single quotes when exporting, e.g. 'pa\$s'."
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  say ""
  say "dry run: nothing was written. Drop --dry-run to publish the two secrets."
  exit 0
fi

say ""
say "writing secrets…"
if ! printf '%s' "$EMAIL" | gh secret set FLCODES_GPLAY_EMAIL --repo "$REPO"; then
  fail "gh secret set FLCODES_GPLAY_EMAIL failed"
  exit 1
fi
if ! printf '%s' "$PASSWORD" | gh secret set FLCODES_GPLAY_PASSWORD --repo "$REPO"; then
  fail "gh secret set FLCODES_GPLAY_PASSWORD failed"
  exit 1
fi

say ""
gh secret list --repo "$REPO" 2>/dev/null | grep -E 'FLCODES_GPLAY' || true
say ""
say "done. The next push (or: gh workflow run flcodes-emulator.yml) runs the"
say "play-store job with these credentials. Check it with: flcodes account check"
