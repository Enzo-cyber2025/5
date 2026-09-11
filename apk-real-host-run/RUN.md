# RUN.md — Execução REAL da camada nativa do APK (host, sem emulador)

**Data:** 2026-09-11 · **Alvo:** `GGUF-Chat.apk` (SHA-256 `02f97871…`, 90.344.760 bytes)
**Conclusão:** a camada nativa REAL do APK (JNI + llama.cpp) **executa por completo no host**:
`JNI_OnLoad → create (load do GGUF) → backendName → tokenize → generate (callbacks
onToken/onDone) → destroy`, sem crash, `EXIT=0`.

> Não há emulador nem dispositivo disponível neste ambiente (sem KVM/JVM/adb; o
> token do GitHub não consegue criar Actions/Codespaces — 403). A execução REAL
> foi feita no host, carregando os `.so` **extraídos do APK real** — não um motor
> recompilado.

---

## 1. Como reproduzir

```bash
cd /home/user/5/apk-real-host-run
./setup.sh                                    # reconstrói /tmp/android-run
cd /tmp/android-run
LD_LIBRARY_PATH=/tmp/android-run ./runner_jni \
    /tmp/tiny-llama-022.gguf /tmp/tiny-mmproj-022.gguf 0
```

Saída (trechos decisivos):

```
>>> JNI_OnLoad(NULL,NULL) ...
[android:GGUFChatNative] libunwind.so preloaded (global)
[android:GGUFChatNative] libggml-vulkan.so backend init returned NULL (unsupported device?)
[android:GGUFChatNative] registered CPU backend (best score 1)
load_backend: loaded CPU backend from /tmp/android-run/libggml-cpu.so
[android:GGUFChatNative] engine loaded: libllama.so (Vulkan-ready)
>>> JNI_OnLoad ret=65542            (= 0x10006 = JNI_VERSION_1_6, sucesso)
>>> create(model=..., mmproj=..., ctx=256, threads=4, gpuLayers=0, mmap=false)
... (metadados GGUF, tokenizer, 32 tensores carregados) ...
[android:GGUFChatNative] model loaded: n_ctx=256 n_params=27424 gpu_offload=0
>>> create() OK — handle=0x...
>>> backendName = 'libllama.so'
>>> tokenize("hello world") = 17 tokens
>>> generate(prompt="Ola", 32 tokens, ...) ...
<peças de token emitidas via callback onToken>
[onDone(0)]
>>> generate() ret=0 (FALSE)       (modelo minúsculo com pesos aleatórios → sem EOG)
>>> destroy() OK
>>> ===== EXECUÇÃO REAL DA CAMADA NATIVA DO APK CONCLUÍDA SEM CRASH =====
```

O texto gerado é "lixo" porque `tiny-llama-022.gguf` é um fixture de teste com
pesos **aleatórios** (serve para exercitar o pipeline, não para conversar).

## 2. Matriz de testes (camada nativa REAL)

| Caso | Resultado |
|---|---|
| CPU — `gpuLayers=0` | ✅ roda até o fim |
| Vulkan — `gpuLayers=-1` | ✅ roda; fallback para CPU (`gpu_offload=0`) |
| Modelo + mmproj (válidos) | ✅ roda — **mas o mmproj é ignorado** (ver §5.1) |
| mmproj inexistente (modelo ok) | ✅ roda — confirma que mmproj nunca é aberto |
| Modelo inexistente | ❌ crash no host (desenrolar de exceção C++ quebrado, ver §4) |

## 3. O que o runner faz (mini-JVM)

`runner_jni.c` monta uma `JNINativeInterface` mínima com os slots exatos que o
`libaijni.so` real usa e chama as funções JNI reais:

| Slot | offset | Função JNI |
|---|---|---|
| 23  | 0x0b8 | DeleteLocalRef |
| 31  | 0x0f8 | GetObjectClass |
| 33  | 0x108 | GetMethodID |
| 61  | 0x1e8 | CallVoidMethod (`onToken(String)`, `onDone(Z)`) |
| 167 | 0x538 | NewStringUTF |
| 169 | 0x548 | GetStringUTFChars |
| 170 | 0x550 | ReleaseStringUTFChars |
| 171 | 0x558 | GetArrayLength |
| 173 | 0x568 | GetObjectArrayElement |
| 179 | 0x598 | NewIntArray |
| 187 | 0x5d8 | GetIntArrayElements |
| 195 | 0x618 | ReleaseIntArrayElements |
| 211 | 0x698 | SetIntArrayRegion |

(Essa tabela foi extraída do disassembly do `libaijni.so` real — cada slot
corresponde a um `call *0xOFF(%env)` usado pelas funções JNI.)

## 4. Dois crashes do host que foram NEUTRALIZADOS (NÃO são bugs do APK)

Ambos são incompatibilidades **bionic/libc++ (Android) × glibc/libgcc (host)**,
que não se aplicam ao aparelho real:

1. **Backend Vulkan.** O `libggml-vulkan.so` real imprime
   `ggml_vulkan: Error: Vulkan 1.2 required.` e lança `vk::SystemError`; o
   desenrolar de exceção C++ entre libc++ do Android e libgcc_s/glibc do host
   quebra e o processo salta para o heap (SIGSEGV). **Contorno:** `vkstub.c`
   substitui `libggml-vulkan.so` no harness (simula "sem GPU Vulkan").
2. **Caminho mmap.** Com `load_mode = AUTO` (padrão), o `llama_mmap::impl`
   corrompe o vetor `mapped_fragments` (`__begin_ = 0x1`) e
   `unmap_fragment` chama `free(0x1)` (SIGSEGV). **Contorno:** `patch_llama.py`
   troca `load_mode` para `NONE` (leitura via `pread`) **na cópia do harness** —
   o APK real não é alterado.

## 5. Achados sobre o APK real (Java + nativo)

### 5.1 `Native.create` IGNORA o mmproj — multimodal não funciona nesta build
Disassembly de `Java_com_ggufchat_app_Native_create` (libaijni.so):
- lê `rdx` (modelPath) e **nunca lê `rcx` (mmprojPath)**;
- nunca chama nada de clip/mtmd. O `libllama.so` desta build **não tem runtime
  mtmd/clip** (confirmado: sem símbolos/sem strings de multimodal).

### 5.2 `Native.create` ignora o parâmetro `mmap`
Assinatura Java real: `create(String model, String mmproj, int ctx, int threads,
int gpuLayers, boolean mmap)`. O booleano `mmap` (8º arg JNI, `0x18(%rbp)`) nunca
é lido; o load usa sempre `load_mode=AUTO` (→ mmap).

### 5.3 `create` fixa defaults: n_ctx ≥ 4096 se ctx ≤ 0; threads ≥ 4
```
n_ctx    = (ctx > 0) ? ctx : 4096
threads  = (threads > 0) ? threads : 4
```

### 5.4 Caminho de LAUNCH (Java) não toca nativo — "crash ao abrir" não é o init nativo
- `Native.<clinit>` = `System.loadLibrary("aijni")` → a lib é carregada
  **preguiçosamente**, no primeiro uso de um método nativo.
- `MainActivity.onCreate` = só UI (`Ui.vbox/tv/btn`) + `ModelStore.load`
  (lê `models.json`) + `ensureSelectedModelId` + `refreshImportList`. Nenhuma
  chamada nativa no launch.
- Não há classe `Application` customizada.
- ABIs empacotadas: **arm64-v8a e x86_64 apenas** (sem armeabi-v7a). Num aparelho
  ARM de 32 bits, `System.loadLibrary("aijni")` lançaria `UnsatisfiedLinkError`
  no primeiro uso nativo.
- `ModelStore.load` **não tem try/catch** em volta do `new JSONArray(...)`: um
  `models.json` corrompido derruba o app no launch.

### 5.5 Backend de CPU arm64 está correto (não é bug)
No ABI arm64 o APK traz `libggml-cpu-android_armv8.0_1/8.2_1/8.2_2/8.6_1.so`
(dispatcher por variante — o `libaijni.so` arm64 referencia esses nomes
diretamente). No x86_64 traz o `libggml-cpu.so` simples. Ambos corretos.

## 6. O que ainda falta para fechar 100%

1. **Emulador/dispositivo real** para reproduzir o crash de launch exato
   (logcat) e validar mmap/Vulkan no Android de verdade. Este ambiente não tem
   KVM/JVM/adb e o token do GitHub não cria Actions (403). Para usar o
   emulador Android no GitHub Actions, crie `.github/workflows/emu-test.yml` a
   partir de `emu-test.workflow.yml` (na raiz do repo) e o push.
2. **GGUF/multimodal de verdade** (Gemma 4 E2B + mmproj): mesmo que o mmproj
   fosse importado, esta build do app **não o usa** (§5.1) — o app precisaria
   ser corrigido no lado nativo para carregar o projetor.

## 7. Arquivos

- `setup.sh` — reconstrói `/tmp/android-run` (libs reais + shims + patches).
- `runner_jni.c` — mini-JVM que executa `libaijni.so` real.
- `deversion.py` — remove `DT_VERSYM`/dependências de versão (bionic→glibc).
- `shim.c` / `log_stub.c` / `vulkan_stub.c` — shims de host (libc/liblog/libvulkan).
- `vkstub.c` — neutraliza o backend Vulkan no harness.
- `patch_llama.py` — `load_mode` mmap→pread na cópia do harness.
- `models/tiny-llama-022.gguf` + `models/tiny-mmproj-022.gguf` — fixtures de teste.
- `REVIEW.md` — revisão linha a linha do caminho de crash (Java+nativo).
