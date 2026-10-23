#!/usr/bin/env bash
# Probe which public sources actually serve the Family Link APK to this runner.
# Prints one line per source: HTTP code, content type, size.
#
#   tools/probe_apk_sources.sh > table.txt
set -uo pipefail

PKG_PARENT="com.google.android.apps.kids.familylink"
PKG_OLD="com.google.android.apps.familylink"
UA_BROWSER="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

probe() {  # probe <label> <url> [extra curl args...]
  local label="$1" url="$2"; shift 2
  local out
  out="$(curl -sS -L --max-time 45 -A "$UA_BROWSER" \
        -o /tmp/probe.bin -w '%{http_code} %{content_type} %{size_download}' \
        "$@" "$url" 2>/tmp/probe.err)"
  local code ctype size err
  code="${out%% *}"; out="${out#* }"
  ctype="${out%% *}"; size="${out##* }"
  err="$(head -1 /tmp/probe.err | tr -d '\n')"
  printf '%-28s %-4s %-28.28s %10s  %s\n' "$label" "$code" "$ctype" "$size" "$err"
}

echo "source                       code content-type                 bytes  note"
echo "------------------------------------------------------------------------------"
probe "play-store-page"      "https://play.google.com/store/apps/details?id=$PKG_PARENT"
probe "apkmirror-index"      "https://www.apkmirror.com/apk/google-inc/google-family-link/"
probe "apkmirror-uploads"    "https://www.apkmirror.com/uploads/?appcategory=family-link"
probe "apkpure-page"         "https://apkpure.com/google-family-link/$PKG_PARENT"
probe "apkpure-net"          "https://apkpure.net/google-family-link/$PKG_PARENT/download"
probe "apkpure-direct-xapk"  "https://d.apkpure.com/b/XAPK/$PKG_PARENT?version=latest"
probe "apkpure-direct-apk"   "https://d.apkpure.com/b/APK/$PKG_PARENT?version=latest"
probe "pureapk-api"          "https://api.pureapk.com/m/v3/cms/app_version?hl=en&package_name=$PKG_PARENT"
probe "apkcombo"             "https://apkcombo.com/google-family-link/$PKG_PARENT/"
probe "apkcombo-app"         "https://apkcombo.app/google-family-link/$PKG_PARENT/"
probe "apk-support"          "https://apk.support/app/$PKG_PARENT"
probe "apkfab"               "https://apkfab.com/family-link/$PKG_PARENT"
probe "apkgk"                "https://apkgk.com/$PKG_PARENT"
probe "apkfollow"            "https://apkfollow.com/app/$PKG_PARENT/"
probe "aurora-auth"          "https://auroraoss.com/api/auth"
probe "aurora-api-v1"        "https://auroraoss.com/api/v1/apps"
probe "apkmirror-ajax"       "https://www.apkmirror.com/wp-admin/admin-ajax.php" -X POST -d "action=checkdownload"
probe "apkmirror-old-pkg"    "https://apkmirror.com/apk/google-inc/family-link/"
echo
echo "note: 403/503 usually means Cloudflare or a datacenter-IP block."
