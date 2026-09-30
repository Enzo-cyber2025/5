#!/bin/bash
set -eux
LOG=wlh.log
: > $LOG
exec > >(tee -a $LOG) 2>&1
java -version
sudo apt-get update -q | tail -2
sudo apt-get install -y wget unzip xxd | tail -2
wget -q https://github.com/iBotPeaches/Apktool/releases/download/v2.9.3/apktool_2.9.3.jar -O /tmp/apktool.jar
wget -q https://github.com/nickola/uber-apk-signer/releases/download/v1.3.0/uber-apk-signer-1.3.0.jar -O /tmp/uber.jar
printf '#!/bin/sh\nexec java -jar /tmp/apktool.jar "$@"\n' > /usr/local/bin/apktool
chmod +x /usr/local/bin/apktool
apktool --version
echo "=== dl source APK (oficial brunodev85 v11.2) ==="
URL="https://github.com/brunodev85/winlator/releases/download/v11.2.0/Winlator_11.2.apk"
wget --tries=3 --timeout=180 "$URL" -O src.apk
M=$(xxd -l 4 -p src.apk | tr -d ' \n')
S=$(stat -c%s src.apk)
echo "M=$M S=$S"
if [ "$M" != "504b0304" ] || [ "$S" -lt 100000000 ]; then echo "APK_INVALID"; exit 10; fi
echo "APK_OK size=$S"
echo "=== unpack ==="
rm -rf out
apktool d src.apk -o out -f 2>&1 | tail -5
echo "=== inject ==="
bash wl/inj.sh out
echo "=== build ==="
apktool b out -o u.apk 2>&1 | tail -5
ls -la u.apk
echo "=== sign ==="
java -jar /tmp/uber.jar -a u.apk --out . --allowResign --zipalign 2>&1 | tail -10
for f in *-aligned-signed.apk; do [ -f "$f" ] && cp "$f" W.apk && break; done
ls -la W.apk
sha256sum W.apk | tee W.sha256
echo BUILD_OK
