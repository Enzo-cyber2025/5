# Execução REAL dos binários do APK (não do engine recompilado)

Esta pasta registra a execução **dos binários nativos extraídos do próprio
`GGUF-Chat.apk`** — não de uma cópia recompilada do engine. Objetivo: testar
**o APK real** e reproduzir/validar, executando de verdade, o crash ao abrir
uma conversa.

## Artefato sob teste

| Campo | Valor |
|---|---|
| APK | `GGUF-Chat.apk` |
| SHA-256 | `02f97871a28936b4374001e0df7352461821181957a5f740207fa5eea4117281` |
| Tamanho | 90 344 760 bytes |
| Libs nativas | `libggml-base.so`, `libggml-vulkan.so`, `libggml-cpu.so`, `libllama.so`, `libc++_shared.so`, `libaijni.so`, `libunwind.so` (x86_64, extraídas do APK) |
| ggml | `0.22.0` (reportado por `ggml_version()` do APK) |

## Resultado central (atualizado nesta rodada)

1. **O APK já contém a correção do crash nas DUAS arquiteturas.** A função
   `ggml_backend_vk_host_buffer_type_alloc_buffer` em `libggml-vulkan.so`
   (arm64-v8a **e** x86_64) tem o null-check do ponteiro "pinned" + fallback
   para CPU (`ggml_backend_buft_alloc_buffer(ggml_backend_cpu_buffer_type(),
   size)`), verificado por disassembly completo de ambos os `.so` reais:

   - **x86_64** (`ggml_backend_vk_host_buffer_type` em `0x21b94f0`):
     ```
     21b9945: test %r12,%r12
     21b9948: je   21b9968                 ; ptr==NULL -> fallback
     21b9950: call ggml_backend_cpu_buffer_from_ptr@plt   ; só se ptr != NULL
     21b9968: call ggml_backend_cpu_buffer_type@plt
     21b9973: call ggml_backend_buft_alloc_buffer@plt     ; fallback CPU
     ... e o catch (exceção vk::SystemError) em 21b9a55 também cai no fallback (21b9a87)
     ```
   - **arm64-v8a** (mesma lógica):
     ```
     21a587c: cbz  x21, 21a58c8           ; ptr==NULL -> fallback
     21a5888: bl   ggml_backend_cpu_buffer_from_ptr   ; só se ptr != NULL
     21a58c8: bl   ggml_backend_cpu_buffer_type
     21a58d0: bl   ggml_backend_buft_alloc_buffer     ; fallback CPU
     ```

2. **O crash original foi reproduzido no `.so` real.** Chamando o caminho que
   a correção previne (`cpu_buffer_from_ptr(NULL, size)` → `get_base`), o
   `libggml-base.so` do APK aborta exatamente onde se esperava:

   ```
   >>> [BUG] cpu_buffer_from_ptr(nullptr, 1048608) -> get_base
   >>> SINAL 5 (Trace/breakpoint trap)  (exit 133)
       #2 /tmp/android-run/libggml-base.so(+0x573e4)
   ```

   `0x573e4` = dentro de `ggml_backend_buffer_get_base` (símbolo em `0x57360`),
   o `int3` logo após `call ggml_abort` com `mov $0x8a,%esi` (linha **138** =
   `GGML_ASSERT(base != NULL && "backend buffer base cannot be NULL")`).

3. **O caminho corrigido executa limpo** (`buft_alloc_buffer(cpu_buffer_type(), size)`):
   `base=0x7f…5040`, exit 0.

4. **Motor REAL do APK executou de ponta a ponta no host, sem crash** (ver
   seção abaixo): backend init → carga do modelo → contexto → decode → geração.

## Execução ponta a ponta do motor real (novo)

As 5 libs x86_64 reais do APK foram carregadas no host (apenas adaptação de
ABI/versionamento — **nenhum byte de `.text` alterado**) e o fluxo completo do
app (o mesmo que `libaijni.so` faz via dlsym) foi executado:

```
>>> libllama.so REAL do APK carregado
>>> llama_backend_init() ...
ggml_vulkan: Error: Vulkan 1.2 required.        ; host sem Vulkan -> pulado graciosamente
load_backend: loaded CPU backend from /tmp/android-run/libggml-cpu.so
>>> backend init OK
>>> llama_model_load_from_file(/tmp/tiny-llama-022.gguf)
   (21 KV + 12 tensores, print_info completo, load_tensors: 2 camadas -> CPU)
>>> llama_init_from_model (contexto) ... OK     ; graph_reserve + sched_reserve
>>> llama_decode(prompt, 4 tokens) ... ret=0 OK
>>> geração greedy (4 tokens): token 148/217/85/100 ...
>>> cleanup ... OK
>>> OK: execução REAL do motor do APK concluída sem crash
exit=0
```

- Modelo de teste: `gen_tiny_gguf022.py` gera um LLaMA mínimo GGUF V3 válido
  (12 tensores com sufixo `.weight`, dims corretas) usando o gguf-py do
  **mesmo formato 0.22.0** do engine.
- `driver_full.c` usa o header `llama.h` 0.22.0 (mesmo ABI) e faz dlsym dos
  símbolos exatos que o app usa (`llama_backend_init`, `llama_model_load_from_file`,
  `llama_init_from_model`, `llama_decode`, `llama_get_logits_ith`, etc.).

### Ajustes de ambiente (sem tocar no código do APK)

- `deversion.py`: remove o versionamento bionic (`DT_VERSYM`→`DT_NULL`) para o
  loader glibc carregar as libs Android.
- `shim.c` → `libc.so`: exporta `__errno`, `__sF`, `__strlen_chk`, `__strchr_chk`
  e os `_Unwind_*` (encaminhados ao `libgcc_s`).
- `vulkan_stub.c` → `libvulkan.so`: reporta **Vulkan 1.0** em
  `vkEnumerateInstanceVersion`; o ggml exige 1.2 e aborta a inicialização Vulkan
  **graciosamente** (exceção capturada em `ggml_backend_vk_reg()` → nullptr),
  caindo no backend CPU — exatamente o comportamento de um host sem Vulkan.

## Como reproduzir

```bash
# 1) extrair as libs reais do APK
unzip -o GGUF-Chat.apk 'lib/x86_64/*' -d /tmp/apk_extract

# 2) de-versionar (ABI, sem tocar em .text) e copiar
for L in libggml-base libggml-vulkan libggml-cpu libggml libllama; do
  python3 apk-real-host-run/deversion.py \
    /tmp/apk_extract/lib/x86_64/$L.so /tmp/android-run/$L.so
done
cp /tmp/apk_extract/lib/x86_64/libc++_shared.so /tmp/android-run/
cp /tmp/apk_extract/lib/x86_64/libunwind.so   /tmp/android-run/
cp /tmp/apk_extract/lib/x86_64/libaijni.so    /tmp/android-run/   # sem DT_VERSYM: copiar direto

# 3) shim libc.so + symlinks + stub libvulkan.so (ver shim.c / vulkan_stub.c)

# 4) reproduzir o crash e validar o fix
gcc -o /tmp/android-run/runner_crash apk-real-host-run/runner_crash.c -ldl -rdynamic
LD_LIBRARY_PATH=/tmp/android-run /tmp/android-run/runner_crash        # bug  -> SIGTRAP em get_base
LD_LIBRARY_PATH=/tmp/android-run /tmp/android-run/runner_crash fix    # fix  -> exit 0

# 5) execução ponta a ponta do motor real
python3 apk-real-host-run/gen_tiny_gguf022.py                         # gera /tmp/tiny-llama-022.gguf
gcc -O2 -I<llama.cpp>/include -I<llama.cpp>/ggml/include \
    apk-real-host-run/driver_full.c -o /tmp/android-run/driver_full -ldl -rdynamic
LD_LIBRARY_PATH=/tmp/android-run /tmp/android-run/driver_full /tmp/tiny-llama-022.gguf
```

## Limitações deste ambiente (bloqueios confirmados)

- **Download do Gemma 4 E2B impossível aqui**: `huggingface.co`, `hf-mirror.com`,
  `cdn-lfs.huggingface.co`, `registry.ollama.ai`, `modelscope.cn`,
  `media.githubusercontent.com` (LFS) e `objects.githubusercontent.com`
  (release assets) respondem todos `000` (SNI bloqueado). Só `github.com` /
  `api.github.com` / `codeload.github.com` respondem — e um GGUF de 3 GB não
  cabe num repositório git (limite 100 MB) nem em LFS (bloqueado).
- **"Q1" não existe para Gemma 4 E2B**; quants disponíveis (unsloth):
  `Q4_K_M` (3,11 GB), `Q5_K_M`, `Q8_0`, `BF16` (e `Q2_K_P` no repo "uncensored").
  **mmproj é BF16** (~992 MB); não há "mmproj Q4" (K-quants não alinham no
  projetor da série E — só BF16).
- **Sem Android**: não há emulador/SDK/Java/adb/KVM e `dl.google.com` está
  bloqueado; por isso a execução do APK aqui é a **execução do motor nativo
  real do APK** no host (mesmo caminho de código que roda no aparelho).
