#!/usr/bin/env bash
# =============================================================================
#  Reconstrói e re-assina o APK corrigido usando as ferramentas OFICIAIS do
#  Android (keytool + zipalign + apksigner). Roda NO RUNNER (ubuntu-latest),
#  onde o Android SDK já vem pré-instalado.
#
#  Por que este script existe: a assinatura v2 implementada "à mão" em Python
#  (rebuild_and_sign.py) tinha a estrutura interna errada e o Android REJEITAVA
#  o APK na instalação (INSTALL_FAILED). Este script usa o apksigner do Google,
#  que gera assinatura v1+v2 corretas e verificáveis.
#
#  Fluxo:
#    1) patch de 1 byte no classes.dex (bug ModelInfo.fromJson: 0x39 -> 0x38)
#       + recalcula SHA-1 (offset 12) e Adler32 (offset 8) do dex.
#    2) re-empacota o APK sem as assinaturas antigas.
#    3) zipalign + apksigner sign + apksigner verify.
#    4) resultado: GGUF-Chat-fixed.apk
# =============================================================================
set -euo pipefail

export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-/usr/local/lib/android/sdk}"
BT="$(ls -d "$ANDROID_SDK_ROOT"/build-tools/* 2>/dev/null | sort -V | tail -1)"
if [ -z "$BT" ] || [ ! -x "$BT/apksigner" ]; then
  yes | "$ANDROID_SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" "build-tools;34.0.0" >/dev/null 2>&1 || true
  BT="$(ls -d "$ANDROID_SDK_ROOT"/build-tools/* 2>/dev/null | sort -V | tail -1)"
fi
echo "build-tools: $BT"

# 1) patch do dex (fusao + showMmprojPicker) + rebuild do zip
python3 - <<'PY'
import zipfile, zlib, hashlib, struct
with zipfile.ZipFile("GGUF-Chat.apk") as z:
    dex = bytearray(z.read("classes.dex"))

def poke(off, old_hex, new_hex, label):
    old = bytes.fromhex(old_hex)
    new = bytes.fromhex(new_hex)
    assert bytes(dex[off:off+len(old)]) == old, label
    dex[off:off+len(new)] = new

poke(0x11C28, "39", "38", "fusao")
poke(0x11190,
     "71 20 42 02 1b 00 0a 07 71 20 42 02 6b 00 0a 08",
     "01 17 00 00 00 00 01 68 00 00 00 00 00 00 00 00",
     "showMmprojPicker")
dex[8:12] = b"\x00" * 4
dex[12:32] = b"\x00" * 20
dex[12:32] = hashlib.sha1(bytes(dex[32:])).digest()
dex[8:12] = struct.pack("<I", zlib.adler32(bytes(dex[12:])) & 0xFFFFFFFF)
with zipfile.ZipFile("GGUF-Chat.apk") as zin, zipfile.ZipFile("unsigned.apk", "w", zipfile.ZIP_DEFLATED) as zout:
    for it in zin.infolist():
        if it.filename == "classes.dex":
            continue
        if it.filename.startswith("META-INF/") and (it.filename.endswith((".SF", ".RSA", ".DSA", ".EC")) or it.filename == "META-INF/MANIFEST.MF"):
            continue
        zout.writestr(it, zin.read(it.filename))
    zout.writestr("classes.dex", bytes(dex))
print("unsigned.apk ok (dex corrigido)")
PY

# 2) keystore (idempotente: o passo "Build APK corrigido" do workflow já pode
#    ter criado key.jks nesta mesma máquina)
if [ ! -f key.jks ]; then
  keytool -genkeypair -keystore key.jks -storetype PKCS12 -alias gguf \
    -keyalg RSA -keysize 2048 -validity 36500 \
    -dname "CN=GGUF Chat, O=ggufchat, C=BR" -storepass ggufchat -keypass ggufchat
fi

# 3) alinhar + assinar + verificar
"$BT/zipalign" -f 4 unsigned.apk aligned.apk
"$BT/apksigner" sign --ks key.jks --ks-pass pass:ggufchat --key-pass pass:ggufchat \
  --out GGUF-Chat-fixed.apk aligned.apk
"$BT/apksigner" verify --verbose GGUF-Chat-fixed.apk
ls -l GGUF-Chat-fixed.apk
echo "PRONTO: GGUF-Chat-fixed.apk"
