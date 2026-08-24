#!/usr/bin/env bash
# =============================================================================
# build_iso.sh — gera o ISO híbrido (UEFI + BIOS legado) e o SHA256
#
# Usa GRUB 2.12 (grub-mkrescue) que embute tanto a imagem BIOS quanto a EFI,
# e o xorriso para produzir uma imagem gravável/arrancável em El Torito.
# O resultado é um ISO híbrido (PMP + El Torito) bootável via BIOS e UEFI.
# Por fim calcula o SHA256 do arquivo.
#
# Requisitos: grub-pc-bin grub-efi-amd64-bin grub-common mtools xorriso
#   dracut. Ajuste: apt install --yes grub-pc-bin grub-efi-amd64-bin \
#   grub-common mtools xorriso dracut
# =============================================================================
set -e -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${HERE}/config.sh"

log() { echo -e "\n\u001b[1;36m[NovaLinux/iso]\u001b[0m $*"; }
R="${ROOTFS_DIR}"
ISODIR="${ISO_DIR}"
mkdir -p "${ISODIR}/boot/grub" "${ISODIR}/boot/grub/themes/${GRUB_THEME}" "${OUT_DIR}"

# --- kernel e initramfs ----------------------------------------------------
log "copiando kernel e initramfs para a árvore de ISO"
cp "${R}/boot/bzImage" "${ISODIR}/boot/vmlinuz-${KERNEL_VERSION}"
cp "${R}/boot/System.map-${KERNEL_VERSION}" "${ISODIR}/boot/System.map-${KERNEL_VERSION}"
cp "${R}/boot/config-${KERNEL_VERSION}" "${ISODIR}/boot/config-${KERNEL_VERSION}" || true
# initramfs (gerado por dracut)
"${HERE}/make_initramfs.sh"

# --- config do GRUB ---------------------------------------------------------
log "escrevendo ${ISODIR}/boot/grub/grub.cfg"
cat > "${ISODIR}/boot/grub/grub.cfg" <<EOF
# NovaLinux GRUB 2.12
set default=0
set timeout=3
set gfxmode=auto
set gfxpayload=keep
insmod all_video
insmod gfxterm
insmod gfxmenu
insmod png
insmod video_bochs
insmod video_cirrus
terminal_output gfxterm
loadfont unicode

menuentry "NovaLinux ${DISTRO_VERSION} (N5030)" {
    linux /boot/vmlinuz-${KERNEL_VERSION} \
        root=UUID=@@@@root@@@@ ${KERNEL_PARAMS}
    initrd /boot/initramfs-${KERNEL_VERSION}.img
}

menuentry "NovaLinux — modo de recuperação" {
    linux /boot/vmlinuz-${KERNEL_VERSION} \
        root=UUID=@@@@root@@@@ single loglevel=3
    initrd /boot/initramfs-${KERNEL_VERSION}.img
}

menuentry "Boot do disco rígido" {
    insmod part_gpt
    insmod part_msdos
    insmod chain
    set root=(hd0)
    chainloader +1
}
EOF

# --- tema gráfico customizado ----------------------------------------------
log "instalando tema GRUB '${GRUB_THEME}'"
cp -r "${PROJECT_DIR}/grub/theme/." "${ISODIR}/boot/grub/themes/${GRUB_THEME}/"
cp "${PROJECT_DIR}/grub/theme.txt" "${ISODIR}/boot/grub/themes/${GRUB_THEME}/theme.txt" 2>/dev/null || true
# seta o tema no grub.cfg (se definido)
if [ -f "${PROJECT_DIR}/grub/theme.txt" ]; then
  sed -i "/terminal_output gfxterm/a set theme=/boot/grub/themes/${GRUB_THEME}/theme.txt" \
    "${ISODIR}/boot/grub/grub.cfg"
fi

# --- arquivos do rootfs (dados de runtime) ---------------------------------
log "mesclando rootfs com os dados do ISO (fora de /boot)"
# Para um live system simples, copiamos a raiz do rootfs para o ISO,
# e o initramfs fará pivot_root para o ISO (loop) ou usará o squashfs.
# Nesta primeira versão usamos o rootfs inline:
cp -a "${R}/." "${ISODIR}/" 2>/dev/null || true
# Remove conflitos do boot (o rootfs não deve sobrescrever o /boot/grub)
rm -rf "${ISODIR}/boot/grub" 2>/dev/null
cp "${PROJECT_DIR}/grub/grub.cfg" "${ISODIR}/boot/grub/grub.cfg"

# --- gerar ISO híbrido com xorriso/grub-mkrescue ----------------------------
log "gerando ISO híbrido (UEFI + BIOS legado) — pode levar alguns minutos"
if command -v grub-mkrescue >/dev/null 2>&1 && command -v "${XORRISO}" >/dev/null 2>&1; then
  grub-mkrescue --modules="ata iso9660 part_gpt part_msdos biosdisk all_video \
       gfxterm gfxmenu png linux normal search search_fs_uuid configfile" \
       -o "${ISO_PATH}" "${ISODIR}"
else
  log "grub-mkrescue/xorriso ausente; tentando usar xorriso diretamente"
  "${XORRISO}" -as mkisofs \
    -b boot/grub/i386-pc/eltorito.img \
    -no-emul-boot -boot-load-size 4 -boot-info-table \
    -eltorito-alt-boot -e boot/grub/efi.img -no-emul-boot \
    -V "${DISTRO_ID:-NOVALINUX}" -o "${ISO_PATH}" "${ISODIR}" 2>&1 || \
    { echo "ERRO: xorriso/grub-mkrescue não disponível"; exit 1; }
fi

log "aplicando híbrido (PMP) ao ISO"
if command -v "${XORRISO}" >/dev/null 2>&1; then
  "${XORRISO}" -boot_image any sync 2>/dev/null || true
fi

# --- SHA256 ----------------------------------------------------------------
log "calculando SHA256"
sha256sum "${ISO_PATH}" | tee "${SHA_PATH}"
sync
log "ISO pronto: ${ISO_PATH}"
ls -lh "${ISO_PATH}" "${SHA_PATH}"
