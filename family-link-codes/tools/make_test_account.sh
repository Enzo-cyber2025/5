#!/usr/bin/env bash
# One command on YOUR machine: create the throwaway account, publish it, run the
# Play Store job. Everything after "here is a Google address" is automatic.
#
#   bash family-link-codes/tools/make_test_account.sh
#
# Why here and not in CI: the CI runner's IP is refused by Google's sign-up
# ("Sorry, we could not create your Google Account." — run 40936371939). From a
# normal connection the same wizard works; a person answering a phone prompt is
# also allowed, which a runner cannot do.
#
# What it does not do: solve a captcha, fabricate a phone number, or hide that a
# browser is driving. If Google asks for a phone, YOU type the code in the
# window that stays open — that is the legitimate path, and it is one field.
#
# Options: --no-publish (create only), --repo owner/name, --ref branch
set -uo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"
PUBLISH=1
REPO="${FLCODES_REPO:-}"
REF="${FLCODES_REF:-}"
PROFILE="${FLCODES_CHROME_PROFILE:-$HOME/.flcodes-chrome-profile}"
WORK="${FLCODES_SIGNUP_DIR:-$REPO_ROOT/out/signup}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-publish) PUBLISH=0; shift ;;
    --repo) REPO="${2:-}"; shift 2 ;;
    --ref) REF="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

say()  { printf '\n%s\n' "$*"; }
die()  { printf 'FAILED: %s\n' "$*" >&2; exit 1; }

BASE_PY="${PYTHON:-python3}"
command -v "$BASE_PY" >/dev/null 2>&1 || die "python3 is required"
VENV="${FLCODES_VENV:-$HOME/.flcodes-tools-venv}"

say "1/4  the tool's own virtualenv ($VENV)"
if [[ ! -x "$VENV/bin/python" ]]; then
  "$BASE_PY" -m venv "$VENV" || die "could not create a virtualenv (install python3-venv)"
fi
PY="$VENV/bin/python"
if ! "$PY" -c 'import playwright' >/dev/null 2>&1; then
  say "installing playwright into the venv (one time)…"
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet playwright \
    || die "pip install playwright failed (no network? see $VENV)"
fi

say "2/4  browser"
CHANNEL="chrome"
if ! "$PY" -m playwright install chrome >/dev/null 2>&1; then
  say "real Chrome unavailable; installing the bundled Chromium"
  "$PY" -m playwright install --with-deps chromium >/dev/null 2>&1 \
    || say "browser download failed — if you are behind a proxy, set HTTPS_PROXY"
  CHANNEL=""
fi

say "3/4  creating the account (a browser window opens — leave it in front)"
mkdir -p "$WORK"
set +e
"$PY" "$HERE/tools/google_signup_probe.py" \
  --headful ${CHANNEL:+--channel "$CHANNEL"} \
  --profile "$PROFILE" \
  --pause-on-wall \
  --out-dir "$WORK"
STATUS=$?
set -e

say "4/4  result"
if [[ ! -f "$WORK/credentials.json" ]]; then
  "$PY" - "$WORK/result.json" <<'EOF'
import json, sys, pathlib
path = pathlib.Path(sys.argv[1])
if not path.exists():
    print("no result file: the wizard never produced a verdict")
    raise SystemExit(0)
data = json.loads(path.read_text())
print(f"verdict: {data.get('verdict')}")
if data.get("error"):
    print(f"reason:  {data['error'][:300]}")
    if "Executable doesn't exist" in data["error"]:
        print("         the browser was never downloaded: run  python3 -m playwright install chrome")
for step in data.get("steps", []):
    print(f"  step {step['step']}: {step['verdict'] or 'form filled'}")
print()
print("screenshots:", path.parent)
EOF
  die "no account was created. If the verdict is 'phone', run it again and type the code in the window when it asks."
fi

EMAIL="$("$PY" -c "import json;print(json.load(open('$WORK/credentials.json'))['email'])")"
say "account: $EMAIL  (password in $WORK/credentials.json, 0600)"

if [[ "$PUBLISH" -eq 0 ]]; then
  say "--no-publish: nothing was sent to GitHub."
  exit 0
fi

export FLCODES_GPLAY_EMAIL="$EMAIL"
export FLCODES_GPLAY_PASSWORD="$("$PY" -c "import json;print(json.load(open('$WORK/credentials.json'))['password'])")"

say "publishing and triggering the Play Store job…"
ARGS=()
[[ -n "$REPO" ]] && ARGS+=(--repo "$REPO")
[[ -n "$REF" ]] && ARGS+=(--ref "$REF")
bash "$HERE/tools/play_run.sh" "${ARGS[@]}"
