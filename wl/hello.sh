#!/bin/bash
set -ux   # sem -e pra nao morrer no primeiro erro
LOG=wlh.log
: > $LOG
exec > >(tee -a $LOG) 2>&1
echo "=== java ==="; java -version
echo "=== apt ==="
sudo apt-get update -q 2>&1 | tail -3
sudo apt-get install -y wget unzip 2>&1 | tail -3
echo "=== dl apktool ==="
wget -v --tries=2 --timeout=60 https://github.com/iBotPeaches/Apktool/releases/download/v2.9.3/apktool_2.9.3.jar -O /tmp/apktool.jar 2>&1 | tail -10
echo "rc=$?"
echo "=== dl uber ==="
wget -v --tries=2 --timeout=60 https://github.com/nickola/uber-apk-signer/releases/download/v1.3.0/uber-apk-signer-1.3.0.jar -O /tmp/uber.jar 2>&1 | tail -10
echo "rc=$?"
ls -la /tmp/apktool.jar /tmp/uber.jar 2>&1 || true
echo FIM
