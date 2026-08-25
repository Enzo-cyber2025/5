#!/usr/bin/env bash
# =============================================================================
# config.sh — configuração central do projeto NovaLinux
#
# Este arquivo define TODOS os parâmetros usados pelo pipeline de build.
# É o ÚNICO lugar onde versões, flags e caminhos precisam ser ajustados.
#
# Execute a partir de qualquer diretório; ele localiza a raiz do projeto e
# exporta as variáveis para os demais scripts.
# =============================================================================
set -e -u

# --- Identificação da distribuição ------------------------------------------
DISTRO_NAME="NovaLinux"
DISTRO_ID="navelinux"
DISTRO_VERSION="1.0"
DISTRO_CODENAME="nova"
RELEASE="1"
HOSTNAME="novastation"
USER_NAME="nova"
USER_PASS="nova123"

# --- Arquitetura / microarquitetura alvo ------------------------------------
# Intel Pentium N5030 = 4x Goldmont Plus (x86_64)
TARGET_ARCH="x86_64"
MCARCH="goldmont-plus"            # -march / -mtune / -m<optimize>

# Flags de otimização aplicadas à toolchain e a todos os pacotes.
# **Nota de honestidade sobre -flto=auto**: para aplicações com LTO pode ser
# necessário usar -flto (autodetect via GCC) ou -flto=auto. Mantemos o valor
# pedido, mas build_rootfs.sh aplica um fallback se o compilador reclamar.
CFLAGS_COMMON="-O3 -pipe -flto=auto -march=${MCARCH} -mtune=${MCARCH}"
CFLAGS="${CFLAGS_COMMON} -fno-semantic-interposition -fstack-protector-strong -D_FORTIFY_SOURCE=2"
CXXFLAGS="${CFLAGS}"
LDFLAGS="-Wl,-s"

# --- Diretórios do projeto (definidos ANTES de serem usados) ---------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${PROJECT_DIR}/build/work"
SRC_DIR="${BUILD_DIR}/src"
ROOTFS_DIR="${BUILD_DIR}/rootfs"
SYSROOT_DIR="${BUILD_DIR}/sysroot"
KERNEL_BUILD_DIR="${BUILD_DIR}/kernel-build"
ISO_DIR="${BUILD_DIR}/iso"
OUT_DIR="${PROJECT_DIR}/dist"

# --- Kernel -----------------------------------------------------------------
KERNEL_MAJOR="6.6"
KERNEL_VERSION="6.6.60"               # última 6.6.x LTS no momento da escrita
KERNEL_URL="https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-${KERNEL_VERSION}.tar.xz"
# Espelho do projeto no GitHub (caso kernel.org esteja inacessível no builder):
KERNEL_URL_ALT="https://github.com/torvalds/linux.git"
KERNEL_SRC_DIR="${SRC_DIR}/linux-${KERNEL_VERSION}"
# PATCHES Goldmont Plus (aplicados após extrair): ver kernel/patches/
KERNEL_PATCH_DIR="${PROJECT_DIR}/kernel/patches"
# CFLAGS do kernel (KCFLAGS) — kernel não usa -march diretamente em CFLAGS; os
# otimizações de CPU entram via CONFIG_ARCH + KCFLAGS.
KCFLAGS="-O3 -pipe -fno-semantic-interposition -march=${MCARCH} -mtune=${MCARCH}"

# --- Toolchain (bootstrap) --------------------------------------------------
# Alvo: GCC 13.2, glibc 2.38, binutils 2.41 — todas "-march=goldmont-plus"
GCC_VERSION="13.2.0"
GLIBC_VERSION="2.38"
BINUTILS_VERSION="2.41"
# Para manter o sistema compilável, o bootstrap é feito em estágios:
#   stage0 = compilador do host (já presente) gera binutils+glibc+gcc alvo
#   stage1 = toolchain alvo dominante recompila a si mesma (double-bootstrap)
BOOTSTRAP_DIR="${SRC_DIR}/bootstrap"

# --- Init system ------------------------------------------------------------
INIT_SYSTEM="openrc"                  # PROIBIDO systemd
OPENRC_VERSION="0.45.2"

# --- Fim das definições de diretórios --------------------------------------

# --- ISO / boot -------------------------------------------------------------
GRUB_VERSION="2.12"
GRUB_THEME="novatheme"
XORRISO="${XORRISO:-/usr/bin/xorriso}"
QEMU="${QEMU:-/usr/bin/qemu-system-x86_64}"
ISO_NAME="${DISTRO_ID}-${DISTRO_VERSION}-${TARGET_ARCH}-${KERNEL_VERSION}.iso"
ISO_PATH="${OUT_DIR}/${ISO_NAME}"
SHA_PATH="${ISO_PATH}.sha256"
KERNEL_PARAMS="quiet loglevel=3 mitigations=off intel_idle.max_cstate=4"

# --- Otimizações de runtime (conferidas no initramfs / sysctl) --------------
SWAPPINESS=10
VFS_CACHE_PRESSURE=50
FS_OPTIONS="noatime,commit=120,data=ordered"

# --- Pacotes de aplicativos incluídos (compilados com otimizações N5030) ----
# Veja novapkg/specs/ para os manifestos .nvpkg de cada um.
APPS_MANDATORY="firefox-esr libreoffice-writer libreoffice-calc libreoffice-impress \
gimp vlc htop neofetch git curl wget nano vim openssh networkmanager \
pulseaudio pipewire cups samba earlyoom preload zstd"
# Linguagens / locale suportados
LOCALE_DEFAULT="en_US.UTF-8"
LOCALES_EXTRA="pt_BR.UTF-8 es_ES.UTF-8 fr_FR.UTF-8"

# Parâmetros de criação do usuário e sudo
SUDO_PASSWORDLESS="yes"                 # sudo sem senha para ${USER_NAME}

# --- Utilidades -------------------------------------------------------------
export DISTRO_NAME DISTRO_ID DISTRO_VERSION DISTRO_CODENAME RELEASE
export HOSTNAME USER_NAME USER_PASS TARGET_ARCH MCARCH
export CFLAGS_COMMON CFLAGS CXXFLAGS LDFLAGS
export KERNEL_MAJOR KERNEL_VERSION KERNEL_URL KERNEL_URL_ALT KERNEL_SRC_DIR
export KERNEL_PATCH_DIR KCFLAGS
export GCC_VERSION GLIBC_VERSION BINUTILS_VERSION BOOTSTRAP_DIR
export INIT_SYSTEM OPENRC_VERSION
export PROJECT_DIR BUILD_DIR ROOTFS_DIR SYSROOT_DIR ISO_DIR OUT_DIR
export KERNEL_BUILD_DIR GRUB_VERSION GRUB_THEME XORRISO QEMU
export ISO_NAME ISO_PATH SHA_PATH KERNEL_PARAMS
export SWAPPINESS VFS_CACHE_PRESSURE FS_OPTIONS
export APPS_MANDATORY LOCALE_DEFAULT LOCALES_EXTRA SUDO_PASSWORDLESS

# Mensagem de resumo
echo "[NovaLinux] config carregada: kernel ${KERNEL_VERSION}, ${MCARCH}, init=${INIT_SYSTEM}"
echo "[NovaLinux] projeto: ${PROJECT_DIR}"
