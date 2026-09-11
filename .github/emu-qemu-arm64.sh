#!/usr/bin/env bash
# Boot do LineageOS 23.2 (Android 15) ARM64 no QEMU local (TCG, sem KVM) + suite completa
# do GGUF-Chat.apk REAL.
#
# Pré-requisitos (todos já resolvidos neste sandbox):
#   QEMU  : /tmp/npmqemu/package          (qemu-portable-linux-x64-musl + firmware EDK2)
#   adb   : /tmp/aosp-sysimg/linux/platform-tools/adb   (extraído do mirror AOSP)
#   imagem: UTM-VM-lineage-*-virtio_arm64only.zip (jqssun/android-lineage-qemu) — ÚNICO
#           item que depende de objects.githubusercontent.com (bloqueado neste sandbox).
set -euo pipefail

Q=/tmp/npmqemu/package
QEMU="$Q/lib/libc.musl-x86_64.so.1 $Q/bin/qemu-system-aarch64"
ADB=/tmp/aosp-sysimg/linux/platform-tools/adb
export LD_LIBRARY_PATH=/tmp/aosp-sysimg/linux/platform-tools/lib64
APK=/home/user/5/GGUF-Chat.apk
IMG_DIR=${IMG_DIR:-/tmp/lineage-vm}
REL=${REL:-v2026.08.22}

run_adb() { "$ADB" "$@"; }

mkdir -p "$IMG_DIR"; cd "$IMG_DIR"

# ---- 1) imagem ---------------------------------------------------------------
if [ ! -d LineageOS_on_*.utm ]; then
  echo ">> baixando UTM-VM-lineage-*-virtio_arm64only.zip (release $REL) ..."
  if ! curl -fL -o vm.zip \
    "https://github.com/jqssun/android-lineage-qemu/releases/download/$REL/UTM-VM-lineage-23.2-20260822-jqssun-virtio_arm64only.zip"; then
    echo "!! download falhou: objects.githubusercontent.com bloqueado na rede deste sandbox."
    echo "!! destrave: reconectar o GitHub com permissão workflows OU liberar objects.githubusercontent.com."
    exit 2
  fi
  unzip -o vm.zip
fi
UTM=$(find . -maxdepth 1 -type d -name "LineageOS_on_*.utm" | head -1)
[ -n "$UTM" ] || { echo "!! não achei LineageOS_on_*.utm"; exit 2; }
EFI_VARS=$(find "$UTM/Data" -name "efi_vars.fd" | head -1)
VDA=$(find "$UTM/Data" -name "vda.qcow2" | head -1)
VDB=$(find "$UTM/Data" -name "vdb.qcow2" | head -1)
[ -f "$EFI_VARS" ] && [ -f "$VDA" ] && [ -f "$VDB" ] || { echo "!! faltam arquivos em $UTM/Data"; exit 2; }

# ---- 2) boot headless (TCG) ---------------------------------------------------
echo ">> bootando LineageOS arm64 (TCG, ~pode levar muitos minutos sem KVM) ..."
# shellcheck disable=SC2086
$QEMU -machine virt -cpu max,pauth-impdef=on -accel tcg,tb-size=1024,thread=multi \
  -m 2048 -smp 2 \
  -device virtio-blk-pci,drive=vda,bootindex=0 \
  -device virtio-blk-pci,drive=vdb,bootindex=1 \
  -drive if=pflash,unit=0,file="$Q/share/qemu/edk2-aarch64-code.fd",format=raw,readonly=on \
  -drive if=pflash,unit=1,file="$EFI_VARS" \
  -drive file="$VDA",if=none,id=vda,discard=unmap,detect-zeroes=unmap \
  -drive file="$VDB",if=none,id=vdb,discard=unmap,detect-zeroes=unmap \
  -device virtio-gpu-pci -display none \
  -device virtio-net-pci,netdev=net0 \
  -netdev user,id=net0,hostfwd=tcp:127.0.0.1:5555-:5555,hostfwd=tcp:127.0.0.1:5554-:5554 \
  -device virtio-serial -device virtio-rng-pci \
  -chardev stdio,mux=on,id=charconsole -serial chardev:charconsole \
  > qemu.log 2>&1 &
QEMU_PID=$!
echo ">> QEMU pid=$QEMU_PID (log: $IMG_DIR/qemu.log)"

# ---- 3) espera o adb ----------------------------------------------------------
echo ">> aguardando o adb responder em 127.0.0.1:5555 ..."
for i in $(seq 1 180); do
  if run_adb connect 127.0.0.1:5555 >/dev/null 2>&1 && run_adb -s 127.0.0.1:5555 get-state >/dev/null 2>&1; then
    echo ">> adb conectado."; break
  fi
  sleep 10
done
run_adb devices

# ---- 4) instala o APK real ----------------------------------------------------
echo ">> instalando GGUF-Chat.apk ..."
run_adb -s 127.0.0.1:5555 install -r "$APK"

# ---- 5) importa GGUF + mmproj -------------------------------------------------
echo ">> importando GGUF + mmproj (fixtures de teste) ..."
GGUF=/home/user/5/apk-real-host-run/models/tiny-llama-022.gguf
MMPROJ=/home/user/5/apk-real-host-run/models/tiny-mmproj-022.gguf
run_adb -s 127.0.0.1:5555 push "$GGUF" /sdcard/Download/model.gguf
run_adb -s 127.0.0.1:5555 push "$MMPROJ" /sdcard/Download/mmproj.gguf

# ---- 6) suite -----------------------------------------------------------------
echo ">> abrindo a MainActivity ..."
run_adb -s 127.0.0.1:5555 shell am start -n com.ggufchat.app/.MainActivity
sleep 5
echo ">> logcat (crash de abertura?) ..."
run_adb -s 127.0.0.1:5555 logcat -d -b crash > logcat-crash.txt
run_adb -s 127.0.0.1:5555 logcat -d > logcat.txt
run_adb -s 127.0.0.1:5555 exec-out screencap -p > screen-main.png

echo ">> logcat na pasta $IMG_DIR (logcat-crash.txt, logcat.txt, screen-main.png)."
echo ">> (QEMU continua rodando, pid=$QEMU_PID; encerre com: kill $QEMU_PID)"
