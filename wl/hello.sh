#!/bin/bash
set -ux
LOG=wlh.log
: > $LOG
exec > >(tee -a $LOG) 2>&1
fail() { echo "FAIL $*"; exit 1; }
java -version || fail "java"
sudo apt-get update -q
sudo apt-get install -y wget unzip xxd aapt || fail "apt"
echo "=== dl tools ==="
wget -q --tries=3 --timeout=60 https://github.com/iBotPeaches/Apktool/releases/download/v2.9.3/apktool_2.9.3.jar -O /tmp/apktool.jar \
  && echo "apktool ok" || fail "apktool dl"
wget -q --tries=3 --timeout=60 https://github.com/patrickfav/uber-apk-signer/releases/download/v1.3.0/uber-apk-signer-1.3.0.jar -O /tmp/uber.jar \
  && echo "uber ok" || fail "uber dl"
printf '#!/bin/sh\nexec java -jar /tmp/apktool.jar "$@"\n' > /usr/local/bin/apktool
chmod +x /usr/local/bin/apktool
apktool --version || fail "apktool ver"
echo "=== dl source Winlator v11.2 (brunodev85) ==="
URL="https://github.com/brunodev85/winlator/releases/download/v11.2.0/Winlator_11.2.apk"
wget --tries=3 --timeout=180 "$URL" -O src.apk || fail "src dl"
M=$(xxd -l 4 -p src.apk | tr -d ' \n')
S=$(stat -c%s src.apk)
echo "magic=$M size=$S"
[ "$M" = "504b0304" ] && [ "$S" -gt 100000000 ] || fail "invalid apk"
echo "=== unpack ==="
rm -rf out
apktool d src.apk -o out -f || fail "unpack"
find out/res/raw -maxdepth 4 -type f -name "*.sh" 2>/dev/null | head -20
echo "=== inject pre-AOT ==="
bash wl/inj.sh out || fail "inject"
echo "=== scripts patcheados: ==="
grep -l "BOX64_DYNAREC_PERSISTENT=1" out/res/raw/*.sh 2>/dev/null
echo "=== repack ==="
rm -f u.apk W.apk
apktool b out -o u.apk || fail "build"
ls -la u.apk
echo "=== sign ==="
rm -rf signed && mkdir signed
java -jar /tmp/uber.jar -a u.apk --out signed --allowResign --zipalign --debug 2>&1 | tail -20 || fail "sign"
ls -la signed/
WAPK=$(ls signed/*.apk 2>/dev/null | head -1)
[ -n "$WAPK" ] && cp "$WAPK" W.apk && echo "signed=$WAPK"
[ -s W.apk ] || fail "no signed apk"
ls -la W.apk
sha256sum W.apk | tee W.sha256
echo BUILD_OK
