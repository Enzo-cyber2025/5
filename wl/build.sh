#!/bin/bash
set -ex
LOG=wl/build.log
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

post() {
  # posta log como comentario na issue #7
  python3 - "$LOG" <<'PY'
import json, os, sys, urllib.request
log = open(sys.argv[1], 'rb').read().decode('utf-8', 'replace')[-55000:]
body = "### build log\n\n```\n" + log + "\n```\n"
repo = os.environ['GITHUB_REPOSITORY']
tok = os.environ.get('GITHUB_TOKEN','')
req = urllib.request.Request(
    f"https://api.github.com/repos/{repo}/issues/7/comments",
    data=json.dumps({'body': body}).encode(),
    headers={'Authorization': f'Bearer {tok}', 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'},
    method='POST')
try:
    r = urllib.request.urlopen(req, timeout=30)
    print("POSTED", r.status)
except Exception as e:
    print("POST ERR", e)
PY
}

on_err() {
  echo "=== ERR exit=$? ==="
  tail -80 "$LOG" || true
  post || true
}
trap on_err ERR

sudo apt-get update
sudo apt-get install -y wget unzip
wget -q https://github.com/iBotPeaches/Apktool/releases/download/v2.9.3/apktool_2.9.3.jar -O /tmp/apktool.jar
wget -q https://github.com/nickola/uber-apk-signer/releases/download/v1.3.0/uber-apk-signer-1.3.0.jar -O /tmp/uber.jar
printf '#!/bin/sh\nexec java -jar /tmp/apktool.jar "$@"\n' > /usr/local/bin/apktool
chmod +x /usr/local/bin/apktool
apktool --version
OK=0
for U in \
  https://github.com/brunovalads/Winlator/releases/download/8.0.1-mod/Winlator_8.0.1-mod.apk \
  https://github.com/brunovalads/Winlator/releases/download/8.0/Winlator_8.0.apk \
  https://github.com/Winlator/Winlator/releases/download/v8.0/Winlator_v8.0.apk; do
  rm -f src.apk
  wget --tries=2 --timeout=90 "$U" -O src.apk || continue
  if file src.apk | grep -q "Zip archive data"; then OK=1; echo "OK=$U"; ls -la src.apk; break; fi
done
[ "$OK" = "1" ]
apktool d src.apk -o out -f
bash wl/inj.sh out
apktool b out -o u.apk
ls -la u.apk
java -jar /tmp/uber.jar -a u.apk --out . --allowResign
for f in *-aligned-signed.apk; do [ -f "$f" ] && cp "$f" W.apk && break; done
ls -la W.apk
sha256sum W.apk | tee W.sha256
echo BUILD_OK
