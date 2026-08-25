#!/usr/bin/env bash
# =============================================================================
# make_novatest_initrd.sh — monta o initramfs de teste (guest_novatest.sh)
#
# Gerado para ser usado por verify.sh. Inclui o script de teste como /init e
# um BusyBox estático para shell/ferramentas. Requisito: busybox-static e zstd.
# =============================================================================
set -e -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${HERE}/config.sh"

TMP=$(mktemp -d)
trap 'rm -rf "${TMP}"' EXIT
OUT="${BUILD_DIR}/guest-novatest-initrd.gz"
mkdir -p "${TMP}/bin" "${TMP}/sbin" "${TMP}/dev" "${TMP}/proc" "${TMP}/sys" "${TMP}/tmp" "${TMP}/etc" "${TMP}/usr/bin" "${TMP}/var"

# BusyBox estático + ligações simbólicas de ferramentas comuns
BB=$(command -v busybox || echo /bin/busybox)
cp "${BB}" "${TMP}/bin/busybox"
for a in sh mount umount sleep echo cat grep ls ps kill ip awk sed find tar xz head tail; do
  ln -sf busybox "${TMP}/bin/${a}" 2>/dev/null || true
done
ln -sf busybox "${TMP}/sbin/init" 2>/dev/null || true

# integra também os binários da NovaUI se estiverem construídos (para o teste)
for b in nova-panel nova-launcher nova-terminal nova-files nova-config; do
  if [ -x "${PROJECT_DIR}/novaui/${b}" ]; then
    cp "${PROJECT_DIR}/novaui/${b}" "${TMP}/usr/bin/${b}"
  fi
done
# integra o nova-pkg se existir
if [ -x "${PROJECT_DIR}/novapkg/novapkg" ]; then
  cp "${PROJECT_DIR}/novapkg/novapkg" "${TMP}/usr/bin/novapkg"
  ln -sf novapkg "${TMP}/usr/bin/nova-pkg"
fi

# script de teste como /init
cp "${PROJECT_DIR}/tests/guest_novatest.sh" "${TMP}/init"
chmod +x "${TMP}/init"

# cria o archive cpio comprimido (gzip; zstd se disponível)
mkdir -p "${BUILD_DIR}"
( cd "${TMP}" && find . | cpio -H newc -o ) | gzip -9 > "${OUT}"
echo "ok: ${OUT}"
ls -lh "${OUT}"
