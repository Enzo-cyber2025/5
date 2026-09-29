#!/bin/bash
set -ex
LOG=wl/build.log
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

on_err() {
  echo "=== ERR (exit=$?) ==="
  tail -100 "$LOG" || true
  # Commita o log de volta em um branch de logs
  cd "$GITHUB_WORKSPACE"
  git config user.email "ci@local"
  git config user.name "ci"
  git checkout -B wl-logs origin/arena/01a0d024-5 || git checkout -B wl-logs
  git add -f wl/build.log
  git commit -m "wl log $(date -u +%H%M%S)" || true
  git push -f origin wl-logs 2>&1 | tail -5 || true
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
