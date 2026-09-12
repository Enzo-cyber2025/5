# arm64-native-run — execução da camada nativa REAL do GGUF-Chat.apk

Este diretório executa o código **nativo arm64-v8a que o APK carrega em
produção** (libaijni.so → libllama.so → libggml.so) fora de um aparelho,
via `qemu-aarch64` (user-mode) + musl aarch64 + um mini-JNI.

Isto **não** é um emulador Android completo: é a execução real das `.so`
arm64 que o APK embarca, com um stub JNI mínimo que responde às chamadas
que o `libaijni.so` faz de volta para a JVM. Serve para provar, sem crash e
sem aparelho, que a camada nativa funciona — e foi exatamente aqui que o
bug "o app crasha antes mesmo de abrir" foi encontrado e corrigido.

## Resultado (estado atual)

O fluxo completo do APK executa **sem crash** (EXIT=0):

```
>>> create() ret=0x7f...           ← modelo carregado, handle válido
>>> backendName=libllama.so
>>> tokenize("Hello world") = 17 tokens
>>> detokenize = '▁Hello▁world'    ← round-trip do tokenizer CORRETO
>>> generate(...) → onToken/onDone ← geração roda (tokens são lixo: modelo aleatório)
>>> destroy() OK
>>> ===== camada nativa arm64 do APK executou SEM CRASH =====
```

Matriz de testes executada (todas com as `.so` reais do APK):

| Cenário | Args do runner | Resultado |
|---|---|---|
| CPU + mmap=1 | `model 0 1` | EXIT=0, sem crash |
| CPU + mmap=0 | `model 0 0` | EXIT=0, sem crash |
| Vulkan (gpuLayers=99) | `model 99 1` | EXIT=0, fallback limpo p/ CPU (`libvulkan.so` ausente) |
| Multimodal (mmproj) | `model mmproj 0 1` | EXIT=0, sem crash |
| Modelo inexistente | `nao-existe.gguf 0 1` | EXIT=5, `create()=0x0`, `lastError="engine not loaded"` |

## Causa-raiz do crash (corrigida)

O APK é compilado para Android/**bionic**, onde as constantes `_SC_*` de
`sysconf()` são **diferentes** das do musl/glibc:

| Constante | bionic | musl |
|---|---|---|
| `_SC_PAGESIZE` | **39** | 30 |
| `_SC_PAGE_SIZE` | **40** | 30 |
| `_SC_ATEXIT_MAX` | 37 | 87 |
| `_SC_IOV_MAX` | 38 | 60 |
| `_SC_NPROCESSORS_*` | 96–99 | 83–86 |

O `libllama.so` chama `sysconf(_SC_PAGESIZE)` (literal `mov w0, #0x27` = 39)
para descobrir o tamanho de página. Sob musl, `sysconf(39)` =
`_SC_BC_STRING_MAX` → retorna lixo → `page_size` incorreto → o assert

```
GGML_ASSERT(last % page_size == 0)   // llama-mmap.cpp, unmap_fragment
```

dispara (`unmap_fragment(0, 7456)`; `7456 % 4096 != 0`) → `ggml_abort` →
`abort()` → SIGABRT/SIGSEGV. O stack era `load_all_data` → `load_tensors` →
`llama_model_load_from_file`, o PC apontava para `libc+0x138d4` (a
`__restore` do sinal, não o código real).

**Correção**: o `bionic_shim.c` intercepta `sysconf()` e remapeia as
constantes bionic para musl (o ponto crítico: `39/40 → 4096`).

## Arquivos

- `runner.c` — harness JNI arm64 (dlopen das .so do APK + mini-JNI).
- `log_stub.c` — stubs `__android_log_*` (bionic) → fprintf.
- `bionic_shim.c` — shim LD_PRELOAD com os símbolos bionic que o musl não
  exporta: `__errno`, `__register_atfork`, `__cxa_thread_atexit_impl`,
  fortify `_chk`, `__open_2`, `__sF`, `__system_property_get`, e o
  interceptor de `sysconf()` (a correção).
- `build_and_run.sh` — compila (Zig → aarch64-linux-musl) e roda tudo.

## Como reproduzir

Pré-requisitos (já presentes no sandbox):
- `/home/user/tools/qemu-aarch64` (qemu-user aarch64)
- `/usr/local/lib/python3.11/dist-packages/ziglang/zig` (Zig, host)
- `/tmp/sysroot/` (sysroot musl aarch64 com as .so arm64 do APK + shim)
- `/tmp/models/tiny-llama-022.gguf` + `tiny-mmproj-022.gguf` (modelo sintético)

```bash
./build_and_run.sh                        # fluxo completo (CPU, mmap=1)
./build_and_run.sh /tmp/models/tiny-llama-022.gguf "" 0 0   # mmap desligado
./build_and_run.sh /tmp/models/tiny-llama-022.gguf "" 99 1  # tenta Vulkan
./build_and_run.sh /tmp/models/nao-existe.gguf "" 0 1       # modelo inexistente
```

## Relação com o emulador Android real

Esta execução prova a camada nativa. O teste completo do APK (Dalvik +
nativo) num emulador Android **arm64** depende de um runner arm64 (o
sandbox atual é x86_64, sem KVM, e os espelhos do Google —
`dl.google.com`, `storage.googleapis.com`, `ci.android.com` — estão
bloqueados na rede). O caminho já documentado no repositório é o runner
**GitHub Actions macos-14/arm64** (commits anteriores), bloqueado apenas
pela permissão `workflows` do token do GitHub.
