#!/usr/bin/env bash
# =============================================================================
# ci_build.sh — constrói um ISO mínimo, REAL e bootável em um runner do
# GitHub Actions (ou qualquer máquina Debian com rede padrão).
#
# Diferente de build_all.sh (que bootstrappia a toolchain alvo completa),
# este script usa as ferramentas do sistema (gcc, bison, flex, bc, xorriso,
# grub, busbox-static, dracut) instaladas via apt. É o caminho confiável para
# gerar o artefato .iso + .sha256 e publicá-lo como Release deste repositório.
#
# Etapas:
#   1. kernel Linux 6.6.x LTS (bzImage) com -O3 -march=goldmont-plus
#   2. initramfs (cpio + zstd) com BusyBox e um init original
#   3. ISO híbrido UEFI+BIOS via grub-mkrescue/xorriso
#   4. SHA256 do ISO
#
# Requisitos no runner (instalados pelo workflow):
#   apt install --yes build-essential bc bison flex libssl-dev libelf-dev \
#      xorriso grub-pc-bin grub-efi-amd64-bin grub-common mtools cpio \
#      zstd busybox-static dracut wget curl xz-utils
# =============================================================================
set -e -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${HERE}/config.sh"

log(){ echo -e "\n\u001b[1;34m[NovaLinux/ci]\u001b[0m $*"; }
KVER="${KERNEL_VERSION}"
OUT="${OUT_DIR}"
mkdir -p "${BUILD_DIR}" "${OUT}" "${ROOTFS_DIR}" "${ISO_DIR}"

command -v grub-mkrescue >/dev/null || { echo "ERRO: grub-mkrescue ausente"; exit 1; }
command -v xorriso    >/dev/null || { echo "ERRO: xorriso ausente"; exit 1; }

# ---------------------------------------------------------------------------
# 1. KERNEL
# ---------------------------------------------------------------------------
if [ -z "${NO_KERNEL:-}" ]; then
  "${HERE}/build_kernel.sh"
else
  log "pulando kernel (NO_KERNEL=1)"
fi
[ -f "${ROOTFS_DIR}/boot/bzImage" ] || { echo "ERRO: bzImage ausente"; exit 1; }

# ---------------------------------------------------------------------------
# 2. BusyBox estatico
# ---------------------------------------------------------------------------
BB="${ROOTFS_DIR}/bin/busybox"
if [ ! -x "${BB}" ]; then
  log "instalando BusyBox estático no rootfs"
  mkdir -p "${ROOTFS_DIR}/bin"
  if [ -x /bin/busybox ]; then
    cp -a /bin/busybox "${BB}"
  elif [ -x /usr/bin/busybox ]; then
    cp -a /usr/bin/busybox "${BB}"
  else
    echo "ERRO: busybox não encontrado no sistema"; exit 1
  fi
fi
chmod +x "${BB}"

# ---------------------------------------------------------------------------
# 3. Rootfs mínimo (só o necessário p/ boot -> shell)
# ---------------------------------------------------------------------------
log "preparando rootfs mínimo"
R="${ROOTFS_DIR}"
mkdir -p "${R}/bin" "${R}/sbin" "${R}/usr/bin" "${R}/usr/sbin" \
         "${R}/etc" "${R}/proc" "${R}/sys" "${R}/dev" "${R}/tmp" "${R}/var"
# liga comandos essenciais ao busybox
for a in sh mount umount ls cp cat echo sleep dmesg mknod mkdir ps kill uname poweroff reboot insmod modprobe switch_root ip ping ifconfig; do
  ln -sf /bin/busybox "${R}/bin/${a}" 2>/dev/null || true
done
ln -sf /bin/busybox "${R}/sbin/init" 2>/dev/null || true
ln -sf /bin/busybox "${R}/sbin/sh" 2>/dev/null || true
# init original (nada de systemd); abre tty e shell
cat > "${R}/init" <<'EOF'
#!/bin/busybox sh
mount -t proc none /proc
mount -t sysfs none /sys
mount -t devtmpfs devtmpfs /dev 2>/dev/null || { mkdir -m 755 /dev 2>/dev/null; mount -t tmpfs tmpfs /dev; }
echo
echo "== NovaLinux (busybox) — boot mínimo =="
echo "hostname: $(cat /etc/hostname 2>/dev/null || echo novastation)"
echo "kernel : $(uname -r)"
echo "Tecle Ctrl+D ou digite 'poweroff' para desligar."
echo
echo "NOVALINUX_BOOT_OK"
exec /bin/busybox sh
EOF
chmod +x "${R}/init"
echo "novastation" > "${R}/etc/hostname"

# ---------------------------------------------------------------------------
# 4. Initramfs (cpio + zstd)
# ---------------------------------------------------------------------------
INITRD="${ISO_DIR}/initramfs-${KVER}.img"
log "gerando initramfs -> ${INITRD}"
( cd "${R}" && find . | cpio -H newc -o 2>/dev/null ) | zstd -q -o "${INITRD}" 2>/dev/null \
  || ( cd "${R}" && find . | cpio -H newc -o 2>/dev/null ) | gzip -c > "${INITRD}"
[ -s "${INITRD}" ] || { echo "ERRO: initramfs vazio"; exit 1; }

# ---------------------------------------------------------------------------
# 5. ISO híbrido
# ---------------------------------------------------------------------------
ISOD="${ISO_DIR}/isoroot"
rm -rf "${ISOD}"; mkdir -p "${ISOD}/boot/grub"
cp "${ROOTFS_DIR}/boot/bzImage" "${ISOD}/boot/vmlinuz-${KVER}"
cp "${INITRD}" "${ISOD}/boot/initramfs-${KVER}.img"
# tema padrão + config GRUB
mkdir -p "${ISOD}/boot/grub/themes/${GRUB_THEME}"
cp "${PROJECT_DIR}/grub/theme/background.png" "${ISOD}/boot/grub/themes/${GRUB_THEME}/" 2>/dev/null || true
cp "${PROJECT_DIR}/grub/theme.txt" "${ISOD}/boot/grub/themes/${GRUB_THEME}/theme.txt" 2>/dev/null || true
cat > "${ISOD}/boot/grub/grub.cfg" <<EOF
set default=0
set timeout=3
set gfxmode=auto
set gfxpayload=keep
insmod all_video
insmod gfxterm
insmod png
insmod linux
insmod normal
insmod search
insmod search_label
insmod search_fs_file
loadfont unicode
terminal_output gfxterm

menuentry "NovaLinux (minimal, N5030 Goldmont Plus)" {
    search --no-floppy --set=root --file /boot/vmlinuz-${KVER}
    linux /boot/vmlinuz-${KVER} ${KERNEL_PARAMS} rdinit=/init
    initrd /boot/initramfs-${KVER}.img
}
menuentry "NovaLinux (verbose)" {
    search --no-floppy --set=root --file /boot/vmlinuz-${KVER}
    linux /boot/vmlinuz-${KVER} loglevel=4 rdinit=/init
    initrd /boot/initramfs-${KVER}.img
}
menuentry "Reiniciar" { reboot }
menuentry "Desligar" { halt }
EOF

log "gerando ISO híbrido (UEFI + BIOS) com grub-mkrescue..."
ISO="${OUT}/${ISO_NAME}"
grub-mkrescue -o "${ISO}" "${ISOD}" 2>&1 || \
  { echo "ERRO: grub-mkrescue falhou"; exit 1; }
[ -s "${ISO}" ] || { echo "ERRO: ISO vazio"; exit 1; }

log "aplicando modo híbrido (pode ser opcional) e calculando SHA256"
( command -v isohybrid >/dev/null && isohybrid "${ISO}" 2>/dev/null ) || true
sha256sum "${ISO}" | tee "${OUT}/${ISO_NAME}.sha256"

log "===== ISO PRONTO ====="
ls -lh "${ISO}" "${OUT}/${ISO_NAME}.sha256"
echo "ISO_PATH=${ISO}"
echo "SHA256=$(sed 's| .*||' "${OUT}/${ISO_NAME}.sha256")"
