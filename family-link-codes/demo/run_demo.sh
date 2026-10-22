#!/usr/bin/env bash
# Full REA rehearsal on synthetic dumps: find the key, store it, generate codes
# and verify them against an independent implementation.
#
#   bash demo/run_demo.sh
#
# Everything runs offline and writes only inside a temporary directory. The keys
# are fake ("AItest-only-..."): this proves the pipeline, not anyone's account.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
work="${TMPDIR:-/tmp}/flcodes-demo"
python="${PYTHON:-python3}"

rm -rf "$work"
mkdir -p "$work"

export FLCODES_HOME="$work/home"
export FLCODES_PASSPHRASE="demo-passphrase"
export PYTHONPATH="$here/.."

echo "== 1. fixtures (HAR, UTF-16 prefs, APK, LevelDB, gzip, post-patch) =="
"$python" "$here/make_fixtures.py" "$work/dumps"

echo
echo "== 2. REA: find the shared secret =="
"$python" -m flcodes rea scan "$work/dumps" --save --save-all --label demo | cat -v

echo
echo "== 3. stored keys (masked) =="
"$python" -m flcodes keys list

echo
echo "== 4. generate three codes (TTL comes from the captured config) =="
"$python" -m flcodes gen --label demo-1 --time 1792684800 --count 3 --json 2>/dev/null \
  | "$python" -c 'import json,sys; [print(r["code"], "|", r["valid_from_utc"], "->", r["valid_to_utc"]) for r in json.load(sys.stdin)]'

echo
echo "== 5. observations from an independent implementation =="
"$python" "$here/make_observations.py" "$work/observations.csv"

echo
echo "== 6. verify: only the right key confirms =="
"$python" -m flcodes verify --file "$work/observations.csv"

echo
echo "== 7. negative control: a code nobody produced =="
set +e
"$python" -m flcodes verify --code 000000 --at 1792685100 >/dev/null 2>&1
status=$?
set -e
if [ "$status" -eq 1 ]; then
  echo "correctly rejected (exit 1)"
else
  echo "UNEXPECTED: exit $status (a random code must not confirm)"
  exit 1
fi

echo
echo "== 8. no-root path: adb backup container -> extract -> key =="
"$python" demo/make_device_fixture.py --out "$work/device" >/dev/null
"$python" -m flcodes abe scan "$work/device/familylink.ab" --label device-fixture

echo
echo "artifacts under: $work"
