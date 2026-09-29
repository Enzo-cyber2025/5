#!/bin/bash
set -e -x
LOG=wl/build.log
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1
echo "=== ENV ==="
whoami; pwd; ls -la
echo "=== APT UPDATE ==="
sudo apt-get update || true
echo "=== APT INSTALL ==="
sudo apt-get install -y wget unzip aapt apksigner zipalign xxd || { echo "APT_FAIL"; sudo apt-get install -y wget unzip; }
echo "=== WGET APKTOOL/UBER ==="
cd "$GITHUB_WORKSPACE"
wget -q https://github.com/iBotPeaches/Apktool/releases/download/v2.9.3/apktool_2.9.3.jar -O /tmp/apktool.jar || echo "apktool_dl_fail"
wget -q https://github.com/nickola/uber-apk-signer/releases/download/v1.3.0/uber-apk-signer-1.3.0.jar -O /tmp/uber.jar || echo "uber_dl_fail"
ls -la /tmp/apktool.jar /tmp/uber.jar || true
echo '#!/bin/sh
exec java -jar /tmp/apktool.jar "$@"' > /usr/local/bin/apktool
chmod +x /usr/local/bin/apktool
apktool --version 2>&1 || true
echo "=== DL SRC ==="
OK=0
for U in \
  https://github.com/brunovalads/Winlator/releases/download/8.0.1-mod/Winlator_8.0.1-mod.apk \
  https://github.com/brunovalads/Winlator/releases/download/8.0/Winlator_8.0.apk \
  https://github.com/Winlator/Winlator/releases/download/v8.0/Winlator_v8.0.apk; do
  echo "-- $U"
  rm -f src.apk
  if wget --tries=2 --timeout=120 "$U" -O src.apk 2>&1 && [ -s src.apk ]; then
    M=$(xxd -l 4 -p src.apk 2>/dev/null | tr -d ' \n')
    S=$(stat -c%s src.apk 2>/dev/null || echo 0)
    echo "M=$M S=$S"
    if [ "$M" = "504b0304" ] && [ "$S" -gt 100000000 ]; then OK=1; echo "OK $U"; break; fi
  fi
done
if [ $OK != 1 ]; then echo "DL_FAIL"; ls -la; exit 10; fi
echo "=== UNPACK ==="
rm -rf out
apktool d src.apk -o out -f 2>&1 | tail -10
find out/res/raw -maxdepth 4 -type f -name "start_*.sh" 2>/dev/null | head
echo "=== INJECT ==="
bash wl/inj.sh out
grep -l BOX64_DYNAREC_PERSISTENT out/res/raw/start_box64.sh out/res/raw/start_wow64.sh 2>/dev/null || echo "inject_grep_miss"
echo "=== BUILD ==="
rm -f u.apk W.apk
apktool b out -o u.apk 2>&1 | tail -10
ls -la u.apk
echo "=== SIGN ==="
java -jar /tmp/uber.jar -a u.apk --out . --allowResign --zipalign 2>&1 | tail -10
ls -la
for f in *-aligned-signed.apk; do [ -f "$f" ] && { cp "$f" W.apk; echo "signed=$f"; break; }; done
[ -s W.apk ] || { echo "SIGN_FAIL"; exit 11; }
ls -la W.apk
sha256sum W.apk | tee W.sha256
echo BUILD_OK
