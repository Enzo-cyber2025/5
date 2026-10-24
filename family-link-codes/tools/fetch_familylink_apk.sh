#!/usr/bin/env bash
# Fetch the newest REAL Family Link APK (no self-built copy) for analysis.
#
# Strategies, in order, each one validated before it is accepted:
#   1. apkeep against Google Play (official store, anonymous session)
#   2. apkeep against APKPure (third-party mirror, dangers acknowledged)
#   2. Aptoide public API (no account)              - JSON with a direct path
#   3. APKPure JSON API (pureapk.com)               - direct download_url
#   4. APKPure download endpoint, Aptoide API       - plain HTTP
#   5. APKMirror uploads page                       - gated, last resort
#
# Set FLCODES_APK_URL to your own copy of the real APK to skip all of this.
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
# The app is published under two ids: the current one (kids.familylink, the app
# that ships the parent-access-code feature) and the old one. Both are accepted
# so a copy the user already has is never thrown away.
PACKAGE="com.google.android.apps.kids.familylink"
PACKAGE_OLD="com.google.android.apps.familylink"
PACKAGE_HELPER="com.google.android.apps.kids.familylinkhelper"
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
  local apk="$1"
  local aapt
  aapt="$(find "${ANDROID_SDK_ROOT:-/usr/local/lib/android/sdk}/build-tools" \
            -name aapt2 2>/dev/null | sort -V | tail -1)"
  if [[ -n "$aapt" ]]; then
    local name
    name="$("$aapt" dump packagename "$apk" 2>/dev/null | tr -d '\r' | head -1)"
    [[ -n "$name" ]] && { printf '%s\n' "$name"; return 0; }
  fi
  python3 - "$apk" <<'PY'
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
  case "$name" in
    "$PACKAGE"|"$PACKAGE_OLD"|"$PACKAGE_HELPER") ;;
    *) log "$(basename "$file"): package is $name, not a Family Link package"
       return 1 ;;
  esac
  log "accepted $(basename "$file") ($(du -h "$file" | cut -f1), package $name)"
  return 0
}

unpack_if_bundle() {  # XAPK/APKS -> base.apk + splits, listed in splits.txt
  local file="$1"
  case "$file" in
    *.xapk|*.apks|*.apkm)
      log "unpacking bundle $(basename "$file")"
      local dir="${file%.*}-unpacked"
      rm -rf "$dir"; mkdir -p "$dir"
      unzip -q -o "$file" -d "$dir" || return 1
      local base
      # the base is literally base.apk; a bare *.apk fallback would pick a
      # config.<lang> split, which cannot be installed on its own
      base="$(find "$dir" -name 'base.apk' | head -1)"
      if [[ -z "$base" ]]; then
        log "bundle has no base.apk; refusing (splits alone cannot install)"
        return 1
      fi
      # everything the installer needs: base first, then the splits
      {
        printf '%s\n' "$(realpath "$base")"
        find "$dir" -name '*.apk' ! -name 'base.apk' | sort | while read -r apk; do
          realpath "$apk"
        done
      } > splits.txt
      while read -r apk; do log "  piece: $(basename "$apk")"; done < splits.txt
      log "bundle pieces: $(wc -l < splits.txt)"
      printf '%s\n' "$base"
      return 0 ;;
    *) : > splits.txt; echo "$file"; return 0 ;;
  esac
}

try_apkeep() {
  local bin="$OUT/apkeep"
  if [[ ! -x "$bin" ]]; then
    local url
    url="$(gh api repos/EFForg/apkeep/releases/latest \
            --jq '[.assets[] | select(.name == "apkeep-x86_64-unknown-linux-gnu") | .browser_download_url] | .[0]' \
            2>/dev/null || true)"
    url="$(printf '%s' "$url" | head -1 | tr -d '[:space:]')"
    if [[ ! "$url" =~ ^https:// ]]; then
      log "apkeep: could not resolve the release asset (got '$url')"
      return 1
    fi
    log "apkeep: downloading $url"
    curl -fsSL --retry 2 -o "$bin" "$url" || return 1
    chmod +x "$bin" || return 1
    "$bin" --version >> "$OUT/apkeep-version.txt" 2>&1 || true
  fi
  log "apkeep: $($bin --version 2>&1 | head -1)"
  rm -f ./*.apk ./*.xapk ./*.apks
  # APKPure is a mirror: apkeep requires the risk to be acknowledged explicitly
  "$bin" -a "$PACKAGE" -d apk-pure -o 'acknowledge_dangers=true' . >&2 || return 1
  local produced
  produced="$(ls -t *.apk *.xapk *.apks 2>/dev/null | head -1)"
  [[ -n "$produced" ]] || return 1
  unpack_if_bundle "$produced"
}

ensure_apkeep() {
  local bin="$OUT/apkeep"
  [[ -x "$bin" ]] && return 0
  local url
  url="$(gh api repos/EFForg/apkeep/releases/latest \
          --jq '[.assets[] | select(.name == "apkeep-x86_64-unknown-linux-gnu") | .browser_download_url] | .[0]' \
          2>/dev/null || true)"
  url="$(printf '%s' "$url" | head -1 | tr -d '[:space:]')"
  [[ "$url" =~ ^https:// ]] || { log "apkeep: asset not found"; return 1; }
  curl -fsSL --retry 2 -o "$bin" "$url" || return 1
  chmod +x "$bin" || return 1
}

try_gplay() {
  ensure_apkeep || return 1
  log "apkeep: official store, anonymous session"
  rm -f ./*.apk ./*.xapk ./*.apks
  "$OUT/apkeep" -a "$PACKAGE" -d google-play . >&2 || return 1
  local produced
  produced="$(ls -t *.apk *.xapk *.apks 2>/dev/null | head -1)"
  if [[ -z "$produced" ]]; then
    log "apkeep: nothing downloaded; available versions follow"
    "$OUT/apkeep" -l -a "$PACKAGE" -o 'arch=x86_64' 2>&1 | head -8 | sed 's/^/  /' >&2 || true
    return 1
  fi
  unpack_if_bundle "$produced"
}

try_aptoide() {
  local meta
  meta="$(curl -fsSL --retry 2 -A "Mozilla/5.0" \
      "https://ws75.aptoide.com/api/7/app/get/package_name=$PACKAGE" 2>"$OUT/aptoide.err")" \
      || { log "aptoide: request failed: $(tail -2 "$OUT/aptoide.err" | tr '\n' ' ')"; return 1; }
  local path version
  path="$(printf '%s' "$meta" | python3 -c '
import json, sys
data = json.load(sys.stdin)
node = (data.get("nodes") or {}).get("meta") or {}
file_info = node.get("file") or {}
print(file_info.get("path") or "")
' 2>/dev/null)" || return 1
  version="$(printf '%s' "$meta" | python3 -c '
import json, sys
data = json.load(sys.stdin)
node = (data.get("nodes") or {}).get("meta") or {}
print(node.get("vername") or "")
' 2>/dev/null || true)"
  [[ -n "$path" ]] || { log "aptoide: no file path in the response"; return 1; }
  log "aptoide: version $version -> $path"
  curl -fsSL --retry 2 -A "Mozilla/5.0" -o "familylink-aptoide.apk" "$path" || return 1
  unpack_if_bundle familylink-aptoide.apk
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

try_apkpure_api() {
  local json
  json="$(curl -fsSL --retry 2 \
      -H "x-cv: 3171503" -H "x-sv: 29" -H "x-abis: arm64-v8a,armeabi-v7a,armeabi" \
      -H "x-g: 1" -H "x-l: en" -A "Dalvik/2.1.0 (Linux; U; Android 10)" \
      "https://api.pureapk.com/m/v3/cms/app_version?hl=en&package_name=$PACKAGE" 2>"$OUT/api.err")" \
      || { log "apkpure api: $(tail -1 "$OUT/api.err" | tr -d '\r')"; return 1; }
  local url
  url="$(printf '%s' "$json" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)
def find(node):
    if isinstance(node, dict):
        for key in ("download_url", "downloadUrl"):
            value = node.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
        for value in node.values():
            found = find(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = find(value)
            if found:
                return found
    return None
print(find(data) or "")
' 2>/dev/null)" || return 1
  [[ "$url" =~ ^https?:// ]] || { log "apkpure api: no download_url"; return 1; }
  log "apkpure api: $url"
  curl -fsSL --retry 2 -A "Mozilla/5.0" -o "familylink-api.pkg" "$url" || return 1
  if unzip -l familylink-api.pkg >/dev/null 2>&1; then
    mv familylink-api.pkg familylink-api.xapk
    unpack_if_bundle familylink-api.xapk
  else
    mv familylink-api.pkg familylink-api.apk
    echo familylink-api.apk
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

try_user_url() {
  local url="${FLCODES_APK_URL:-}"
  [[ -n "$url" ]] || return 1
  log "using FLCODES_APK_URL"
  curl -fsSL --retry 2 -A "Mozilla/5.0" -o "user.apk" "$url" || return 1
  unpack_if_bundle user.apk
}

FOUND=""
for strategy in try_user_url try_gplay try_apkeep try_apkpure_api try_aptoide try_apkpure try_apkmirror; do
  log "strategy: $strategy"
  set +e
  candidate="$($strategy)"
  status=$?
  set -e
  log "files now: $(ls -1 2>/dev/null | tr '\n' ' ')"
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
