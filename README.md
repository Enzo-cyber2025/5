# NovaLinux

Uma distribuição Linux construída do zero, com foco no **Intel Pentium N5030**
(quad-core **Goldmont Plus**, x86_64) — o SoC de notebooks/htpc de baixo custo
com iGPU Intel UHD 605.

> **Estado real do projeto (atualizado).** Foi compilado e publicado um
> **ISO bootável REAL** neste repositório (**`NOVALINUX/dist/`**), com um
> kernel Linux compilado neste ambiente (`-O3 -march=goldmont-plus`), um
> initramfs BusyBox embutido e boot UEFI (El Torito EFI). O processo de
> construção está documentado em `NOVALINUX/build/build_iso_real.sh` e
> `docs/BUILD.md`. A validação estrutural (El Torito, kernel EFI, initramfs)
> foi feita com `pycdlib`; a verificação de boot em QEMU **não pôde** ser
> executada aqui porque o QEMU não está disponível/instalável no sandbox.

---

## Objetivo

Criar um Linux **completo, otimizado e original** para o N5030, com:

- **Kernel Linux 6.6.x LTS** compilado com `-march=goldmont-plus -mtune=goldmont-plus -O3 -pipe -flto=auto`.
- **Toolchain própria** GCC 13.2, glibc 2.38, binutils 2.41, todas otimizadas para Goldmont Plus.
- **Init system: OpenRC** (proibido systemd).
- **NovaUI** — interface gráfica 100% nova (WM, painel, terminal, gerenciador
  de arquivos, central de configurações, lançador). Nada de Qt/GTK/EFL/FLTK/
  wxWidgets; apenas Xlib + Cairo + Pango + FreeType + libinput.
- **NovaPKG** — gerenciador de pacotes próprio, formato `.nvpkg` (tar.xz + JSON).
- **Boot híbrido** (UEFI + BIOS) via GRUB 2.12 + tema gráfico próprio, initramfs
  dracut, boot < 15 s.
- Otimizações de runtime (schedutil, swappiness=10, vfs_cache_pressure=50,
  swap zstd, earlyoom, preload, ext4 `noatime,commit=120,data=ordered`,
  boot `quiet loglevel=3 mitigations=off intel_idle.max_cstate=4`).

## Estrutura

```
NOVALINUX/
├── build/        # pipeline automatizado (config.sh + scripts)
├── kernel/       # patches Goldmont Plus + config de referência
├── initramfs/    # esqueleto do initramfs / dracut
├── grub/         # grub.cfg + tema gráfico
├── rootfs/       # serviços OpenRC e configs de runtime
├── novapkg/      # NovaPKG + specs de pacotes (.nvpkg)
├── novaui/       # código-fonte da interface (NovaUI)
├── tests/        # suite de verificação QEMU
└── docs/         # documentação técnica e avaliação honesta
```

## Compilação

Em uma máquina Debian/amd64 com as dependências listadas em `docs/`:

```sh
cd NOVALINUX/build
./build_all.sh      # toolchain -> kernel -> rootfs -> initramfs -> ISO -> verify
```

Para construir apenas os aplicativos como `.nvpkg`:

```sh
./build_apps.sh                 # apps leves
./build_apps.sh --full          # inclui LibreOffice/Firefox/GIMP/VLC (pesado)
```

Para publicar apenas o `.iso` + `.sha256` na branch `release`:

```sh
NOVALINUX_REPO=<usuario>/NovaLinux-ISO ./upload.sh
```

## Pré-requisitos do builder

`build-essential bc flex bison libssl-dev libelf-dev xorriso grub-pc-bin
grub-efi-amd64-bin grub-common mtools dracut qemu-system-x86 qemu-utils
debootstrap busybox-static openrc zstd xz-utils curl wget`
(plus bibliotecas dev da NovaUI: `libx11-dev libcairo2-dev libpangocairo-1.0-0
libfreetype6-dev libfontconfig1-dev libinput-dev`).

## Aviso

O upload para `release` é **restrito ao `.iso` e ao `.sha256`** (conforme
pedido); nenhum código-fonte vai para lá. O código-fonte fica na branch de
desenvolvimento deste repositório.
