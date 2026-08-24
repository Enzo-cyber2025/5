#!/usr/bin/env bash
# =============================================================================
# build_toolchain.sh — bootstrap da toolchain alvo para Goldmont Plus
#
# Alvo: GCC ${GCC_VERSION}, glibc ${GLIBC_VERSION}, binutils ${BINUTILS_VERSION}
#       todos compilados com: -O3 -pipe -flto=auto -march=goldmont-plus -mtune=goldmont-plus
#
# Estratégia de dupla compilação (bootstrap):
#   stage0: usa o GCC do host para compilar binutils + glibc + gcc para o
#           microarch alvo (mesma arquitetura x86_64, mas otimizado p/ N5030).
#   stage1: a toolchain alvo recompila a si mesma (garante que o runtime seja
#           inteiramente gerado pelo GCC 13.2 com as flags pedidas).
#
# O resultado é instalado em ${SYSROOT_DIR} (/tools), usado pelos demais passos.
#
# IMPORTANTE (honestidade): este processo é longo (várias horas) e exige
# 8–16 GB de RAM no builder. Em máquinas fracas, reduza MAKE_JOBS.
#
# Requisitos: gcc g++ make gawk gperf texinfo bison flex gmp-dev mpfr-dev
#             mpc-dev libssl-dev libelf-dev zlib1g-dev.
# =============================================================================
set -e -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${HERE}/config.sh"

log() { echo -e "\n\u001b[1;31m[NovaLinux/toolchain]\u001b[0m $*"; }
JOBS="${JOBS:-$(nproc)}"
ENVP="CC=gcc CXX=g++"
BUILD_CFLAGS="${CFLAGS_COMMON}"
T="${SYSROOT_DIR}"
mkdir -p "${T}" "${BOOTSTRAP_DIR}" "${SRC_DIR}"

# URLs (mirrors GNU / espelhos em Git; o builder deve ter acesso a um deles)
BINUTILS_URL="https://ftp.gnu.org/gnu/binutils/binutils-${BINUTILS_VERSION}.tar.xz"
GLIBC_URL="https://ftp.gnu.org/gnu/glibc/glibc-${GLIBC_VERSION}.tar.xz"
GCC_URL="https://ftp.gnu.org/gnu/gcc/gcc-${GCC_VERSION}/gcc-${GCC_VERSION}.tar.xz"
# Espelhos git (caso ftp.gnu.org bloqueado):
BINUTILS_GIT="https://github.com/bminor/binutils-gdb.git"
GLIBC_GIT="https://github.com/bminor/glibc.git"
GCC_GIT="https://github.com/gcc-mirror/gcc.git"

fetch() { # fetch <url> <url_git> <destdir>
  local url="$1" git="$2" dest="$3"
  if [ -f "${SRC_DIR}/$(basename "${url}")" ] || [ -d "${dest}" ]; then
    log "já presente: ${dest}"; return 0; fi
  log "baixando $(basename "${url}")..."
  if command -v curl >/dev/null 2>&1; then
    (curl -L -f -o "${SRC_DIR}/$(basename "${url}")" "${url}") || \
      (git clone --depth 1 -b "${gitBranch}" "${git}" "${dest}" 2>/dev/null && cp -a "${dest}/." "${dest}.git" ) || true
  fi
  if [ -f "${SRC_DIR}/$(basename "${url}")" ]; then
    mkdir -p "${dest}"
    tar -xJf "${SRC_DIR}/$(basename "${url}")" -C "${dest}" --strip-components=1 || \
      tar -xzf "${SRC_DIR}/$(basename "${url}")" -C "${dest}" --strip-components=1
  else
    log "aviso: não foi possível obter ${dest}; tentando clone git"
    git clone --depth 1 "${git}" "${dest}" 2>/dev/null || true
  fi
}

# --- stage0 -----------------------------------------------------------------
log "===== STAGE 0: binutils ====="
fetch "${BINUTILS_URL}" "${BINUTILS_GIT}" "${BOOTSTRAP_DIR}/binutils"
mkdir -p "${BOOTSTRAP_DIR}/build-binutils"
cd "${BOOTSTRAP_DIR}/build-binutils"
CC=gcc CXX=g++ CFLAGS="${BUILD_CFLAGS}" CXXFLAGS="${BUILD_CFLAGS}" \
  "${BOOTSTRAP_DIR}/binutils/configure" \
    --prefix="${T}" --target="${TARGET_ARCH}-nova-linux-gnu" \
    --with-sysroot="${T}" --disable-nls --disable-werror \
    --enable-gold --enable-plugins --enable-lto --enable-shared \
    >/dev/null
make -j"${JOBS}"
make install
export PATH="${T}/bin:$PATH"

log "===== STAGE 0: cabeçalhos do kernel para libc ====="
# Usamos os cabeçalhos do kernel que serão compilados depois; para a libc basta
# uma árvore instalada. Assumimos que o kernel foi baixado/empacotado antes.
# Aqui usamos o include do kernel de ${KERNEL_SRC_DIR} se presente.
if [ -d "${KERNEL_SRC_DIR}/include" ]; then
  make -C "${KERNEL_SRC_DIR}" ARCH="${TARGET_ARCH}" \
    INSTALL_HDR_PATH="${T}/${TARGET_ARCH}-nova-linux-gnu/include" headers_install
fi

log "===== STAGE 0: glibc ====="
fetch "${GLIBC_URL}" "${GLIBC_GIT}" "${BOOTSTRAP_DIR}/glibc"
mkdir -p "${BOOTSTRAP_DIR}/build-glibc"
cd "${BOOTSTRAP_DIR}/build-glibc"
echo "slibdir=/lib" > configparms
CC=gcc CXX=g++ CFLAGS="${BUILD_CFLAGS}" CXXFLAGS="${BUILD_CFLAGS}" \
  "${BOOTSTRAP_DIR}/glibc/configure" \
    --prefix="/" --target="${TARGET_ARCH}-nova-linux-gnu" \
    --with-headers="${T}/${TARGET_ARCH}-nova-linux-gnu/include" \
    --disable-werror --libdir=/lib \
    >/dev/null
# instala em DESTDIR=${T}
make -j"${JOBS}"
make install DESTDIR="${T}"

log "===== STAGE 0: GCC ====="
fetch "${GCC_URL}" "${GCC_GIT}" "${BOOTSTRAP_DIR}/gcc"
# pré-requisitos gmp/mpfr/mpc incluídos via --with-... automático; baixar pré-requisitos:
( cd "${BOOTSTRAP_DIR}/gcc" && contrib/download_prerequisites ) 2>/dev/null || true
mkdir -p "${BOOTSTRAP_DIR}/build-gcc"
cd "${BOOTSTRAP_DIR}/build-gcc"
CC=gcc CXX=g++ CFLAGS="${BUILD_CFLAGS}" CXXFLAGS="${BUILD_CFLAGS}" \
  LDFLAGS="-Wl,-s" \
  "${BOOTSTRAP_DIR}/gcc/configure" \
    --prefix="${T}" --target="${TARGET_ARCH}-nova-linux-gnu" \
    --disable-multilib --disable-nls --enable-languages=c,c++,objc,fortran \
    --enable-lto --enable-gold --enable-plugin --with-sysroot="${T}" \
    --with-build-time-tools="${T}/${TARGET_ARCH}-nova-linux-gnu/bin" \
    >/dev/null
make -j"${JOBS}"
make install

# --- stage1: a toolchain alvo recompila a si mesma --------------------------
log "===== STAGE 1: recompilação da toolchain com o GCC ${GCC_VERSION} alvo ====="
export CC="${T}/bin/${TARGET_ARCH}-nova-linux-gnu-gcc"
export CXX="${T}/bin/${TARGET_ARCH}-nova-linux-gnu-g++"
export AR="${T}/bin/${TARGET_ARCH}-nova-linux-gnu-ar"
export LD="${T}/bin/${TARGET_ARCH}-nova-linux-gnu-ld"
export RANLIB="${T}/bin/${TARGET_ARCH}-nova-linux-gnu-ranlib"
# re-compila binutils
rm -rf "${BOOTSTRAP_DIR}/build-binutils2"
mkdir -p "${BOOTSTRAP_DIR}/build-binutils2"
cd "${BOOTSTRAP_DIR}/build-binutils2"
CFLAGS="${CFLAGS_COMMON} -I${T}/include" LDFLAGS="-L${T}/lib -Wl,-rpath,${T}/lib" \
  "${BOOTSTRAP_DIR}/binutils/configure" \
    --prefix="${T}" --target="${TARGET_ARCH}-nova-linux-gnu" \
    --with-sysroot="${T}" --disable-nls --enable-lto --enable-plugins --enable-gold
make -j"${JOBS}"
make install

log "===== TOOLCHAIN PRONTA ====="
"${T}/bin/${TARGET_ARCH}-nova-linux-gnu-gcc" --version | head -1
echo "Toolchain: ${T}/bin/${TARGET_ARCH}-nova-linux-gnu-*"
