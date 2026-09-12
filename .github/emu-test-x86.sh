#!/usr/bin/env bash
# =============================================================================
#  Emulador Android x86_64 (KVM) + testes do APK REAL GGUF-Chat-fixed.apk
# -----------------------------------------------------------------------------
#  Roda no runner ubuntu-latest (x86_64) do GitHub Actions, que TEM /dev/kvm
#  (virtualização aninhada habilitada). O emulador x86_64 boota em ~2-5 min.
#  O APK traz libs nativas x86_64 (além de arm64-v8a), então roda nativamente.
#  Chama .github/emu-test.sh (mesma suite: importa llava+mmproj pela UI,
#  verifica fusão+persistência, gera CPU/Vulkan, testa modelo inexistente).
# =============================================================================
set -u

API=30
IMG="system-images;android-${API};google_apis;x86_64"
AVD="x86avd"
SDK_ROOT="${ANDROID_HOME:-$HOME/android-sdk}"
export ANDROID_HOME="$SDK_ROOT"
export ANDROID_SDK_ROOT="$SDK_ROOT"
CT="$SDK_ROOT/cmdline-tools/latest/bin"
mkdir -p "$SDK_ROOT" evidence

log() { echo "[emu-x86 $(date -u +%H:%M:%S)] $*" | tee -a evidence/00_boot.log; }

# KVM é o ponto-chave: sem ele, o x86_64 também fica lento.
if [ -e /dev/kvm ] && [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
  log "/dev/kvm disponível (aceleração KVM ativa)"
else
  ls -l /dev/kvm 2>&1 | tee -a evidence/00_boot.log || true
  log "AVISO: /dev/kvm indisponível; boot será lento."
fi

# ---------- 1) SDK ----------
if [ ! -x "$SDK_ROOT/emulator/emulator" ] || [ ! -d "$SDK_ROOT/system-images/android-${API}/google_apis/x86_64" ]; then
  log "baixando cmdline-tools (linux)..."
  CTZIP="https://dl.google.com/android/repository/commandlinetools-linux-8512546_latest.zip"
  curl -sSLo /tmp/ct.zip "$CTZIP" || { log "falha ao baixar cmdline-tools"; exit 3; }
  unzip -qo /tmp/ct.zip -d /tmp/ct
  mkdir -p "$SDK_ROOT/cmdline-tools/latest"
  rm -rf "$SDK_ROOT/cmdline-tools/latest"/* 2>/dev/null || true
  mv /tmp/ct/cmdline-tools/* "$SDK_ROOT/cmdline-tools/latest/"
  log "aceitando licenças + instalando emulator / platform-tools / $IMG"
  yes | "$CT/sdkmanager" --licenses >/dev/null 2>&1 || true
  "$CT/sdkmanager" "platform-tools" "emulator" "$IMG" 2>&1 | tail -20 | tee -a evidence/00_boot.log || { log "sdkmanager falhou"; exit 4; }
fi
log "SDK pronto."
export PATH="$SDK_ROOT/emulator:$SDK_ROOT/platform-tools:$PATH"

# ---------- 2) AVD ----------
if ! "$CT/avdmanager" list avd 2>/dev/null | grep -q "$AVD"; then
  log "criando AVD $AVD ($IMG)"
  echo no | "$CT/avdmanager" create avd -n "$AVD" -k "$IMG" -d pixel_5 --force || true
fi

# ---------- 3) aceleração ----------
"$SDK_ROOT/emulator/emulator" -accel-check 2>&1 | tee -a evidence/00_boot.log || true
ACCEL=""
"$SDK_ROOT/emulator/emulator" -accel-check 2>&1 | grep -qi "usable" || ACCEL="-no-accel"
[ -n "$ACCEL" ] && log "SEM KVM -> software (lento)" || log "KVM ativo"

# ---------- 4) boot ----------
log "iniciando emulador x86_64 (RAM 3G, cores 2)..."
nohup "$SDK_ROOT/emulator/emulator" -avd "$AVD" -no-window -gpu swiftshader_indirect -no-snapshot \
  -noaudio -no-boot-anim -memory 3072 -cores 2 $ACCEL > /tmp/emu-x86.log 2>&1 &

adb wait-for-device 2>&1 | tee -a evidence/00_boot.log &
ADBW=$!
for i in $(seq 1 60); do
  if ! kill -0 $ADBW 2>/dev/null; then break; fi
  BOOT=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
  log "aguardando boot: boot_completed=${BOOT:-'?'} (iter $i/60)"
  [ "$BOOT" = "1" ] && break
  sleep 10
done
echo "boot_completed=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" | tee -a evidence/00_boot.log
echo "abi=$(adb shell getprop ro.product.cpu.abi 2>/dev/null | tr -d '\r')" | tee -a evidence/00_boot.log
echo "sdk=$(adb shell getprop ro.build.version.sdk 2>/dev/null | tr -d '\r')" | tee -a evidence/00_boot.log
tail -20 /tmp/emu-x86.log 2>/dev/null | tee -a evidence/00_boot.log

# ---------- 5) testes do APK real ----------
log "rodando suite de testes do APK real (.github/emu-test.sh)"
bash .github/emu-test.sh
echo "FIM X86" | tee -a evidence/00_boot.log
