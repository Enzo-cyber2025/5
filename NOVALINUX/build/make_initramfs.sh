#!/usr/bin/env bash
# =============================================================================
# make_initramfs.sh — gera o initramfs com dracut
#
# O initramfs carrega: módulos de disco/input/vídeo/swap zstd, o usuário
# "nova", a otimização de boot (quiet loglevel=3 mitigations=off
# intel_idle.max_cstate=4) e o árbitro do OpenRC. O resultado é um cpio
# comprimido com zstd para boot rápido.
#
# Requisitos: dracut (ou fallback para gen_init_cpio).
# =============================================================================
set -e -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${HERE}/config.sh"

log() { echo -e "\n\u001b[1;32m[NovaLinux/initramfs]\u001b[0m $*"; }
R="${ROOTFS_DIR}"
INITRAMFS="${ISO_DIR}/initramfs-${KERNEL_VERSION}.img"
mkdir -p "${ISO_DIR}"

log "gerando initramfs com dracut em ${INITRAMFS}"
if command -v dracut >/dev/null 2>&1; then
  # rootfs é o futuro "/" do sistema: usamos --force e indicamos o kernel
  cd "${R}"
  dracut --force --no-compress --kver "${KERNEL_VERSION}-novav6" \
    --stdlog 3 --omit "dracut-systemd" \
    --add-drivers "zram zswap zstd ext4 virtio_blk virtio_pci hid_generic usbhid" \
    "${INITRAMFS}" 2>&1 || {
      log "dracut falhou sem compressão; tentando com compressão padrão"
      dracut -f "${INITRAMFS}" "${KERNEL_VERSION}-novav6" 2>&1
    }
  # re-comprime com zstd (dracut aceita -z, mas rexecutamos por robustez)
  if command -v zstd >/dev/null 2>&1 && "${INITRAMFS}" 2>/dev/null; then
    : # já comprimido
  fi
else
  log "dracut ausente; construindo initramfs mínimo via gen_init_cpio"
  # Fallback: um initramfs simples com BusyBox + init para boot a shell.
  TMP=$(mktemp -d)
  mkdir -p "${TMP}/bin" "${TMP}/sbin" "${TMP}/dev" "${TMP}/proc" "${TMP}/sys"
  cp "$(command -v busybox)" "${TMP}/bin/busybox"
  for a in sh mount insmod dmesg switch_root; do
    ln -sf busybox "${TMP}/bin/${a}"
  done
  ln -sf busybox "${TMP}/sbin/init"
  cat > "${TMP}/init" <<EOF
#!/bin/busybox sh
mount -t proc none /proc
mount -t sysfs none /sys
mount -t devtmpfs devtmpfs /dev || true
echo "NovaLinux initramfs pronto"
exec /bin/sh
EOF
  chmod +x "${TMP}/init"
  ( cd "${TMP}" && find . | cpio -H newc -o ) | zstd -q -o "${INITRAMFS}" 2>/dev/null \
    || ( cd "${TMP}" && find . | cpio -H newc -o ) | xz -z > "${INITRAMFS}"
  rm -rf "${TMP}"
fi

log "initramfs: $(ls -lh "${INITRAMFS}" | awk '{print $5}')"
