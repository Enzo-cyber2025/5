# EMULATOR.md — status da execução por emulador (2026-09-11, atualizado)

## O que o usuário pediu
Rodar o **GGUF-Chat.apk real** num emulador Android, importar um GGUF + mmproj, testar
tudo e corrigir os bugs. "Roda aonde você quiser, mas TEM QUE RODAR."

## Estado ATUAL: emulador ARM64 real está a 1 download de distância

Nesta rodada, o que mudou:

1. **QEMU 11.0.2 funcionando** (`qemu-portable-linux-x64-musl` via npm). Executar com o
   loader musl do próprio pacote (sem precisar recompilar):
   ```bash
   Q=/tmp/npmqemu/package
   LD_LIBRARY_PATH=$Q/lib $Q/lib/libc.musl-x86_64.so.1 $Q/bin/qemu-system-aarch64 --version
   # → QEMU emulator version 11.0.2   (accel disponível: tcg)
   ```
   O firmware UEFI **já vem no pacote**: `$Q/share/qemu/edk2-aarch64-code.fd`.

2. **Imagem ARM64 compatível com este QEMU encontrada**: o projeto
   `jqssun/android-lineage-qemu` publica **LineageOS 23.2 (Android 15) arm64 que roda
   com `qemu-system-aarch64 -machine virt`** (não precisa da máquina ranchu do emulador
   oficial). O comando de boot TCG está no README do projeto:
   ```bash
   qemu-system-aarch64 -machine virt -cpu max,pauth-impdef=on \
     -accel tcg,tb-size=1024,thread=multi -m 2048 \
     -device virtio-blk-pci,drive=vda,bootindex=0 \
     -device virtio-blk-pci,drive=vdb,bootindex=1 \
     -drive if=pflash,unit=1,file=<utm>/Data/efi_vars.fd \
     -drive if=pflash,unit=0,file=$Q/share/qemu/edk2-aarch64-code.fd,format=raw,readonly=on \
     -drive file=<utm>/Data/vda.qcow2,if=none,id=vda \
     -drive file=<utm>/Data/vdb.qcow2,if=none,id=vdb \
     -device virtio-gpu-pci -display none \
     -device virtio-net-pci,netdev=net0 -netdev user,id=net0,hostfwd=tcp:0.0.0.0:5555-:5555 \
     -device virtio-serial -device virtio-rng-pci
   ```
   ADB depois do boot: `adb connect 127.0.0.1:5555`.

3. **O único bloqueio é o download da imagem** (1,1 GB). A imagem está em **release
   asset** do GitHub, servida por `objects.githubusercontent.com`. Mapa de rede deste
   sandbox (verificado por curl):

   | host | resultado |
   |---|---|
   | `github.com` (git), `api.github.com`, `codeload.github.com` | ✅ 200 |
   | `registry.npmjs.org`, `pypi.org` | ✅ 200 |
   | `objects.githubusercontent.com` / `media.githubusercontent.com` (release/LFS) | ❌ 000 (TCP bloqueado por IP, não por DNS) |
   | `dl.google.com`, `google.com`, `maven.google.com`, `repo1.maven.org`, `huggingface.co`, `gitlab.com`, `archive.ubuntu.com`, `deb.debian.org`, `hub.docker.com`, `ghcr.io`, `gcr.io`, `raw.githubusercontent.com`, `jsdelivr`, `unpkg` | ❌ 000 |

   **Não existe imagem Android bootável em git/npm/PyPI** (verificado: o mirror
   `aosp-mirror-neo/platform_prebuilts_android-emulator-build_system-images` só tem
   SDK tools — adb, android.jar, cmdline-tools — sem `system.img`/kernel/ramdisk).

## Bloqueio do GitHub Actions (não muda)

O push de `.github/workflows/*.yml` é **rejeitado pelo GitHub**:
```
! [remote rejected] ... (refusing to allow a GitHub App to create or update workflow
 `.github/workflows/emu-test.yml` without `workflows` permission)
```
O token desta sessão não tem escopo `workflows` nem `actions` (403 na API). Por isso
o caminho "runner com internet plena + KVM" não dispara sozinho.

## O que destrava AGORA (qualquer uma)

1. **Reconectar o GitHub no Arena concedendo a permissão `workflows`** → o workflow
   `emu-test-arm64` roda no runner `macos-14` (host ARM64, HVF) e faz tudo sozinho.
2. **Liberar `objects.githubusercontent.com` na rede** → rodo aqui mesmo: baixo o
   `UTM-VM-lineage-*.zip` (arm64), extraio `vda/vdb.qcow2` e booto com o QEMU local
   (comando acima), conecto adb e executo a suite completa.
3. Qualquer dispositivo/emulador Android que o usuário conecte (adb) — eu assumo o
   resto (instala APK, importa GGUF+mmproj, testa CPU/Vulkan/multimodal/inexistente,
   coleta logcat + screenshots e corrijo).

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
