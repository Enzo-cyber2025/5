# Guia de build

## Pré-requisitos (máquina de build adequada)

Sistema: Debian/Ubuntu amd64 (ou compatível). Recomendado: 16 GB RAM, 8+ vCPUs.

```sh
sudo apt update && sudo apt install --yes \
  build-essential bc flex bison libssl-dev libelf-dev libncurses-dev \
  xorriso grub-pc-bin grub-efi-amd64-bin grub-common mtools dracut \
  qemu-system-x86 qemu-utils debootstrap busybox-static openrc zstd \
  xz-utils curl wget autoconf automake libtool pkg-config \
  libx11-dev libxext-dev libxrender-dev libcairo2-dev libpangocairo-1.0-0 \
  libfreetype6-dev libfontconfig1-dev libinput-dev \
  libasound2-dev libdbus-1-dev libglib2.0-dev libpixman-1-dev
```

## Build completo

```sh
cd NOVALINUX/build
./build_all.sh
```

Etapas executadas por `build_all.sh`:

1. `build_toolchain.sh` — bootstrap GCC 13.2 / glibc 2.38 / binutils 2.41
   (Goldmont Plus). Requer 8–16 GB RAM e horas.
2. `build_kernel.sh` — kernel 6.6.x LTS + patches + `-march=goldmont-plus`.
3. `build_rootfs.sh` — sistema base + OpenRC + usuário `nova` + locales + otimizações.
4. `build_iso.sh` — initramfs dracut + ISO híbrido + SHA256.
5. `verify.sh` — testes QEMU (boot, RAM, VLC, Firefox, NovaPKG, suspend, offline).

### Flags úteis

```sh
./build_all.sh --skip-verify        # não roda a verificação QEMU
./build_all.sh --skip-toolchain     # usa toolchain do host
./build_all.sh --only kernel        # executa apenas uma etapa
```

## Build de aplicativos (.nvpkg)

```sh
cd NOVALINUX/build
./build_apps.sh             # apps leves (htop, neofetch, condas, etc.)
./build_apps.sh --full      # inclui LibreOffice, Firefox ESR, GIMP, VLC
```

## Testes isolados

```sh
# initramfs de teste
./make_novatest_initrd.sh
# verificação (precisa do ISO e do initrd de teste)
./verify.sh
```

## Publicação (branch `release`)

```sh
NOVALINUX_REPO=<usuario>/NovaLinux-ISO ./upload.sh
```

Publica **apenas** `*.iso` e `*.sha256` na branch `release` de um repositório
GitHub público. Nenhum código-fonte vai para lá.
