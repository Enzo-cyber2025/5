# EMULATOR.md — status da execução por emulador (2026-09-11, atualizado)

## O que o usuário pediu
Rodar o **GGUF-Chat.apk real** num emulador Android, importar um GGUF + mmproj, testar
tudo e corrigir os bugs. "Roda aonde você quiser, mas TEM QUE RODAR."

## Estado ATUAL: emulador ARM64 real a 1 peça de distância (imagem `system`)

Nesta rodada, o que mudou:

1. **QEMU 11.0.2 funcionando** (`qemu-portable-linux-x64-musl` via npm). Executar com o
   loader musl do próprio pacote (sem precisar recompilar):
   ```bash
   Q=/tmp/npmqemu/package
   LD_LIBRARY_PATH=$Q/lib $Q/lib/libc.musl-x86_64.so.1 $Q/bin/qemu-system-aarch64 --version
   # → QEMU emulator version 11.0.2   (accel disponível: tcg)
   ```

2. **adb real v33.0.3** extraído do mirror AOSP via git:
   `aosp-mirror-neo/platform_prebuilts_android-emulator-build_system-images`
   (branch `emu-33-dev`, path `linux/platform-tools/`) — rodando.

3. **Projeto de emulador ARM64 completo encontrado e compatível com o QEMU que tenho**:
   `DangerousAndroid/AluminiumOS` — **Android 17 arm64** (ALOS, o "Googlebooks" vazado)
   que boota com `qemu-system-aarch64 -machine virt` (TCG). Baixável via `git clone`
   (github.com funciona). Contém: kernel arm64 (`cuttlefish/boot/kernel`), ramdisk do
   Pixel "comet" (`comet/vendor_boot/alos.cpio`), DTB, firmware EFI, e TODAS as
   partições extraídas (`cuttlefish/{vendor,system_ext,product,odm,odm_dlkm,system_dlkm,
   vendor_dlkm}`). Comando de boot (adaptado p/ RAM/CPU do sandbox):
   ```bash
   qemu-system-aarch64 -M virt,gic-version=3 -cpu max,sve=off -smp 2 -m 2048 \
     -accel tcg,thread=multi,tb-size=4096 \
     -kernel ./cuttlefish/boot/kernel -initrd ./comet/vendor_boot/alos.cpio \
     -dtb ./dtb/alos.dtb \
     -drive file=super_disk.img,if=none,id=super_drive,format=raw,cache=unsafe,aio=threads \
     -device virtio-blk-pci,drive=super_drive,id=super-disk,addr=04.0 \
     -append "$CMDLINE" \
     -device virtio-gpu-pci -display none -device virtio-tablet-pci \
     -device virtio-keyboard-pci \
     -netdev user,id=net0,hostfwd=tcp:127.0.0.1:5555-:5555 \
     -device virtio-net-pci,netdev=net0 -serial mon:stdio
   ```
   ADB depois do boot: `adb connect 127.0.0.1:5555` (o build já liga
   `service.adb.tcp.port=5555` + `ro.adb.secure=0`).

4. **A ÚNICA peça que falta é a partição `system`** (o framework Android), que nesse
   projeto vive no **submodule GitLab** `https://gitlab.com/DangerousAndroid/alos-gsi.git`
   (`alos-gsi/`). Os scripts `make_system.sh`/`make_product.sh`/`make_system_ext.sh`
   copiam `./alos-gsi/` para montar `alos.img` (6 GB) e depois `lpmake` monta
   `super_alos.img`. **`gitlab.com` está bloqueado neste sandbox** (TLS cortado), e não
   existe mirror desse repo no GitHub (busca exaustiva por `alos-gsi`/forks = nada).

## Mapa de rede do sandbox (verificado por curl)

| host | resultado |
|---|---|
| `github.com` (git clone/push), `api.github.com`, `codeload.github.com` | ✅ 200 |
| `registry.npmjs.org`, `pypi.org`, `files.pythonhosted.org` | ✅ 200 |
| `objects.githubusercontent.com` / `release-assets.githubusercontent.com` / `media.githubusercontent.com` (release/LFS) | ❌ 000 |
| `raw.githubusercontent.com`, `nodeload.githubusercontent.com` | ❌ 000 |
| `gitlab.com` | ❌ 000 (TLS cortado — é onde está o `alos-gsi`) |
| `dl.google.com`, `ci.android.com`, `storage.googleapis.com`, `maven.google.com`, `repo1.maven.org` | ❌ 000 |
| `huggingface.co`, `gitee.com`, `modelscope.cn`, `archive.org`, `sourceforge.net`, `ipfs.io`, `cdn.jsdelivr.net`, `unpkg.com`, `blob.core.windows.net`, `azureedge.net`, `cdnjs.cloudflare.com` | ❌ 000 |
| `apt`/`deb.debian.org`/`archive.ubuntu.com`/`hub.docker.com`/`ghcr.io` | ❌ 000 |

**Conclusão da varredura:** nenhuma imagem Android bootável (arm64 ou x86_64) existe em
git/npm/PyPI — imagens completas são >100 MB e só são distribuídas nos hosts bloqueados
(release assets, LFS, dl.google.com, gitlab, mirror). O que dá para puxar via git
(AluminiumOS) tem TUDO menos o `system`, que está no submodule GitLab bloqueado.

## Bloqueio do GitHub Actions (não muda)

O push de `.github/workflows/*.yml` é **rejeitado pelo GitHub**:
```
! [remote rejected] ... (refusing to allow a GitHub App to create or update workflow
 `.github/workflows/emu-test.yml` without `workflows` permission)
```
O token desta sessão não tem escopo `workflows` nem `actions` (403 na API). Por isso
o caminho "runner com internet plena + KVM" não dispara sozinho.

## O que destrava AGORA (qualquer uma)

1. **Liberar `gitlab.com` (ou qualquer um dos hosts acima) na rede** → rodo aqui mesmo:
   `git clone --recurse-submodules https://github.com/DangerousAndroid/AluminiumOS.git`,
   `make_system && make_vendor && make_product && make_system_ext && make_super`,
   booto com o QEMU local (comando acima), conecto adb e executo a suite completa.
2. **Reconectar o GitHub no Arena concedendo a permissão `workflows`** → o workflow
   `emu-test-arm64` roda no runner `macos-14` (host ARM64, HVF) e faz tudo sozinho.
3. **Um mirror do `alos-gsi` em qualquer repo git acessível** (ou qualquer GSI arm64
   commitada em git) → o resto já está montado.

Enquanto isso, a execução REAL que foi possível fazer — a camada nativa **do APK real**
rodando por completo no host — está em `apk-real-host-run/RUN.md`, e a revisão do
caminho de abertura/crash em `apk-real-host-run/REVIEW.md`.

## Scripts prontos
- `.github/emu-qemu-arm64.sh` — boot do LineageOS arm64 no QEMU local (TCG) + suite.
- `.github/emu-test-arm64.sh` — emulador oficial arm64-v8a (runner macOS-14, HVF).
- `.github/emu-test.sh` — emulador oficial x86_64 (KVM).
- `emu-test-arm64.workflow.yml` / `emu-test.workflow.yml` — workflows prontos (bloqueio:
  permissão `workflows`).

## Execução REAL já concluída (enquanto o emulador não sai)
- `apk-real-host-run/RUN.md` — camada nativa REAL do APK (JNI_OnLoad → create → tokenize
  → generate → destroy) rodando no host, `EXIT=0` (CPU e fallback Vulkan→CPU).
- `apk-real-host-run/REVIEW.md` — revisão do caminho de abertura/crash (bytecode real):
  o Java de abertura não crasha; o único ponto de morte é o load nativo do modelo.
