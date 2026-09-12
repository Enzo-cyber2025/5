#!/usr/bin/env bash
# =============================================================================
#  Emulador Android ARM64 (arm64-v8a) + testes do APK REAL GGUF-Chat-fixed.apk
# -----------------------------------------------------------------------------
#  Roda no runner macos-14 (Apple Silicon arm64) do GitHub Actions.
#  Se HVF não estiver disponível (VM sem virtualização aninhada), cai para
#  emulação por software (-no-accel), que é muito lenta — por isso TODO o
#  progresso é registrado em evidence/ (vai para a branch evidence-arm64),
#  para diagnóstico mesmo quando o job estoura o timeout.
# =============================================================================
set -u

API="${API_LEVEL:-30}"
IMG="system-images;android-${API};google_apis;arm64-v8a"
AVD="arm64avd"
SDK_ROOT="${ANDROID_HOME:-$HOME/android-sdk}"
export ANDROID_HOME="$SDK_ROOT"
export ANDROID_SDK_ROOT="$SDK_ROOT"
CT="$SDK_ROOT/cmdline-tools/latest/bin"
mkdir -p "$SDK_ROOT" evidence

log() { echo "[emu-arm64 $(date -u +%H:%M:%S)] $*" | tee -a evidence/00_boot.log; }

# ---------- Java ----------
if ! command -v java >/dev/null 2>&1; then
  log "Java não encontrado"; exit 2
fi
java -version 2>&1 | tee -a evidence/00_boot.log

# ---------- 1) SDK + imagem arm64-v8a ----------
if [ ! -x "$SDK_ROOT/emulator/emulator" ] || [ ! -d "$SDK_ROOT/system-images/android-${API}/google_apis/arm64-v8a" ]; then
  log "baixando cmdline-tools..."
  CTZIP="https://dl.google.com/android/repository/commandlinetools-mac-8512546_latest.zip"
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
if "$SDK_ROOT/emulator/emulator" -accel-check 2>&1 | grep -qi "usable"; then
  ACCEL=""; log "aceleração HVF ativa"
else
  ACCEL="-no-accel"; log "SEM aceleração -> emulação por software (muito lenta)"
fi

# ---------- 4) boot ----------
log "iniciando emulador arm64 (RAM 3G, cores 3)..."
nohup "$SDK_ROOT/emulator/emulator" -avd "$AVD" -no-window -gpu swiftshader_indirect -no-snapshot \
  -noaudio -no-boot-anim -memory 3072 -cores 3 $ACCEL > /tmp/emu-arm64.log 2>&1 &
echo $! > /tmp/emu.pid

"$SDK_ROOT/platform-tools/adb" wait-for-device 2>&1 | tee -a evidence/00_boot.log &
ADBW=$!
for i in $(seq 1 90); do
  if ! kill -0 $ADBW 2>/dev/null; then break; fi
  DEV=$("$SDK_ROOT/platform-tools/adb" devices 2>/dev/null | grep -c "device$" || true)
  BOOT=$("$SDK_ROOT/platform-tools/adb" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
  log "aguardando boot: devices=$DEV boot_completed=${BOOT:-'?'} (iter $i/90)"
  [ "$BOOT" = "1" ] && break
  sleep 20
done

echo "boot_completed=$("$SDK_ROOT/platform-tools/adb" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" | tee -a evidence/00_boot.log
echo "abi=$("$SDK_ROOT/platform-tools/adb" shell getprop ro.product.cpu.abi 2>/dev/null | tr -d '\r')" | tee -a evidence/00_boot.log
echo "sdk=$("$SDK_ROOT/platform-tools/adb" shell getprop ro.build.version.sdk 2>/dev/null | tr -d '\r')" | tee -a evidence/00_boot.log
echo "--- /tmp/emu-arm64.log (tail) ---" | tee -a evidence/00_boot.log
tail -40 /tmp/emu-arm64.log 2>/dev/null | tee -a evidence/00_boot.log

# ---------- 5) testes do APK real ----------
log "rodando suite de testes do APK real (.github/emu-test.sh)"
bash .github/emu-test.sh
echo "FIM ARM64" | tee -a evidence/00_boot.log
