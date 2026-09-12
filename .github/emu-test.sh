#!/usr/bin/env bash
# =============================================================================
#  Suite completa do APK REAL GGUF-Chat-fixed.apk num emulador Android ARM64.
#  Executado por .github/emu-test-arm64.sh (runner macos-14, Apple Silicon).
#
#  Fluxo verificado contra o bytecode REAL do APK:
#   1) boot + swap + instala o APK CORRIGIDO (GGUF-Chat-fixed.apk)
#   2) importa pela UI gráfica (SAF) um modelo de visão (llava) + um mmproj (clip)
#      -> linkMmprojs() funde automaticamente: mmprojPath + multimodal=true
#   3) verifica a FUSÃO em models.json E que ela PERSISTE após force-stop+relaunch
#      (regressão do bug ModelInfo.fromJson mmprojPath, corrigido no dex)
#   4) gera texto com um LM real (SmolLM2-135M baixado, senão fallback tiny)
#      nos backends CPU e Vulkan (SwiftShader) -> evidência em logcat
#   5) modelo inexistente -> erro tratado, sem crash
# =============================================================================
set -u
mkdir -p evidence

log() { echo "[emu-test] $*"; }

# ---------- helpers de UI ----------
dump_ui() { adb shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1; adb pull /sdcard/ui.xml /tmp/ui.xml >/dev/null 2>&1; }

find_text() {
  python3 - "$1" <<'PY'
import sys, re, xml.etree.ElementTree as ET
needle = sys.argv[1].lower()
try:
    root = ET.parse('/tmp/ui.xml').getroot()
except Exception:
    sys.exit(1)
for n in root.iter('node'):
    t = (n.get('text') or '').lower()
    if needle in t:
        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', n.get('bounds') or '')
        if m:
            print((int(m.group(1))+int(m.group(3)))//2, (int(m.group(2))+int(m.group(4)))//2)
            sys.exit(0)
sys.exit(1)
PY
}

find_desc() {
  python3 - "$1" <<'PY'
import sys, re, xml.etree.ElementTree as ET
needle = sys.argv[1].lower()
try:
    root = ET.parse('/tmp/ui.xml').getroot()
except Exception:
    sys.exit(1)
for n in root.iter('node'):
    t = (n.get('content-desc') or '').lower()
    if needle in t:
        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', n.get('bounds') or '')
        if m:
            print((int(m.group(1))+int(m.group(3)))//2, (int(m.group(2))+int(m.group(4)))//2)
            sys.exit(0)
sys.exit(1)
PY
}

tap_text() {
  local tries c
  for tries in 1 2 3 4 5 6; do
    dump_ui
    c=$(find_text "$1") && { adb shell input tap $c; return 0; }
    sleep 2
  done
  return 1
}

tap_desc() {
  local tries c
  for tries in 1 2 3 4 5 6; do
    dump_ui
    c=$(find_desc "$1") && { adb shell input tap $c; return 0; }
    sleep 2
  done
  return 1
}

shot() { adb exec-out screencap -p > "evidence/$1" 2>/dev/null || true; }

# salva o dump da hierarquia de UI (texto) em evidence/ para diagnóstico
dump_ui_ev() { dump_ui; cp /tmp/ui.xml "evidence/$1" 2>/dev/null || true; }

# tenta confirmar a seleção no picker multi-seleção do DocumentsUI.
# O app abre ACTION_OPEN_DOCUMENT com EXTRA_ALLOW_MULTIPLE=true, então tocar no
# arquivo só marca a seleção — é preciso tocar no botão "Open"/"Select".
confirm_picker() {
  local tries c
  for tries in 1 2 3 4; do
    dump_ui
    for t in "open" "select" "done" "confirm" "ok" "abrir" "selecionar"; do
      c=$(find_text "$t" 2>/dev/null) && { adb shell input tap $c; sleep 2; return 0; }
    done
    for d in "Open" "Select" "Done" "Select all"; do
      c=$(find_desc "$d" 2>/dev/null) && { adb shell input tap $c; sleep 2; return 0; }
    done
    sleep 2
  done
  return 1
}

# o picker (DocumentsUI) está aberto?
in_picker() {
  dump_ui
  find_desc "Show roots" >/dev/null 2>&1 && return 0
  find_text "Recent" >/dev/null 2>&1
}

# raiz do armazenamento interno no DocumentsUI (lê o filesystem real)
tap_storage_root() {
  local l
  for l in "Internal storage" "internal storage" "sdcard" "SD card" "sd card" "emulator" "Pixel"; do
    c=$(find_text "$l" 2>/dev/null) && { adb shell input tap $c; return 0; }
  done
  return 1
}

# seleciona um arquivo no SAF picker (OpenDocument) e confirma a seleção.
# $1 = nome exibido; $2 = trecho de busca (stem) opcional
pick_file() {
  local name="$1" stem="${2:-$1}" tries
  for tries in 1 2 3 4 5 6 7 8; do
    dump_ui
    # 1) o arquivo já aparece na tela atual (Recent/Downloads)?
    if find_text "$stem" >/dev/null 2>&1; then
      tap_text "$stem"; sleep 1
      if confirm_picker && ! in_picker; then return 0; fi
      confirm_picker; sleep 2
      if ! in_picker; then return 0; fi
    fi
    # 2) abre a gaveta -> Downloads (MediaStore)
    tap_desc "Show roots"; sleep 2
    tap_text "Downloads"; sleep 3
    if find_text "$stem" >/dev/null 2>&1; then
      tap_text "$stem"; sleep 1
      if confirm_picker && ! in_picker; then return 0; fi
      confirm_picker; sleep 2
      if ! in_picker; then return 0; fi
    fi
    # 3) fallback: raiz do armazenamento interno -> pasta Download
    tap_desc "Show roots"; sleep 2
    tap_storage_root; sleep 2
    tap_text "Download"; sleep 3
    if find_text "$stem" >/dev/null 2>&1; then
      tap_text "$stem"; sleep 1
      if confirm_picker && ! in_picker; then return 0; fi
      confirm_picker; sleep 2
      if ! in_picker; then return 0; fi
    fi
    dump_ui_ev "ui_picker_retry_${stem}_${tries}.xml"
    sleep 2
  done
  return 1
}

# ---------- boot ----------
adb wait-for-device
for i in $(seq 1 120); do
  B=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
  [ "$B" = "1" ] && break
  sleep 5
done
log "boot_completed=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')"
adb shell getprop ro.product.cpu.abi  > evidence/00_abi.txt 2>/dev/null || true
adb shell getprop ro.build.version.sdk > evidence/00_sdk.txt 2>/dev/null || true

adb root >/dev/null 2>&1; sleep 2; adb wait-for-device
adb shell settings put global window_animation_scale 0 || true
adb shell settings put global transition_animation_scale 0 || true
adb shell settings put global animator_duration_scale 0 || true

# ---------- SWAP ----------
log "configurando swap"
adb shell 'if [ -e /sys/block/zram0/disksize ]; then
    swapoff /dev/block/zram0 2>/dev/null
    echo 2G > /sys/block/zram0/disksize 2>/dev/null
    mkswap /dev/block/zram0 2>/dev/null && swapon /dev/block/zram0 2>/dev/null
  fi
  if ! grep -q swap /proc/swaps 2>/dev/null; then
    dd if=/dev/zero of=/data/local/tmp/swapfile bs=1M count=1024 2>/dev/null
    mkswap /data/local/tmp/swapfile 2>/dev/null && swapon /data/local/tmp/swapfile 2>/dev/null
  fi'
adb shell 'cat /proc/swaps; echo "--- mem ---"; head -3 /proc/meminfo' > evidence/00_swap.txt 2>&1 || true

# ---------- modelo real (best-effort) ----------
GEN_MODEL="tiny-llama-022.gguf"; GEN_SRC="apk-real-host-run/models/tiny-llama-022.gguf"
log "tentando baixar SmolLM2-135M-Instruct Q4_K_M (~105MB, modelo REAL)..."
if curl -fsSL --retry 2 --connect-timeout 30 --max-time 240 \
     -o /tmp/smollm.gguf \
     "https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF/resolve/main/SmolLM2-135M-Instruct-Q4_K_M.gguf"; then
  SZ=$(wc -c < /tmp/smollm.gguf)
  if [ "$SZ" -gt 50000000 ]; then
    GEN_MODEL="smollm2-135m.gguf"; GEN_SRC="/tmp/smollm.gguf"; REAL_MODEL=1
    log "SmolLM2 baixado: $SZ bytes (modelo REAL)"
  fi
fi
[ "${REAL_MODEL:-0}" = "1" ] || log "sem modelo real (fallback para fixture tiny). REAL_MODEL=${REAL_MODEL:-0}"

# ---------- instala o APK CORRIGIDO ----------
log "instalando GGUF-Chat-fixed.apk"
adb install -r -g GGUF-Chat-fixed.apk || adb install -r GGUF-Chat-fixed.apk
adb shell dumpsys package com.ggufchat.app | grep -E "versionName|primaryCpuAbi|userId" | tee evidence/00_pkg.txt || true
APPUID=$(adb shell dumpsys package com.ggufchat.app | grep -E 'userId=' | head -1 | sed -E 's/.*userId=([0-9]+).*/\1/' | tr -d '\r')
log "APPUID=$APPUID"

# ---------- arquivos para a importação via UI (SAF) ----------
adb push apk-real-host-run/models/tiny-llava.gguf    /sdcard/Download/ >/dev/null
adb push apk-real-host-run/models/tiny-mmproj-022.gguf /sdcard/Download/ >/dev/null
adb push "$GEN_SRC" /sdcard/Download/"$GEN_MODEL" >/dev/null
# força a indexação pelo MediaProvider (best-effort; o FUSE normalmente indexa
# sozinho, mas alguns runners demoram) para o picker do DocumentsUI listar.
for f in tiny-llava.gguf tiny-mmproj-022.gguf "$GEN_MODEL"; do
  adb shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE \
    -d "file:///storage/emulated/0/Download/$f" >/dev/null 2>&1 || true
done
adb shell 'content call --uri content://media/none/media_scanner --method scan_volume --arg external_primary' >/dev/null 2>&1 || true
sleep 5
adb shell ls -l /sdcard/Download/ | tee evidence/00_download.txt || true

# ---------- LAUNCH ----------
adb logcat -c
log "launch MainActivity"
adb shell am start -n com.ggufchat.app/.MainActivity || true
sleep 12
PID=$(adb shell pidof com.ggufchat.app | tr -d '\r')
if [ -n "$PID" ]; then echo "LAUNCH_OK pid=$PID" > evidence/01_launch.txt; else echo "LAUNCH_CRASH" > evidence/01_launch.txt; fi
log "$(cat evidence/01_launch.txt)"
shot 03_launch.png
adb logcat -d > evidence/04_logcat_launch.txt
grep -E "FATAL EXCEPTION|AndroidRuntime|SIGSEGV|Fatal signal" evidence/04_logcat_launch.txt > evidence/05_launch_errors.txt || true
if [ -s evidence/05_launch_errors.txt ]; then log "ERROS DE LAUNCH:"; cat evidence/05_launch_errors.txt; fi

# ---------- importação via UI (fluxo REAL) ----------
import_via_ui() {
  local name="$1" stem="$2"
  tap_text "Importar" || { tap_text "Importar .gguf"; }
  sleep 2
  tap_text "Importar .gguf" || log "botão Importar .gguf não encontrado"
  sleep 4
  dump_ui_ev "ui_picker_open_${stem}.xml"
  if ! pick_file "$name" "$stem"; then
    dump_ui_ev "ui_picker_fail_${stem}.xml"
    log "falha ao selecionar $name no picker"
    return 1
  fi
  sleep 4
  dump_ui_ev "ui_after_import_${stem}.xml"
  return 0
}

log "importando modelo de visão (llava) via UI"
import_via_ui "tiny-llava.gguf" "tiny-llava"
sleep 4; shot 06_after_import1.png

log "importando mmproj (clip) via UI"
import_via_ui "tiny-mmproj-022.gguf" "tiny-mmproj"
sleep 8; shot 07_after_import2.png

log "importando modelo de geração via UI: $GEN_MODEL"
import_via_ui "$GEN_MODEL" "${GEN_MODEL%.gguf}"
sleep 8; shot 08_after_import3.png

# dá tempo para linkMmprojs() rodar (roda após o último import, na thread de UI)
sleep 6
shot 09_after_link.png

# espera a cópia dos arquivos terminar: models.json deve listar 3 modelos
for i in $(seq 1 30); do
  N=$(adb shell cat /data/data/com.ggufchat.app/files/models.json 2>/dev/null | \
      python3 -c 'import sys,json
try: print(len(json.load(sys.stdin)))
except Exception: print(0)' 2>/dev/null | tr -d '\r')
  [ -n "$N" ] && [ "$N" -ge 3 ] && break
  sleep 4
done
log "modelos em models.json após import: N=${N:-0}"

# ---------- verificação da FUSÃO ----------
log "verificando fusão modelo+mmproj em models.json"
adb shell cat /data/data/com.ggufchat.app/files/models.json > evidence/20_fusion.json 2>/dev/null || true
python3 - evidence/20_fusion.json <<'PY'
import sys, json
try:
    d = json.load(open(sys.argv[1]))
except Exception as e:
    print("FUSION_JSON_ERR", e); raise SystemExit(0)
if not isinstance(d, list):
    print("FUSION_JSON_NOT_LIST"); raise SystemExit(0)
vision = [m for m in d if (m.get("architecture") or "").lower() == "llava"]
mmproj = [m for m in d if "mmproj" in (m.get("fileName") or "").lower() or (m.get("architecture") or "").lower() == "clip"]
print("MODELS=%d VISION=%d MMPROJ=%d" % (len(d), len(vision), len(mmproj)))
for m in vision:
    print("VISION id=%s name=%s mmprojPath=%s multimodal=%s arch=%s" % (
        m.get("id"), m.get("name"), m.get("mmprojPath"), m.get("multimodal"), m.get("architecture")))
if vision and mmproj:
    v = vision[0]; p = mmproj[0].get("path")
    if v.get("mmprojPath") == p and v.get("multimodal"):
        print("FUSION_OK mmprojPath=%s multimodal=true" % v.get("mmprojPath"))
    else:
        print("FUSION_FAIL mmprojPath=%r (esperado %r) multimodal=%r" % (v.get("mmprojPath"), p, v.get("multimodal")))
PY
tee evidence/21_fusion_summary.txt

# ---------- PERSISTÊNCIA (regressão do bug fromJson) ----------
log "forçando stop + relaunch para testar persistência da fusão"
adb shell am force-stop com.ggufchat.app || true
sleep 3
adb logcat -c
adb shell am start -n com.ggufchat.app/.MainActivity || true
sleep 12
PID=$(adb shell pidof com.ggufchat.app | tr -d '\r')
echo "RELAUNCH pid=$PID" >> evidence/01_launch.txt
adb shell cat /data/data/com.ggufchat.app/files/models.json > evidence/22_fusion_after_relaunch.json 2>/dev/null || true
python3 - evidence/22_fusion_after_relaunch.json <<'PY'
import sys, json
try:
    d = json.load(open(sys.argv[1]))
except Exception as e:
    print("PERSIST_JSON_ERR", e); raise SystemExit(0)
vision = [m for m in d if (m.get("architecture") or "").lower() == "llava"]
if not vision:
    print("PERSIST_NO_VISION"); raise SystemExit(0)
v = vision[0]
if v.get("mmprojPath") and v.get("multimodal"):
    print("PERSIST_OK mmprojPath=%s multimodal=true" % v.get("mmprojPath"))
else:
    print("PERSIST_FAIL mmprojPath=%r multimodal=%r" % (v.get("mmprojPath"), v.get("multimodal")))
PY
tee evidence/23_persist_summary.txt

# ---------- geração CPU ----------
log "definindo backend CPU (gpuLayers=0) via shared_prefs"
adb shell am force-stop com.ggufchat.app || true
adb shell mkdir -p /data/data/com.ggufchat.app/shared_prefs
adb shell 'cat > /data/data/com.ggufchat.app/shared_prefs/ggufchat_settings.xml <<EOF
<?xml version="1.0" encoding="utf-8" standalone="yes" ?>
<map>
    <int name="gpuLayers" value="0" />
    <int name="contextSize" value="2048" />
    <int name="nThreads" value="4" />
    <boolean name="useMmap" value="true" />
</map>
EOF'
if [ -n "$APPUID" ]; then adb shell chown "$APPUID:$APPUID" /data/data/com.ggufchat.app/shared_prefs/ggufchat_settings.xml || true; fi
adb shell chmod 600 /data/data/com.ggufchat.app/shared_prefs/ggufchat_settings.xml || true
adb logcat -c
adb shell am start -n com.ggufchat.app/.MainActivity || true
sleep 12

log "abrindo nova conversa com $GEN_MODEL"
tap_text "Chat" || true
sleep 2
tap_text "+ Nova conversa" || tap_text "Nova conversa" || log "botão nova conversa não encontrado"
sleep 3; shot 10_picker.png
if ! tap_text "$GEN_MODEL"; then
  # fallback: escolhe o primeiro modelo da lista
  tap_text "tiny" || log "modelo não encontrado no picker"
fi
sleep 10; shot 11_chat_cpu.png
adb logcat -d > evidence/30_logcat_cpu_create.txt
grep -E "GGUFChatNative|llama_model_loader|model loaded|engine loaded|backend" evidence/30_logcat_cpu_create.txt > evidence/31_cpu_create_lines.txt || true
log "linhas nativas (CPU):"; cat evidence/31_cpu_create_lines.txt | head -40

# envia mensagem e espera geração
dump_ui
C=$(python3 - <<'PY'
import re, xml.etree.ElementTree as ET
try:
    root = ET.parse('/tmp/ui.xml').getroot()
except Exception:
    raise SystemExit(1)
for n in root.iter('node'):
    if (n.get('class') or '').endswith('EditText'):
        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', n.get('bounds') or '')
        if m:
            print((int(m.group(1))+int(m.group(3)))//2, (int(m.group(2))+int(m.group(4)))//2)
            raise SystemExit(0)
raise SystemExit(1)
PY
) && adb shell input tap $C
sleep 1
adb shell input text "Ola"
sleep 1
tap_text "Enviar" || log "botão Enviar não encontrado"
log "aguardando geração (CPU)..."
for i in $(seq 1 24); do sleep 5; done
shot 12_after_generate_cpu.png
adb logcat -d > evidence/32_logcat_cpu_gen.txt
grep -E "GGUFChatNative|model loaded|onToken|FATAL|AndroidRuntime|SIGSEGV|Fatal signal|generate|error" evidence/32_logcat_cpu_gen.txt > evidence/33_cpu_gen_lines.txt || true
log "linhas geração (CPU):"; cat evidence/33_cpu_gen_lines.txt | head -60
dump_ui
python3 - <<'PY' > evidence/34_cpu_reply.txt 2>/dev/null || true
import xml.etree.ElementTree as ET
try:
    root = ET.parse('/tmp/ui.xml').getroot()
except Exception:
    print("UI_DUMP_ERR"); raise SystemExit(0)
texts = [n.get('text') for n in root.iter('node') if n.get('text')]
reply = [t for t in texts if t and len(t) > 2 and t != "Ola"]
print("TEXT_NODES=%d REPLY_CANDIDATES=%d" % (len(texts), len(reply)))
for t in reply[:5]:
    print("REPLY:", t[:200])
PY
cat evidence/34_cpu_reply.txt

# ---------- geração Vulkan ----------
log "definindo backend Vulkan (gpuLayers=-1) via shared_prefs"
adb shell am force-stop com.ggufchat.app || true
adb shell 'cat > /data/data/com.ggufchat.app/shared_prefs/ggufchat_settings.xml <<EOF
<?xml version="1.0" encoding="utf-8" standalone="yes" ?>
<map>
    <int name="gpuLayers" value="-1" />
    <int name="contextSize" value="2048" />
    <int name="nThreads" value="4" />
    <boolean name="useMmap" value="true" />
</map>
EOF'
if [ -n "$APPUID" ]; then adb shell chown "$APPUID:$APPUID" /data/data/com.ggufchat.app/shared_prefs/ggufchat_settings.xml || true; fi
adb shell chmod 600 /data/data/com.ggufchat.app/shared_prefs/ggufchat_settings.xml || true
adb logcat -c
adb shell am start -n com.ggufchat.app/.MainActivity || true
sleep 12
log "nova conversa com backend Vulkan"
tap_text "Chat" || true
sleep 2
tap_text "+ Nova conversa" || tap_text "Nova conversa" || log "botão nova conversa não encontrado"
sleep 3
if ! tap_text "$GEN_MODEL"; then tap_text "tiny" || log "modelo não encontrado"; fi
sleep 12; shot 13_chat_vulkan.png
adb logcat -d > evidence/40_logcat_vulkan_create.txt
grep -E "GGUFChatNative|engine loaded|registered backend|backend library|model loaded|Vulkan|gpu_offload" evidence/40_logcat_vulkan_create.txt > evidence/41_vulkan_lines.txt || true
log "linhas Vulkan:"; cat evidence/41_vulkan_lines.txt | head -60

dump_ui
C=$(python3 - <<'PY'
import re, xml.etree.ElementTree as ET
try:
    root = ET.parse('/tmp/ui.xml').getroot()
except Exception:
    raise SystemExit(1)
for n in root.iter('node'):
    if (n.get('class') or '').endswith('EditText'):
        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', n.get('bounds') or '')
        if m:
            print((int(m.group(1))+int(m.group(3)))//2, (int(m.group(2))+int(m.group(4)))//2)
            raise SystemExit(0)
raise SystemExit(1)
PY
) && adb shell input tap $C
sleep 1
adb shell input text "Teste vulkan"
sleep 1
tap_text "Enviar" || log "botão Enviar não encontrado"
log "aguardando geração (Vulkan)..."
for i in $(seq 1 24); do sleep 5; done
shot 14_after_generate_vulkan.png
adb logcat -d > evidence/42_logcat_vulkan_gen.txt
grep -E "GGUFChatNative|model loaded|FATAL|AndroidRuntime|SIGSEGV|Fatal signal|error" evidence/42_logcat_vulkan_gen.txt > evidence/43_vulkan_gen_lines.txt || true
log "linhas geração (Vulkan):"; cat evidence/43_vulkan_gen_lines.txt | head -60

# ---------- modelo inexistente ----------
log "teste de modelo inexistente (não deve crashar)"
adb shell am force-stop com.ggufchat.app || true
adb shell mkdir -p /data/data/com.ggufchat.app/files
cat > /tmp/models_bad.json <<'JSON'
[
 {"id":"bad1","name":"modelo-inexistente","architecture":"llama","path":"/data/user/0/com.ggufchat.app/files/models/nao-existe.gguf","size":1,"importedAt":1750000000000,"fileName":"nao-existe.gguf","mmprojPath":null,"multimodal":false}
]
JSON
adb push /tmp/models_bad.json /data/local/tmp/ >/dev/null
adb shell cp /data/local/tmp/models_bad.json /data/data/com.ggufchat.app/files/models.json || true
if [ -n "$APPUID" ]; then adb shell chown "$APPUID:$APPUID" /data/data/com.ggufchat.app/files/models.json || true; fi
adb shell chmod 644 /data/data/com.ggufchat.app/files/models.json || true
adb logcat -c
adb shell am start -n com.ggufchat.app/.MainActivity || true
sleep 10
tap_text "Chat" || true
sleep 2
tap_text "+ Nova conversa" || tap_text "Nova conversa" || log "sem botão nova conversa"
sleep 3
tap_text "modelo-inexistente" || tap_text "nao-existe" || log "modelo inexistente não listado"
sleep 8; shot 15_nonexistent.png
PID=$(adb shell pidof com.ggufchat.app | tr -d '\r')
if [ -n "$PID" ]; then echo "NONEXISTENT_NO_CRASH pid=$PID" > evidence/50_nonexistent.txt; else echo "NONEXISTENT_CRASH" > evidence/50_nonexistent.txt; fi
adb logcat -d > evidence/51_logcat_nonexistent.txt
grep -E "FATAL|AndroidRuntime|SIGSEGV|Fatal signal|GGUFChatNative|Não foi possível carregar|modelo" evidence/51_logcat_nonexistent.txt > evidence/52_nonexistent_lines.txt || true
log "modelo inexistente:"; cat evidence/50_nonexistent.txt; cat evidence/52_nonexistent_lines.txt | head -30

# ---------- resumo ----------
{
  echo "boot=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')"
  echo "abi=$(cat evidence/00_abi.txt 2>/dev/null)"
  echo "sdk=$(cat evidence/00_sdk.txt 2>/dev/null)"
  echo "REAL_MODEL=${REAL_MODEL:-0}"
  echo "--- launch ---"; cat evidence/01_launch.txt 2>/dev/null
  echo "--- swap ---"; cat evidence/00_swap.txt 2>/dev/null
  echo "--- fusao ---"; cat evidence/20_fusion.json 2>/dev/null
  echo "--- fusao summary ---"; cat evidence/21_fusion_summary.txt 2>/dev/null
  echo "--- persistencia ---"; cat evidence/23_persist_summary.txt 2>/dev/null
  echo "--- CPU create ---"; cat evidence/31_cpu_create_lines.txt 2>/dev/null | head -30
  echo "--- CPU reply ---"; cat evidence/34_cpu_reply.txt 2>/dev/null
  echo "--- Vulkan ---"; cat evidence/41_vulkan_lines.txt 2>/dev/null | head -40
  echo "--- inexistente ---"; cat evidence/50_nonexistent.txt 2>/dev/null
} | tee evidence/99_summary.txt

# ---------- APK corrigido (publicado para download) ----------
if [ -f GGUF-Chat-fixed.apk ]; then
  cp -f GGUF-Chat-fixed.apk evidence/GGUF-Chat-fixed.apk
  ls -l GGUF-Chat-fixed.apk | tee evidence/60_apk.txt
  echo "APK_SHA256=$(sha256sum GGUF-Chat-fixed.apk | cut -d' ' -f1)" | tee -a evidence/60_apk.txt
else
  echo "APK ausente" | tee evidence/60_apk.txt
fi

log "FIM"
