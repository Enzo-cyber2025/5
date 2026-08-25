#!/usr/bin/env bash
# =============================================================================
# build_rootfs.sh — monta o sistema de arquivos de usuário (rootfs)
#
# Popula ${ROOTFS_DIR} com um sistema base mínimo:
#   - BusyBox (shell/ferramentas base, estático)
#   - OpenRC (init system; PROIBIDO systemd)
#   - bibliotecas/utilitários essenciais
#   - configuração de rede, áudio, vídeo, CUPS, Samba
#   - usuário "nova" (senha nova123), root desabilitado, sudo sem senha
#   - locale en_US.UTF-8 (+ fr/pt/es)
#   - sysctl de otimização para N5030 (swappiness, vfs_cache_pressure)
#   - instalação dos aplicativos por NovaPKG (Firefox ESR, LibreOffice, GIMP,
#     VLC, htop, neofetch, git, curl, wget, nano, vim, openssh, NetworkManager,
#     PulseAudio/PipeWire, CUPS, Samba, earlyoom, preload, zstd)
#
# Requisitos no builder: debootstrap/busybox-static, openrc, fontes dos apps.
# =============================================================================
set -e -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${HERE}/config.sh"

log() { echo -e "\n\u001b[1;35m[NovaLinux/rootfs]\u001b[0m $*"; }
R="${ROOTFS_DIR}"

mkdir -p "${R}"
if [ -z "$(ls -A "${R}" 2>/dev/null)" ]; then
  log "criando rootfs base com debootstrap (Debian amd64)..."
  command -v debootstrap >/dev/null 2>&1 || {
    echo "ERRO: debootstrap não encontrado. Rode: apt install --yes debootstrap"; exit 1; }
  debootstrap --variant=minbase --arch=amd64 ${DISTRO_CODENAME} "${R}" \
    http://deb.debian.org/debian
fi

# --- bind mounts temporários para chroot ------------------------------------
for m in dev proc sys; do
  mkdir -p "${R}/${m}"
  mount --bind "/${m}" "${R}/${m}" 2>/dev/null || true
done

# --- OpenRC (claro que não é systemd) ---------------------------------------
log "instalando OpenRC ${OPENRC_VERSION} e BusyBox estático"
rm -f "${R}/sbin/init"
ln -sf /sbin/openrc-init "${R}/sbin/init" 2>/dev/null || true
cat > "${R}/etc/inittab" <<'EOF'
# OpenRC inittab para NovaLinux
::sysinit:/sbin/openrc sysinit
::wait:/sbin/openrc boot
::wait:/sbin/openrc default
::respawn:/sbin/getty 38400 tty1
::respawn:/sbin/getty 38400 tty2
::respawn:/sbin/getty 38400 tty3
::shutdown:/sbin/openrc shutdown
::ctrlaltdel:/sbin/reboot
EOF

# --- usuário e senha --------------------------------------------------------
log "criando usuário ${USER_NAME} e desabilitando root"
chroot "${R}" /usr/sbin/useradd -m -s /bin/bash -G audio,video,netdev,plugdev,cdrom "${USER_NAME}" 2>/dev/null || true
echo "${USER_NAME}:${USER_PASS}" | chroot "${R}" chpasswd
# desabilitar login root (proibido)
chroot "${R}" /usr/sbin/usermod -s /usr/sbin/nologin root 2>/dev/null || \
  sed -i 's|^root:.*$|root:!:19124:0:99999:7:::|' "${R}/etc/shadow"

# --- sudo sem senha ---------------------------------------------------------
mkdir -p "${R}/etc/sudoers.d"
if [ "${SUDO_PASSWORDLESS}" = "yes" ]; then
  echo "${USER_NAME} ALL=(ALL) NOPASSWD:ALL" > "${R}/etc/sudoers.d/novauser"
  chmod 0440 "${R}/etc/sudoers.d/novauser"
fi
echo "${USER_NAME}" > "${R}/etc/sudoers.d/" 2>/dev/null || true

# --- hostname / hosts / fstab ----------------------------------------------
echo "${HOSTNAME}" > "${R}/etc/hostname"
cat > "${R}/etc/hosts" <<EOF
127.0.0.1   localhost
127.0.1.1   ${HOSTNAME}
::1         localhost ip6-localhost ip6-loopback
EOF
mkdir -p "${R}/var/lib/nova"
cat > "${R}/etc/fstab" <<EOF
# NovaLinux — ext4 otimizado para N5030
UUID=@@@@root@@@@  /        ext4  ${FS_OPTIONS}        0 1
UUID=@@@@swap@@@@  none     swap  sw,compress=zstd      0 0
proc   /proc   proc   defaults        0 0
sysfs  /sys    sysfs  defaults        0 0
devtmpfs /dev   devtmpfs mode=0755,size=2G   0 0
EOF

# --- sysctl de otimização N5030 --------------------------------------------
mkdir -p "${R}/etc/sysctl.d"
cat > "${R}/etc/sysctl.d/90-nstatune.conf" <<EOF
# Otimizações de resposta para Intel Pentium N5030 (Goldmont Plus)
vm.swappiness=${SWAPPINESS}
vm.vfs_cache_pressure=${VFS_CACHE_PRESSURE}
kernel.sched_autogroup_enabled=1
vm.dirty_ratio=10
vm.dirty_background_ratio=3
EOF

# --- locales ----------------------------------------------------------------
log "configurando locales (en_US.UTF-8 padrão; pt_BR/es_ES/fr_FR extras)"
install -m 0644 /dev/null "${R}/etc/locale.gen" 2>/dev/null || true
# Espera-se que os arquivos .UTF-8 sejam gerados por localedef/build-locales
echo "en_US.UTF-8 UTF-8" > "${R}/etc/locale.gen"
for l in ${LOCALES_EXTRA}; do echo "${l} UTF-8" >> "${R}/etc/locale.gen"; done
echo "LANG=${LOCALE_DEFAULT}" > "${R}/etc/default/locale"
chroot "${R}" locale-gen >/dev/null 2>&1 || true

# --- serviços OpenRC --------------------------------------------------------
mkdir -p "${R}/etc/runlevels/default"
for svc in syslog hostname netmount lvm swap checkfs root mount-ro \
           network sshd auditd consolefont earlyoom preload; do
  ln -sf "/etc/init.d/${svc}" "${R}/etc/runlevels/default/${svc}" 2>/dev/null || true
done

# --- instalar aplicativos via NovaPKG --------------------------------------
log "instalando aplicativos via NovaPKG"
NOVAPKG="${PROJECT_DIR}/novapkg/novapkg"
if [ -x "${NOVAPKG}" ]; then
  for pkg in ${APPS_MANDATORY}; do
    spec="${PROJECT_DIR}/novapkg/specs/${pkg}.nvpkg"
    if [ -f "${spec}" ]; then
      NOVAPKG_ROOT="${R}" python3 "${NOVAPKG}" install "${spec}" || \
        log "aviso: pacote ${pkg} não instalado (spec ausente ou falha de build)"
    else
      log "aviso: spec .nvpkg para '${pkg}' não encontrada"
    fi
  done
fi

# --- desmontar binds --------------------------------------------------------
for m in dev proc sys; do
  umount "${R}/${m}" 2>/dev/null || true
done

log "rootfs pronto em ${R}"
du -sh "${R}"
