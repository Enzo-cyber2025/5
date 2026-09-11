#!/usr/bin/env bash
# =============================================================================
#  Emulador Android ARM64 (arm64-v8a) + testes do APK REAL GGUF-Chat.apk
# -----------------------------------------------------------------------------
#  Roda EM DOIS LUGARES:
#   1) Local, num Mac Apple Silicon (M1/M2/M3):  bash .github/emu-test-arm64.sh
#      -> usa aceleração HVF (rápido). É o jeito MAIS fiel de reproduzir o crash
#         (o celular do usuário é arm64).
#   2) No runner macos-14 do GitHub Actions (Apple Silicon arm64).
#      -> se HVF não estiver disponível, cai automaticamente para emulação por
#         software (-no-accel), mais lenta mas funcional.
#
#  POR QUE ARM64: o APK traz libs nativas em arm64-v8a E x86_64. O celular real
#  (onde o app "crasha antes de abrir") é arm64; se o crash estiver na lib nativa
#  arm64, só um host arm64 reproduz. O emulador oficial NÃO roda guest arm64 em
#  host x86_64 ("PANIC: arm64 not supported on x86_64 host") — por isso isto roda
#  num host ARM64 de verdade.
#
#  Depois de bootar, chama .github/emu-test.sh, que faz o teste completo:
#  instala o APK real -> importa GGUF+mmproj -> abre MainActivity/ChatActivity ->
#  CPU / Vulkan / modelo+mmproj / modelo inexistente -> logcat + screenshots.
# =============================================================================
set -u

API=30                      # minSdk do APK é 24; 30 é o arm64-v8a "canônico".
IMG="system-images;android-${API};google_apis;arm64-v8a"
AVD="arm64avd"
SDK_ROOT="${ANDROID_HOME:-$HOME/android-sdk}"
export ANDROID_HOME="$SDK_ROOT"
export ANDROID_SDK_ROOT="$SDK_ROOT"
CT="$SDK_ROOT/cmdline-tools/latest/bin"
mkdir -p "$SDK_ROOT"

log() { echo "[emu-arm64] $*"; }

# ---------- Java (sdkmanager é um programa Java) ----------
if ! command -v java >/dev/null 2>&1; then
  log "Java não encontrado — instale um JDK (ex.: temurin 17) e rode de novo."
  exit 2
fi

# ---------- 1) SDK + imagem arm64-v8a (pula se já existir) ----------
if [ ! -x "$SDK_ROOT/emulator/emulator" ] || [ ! -d "$SDK_ROOT/system-images/android-${API}/google_apis/arm64-v8a" ]; then
  log "baixando cmdline-tools..."
  CTZIP="https://dl.google.com/android/repository/commandlinetools-mac-11076708_latest.zip"
  curl -sSLo /tmp/ct.zip "$CTZIP" || { log "falha ao baixar cmdline-tools de $CTZIP"; exit 3; }
  unzip -qo /tmp/ct.zip -d /tmp/ct
  mkdir -p "$SDK_ROOT/cmdline-tools/latest"
  rm -rf "$SDK_ROOT/cmdline-tools/latest"/* 2>/dev/null || true
  mv /tmp/ct/cmdline-tools/* "$SDK_ROOT/cmdline-tools/latest/"
  log "aceitando licenças + instalando emulator / platform-tools / $IMG"
  yes | "$CT/sdkmanager" --licenses >/dev/null 2>&1 || true
  "$CT/sdkmanager" "platform-tools" "emulator" "$IMG" || { log "sdkmanager falhou"; exit 4; }
fi
export PATH="$SDK_ROOT/emulator:$SDK_ROOT/platform-tools:$PATH"

# ---------- 2) AVD ----------
if ! "$CT/avdmanager" list avd 2>/dev/null | grep -q "$AVD"; then
  log "criando AVD $AVD ($IMG)"
  echo no | "$CT/avdmanager" create avd -n "$AVD" -k "$IMG" -d pixel_5 --force || true
fi

# ---------- 3) aceleração: tenta HVF, senão software ----------
if emulator -accel-check 2>&1 | grep -qi "usable"; then
  ACCEL=""; log "aceleração HVF ativa"
else
  ACCEL="-no-accel"; log "SEM aceleração -> emulação por software (lenta)"
fi

# ---------- 4) boot em background ----------
log "iniciando emulador arm64..."
nohup emulator -avd "$AVD" -no-window -gpu swiftshader_indirect -no-snapshot \
  -noaudio -no-boot-anim $ACCEL >/tmp/emu-arm64.log 2>&1 &

adb wait-for-device
log "device conectado; esperando boot_completed (pode demorar em software)..."
for i in $(seq 1 240); do
  B=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
  [ "$B" = "1" ] && break
  sleep 10
done
echo "boot_completed=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')"
echo "abi=$(adb shell getprop ro.product.cpu.abi 2>/dev/null | tr -d '\r')"
echo "sdk=$(adb shell getprop ro.build.version.sdk 2>/dev/null | tr -d '\r')"

# ---------- 5) testes do APK real ----------
log "rodando suite de testes do APK real (.github/emu-test.sh)"
bash .github/emu-test.sh
echo "FIM ARM64"
