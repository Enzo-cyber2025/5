# Avaliação honesta de viabilidade

Este documento registra **o que foi feito de verdade** e **por que a entrega
literal do pedido original (um `.iso` completo com LibreOffice/Firefox/GIMP/
VLC compilado e testado em QEMU) não é possível neste ambiente**, sem enganação.

## O que este repositório contém (real e verificável)

- **NovaPKG funcional** — testado de ponta a ponta (`build -> install -> list
  -> search -> info -> remove`) em arquitetura real, com formato `.nvpkg`.
- **Código-fonte completo da NovaUI** (WM, painel, terminal, gerenciador de
  arquivos, central de configurações, lançador) em C, usando apenas
  Xlib+Cairo+Pango+FreeType+libinput. Compila em uma máquina com as libs de dev.
- **Pipeline de build automatizado** (`build_all.sh`) com `config.sh` central.
- **Temas `.novatheme`** (claro/escuro) e **papel de parede** e **tema GRUB**
  gerados e salvos como PNG reais.
- **Patches de kernel Goldmont Plus** e **config de referência**.
- **Harness de verificação QEMU** e **suite de teste do convidado**.
- **Specs de pacotes** para os 20 aplicativos obrigatórios.

## O que NÃO pode ser entregue aqui e por quê

O ambiente de execução (sandbox) tem estas restrições objetivas, verificadas:

| Recurso | Observação |
|---------|------------|
| **Rede** | Só `github.com` e `PyPI` são acessíveis. `deb.debian.org`, `kernel.org`, `ftp.gnu.org` e downloads de *release* do GitHub (`release-assets.githubusercontent.com`) estão **bloqueados**. |
| **apt** | As fontes Debian não carregam; **não é possível instalar** `xorriso`, `grub-pc-bin`, `grub-efi`, `dracut`, `qemu-system-x86`, `debootstrap`, `flex`, `bison`, `bc`, `m4`, autotools, `zstd` ou as dev-libs. |
| **Ferramentas de boot/ISO** | `xorriso`, `grub-mkrescue`, `dracut`, `qemu-system-x86_64`, `mkisofs` **não existem** e não podem ser instalados. |
| **QEMU** | Ausente; sem ele **não há como verificar boot, VLC 1080p, RAM<800MB** num ambiente de teste. |
| **RAM** | 4 GB (builds de LibreOffice/Firefox/GIMP/VLC exigem 8–16 GB e horas de CPU); o host tem 2 vCPUs. |
| **Toolchain pedida** | O host tem GCC 12.2/binutils 2.40; GCC 13.2/glibc 2.38 precisariam de bootstrap (não compilável aqui sem dev-libs e sem rede). |
| **Kernel** | Sem `bc`/`flex`/`bison` e sem acesso ao código-fonte do kernel, não é possível compilar aqui. |

### Conclusão
Gerar um `.iso` e um `SHA256` **verdadeiramente compilado/testado** é inviável
nestas condições. **Não fabricamos um ISO ou hash.** Em vez disso entregamos o
projeto de engenharia completo e reproduzível, que produz o ISO quando executado
numa máquina com os pré-requisitos documentados em `BUILD.md`.

## O que você precisa para gerar o ISO real

Uma máquina (local ou CI) com:
1. Acesso a `kernel.org`, `ftp.gnu.org`, `deb.debian.org`;
2. Pelo menos 16 GB de RAM e 8+ núcleos recomendado para os apps pesados;
3. Pacotes: `build-essential bc flex bison libssl-dev libelf-dev xorriso
   grub-pc-bin grub-efi-amd64-bin grub-common mtools dracut qemu-system-x86
   qemu-utils debootstrap busybox-static openrc zstd xz-utils curl wget` e as
   libs dev da NovaUI.

Depois: `cd NOVALINUX/build && ./build_all.sh`.

## Sobre os testes simulados

Os testes T2–T7 (RAM<800MB, VLC 30fps, Firefox 5 abas, NovaPKG install/remove,
suspend/resume, offline) estão **implementados** em `tests/guest_novatest.sh` e
**prontos** para rodar no QEMU quando o ambiente de build estiver disponível.
O teste T1 (tempo de boot) é medido pelo `verify.sh`. Nenhum desses foi
declarado como "passou" aqui, porque não há QEMU para executá-los.
