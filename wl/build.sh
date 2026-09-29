#!/bin/bash
set -e
LOG=wl/build.log
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

post_log() {
python3 - "$LOG" <<'PY'
import json, os, sys, urllib.request
log_path = sys.argv[1]
try:
    log = open(log_path, 'rb').read().decode('utf-8', 'replace')
except FileNotFoundError:
    log = "(no log)"
log = log[-58000:]
body = "### build log (sha "+os.environ.get("GITHUB_SHA","?")[:8]+")\n\n```\n"+log+"\n```\n"
repo = os.environ['GITHUB_REPOSITORY']; tok = os.environ.get('GITHUB_TOKEN','')
req = urllib.request.Request(
    f"https://api.github.com/repos/{repo}/issues/7/comments",
    data=json.dumps({'body': body}).encode(),
    headers={'Authorization': f'Bearer {tok}', 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'},
    method='POST')
try:
    r = urllib.request.urlopen(req, timeout=30); print("LOG POSTED", r.status)
except Exception as e:
    print("LOG POST ERR", e)
PY
}
trap 'rc=$?; echo "=== ERR rc=$rc line=$LINENO ==="; tail -120 "$LOG" 2>/dev/null; post_log; exit $rc' ERR
trap 'echo "=== EXIT ==="; post_log' EXIT

echo "=== SO ==="; cat /etc/os-release | head -3; uname -a
echo "=== JAVA ==="; which java; java -version 2>&1 | head -3
echo "=== INSTALA DEPS ==="
sudo apt-get update
sudo apt-get install -y --no-install-recommends wget unzip aapt apksigner zipalign xxd
echo "=== BAIXA FERRAMENTAS ==="
wget -q --tries=3 --timeout=60 https://github.com/iBotPeaches/Apktool/releases/download/v2.9.3/apktool_2.9.3.jar -O /tmp/apktool.jar
wget -q --tries=3 --timeout=60 https://github.com/nickola/uber-apk-signer/releases/download/v1.3.0/uber-apk-signer-1.3.0.jar -O /tmp/uber.jar
ls -la /tmp/apktool.jar /tmp/uber.jar
printf '#!/bin/sh\nexec java -jar /tmp/apktool.jar "$@"\n' > /usr/local/bin/apktool
chmod +x /usr/local/bin/apktool
apktool --version 2>&1
echo "=== BAIXA WINLATOR ORIGINAL ==="
URLS=(
  "https://github.com/brunovalads/Winlator/releases/download/8.0.1-mod/Winlator_8.0.1-mod.apk"
  "https://github.com/brunovalads/Winlator/releases/download/8.0/Winlator_8.0.apk"
  "https://github.com/Winlator/Winlator/releases/download/v8.0/Winlator_v8.0.apk"
)
OK=0
for U in "${URLS[@]}"; do
  echo "-- $U"
  rm -f src.apk
  if wget --tries=2 --timeout=120 "$U" -O src.apk && [ -s src.apk ]; then
    MAGIC=$(xxd -l 4 -p src.apk 2>/dev/null)
    SIZE=$(stat -c%s src.apk)
    echo "magic=$MAGIC size=$SIZE"
    if [[ "$MAGIC" == 504b0304 ]] && [ "$SIZE" -gt 100000000 ]; then OK=1; echo "OK url=$U size=$SIZE"; break; fi
  fi
done
if [ "$OK" != "1" ]; then echo "TODOS DOWNLOADS FALHARAM"; ls -la; exit 10; fi
echo "=== DESCOMPACTA ==="
rm -rf out
apktool d src.apk -o out -f
find out/res/raw -maxdepth 3 -type f -name "*.sh" | head -20
echo "=== INJETA PRE-AOT ==="
bash wl/inj.sh out
grep -l "BOX64_DYNAREC_PERSISTENT=1" out/res/raw/*.sh 2>/dev/null | head
echo "=== COMPILA ==="
rm -f u.apk W.apk
apktool b out -o u.apk
ls -la u.apk
echo "=== ASSINA ==="
java -jar /tmp/uber.jar -a u.apk --out . --allowResign --zipalign 2>&1 | tail -20
for f in *-aligned-signed.apk; do [ -f "$f" ] && cp "$f" W.apk && break; done
if [ ! -s W.apk ]; then echo "assinatura falhou"; ls -la; exit 11; fi
ls -la W.apk
sha256sum W.apk | tee W.sha256
echo BUILD_OK
