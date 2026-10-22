#!/usr/bin/env bash
# Fetch the newest REAL Family Link APK (no self-built copy) for analysis.
#
# Strategies, in order, each one validated before it is accepted:
#   1. apkeep (APKPure backend, anonymous)          - release binary from GitHub
#   2. APKPure direct download endpoint             - plain HTTP
#   3. APKMirror uploads page                       - scraped, last resort
#
# Every candidate is unzipped and the package name is read from the binary
# manifest; anything that is not com.google.android.apps.familylink is thrown
# away. Split bundles (XAPK/APKS) are supported: the base APK is returned and
# the splits are listed next to it.
#
#   tools/fetch_familylink_apk.sh --out /tmp/familylink
#
# Prints the chosen APK path on the last line (and writes apk-path.txt).
set -euo pipefail

OUT="${TMPDIR:-/tmp}/familylink"
PACKAGE="com.google.android.apps.familylink"
VERSION="latest"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --package) PACKAGE="$2"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$OUT"
cd "$OUT"

log() { echo "[fetch] $*" >&2; }

package_of() {  # read the package name out of the binary manifest
  python3 - "$1" <<'PY'
import sys, zipfile, re
path = sys.argv[1]
try:
    with zipfile.ZipFile(path) as archive:
        blob = archive.read("AndroidManifest.xml")
except Exception:
    sys.exit(1)
# the manifest string pool stores the package as UTF-16
text = blob.decode("utf-16-le", errors="ignore") + blob.decode("latin-1", errors="ignore")
match = re.search(r"((?:[a-z][a-z0-9_]*\.){2,}[a-z][a-z0-9_]*)", text)
print(match.group(1) if match else "")
PY
}

accept() {  # accept <file>: true when it is the right package
  local file="$1"
  [[ -s "$file" ]] || return 1
  local name
  name="$(package_of "$file" || true)"
  if [[ -z "$name" ]]; then
    log "$(basename "$file"): no package name (not an APK?)"
    return 1
  fi
  if [[ "$name" != "$PACKAGE" ]]; then
    log "$(basename "$file"): package is $name, wanted $PACKAGE"
    return 1
  fi
  log "accepted $(basename "$file") ($(du -h "$file" | cut -f1), package $name)"
  return 0
}

unpack_if_bundle() {  # XAPK/APKS -> base.apk + splits
  local file="$1"
  case "$file" in
    *.xapk|*.apks|*.apkm)
      log "unpacking bundle $(basename "$file")"
      local dir="${file%.*}-unpacked"
      rm -rf "$dir"; mkdir -p "$dir"
      unzip -q -o "$file" -d "$dir" || return 1
      local base
      base="$(find "$dir" -maxdepth 2 -name 'base.apk' -o -maxdepth 2 -name '*.apk' | head -1)"
      [[ -n "$base" ]] || return 1
      find "$dir" -name '*.apk' | sed 's/^/  split: /' >&2
      echo "$base"
      return 0 ;;
    *) echo "$file"; return 0 ;;
  esac
}

try_apkeep() {
  local bin="$OUT/apkeep"
  if [[ ! -x "$bin" ]]; then
    local url
    url="$(gh api repos/efyang/apkeep/releases/latest --jq '.assets[] | select(.name | test("x86_64-unknown-linux-musl.tar.gz$")) | .browser_download_url' 2>/dev/null | head -1)"
    [[ -n "$url" ]] || return 1
    curl -fsSL --retry 3 -o "$OUT/apkeep.tgz" "$url" || return 1
    tar -xzf "$OUT/apkeep.tgz" -C "$OUT" || return 1
    mv "$OUT"/apkeep* "$bin" 2>/dev/null || true
    chmod +x "$bin" || return 1
  fi
  rm -f "familylink.apk"
  "$bin" -a "$PACKAGE" -d apk-pure . >&2 || return 1
  local produced
  produced="$(ls -t *.apk 2>/dev/null | head -1)"
  [[ -n "$produced" ]] || return 1
  unpack_if_bundle "$produced"
}

try_apkpure() {
  local url="https://d.apkpure.com/b/APK/$PACKAGE?version=$VERSION"
  curl -fsSL --retry 2 -A "Mozilla/5.0 (X11; Linux x86_64)" -o apkpure.bin "$url" || return 1
  # the endpoint can answer with an XAPK zip or with an APK
  mv apkpure.bin apkpure.pkg
  if unzip -l apkpure.pkg >/dev/null 2>&1; then
    mv apkpure.pkg "familylink-pure.xapk"
    unpack_if_bundle "familylink-pure.xapk"
  else
    mv apkpure.pkg familylink-pure.apk
    echo familylink-pure.apk
  fi
}

try_apkmirror() {
  local page="https://www.apkmirror.com/uploads/?appcategory=family-link"
  local html
  html="$(curl -fsSL --retry 2 -A "Mozilla/5.0 (X11; Linux x86_64)" "$page" 2>/dev/null)" || return 1
  local href
  href="$(printf '%s' "$html" | grep -oE 'href="/apk/google-inc/family-link/[^"]+"' \
          | sed 's/href="//; s/"$//' | head -1)"
  [[ -n "$href" ]] || return 1
  log "apkmirror entry: $href (manual download is gated; skipping)"
  return 1
}

FOUND=""
for strategy in try_apkeep try_apkpure try_apkmirror; do
  log "strategy: $strategy"
  set +e
  candidate="$($strategy)"
  status=$?
  set -e
  if [[ $status -ne 0 || -z "$candidate" ]]; then
    log "$strategy: no download"
    continue
  fi
  candidate="$(echo "$candidate" | tail -1)"
  if accept "$candidate"; then FOUND="$candidate"; break; fi
done

if [[ -z "$FOUND" ]]; then
  log "could not download $PACKAGE (all providers failed)"
  exit 1
fi

cp -f "$FOUND" "base.apk"
sha256sum base.apk > SHA256SUMS
stat -c '%n %s bytes' base.apk
echo "$OUT/base.apk" > apk-path.txt
printf '%s\n' "$OUT/base.apk"
