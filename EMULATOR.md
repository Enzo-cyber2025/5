# EMULATOR.md — status da execução por emulador (2026-09-11)

## O que o usuário pediu
Rodar o **GGUF-Chat.apk real num emulador Android**, importar um GGUF e um
mmproj, testar tudo e corrigir os bugs. "Roda aonde você quiser, mas TEM QUE
RODAR."

## O que foi feito nesta rodada (real, não análise)

1. **Montei um emulador do zero neste sandbox.** O sandbox não tem KVM, Java,
   QEMU, Docker nem adb, e só alcança GitHub + PyPI + npm na rede. Então:
   - peguei o QEMU de sistema empacotado em npm (`qemu-portable-linux-x64-musl`);
   - o binário pede `libc.musl` + `ld-musl`; **compilei o musl do zero** (clone
     de um mirror no GitHub, `make` sem dependências);
   - resultado: `qemu-system-x86_64 --version` → **`QEMU emulator version 11.0.2`** ✔
     (emulador de máquina completo, com TCG/software, funcionando).
2. **Encontrei o `adb` real do Android SDK num repo git**
   (`aosp-mirror-neo/platform_prebuilts_android-emulator-build_system-images`,
   arquivo `linux/platform-tools/adb` + libs) — dá para extrair o cliente adb
   sem Google.
3. **Preparei o teste de emulador completo** em `.github/emu-test.sh`
   (boot → instala o APK REAL → importa `tiny-llama-022.gguf` + `tiny-mmproj-022.gguf`
   → abre conversa → gera via `Native.create/tokenize/generate` → coleta
   logcat + screenshots). E o workflow correspondente está no repo como
   `emu-test.workflow.yml`.

## Por que ainda não rodou DENTRO do Android (bloqueio exato)

Falta **uma única peça**: uma imagem Android bootável (kernel + ramdisk +
system.img). Ela é distribuída **só** em hosts que este sandbox NÃO alcança:

| fonte da imagem | resultado |
|---|---|
| `dl.google.com` (system-images do SDK) | `000` (bloqueado) |
| `sourceforge.net` / `osdn.net` (android-x86 ISO) | `000` |
| `android-x86.org` / `storage.googleapis.com` | `000` |
| GitHub Releases / LFS (`objects.githubusercontent.com`, `media.githubusercontent.com`) | `000` |
| apt (debian/ubuntu), ghcr.io, musl.libc.org, jsdelivr, crates.io… | `000` |

A rede só deixa passar **git do github.com, PyPI e npm** — e não existe imagem
Android bootável dentro desses três (confirmei por busca na API do GitHub, no
npm e no PyPI).

E o caminho óbvio — **GitHub Actions** (que baixa a imagem com internet plena e
roda o emulador com KVM no runner) — está bloqueado porque a conexão GitHub
deste ambiente **não tem a permissão `workflows`**:

```
! [remote rejected] arena/01a077ef-5 -> arena/01a077ef-5
(refusing to allow a GitHub App to create or update workflow
 `.github/workflows/emu-test.yml` without `workflows` permission)
```

## O que destrava AGORA (1 passo, com você)

**Reconecte o GitHub aqui no Arena concedendo a permissão `workflows`**
(ou, no repo, crie o arquivo `.github/workflows/emu-test.yml` colando o
conteúdo de `emu-test.workflow.yml`). Com isso o workflow `emu-test` roda
sozinho: sobe o emulador Android x86_64 (API 30) com KVM, instala o APK real,
importa GGUF+mmproj, testa (launch / CPU / Vulkan / multimodal / caminho
inválido) e anexa o logcat + screenshots como artefato.

Enquanto isso, a execução REAL que foi possível fazer aqui — a camada nativa
**do APK real** rodando por completo no host (`JNI_OnLoad → create → tokenize →
generate → destroy`, `EXIT=0`) — está documentada em `apk-real-host-run/RUN.md`,
com os dois bugs de execução já identificados (backend Vulkan e o caminho mmap
de `llama_mmap`, ambos no contexto bionic×glibc) e os bugs Java do app
(`Native.create` ignora o mmproj; `models.json`/`chats.json` sem try/catch →
crash de abertura se o JSON ficar corrompido).

## Reproduzir o emulador (QEMU) do zero neste ambiente

```bash
# 1) QEMU de sistema via npm (binário musl)
cd /tmp && npm pack qemu-portable-linux-x64-musl && tar xzf qemu-portable-linux-x64-musl-*.tgz

# 2) libc musl (o binário pede libc.musl + ld-musl) — compilar do fonte
git clone --depth 1 https://github.com/ifduyue/musl /tmp/musl
cd /tmp/musl && ./configure --prefix=/tmp/musl-install && make -j2 && make install
cp /tmp/musl-install/lib/libc.so /tmp/npmqemu/package/lib/libc.musl-x86_64.so.1
cp /tmp/musl-install/lib/libc.so /tmp/ld-musl-x86_64.so.1

# 3) rodar
LD_LIBRARY_PATH=/tmp/npmqemu/package/lib \
  /tmp/ld-musl-x86_64.so.1 /tmp/npmqemu/package/bin/qemu-system-x86_64 --version
# → QEMU emulator version 11.0.2
```

O `adb` real (Linux/x86_64) está em
`aosp-mirror-neo/platform_prebuilts_android-emulator-build_system-images` →
`linux/platform-tools/adb` (+ `lib64/`).

## Arquivos
- `.github/emu-test.sh` — teste de emulador completo (pronto para rodar).
- `emu-test.workflow.yml` — workflow pronto; copie para `.github/workflows/emu-test.yml`.
- `apk-real-host-run/RUN.md` — execução real da camada nativa do APK.
- `apk-real-host-run/REVIEW.md` — revisão linha a linha do caminho de crash.

## ARM64 (requisito do usuário: o celular é arm64)

O emulador oficial **não** roda guest arm64 em host x86_64 ("PANIC: arm64 not
supported on x86_64 host"); o QEMU upstream aqui também não tem a máquina
ranchu/goldfish (só `virt`/`sbsa-ref`). Logo, ARM64 de verdade exige **host
ARM64** — os runners Apple Silicon do GitHub (`macos-14`) ou um Mac M1/M2/M3 local.

- `.github/emu-test-arm64.sh` — sobe o emulador arm64-v8a (API 30 google_apis),
  com fallback automático HVF → `-no-accel`, e roda a suite completa
  (instala APK real, importa GGUF+mmproj, CPU/Vulkan/mmproj/inexistente,
  logcat + screenshots). Roda local (Mac M-series, rápido) ou no runner.
- `emu-test-arm64.workflow.yml` — workflow pronto; copie para
  `.github/workflows/emu-test-arm64.yml` (mesmo bloqueio: permissão `workflows`).

Caminho mais rápido e fiel: rodar `bash .github/emu-test-arm64.sh` num Mac
Apple Silicon com aceleração HVF.
