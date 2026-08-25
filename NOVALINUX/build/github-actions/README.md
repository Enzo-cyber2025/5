# GitHub Actions para compilar o ISO do NovaLinux

Este diretório contém o workflow **pronto para ativar** no GitHub.

> **Por que não está em `.github/workflows/`?**
> O token de automação usado nesta sessão não tem permissão de escrita em
> arquivos de workflow (`workflows`), então o push direto para
> `.github/workflows/` é recusado pelo GitHub. O arquivo está aqui intacto;
> basta copiá-lo para o caminho padrão para ativar o CI.

## Como ativar

```sh
# opção A: mover manualmente para a raiz do repo
mkdir -p .github/workflows
cp NOVALINUX/build/github-actions/build-iso.yml .github/workflows/
git add .github/workflows/build-iso.yml
git commit -m "ativa workflow do ISO"
git push
```

Ou, pela interface do GitHub: **Actions → New workflow → set up a workflow
yourself**, e cole o conteúdo de `build-iso.yml`.

## O que ele faz

Ao rodar (manual, ou em push para `release`), num runner `ubuntu-latest`
(com rede completa):

1. Instala as dependências (`bison`, `flex`, `bc`, `xorriso`, `grub`,
   `dracut`, `qemu`, etc.).
2. Executa `NOVALINUX/build/ci_build.sh`, que:
   - compila o kernel Linux 6.6.x (`bzImage`) com `-O3 -march=goldmont-plus`;
   - monta um rootfs mínimo com BusyBox + um `/init` original;
   - gera o initramfs (`cpio` + `zstd`);
   - monta o ISO híbrido (UEFI + BIOS) com `grub-mkrescue`/`xorriso`;
   - calcula o `SHA256`.
3. Tenta bootar no QEMU (best-effort) e guarda o log.
4. Publica um **GitHub Release** contendo **apenas** o `.iso` e o `.sha256`.

## Rodar localmente (sem CI)

Em qualquer máquina Debian com rede padrão:

```sh
bash NOVALINUX/build/ci_build.sh
```
