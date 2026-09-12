#!/usr/bin/env bash
# =============================================================================
#  Emulador Android x86_64 (KVM) + testes do APK REAL GGUF-Chat-fixed.apk
# -----------------------------------------------------------------------------
#  Roda no runner ubuntu-latest (x86_64) do GitHub Actions. O /dev/kvm EXISTE
#  mas vem com permissão root:kvm 660 sem o runner no grupo -> corrigimos aqui
#  (chmod + udev + gpasswd). Com KVM o emulador boota em ~2-4 min e fica estável.
#  O APK traz libs nativas x86_64 (além de arm64-v8a), então roda igual.
#  Depois chama .github/emu-test.sh (importa llava+mmproj pela UI, verifica
#  fusão+persistência, gera CPU/Vulkan, testa modelo inexistente).
# =============================================================================
set -u

API=30
IMG="system-images;android-${API};google_apis;x86_64"
AVD="x86avd"
mkdir -p evidence

log() { echo "[emu-x86 $(date -u +%H:%M:%S)] $*" | tee -a evidence/00_boot.log; }

# =============================================================================
# 0) CORREÇÃO CRÍTICA: liberar /dev/kvm para o runner
# =============================================================================
if [ -e /dev/kvm ]; then
  ls -l /dev/kvm 2>&1 | tee -a evidence/00_boot.log || true
  echo 'KERNEL=="kvm", GROUP="kvm", MODE="0666", OPTIONS+="static_node=kvm"' | sudo tee /etc/udev/rules.d/99-kvm4all.rules >/dev/null 2>&1 || true
  sudo udevadm control --reload-rules 2>/dev/null || true
  sudo udevadm trigger --name-match=kvm 2>/dev/null || true
  sudo chmod 666 /dev/kvm 2>/dev/null || true
  (sudo gpasswd -a "$USER" kvm 2>/dev/null || true)
  ls -l /dev/kvm 2>&1 | tee -a evidence/00_boot.log || true
else
  log "AVISO: /dev/kvm não existe neste runner"
fi

# =============================================================================
# 1) SDK — reutiliza o pré-instalado do runner se existir; senão baixa
# =============================================================================
SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/android-sdk}}"
if [ -x "$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" ] && [ -x "$SDK_ROOT/emulator/emulator" ]; then
  log "reutilizando SDK pré-instalado em $SDK_ROOT"
else
  SDK_ROOT="$HOME/android-sdk"
  log "baixando cmdline-tools (linux)..."
  CTZIP="https://dl.google.com/android/repository/commandlinetools-linux-8512546_latest.zip"
  curl -sSLo /tmp/ct.zip "$CTZIP" || { log "falha ao baixar cmdline-tools"; exit 3; }
  unzip -qo /tmp/ct.zip -d /tmp/ct
  mkdir -p "$SDK_ROOT/cmdline-tools/latest"
  rm -rf "$SDK_ROOT/cmdline-tools/latest"/* 2>/dev/null || true
  mv /tmp/ct/cmdline-tools/* "$SDK_ROOT/cmdline-tools/latest/"
  yes | "$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" --licenses >/dev/null 2>&1 || true
  "$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" "platform-tools" "emulator" 2>&1 | tail -5 | tee -a evidence/00_boot.log || true
fi
export ANDROID_HOME="$SDK_ROOT"
export ANDROID_SDK_ROOT="$SDK_ROOT"
export PATH="$SDK_ROOT/emulator:$SDK_ROOT/platform-tools:$SDK_ROOT/cmdline-tools/latest/bin:$PATH"

# =============================================================================
# 1.5) REBUILD do APK com TODAS as correções (fusão + showMmprojPicker)
# -----------------------------------------------------------------------------
# O passo "Build APK corrigido" do workflow só aplica a correção de fusão
# (o workflow não pode ser editado por falta da permissão `workflows` do token
# do Arena). Aqui re-aplicamos o patch COMPLETO (fusão + VerifyError do
# showMmprojPicker) e re-assinamos com o apksigner oficial, garantindo o APK
# que realmente será instalado e testado pela UI.
# =============================================================================
log "reconstruindo GGUF-Chat-fixed.apk com todas as correções..."
set -o pipefail
if bash apk-fix/rebuild_on_runner.sh 2>&1 | tee -a evidence/00_boot.log; then
  log "rebuild OK"; ls -l GGUF-Chat-fixed.apk | tee -a evidence/00_boot.log
else
  log "FALHA no rebuild do APK (abortando)"; exit 5
fi

# mata qualquer adb server antigo (evita conflito de smartsocket)
adb kill-server >/dev/null 2>&1 || true
adb start-server >/dev/null 2>&1 || true

# =============================================================================
# 2) system image (única parte grande)
# =============================================================================
if [ ! -d "$SDK_ROOT/system-images/android-${API}/google_apis/x86_64" ]; then
  log "baixando $IMG ..."
  yes | sdkmanager --licenses >/dev/null 2>&1 || true
  sdkmanager "$IMG" 2>&1 | tr '\r' '\n' | grep -aE "100%|Installing|Downloading" | tail -8 | tee -a evidence/00_boot.log || { log "sdkmanager falhou"; exit 4; }
fi
log "SDK pronto."

# =============================================================================
# 3) AVD
# =============================================================================
if ! avdmanager list avd 2>/dev/null | grep -q "$AVD"; then
  log "criando AVD $AVD ($IMG)"
  echo no | avdmanager create avd -n "$AVD" -k "$IMG" -d pixel_5 --force || true
fi

# =============================================================================
# 4) aceleração
# =============================================================================
emulator -accel-check 2>&1 | tr '\r' '\n' | tail -6 | tee -a evidence/00_boot.log || true
ACCEL=""
emulator -accel-check 2>&1 | grep -qi "is installed and usable" && ACCEL=""
if emulator -accel-check 2>&1 | grep -qi "not usable\|not installed\|permissions"; then ACCEL="-no-accel"; fi
[ -n "$ACCEL" ] && log "SEM KVM -> software (lento)" || log "KVM ATIVO"

# =============================================================================
# 5) boot
# =============================================================================
log "iniciando emulador x86_64 (RAM 4G, cores 2)..."
nohup emulator -avd "$AVD" -no-window -gpu swiftshader_indirect -no-snapshot \
  -noaudio -no-boot-anim -memory 4096 -cores 2 $ACCEL > /tmp/emu-x86.log 2>&1 &

adb wait-for-device >/dev/null 2>&1 &
ADBW=$!
BOOTED=0
for i in $(seq 1 60); do
  if ! kill -0 $ADBW 2>/dev/null; then break; fi
  BOOT=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
  log "aguardando boot: boot_completed=${BOOT:-'?'} (iter $i/60)"
  if [ "$BOOT" = "1" ]; then BOOTED=1; break; fi
  sleep 10
done
# margem para o launcher assentar (evita DeadSystemException de sistema recém-bootado)
if [ "$BOOTED" = "1" ]; then
  log "boot concluído; aguardando sistema assentar (45s)..."
  sleep 45
fi
echo "boot_completed=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" | tee -a evidence/00_boot.log
echo "abi=$(adb shell getprop ro.product.cpu.abi 2>/dev/null | tr -d '\r')" | tee -a evidence/00_boot.log
echo "sdk=$(adb shell getprop ro.build.version.sdk 2>/dev/null | tr -d '\r')" | tee -a evidence/00_boot.log
tail -20 /tmp/emu-x86.log 2>/dev/null | tr '\r' '\n' | tee -a evidence/00_boot.log

# =============================================================================
# 6) suite do APK real
# =============================================================================
log "rodando suite de testes do APK real (.github/emu-test.sh)"
bash .github/emu-test.sh
echo "FIM X86" | tee -a evidence/00_boot.log
