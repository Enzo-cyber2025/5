#!/usr/bin/env bash
# One command from "I have a throwaway Google identity" to "the Play Store job
# is running with it".
#
#   read -r  FLCODES_GPLAY_EMAIL;    export FLCODES_GPLAY_EMAIL
#   read -rs FLCODES_GPLAY_PASSWORD; export FLCODES_GPLAY_PASSWORD
#   bash family-link-codes/tools/play_run.sh            # publish + trigger + wait
#   bash family-link-codes/tools/play_run.sh --check    # only validate
#
# Steps, each one printed and each one aborting the rest on failure:
#   1. validate the pair with `flcodes account check` (nothing is booted);
#   2. publish the two repository secrets with `gh secret set`;
#   3. trigger flcodes-emulator.yml — `gh workflow run` if the token may
#      dispatch, otherwise a one-line commit under family-link-codes/ that the
#      workflow's `push` path filter picks up;
#   4. watch the run and print the play-store job's verdict.
#
# It never echoes the password and never writes it to disk.
set -uo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
REPO="${FLCODES_REPO:-}"
REF="${FLCODES_REF:-}"
CHECK_ONLY=0
NO_WAIT=0
KEEP_TREE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) CHECK_ONLY=1; shift ;;
    --no-wait) NO_WAIT=1; shift ;;
    --repo) REPO="${2:-}"; shift 2 ;;
    --ref) REF="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

say()  { printf '%s\n' "$*"; }
step() { printf '\n===== %s =====\n' "$*"; }
die()  { printf 'FAILED: %s\n' "$*" >&2; exit 1; }

command -v gh >/dev/null 2>&1 || die "gh is not installed"
gh auth status >/dev/null 2>&1 || die "gh is not authenticated (run: gh auth login)"
[[ -n "$REPO" ]] || REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)"
[[ -n "$REPO" ]] || die "cannot work out the repository; pass --repo owner/name"
[[ -n "$REF" ]] || REF="$(cd "$HERE/.." && pwd | xargs -I{} git -C {} rev-parse --abbrev-ref HEAD 2>/dev/null)"
[[ -n "$REF" && "$REF" != "HEAD" ]] || die "cannot work out the branch; pass --ref"
say "repository: $REPO"
say "branch:     $REF"

# ---------------------------------------------------------------- 1. validate
step "1. is the identity usable?"
EMAIL_SRC=""
if [[ -z "${FLCODES_GPLAY_EMAIL:-}" || -z "${FLCODES_GPLAY_PASSWORD:-}" ]]; then
  if [[ -t 0 ]]; then
    [[ -n "${FLCODES_GPLAY_EMAIL:-}" ]] || { printf 'Google address (throwaway): '; read -r FLCODES_GPLAY_EMAIL; }
    [[ -n "${FLCODES_GPLAY_PASSWORD:-}" ]] || { printf 'password (not echoed): '; read -rs FLCODES_GPLAY_PASSWORD; echo; }
    EMAIL_SRC="prompt"
  fi
fi
[[ -n "${FLCODES_GPLAY_EMAIL:-}" && -n "${FLCODES_GPLAY_PASSWORD:-}" ]] \
  || die "no credentials. Set FLCODES_GPLAY_EMAIL and FLCODES_GPLAY_PASSWORD, or run in a terminal to be prompted"

PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}" python3 -m flcodes account check || {
  say ""
  die "the pair would not sign the Play Store in; nothing was published. See 'flcodes account howto'."
}
[[ "$CHECK_ONLY" -eq 1 ]] && { say ""; say "check only: nothing was published."; exit 0; }

# ----------------------------------------------------------------- 2. publish
step "2. publish the secrets"
if ! printf '%s' "$FLCODES_GPLAY_EMAIL" | gh secret set FLCODES_GPLAY_EMAIL --repo "$REPO" 2>/dev/null; then
  die "gh secret set FLCODES_GPLAY_EMAIL failed (the token needs secrets:write; the web UI always works: Settings -> Secrets -> Actions)"
fi
if ! printf '%s' "$FLCODES_GPLAY_PASSWORD" | gh secret set FLCODES_GPLAY_PASSWORD --repo "$REPO" 2>/dev/null; then
  die "gh secret set FLCODES_GPLAY_PASSWORD failed"
fi
say "published: FLCODES_GPLAY_EMAIL, FLCODES_GPLAY_PASSWORD (${#FLCODES_GPLAY_PASSWORD} chars, not printed)"

# ----------------------------------------------------------------- 3. trigger
step "3. trigger the workflow"
BEFORE="$(gh run list --repo "$REPO" --branch "$REF" --limit 1 --json databaseId -q '.[0].databaseId' 2>/dev/null || true)"
TRIGGERED=""
if gh workflow run flcodes-emulator.yml --repo "$REPO" --ref "$REF" >/dev/null 2>&1; then
  TRIGGERED="dispatch"
  say "triggered with workflow_dispatch"
else
  say "workflow_dispatch refused by this token; falling back to a filtered push"
  HERE_GIT="$(cd "$HERE/.." && pwd)"
  TOUCH="$HERE_GIT/family-link-codes/.play-run-trigger"
  printf 'play-store run requested %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$TOUCH"
  if ! git -C "$HERE_GIT" add "$TOUCH" || \
     ! git -C "$HERE_GIT" commit -q -m "ci: run the Play Store job with the new identity" || \
     ! git -C "$HERE_GIT" push -q origin "$REF"; then
    die "could not push the trigger commit; run the job from the Actions tab instead"
  fi
  TRIGGERED="push"
  say "triggered with a push to $REF"
fi

# -------------------------------------------------------------------- 4. wait
sleep 10
RUN=""
for _ in $(seq 1 12); do
  RUN="$(gh run list --repo "$REPO" --branch "$REF" --limit 1 --json databaseId -q '.[0].databaseId' 2>/dev/null || true)"
  [[ -n "$RUN" && "$RUN" != "$BEFORE" ]] && break
  sleep 5
done
[[ -n "$RUN" ]] || die "no new run appeared; open the Actions tab"
say "run: https://github.com/$REPO/actions/runs/$RUN"

if [[ "$NO_WAIT" -eq 1 ]]; then
  say ""
  say "not waiting (--no-wait). Watch it with: gh run watch $RUN --repo $REPO"
  exit 0
fi

gh run watch "$RUN" --repo "$REPO" --interval 30 --exit-status >/dev/null 2>&1
STATUS=$?

step "4. what the Play Store job did"
gh run view "$RUN" --repo "$REPO" 2>/dev/null | sed -n '/JOBS/,/ANNOTATIONS/p'
gh api "repos/$REPO/check-runs" -q '.check_runs[]?|select(.name|test("Play Store"))|.output.summary//empty' 2>/dev/null | head -20 || true

say ""
if [[ "$STATUS" -eq 0 ]]; then
  say "the run finished green."
else
  say "the run finished with a failure — read the play-store job's annotations;"
  say "'flcodes account howto' lists the reasons a valid account still fails."
fi
exit "$STATUS"
