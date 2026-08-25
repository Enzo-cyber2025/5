# Guia de build do ISO real (validado neste ambiente)

Esta é a via que **funcionou** para compilar e empacotar um ISO bootável
dentro de um sandbox com rede restrita (apenas GitHub/PyPI, sem `apt`,
sem `xorriso`, sem `qemu`).

## Restrições do ambiente (verificadas)

| Recurso | Disponível |
|---------|-----------|
| rede | `github.com` + `PyPI` apenas. `ftp.gnu.org`/`kernel.org`/Debian **bloqueados**; downloads de release do GitHub **bloqueados** (Git-LFS). |
| toolchain | `gcc`, `make`, `binutils`, `perl`, `python3` presentes. |
| ausentes | `flex`, `bison`, `bc`, `m4`, `autoconf`, `automake`, `xorriso`, `grub`, `qemu`, `mkfs.vfat`, `mcopy`. Não instaláveis (sem apt). |

## Estratégia usada

1. **Kernel com kconfig pré-gerado** — usa um LTS que embarca
   `scripts/kconfig/*_shipped` (Flex/Bison não são chamados).
2. **`bc` substituído por um wrapper Python** — o kernel pede `bc` apenas para
   gerar `include/generated/timeconst.h`; emulamos o `kernel/time/timeconst.bc`.
3. **`R_X86_64_PLT32` resolvido** — binutils 2.40 emite essa relocação;
   o `arch/x86/tools/relocs.c` de kernels antigos não a conhecia (patch).
4. **Initramfs embutido** — `CONFIG_INITRAMFS_SOURCE=usr/initramfs` com BusyBox
   estático → o kernel já vira o `/init`; não precisa de módulos nem de outro
   initramfs.
5. **ISO UEFI sem GRUB/SYSLINUX** — o kernel é construído com `CONFIG_EFI_STUB`
   (vira um binário `pei-x86-64`). Empacotamos o kernel como `\EFI\BOOT\BOOTX64.EFI`
   numa imagem FAT12 e geramos um ISO **El Torito EFI** com `pycdlib`.

## Como reproduzir

```sh
cd NOVALINUX/build
./build_iso_real.sh
# → gera NOVALINUX/dist/navelinux-1.0-x86_64-4.14-uefi.iso + .sha256
```

O script `build_iso_real.sh` faz o clone, os patches, o initramfs, a configuração
do kernel, o `make bzImage` e o empacotamento do ISO.

## Arquivos de apoio

- `build/tools/mkfat.py` — gera a imagem FAT12 (com `BOOTX64.EFI`) usada como
  imagem de boot EFI do ISO.
- `build/tools/mkisouefi.py` — monta o ISO El Torito EFI com `pycdlib`.
- `build/tools/kernel-4.14.novaconfig` — `.config` usado no kernel compilado.
- `build/build_iso_real.sh` — orquestra tudo.

## Validação feita

- Kernel: produz um `bzImage` `pei-x86-64` (EFI stub) — verificado com `objdump`.
- Initramfs embutido confirmado (`/init`, `bin/busybox`, `etc/hostname`).
- ISO: `pycdlib` lê o volume `NOVALINUX`, El Torito presente com
  `platform_id=0xef` (UEFI), `boot_media_type=0` (no-emul), kernel como
  `BOOTX64.EFI` na imagem FAT.

### Limite
**Não foi possível executar o boot em QEMU** porque o QEMU não está disponível
nem instalável no sandbox. A verificação de boot ("acha o firmware UEFI e chega
ao prompt do BusyBox") deve ser feita numa máquina com QEMU ou hardware UEFI:

```sh
qemu-system-x86_64 -m 1024 -smp 2 \
  -drive file=NOVALINUX/dist/navelinux-1.0-x86_64-4.14-uefi.iso,media=cdrom \
  -bios OVMF.fd -nographic
```
