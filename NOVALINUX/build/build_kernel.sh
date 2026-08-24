#!/usr/bin/env bash
# =============================================================================
# build_kernel.sh — compila o kernel Linux 6.6.x LTS otimizado para Goldmont Plus
#
# Etapas:
#   1. Baixa o tarball do kernel (kernel.org ou espelho GitHub).
#   2. Aplica os patches deste projeto em kernel/patches.
#   3. Configura a partir de x86_64_defconfig ajustado para N5030.
#   4. Compila bzImage, módulos e DTBs com KCFLAGS otimizados.
#   5. Instala o kernel dentro de ${ROOTFS_DIR}.
#
# Requisitos no builder (Debian): gcc make bc flex bison libssl-dev libelf-dev
#   bzip2 xz-utils. Ajuste com: apt install --yes build-essential bc flex bison \
#   libssl-dev libelf-dev bzip2 xz-utils
# =============================================================================
set -e -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${HERE}/config.sh"

log() { echo -e "\n\u001b[1;34m[NovaLinux/kernel]\u001b[0m $*"; }

mkdir -p "${SRC_DIR}" "${KERNEL_BUILD_DIR}"

# --- 1. obter o código-fonte ------------------------------------------------
if [ ! -d "${KERNEL_SRC_DIR}/.git" ] && [ ! -f "${KERNEL_SRC_DIR}/Makefile" ]; then
  log "baixando kernel ${KERNEL_VERSION}..."
  if command -v curl >/dev/null 2>&1; then
    curl -L -o "${SRC_DIR}/linux.tar.xz" "${KERNEL_URL}" \
      || curl -L -o "${SRC_DIR}/linux.tar.xz" "${KERNEL_URL_ALT}/archive/refs/tags/v${KERNEL_VERSION}.tar.gz"
  else
    wget -O "${SRC_DIR}/linux.tar.xz" "${KERNEL_URL}"
  fi
  log "extraindo..."
  mkdir -p "${SRC_DIR}"
  tar -xJf "${SRC_DIR}/linux.tar.xz" -C "${SRC_DIR}" 2>/dev/null \
    || tar -xzf "${SRC_DIR}/linux.tar.xz" -C "${SRC_DIR}"
  # renomeia caso o diretório não bata com o nome esperado
  if [ ! -d "${KERNEL_SRC_DIR}" ]; then
    actual="$(find "${SRC_DIR}" -maxdepth 1 -type d -name 'linux-*' | head -1)"
    if [ -n "${actual}" ] && [ "${actual}" != "${KERNEL_SRC_DIR}" ]; then
      mv "${actual}" "${KERNEL_SRC_DIR}"
    fi
  fi
else
  log "código-fonte já presente em ${KERNEL_SRC_DIR}"
fi

cd "${KERNEL_SRC_DIR}"
make ARCH="${TARGET_ARCH}" mrproper 2>/dev/null || true

# --- 2. aplicar patches Goldmont Plus --------------------------------------
if [ -d "${KERNEL_PATCH_DIR}" ]; then
  for patch in "${KERNEL_PATCH_DIR}"/*.patch; do
    [ -e "${patch}" ] || continue
    log "aplicando patch: $(basename "${patch}")"
    patch -p1 < "${patch}"
  done
fi

# --- 3. configuração --------------------------------------------------------
log "configurando para ${MCARCH} (x86_64_defconfig + ajustes N5030)"
make ARCH="${TARGET_ARCH}" x86_64_defconfig

# Ajustes de configuração via scripts/config (ferramenta embutida no kernel)
CFG="${KERNEL_SRC_DIR}/scripts/config"
${CFG} --enable CONFIG_64BIT
${CFG} --set-str CONFIG_LOCALVERSION "-novav6"
${CFG} --set-str CONFIG_DEFAULT_HOSTNAME "novastation"

# --- Firmware/drivers de vídeo e input para desktop ---
${CFG} --enable CONFIG_DRM
${CFG} --enable CONFIG_DRM_SIMPLEDRM
${CFG} --enable CONFIG_FB
${CFG} --enable CONFIG_FRAMEBUFFER_CONSOLE
${CFG} --enable CONFIG_FB_EFI
${CFG} --enable CONFIG_INPUT
${CFG} --enable CONFIG_INPUT_EVDEV
${CFG} --enable CONFIG_HID
${CFG} --enable CONFIG_HID_GENERIC
${CFG} --enable CONFIG_USB_HID
${CFG} --enable CONFIG_SOUND
${CFG} --enable CONFIG_SND
${CFG} --enable CONFIG_SND_HDA_INTEL

# --- Sistemas de arquivos e swap comprimido com zstd ---
${CFG} --enable CONFIG_EXT4_FS
${CFG} --enable CONFIG_EXT4_FS_POSIX_ACL
${CFG} --enable CONFIG_EXT4_FS_SECURITY
${CFG} --enable CONFIG_ZSWAP
${CFG} --enable CONFIG_ZRAM
${CFG} --enable CONFIG_ZRAM_DEF_COMP_ZSTD
${CFG} --set-str CONFIG_ZRAM_DEF_COMP "zstd"
${CFG} --enable CONFIG_ZSTD_COMPRESS
${CFG} --enable CONFIG_ZSTD_DECOMPRESS

# --- Rede / USB / storage (para NetworkManager, libinput, CUPS/Samba) ---
${CFG} --enable CONFIG_NET
${CFG} --enable CONFIG_WIRELESS
${CFG} --enable CONFIG_CFG80211
${CFG} --enable CONFIG_MAC80211
${CFG} --enable CONFIG_NETDEVICES
${CFG} --enable CONFIG_USB
${CFG} --enable CONFIG_USB_STORAGE
${CFG} --enable CONFIG_MMC
${CFG} --enable CONFIG_SATA_AHCI

# --- Presets de desempenho / baixa latência ---
${CFG} --enable CONFIG_HZ_1000
${CFG} --set-str CONFIG_HZ "1000"
${CFG} --enable CONFIG_SCHED_AUTOGROUP
${CFG} --enable CONFIG_CGROUP_SCHED
${CFG} --enable CONFIG_CPU_FREQ
${CFG} --enable CONFIG_CPU_FREQ_GOV_SCHEDUTIL
${CFG} --enable CONFIG_CPU_FREQ_DEFAULT_GOV_SCHEDUTIL
${CFG} --enable CONFIG_INTEL_IDLE

# --- Compilação otimizada (menos features para boot rápido, sem perder uso) ---
${CFG} --enable CONFIG_KALLSYMS
${CFG} --enable CONFIG_IKCONFIG
${CFG} --enable CONFIG_MODULES
${CFG} --enable CONFIG_MODULE_UNLOAD
${CFG} --disable CONFIG_DEBUG_KERNEL
${CFG} --disable CONFIG_DEBUG_INFO
# EFI para boot UEFI
${CFG} --enable CONFIG_EFI
${CFG} --enable CONFIG_EFI_STUB
${CFG} --enable CONFIG_BLK_DEV_INITRD
${CFG} --enable CONFIG_RD_ZSTD
${CFG} --enable CONFIG_RD_XZ

# Regenera o .config após os ajustes
make ARCH="${TARGET_ARCH}" olddefconfig

# --- 4. compilar ------------------------------------------------------------
log "compilando o kernel com KCFLAGS=${KCFLAGS}"
JOBS="${JOBS:-$(nproc)}"
export KCFLAGS="${KCFLAGS}"
make ARCH="${TARGET_ARCH}" -j"${JOBS}" bzImage
make ARCH="${TARGET_ARCH}" -j"${JOBS}" modules
make ARCH="${TARGET_ARCH}" -j"${JOBS}" dtbs 2>/dev/null || true

# --- 5. instalar no rootfs --------------------------------------------------
log "instalando kernel e módulos em ${ROOTFS_DIR}"
for dir in "${ROOTFS_DIR}/boot" "${ROOTFS_DIR}/lib/modules/${KERNEL_VERSION}-novav6"; do
  mkdir -p "${dir}"
done
cp "arch/${TARGET_ARCH}/boot/bzImage" "${ROOTFS_DIR}/boot/bzImage"
cp "System.map" "${ROOTFS_DIR}/boot/System.map-${KERNEL_VERSION}"
cp ".config" "${ROOTFS_DIR}/boot/config-${KERNEL_VERSION}"
make ARCH="${TARGET_ARCH}" -j"${JOBS}" modules_install INSTALL_MOD_PATH="${ROOTFS_DIR}"

log "kernel pronto: ${ROOTFS_DIR}/boot/bzImage"
ls -lh "${ROOTFS_DIR}/boot/bzImage"
