#!/usr/bin/env bash
# Testa o APK REAL (GGUF-Chat.apk) num emulador Android x86_64 (API 30, google_apis).
# Fluxo: boot -> instala -> importa um GGUF + um mmproj -> abre o app -> cria
# conversa -> gera (Native.create/tokenize/generate reais) -> coleta evidência.
set -u
mkdir -p evidence

log() { echo "[emu-test] $*"; }

# ---------- helpers de UI ----------
dump_ui() { adb shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1; adb pull /sdcard/ui.xml /tmp/ui.xml >/dev/null 2>&1; }

# centro do nó cujo text CONTÉM $1 (case-insensitive)
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

# centro do nó cujo content-desc CONTÉM $1
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
  local tries
  for tries in 1 2 3 4 5; do
    dump_ui
    local c; c=$(find_text "$1") && { adb shell input tap $c; return 0; }
    sleep 2
  done
  return 1
}

tap_desc() {
  local tries
  for tries in 1 2 3 4 5; do
    dump_ui
    local c; c=$(find_desc "$1") && { adb shell input tap $c; return 0; }
    sleep 2
  done
  return 1
}

shot() { adb exec-out screencap -p > "evidence/$1" 2>/dev/null || true; }

# ---------- boot ----------
adb wait-for-device
for i in $(seq 1 120); do
  B=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
  [ "$B" = "1" ] && break
  sleep 5
done
log "boot_completed=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')"

adb root >/dev/null 2>&1; sleep 2; adb wait-for-device
adb shell settings put global window_animation_scale 0 || true
adb shell settings put global transition_animation_scale 0 || true
adb shell settings put global animator_duration_scale 0 || true

# ---------- SWAP (pedido: "usa swap") ----------
# Habilita/expande zram e, se falhar, cria um swapfile, para a importação/carga
# de modelos grandes não esbarrar em memória.
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
adb shell 'cat /proc/swaps; echo "--- mem ---"; cat /proc/meminfo | head -3' > evidence/00_swap.txt 2>&1 || true
log "swap: $(tr '\n' ' ' < evidence/00_swap.txt 2>/dev/null | head -c 200)"

# ---------- instala o APK REAL ----------
log "instalando APK"
adb install -r -g GGUF-Chat.apk || adb install -r GGUF-Chat.apk
adb shell dumpsys package com.ggufchat.app | grep -E "versionName|primaryCpuAbi|userId" | tee evidence/00_pkg.txt || true

APPUID=$(adb shell dumpsys package com.ggufchat.app | grep -E 'userId=' | head -1 | sed -E 's/.*userId=([0-9]+).*/\1/' | tr -d '\r')
log "APPUID=$APPUID"

# arquivos para a importação via SAF (Download) e para o seed (root)
adb push apk-real-host-run/models/tiny-llama-022.gguf  /sdcard/Download/ >/dev/null
adb push apk-real-host-run/models/tiny-mmproj-022.gguf /sdcard/Download/ >/dev/null
adb shell ls -l /sdcard/Download/ | tee evidence/00_download.txt || true

# ---------- LAUNCH: o app crasha antes de abrir? ----------
adb logcat -c
log "launch MainActivity"
adb shell am start -n com.ggufchat.app/.MainActivity || true
sleep 12
PID=$(adb shell pidof com.ggufchat.app | tr -d '\r')
if [ -n "$PID" ]; then
  echo "LAUNCH_OK pid=$PID" > evidence/01_launch.txt
  log "LAUNCH_OK pid=$PID"
else
  echo "LAUNCH_CRASH" > evidence/01_launch.txt
  log "LAUNCH_CRASH (processo morto)"
fi
adb shell dumpsys activity activities 2>/dev/null | grep -iE "ggufchat|Resumed" > evidence/02_resumed.txt || true
shot 03_launch.png
adb logcat -d > evidence/04_logcat_launch.txt
grep -E "FATAL EXCEPTION|AndroidRuntime|SIGSEGV|Fatal signal" evidence/04_logcat_launch.txt > evidence/05_launch_errors.txt || true
if [ -s evidence/05_launch_errors.txt ]; then log "ERROS DE LAUNCH ENCONTRADOS:"; cat evidence/05_launch_errors.txt; fi

# ---------- importação via UI (SAF) — fluxo real ----------
log "tentando importar via UI"
tap_text "Importar" || log "aba Importar não encontrada"
sleep 2; shot 06_import_tab.png

tap_text "Importar .gguf" || log "botão Importar .gguf não encontrado"
sleep 4; shot 07_picker.png
if ! tap_text "tiny-llama-022.gguf"; then
  tap_desc "Show roots" && sleep 2 && tap_text "Downloads" && sleep 2
  tap_text "tiny-llama-022.gguf"
fi
sleep 6; shot 08_after_import1.png

tap_text "Importar .gguf" || true
sleep 4
if ! tap_text "tiny-mmproj-022.gguf"; then
  tap_desc "Show roots" && sleep 2 && tap_text "Downloads" && sleep 2
  tap_text "tiny-mmproj-022.gguf"
fi
sleep 6; shot 09_after_import2.png

# ---------- seed via root (garantia) ----------
log "seed via root"
adb shell mkdir -p /data/data/com.ggufchat.app/files/models
adb push apk-real-host-run/models/tiny-llama-022.gguf  /data/local/tmp/ >/dev/null
adb push apk-real-host-run/models/tiny-mmproj-022.gguf /data/local/tmp/ >/dev/null
adb shell cp /data/local/tmp/tiny-llama-022.gguf  /data/data/com.ggufchat.app/files/models/ || true
adb shell cp /data/local/tmp/tiny-mmproj-022.gguf /data/data/com.ggufchat.app/files/models/ || true
cat > /tmp/models.json <<'JSON'
[
 {"id":"a1","name":"tiny-llama-022","architecture":"llava","path":"/data/user/0/com.ggufchat.app/files/models/tiny-llama-022.gguf","size":114976,"importedAt":1750000000000,"fileName":"tiny-llama-022.gguf","mmprojPath":null,"multimodal":false},
 {"id":"a2","name":"tiny-mmproj-022","architecture":"clip","path":"/data/user/0/com.ggufchat.app/files/models/tiny-mmproj-022.gguf","size":64608,"importedAt":1750000000001,"fileName":"tiny-mmproj-022.gguf","mmprojPath":null,"multimodal":false}
]
JSON
# nota: architecture "llava" (só no metadata p/ a UI) faz isVisionModel()=true e
# dispara a FUSÃO real (findMmprojFor -> mergeAndCreate) ao abrir a conversa.
adb push /tmp/models.json /data/local/tmp/ >/dev/null
adb shell cp /data/local/tmp/models.json /data/data/com.ggufchat.app/files/models.json || true
if [ -n "$APPUID" ]; then
  adb shell chown -R "$APPUID:$APPUID" /data/data/com.ggufchat.app/files || true
fi
adb shell chmod 644 /data/data/com.ggufchat.app/files/models.json || true

# verifica models.json final (via root)
adb shell cat /data/data/com.ggufchat.app/files/models.json > evidence/10_models.json || true
log "models.json: $(cat evidence/10_models.json 2>/dev/null | head -c 300)"

# ---------- relaunch para carregar os modelos ----------
adb shell am force-stop com.ggufchat.app || true
sleep 2
adb logcat -c
adb shell am start -n com.ggufchat.app/.MainActivity || true
sleep 12
PID=$(adb shell pidof com.ggufchat.app | tr -d '\r')
echo "RELAUNCH pid=$PID" >> evidence/01_launch.txt

# ---------- abrir aba AI Modelos e conferir a lista ----------
tap_text "AI Modelos" || log "aba AI Modelos não encontrada"
sleep 2; shot 11_models_tab.png
dump_ui
grep -o "tiny-llama-022" /tmp/ui.xml >/dev/null 2>&1 && echo "MODEL_LISTED" >> evidence/12_list.txt || echo "MODEL_NOT_LISTED" >> evidence/12_list.txt
grep -o "tiny-mmproj-022" /tmp/ui.xml >/dev/null 2>&1 && echo "MMPROJ_LISTED" >> evidence/12_list.txt || echo "MMPROJ_NOT_LISTED" >> evidence/12_list.txt
cat evidence/12_list.txt

# ---------- abrir conversa e GERAR ----------
tap_text "Chat" || true
sleep 2
tap_text "+ Nova conversa" || log "botão + Nova conversa não encontrado"
sleep 3; shot 13_picker.png
tap_text "tiny-llama-022" || log "modelo no picker não encontrado"
sleep 5; shot 14_chat.png

# ---------- verificação da FUSÃO (mmproj vinculado ao modelo principal) ----------
# Ao escolher o modelo (finishNewChat), o app deve ter rodado findMmprojFor ->
# mergeAndCreate: ModelInfo.mmprojPath aponta para o mmproj e multimodal=true.
log "verificando fusão modelo+mmproj"
adb shell cat /data/data/com.ggufchat.app/files/models.json > evidence/20_fusion.json 2>/dev/null || true
python3 - evidence/20_fusion.json <<'PY'
import sys, json
try:
    d = json.load(open(sys.argv[1]))
except Exception as e:
    print("FUSION_JSON_ERR", e); raise SystemExit(0)
for m in d:
    if m.get("architecture","").lower() == "llava":
        mm = m.get("mmprojPath")
        multi = m.get("multimodal")
        if mm and multi:
            print("FUSION_OK mmprojPath=%s multimodal=%s" % (mm, multi))
        else:
            print("FUSION_FAIL mmprojPath=%r multimodal=%r" % (mm, multi))
PY
adb logcat -d > evidence/15_logcat_open.txt
grep -E "GGUFChatNative|llama_model_loader|model loaded|llama_context|backend" evidence/15_logcat_open.txt > evidence/16_native_create.txt || true
head -40 evidence/16_native_create.txt

# digita e envia
tap_text "Enviar" && sleep 1   # foca/rola; o clique real é após digitar
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
log "aguardando geração..."
for i in $(seq 1 12); do sleep 5; done
shot 17_after_generate.png
adb logcat -d > evidence/18_logcat_final.txt
grep -E "GGUFChatNative|model loaded|llama_model_loader|onToken|FATAL|AndroidRuntime|SIGSEGV|Fatal signal|generate" evidence/18_logcat_final.txt > evidence/19_native_lines.txt || true
log "linhas nativas:"; cat evidence/19_native_lines.txt | head -60

# ---------- resumo ----------
{
  echo "boot=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')"
  echo "pid=$(adb shell pidof com.ggufchat.app | tr -d '\r')"
  echo "--- swap ---"; cat evidence/00_swap.txt 2>/dev/null
  echo "--- launch ---"; cat evidence/01_launch.txt 2>/dev/null
  echo "--- lista ---"; cat evidence/12_list.txt 2>/dev/null
  echo "--- fusao ---"; cat evidence/20_fusion.json 2>/dev/null
  echo "--- native ---"; cat evidence/19_native_lines.txt 2>/dev/null | head -60
} | tee evidence/99_summary.txt

echo "FIM"
