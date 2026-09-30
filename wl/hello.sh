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
OK=0
for U in \
  https://github.com/brunovalads/Winlator/releases/download/8.0.1-mod/Winlator_8.0.1-mod.apk \
  https://github.com/brunovalads/Winlator/releases/download/8.0/Winlator_8.0.apk \
  https://github.com/Winlator/Winlator/releases/download/v8.0/Winlator_v8.0.apk; do
  echo "-- $U"
  rm -f src.apk
  if wget --tries=2 --timeout=120 "$U" -O src.apk; then
    M=$(xxd -l 4 -p src.apk 2>/dev/null | tr -d ' \n')
    S=$(stat -c%s src.apk)
    echo "M=$M S=$S"
    if [ "$M" = "504b0304" ] && [ "$S" -gt 100000000 ]; then OK=1; echo "OK url=$U size=$S"; break; fi
  fi
done
if [ "$OK" != "1" ]; then echo "DL_FAIL"; ls -la; exit 10; fi
echo "DL_OK size=$(stat -c%s src.apk)"
