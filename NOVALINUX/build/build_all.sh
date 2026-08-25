#!/usr/bin/env bash
# =============================================================================
# build_all.sh — constrói todo o NovaLinux de forma automatizada e sem
# interação manual.
#
#   Etapas:
#     [1] bootstrap da toolchain  (GCC 13.2 / glibc 2.38 / binutils 2.41, -march=goldmont-plus)
#     [2] kernel Linux 6.6.x LTS   (com patches Goldmont Plus)
#     [3] rootfs com OpenRC        (+ usuário nova, locales, sudo, otimizações)
#     [4] initramfs com dracut
#     [5] ISO híbrido UEFI+BIOS    (GRUB 2.12 + xorriso) + SHA256
#     [6] verificação em QEMU      (boot, RAM idle<800MB, VLC 1080p 30fps, etc.)
#
#   Uso:
#     ./build_all.sh                 # tudo
#     ./build_all.sh --skip verify   # sem o passo de verificação
#     ./build_all.sh --only kernel   # só o kernel
#     ./build_all.sh --yes           # sem pausas
#
# Requisitos no builder (Debian amd64):
#     apt install --yes build-essential bc flex bison libssl-dev libelf-dev \
#         xorriso grub-pc-bin grub-efi-amd64-bin grub-common mtools dracut \
#         qemu-system-x86 qemu-utils debootstrap busybox-static openrc \
#         zstd xz-utils curl wget
# =============================================================================
set -e -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${HERE}/config.sh"

log() { echo -e "\n\u001b[1;33m[NovaLinux]\u001b[0m $*"; }

SKIP_VERIFY=0
SKIP_TOOLCHAIN=0
ONLY=""
YES=0
for arg in "$@"; do
  case "${arg}" in
    --skip|--skip-verify) SKIP_VERIFY=1 ;;
    --skip-toolchain)     SKIP_TOOLCHAIN=1 ;;
    --only)               ONLY="next" ;;
    --yes)                YES=1 ;;
    *)                    if [ "${ONLY}" = "next" ]; then ONLY="${arg}"; fi ;;
  esac
done

mkdir -p "${BUILD_DIR}" "${OUT_DIR}"

run() { # run <nome> <script>
  local name="$1"; local script="$2"
  if [ -n "${ONLY}" ] && [ "${ONLY}" != "${name}" ]; then
    log "pulando '${name}' (filtro --only ${ONLY})"; return 0; fi
  log "== etapa [${name}] usando ${script} =="
  "${HERE}/${script}"
}

# --- [1] toolchain ----------------------------------------------------------
if [ "${SKIP_TOOLCHAIN}" = "1" ]; then
  log "pulando bootstrap da toolchain (--skip-toolchain)"
else
  run "toolchain" "build_toolchain.sh"
fi

# --- [2] kernel -------------------------------------------------------------
run "kernel" "build_kernel.sh"

# --- [3] rootfs -------------------------------------------------------------
run "rootfs" "build_rootfs.sh"

# --- [4/5] initramfs + ISO --------------------------------------------------
run "iso" "build_iso.sh"

# --- [6] verificação --------------------------------------------------------
if [ "${SKIP_VERIFY}" = "1" ]; then
  log "pulando verificação QEMU (--skip-verify)"
else
  run "verify" "verify.sh"
fi

log "===== BUILD CONCLUÍDO ====="
log "ISO : ${ISO_PATH}"
log "SHA : $(cat "${SHA_PATH}")"
