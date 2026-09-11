# Revisão linha por linha do caminho de crash (Java + nativo)

Fonte: classes.dex do `GGUF-Chat.apk` (descompilado com androguard) + `libaijni.so`
x86_64 (disassembly). Registra o que foi verificado **e** os achados reais.

## Fluxo de abertura de conversa (onde o app morre)

```
ChatActivity.onCreate()
  └─ beginModelLoad()                       // roda em background thread
       └─ ChatActivity$16.run()
            └─ EngineManager.load(modelPath, mmprojPath, contextSize, nThreads, gpuLayers, useMmap)
                 └─ Native.create(...)      // JNI → libaijni.so
                      ├─ llama_backend_init()
                      ├─ llama_model_load_from_file()
                      ├─ llama_new_context_with_model()   // API deprecated
                      └─ llama_sampler_chain_init()
```

## Achados

### 1. Java não é a origem do crash — o crash é NATIVO
`ChatActivity$16.run()` envolve `EngineManager.load(...)` em `try/catch`; qualquer
`Exception` (inclusive `UnsatisfiedLinkError` e falha do motor) vira um **toast**
("Não foi possível carregar o modelo…"), não derruba o processo.
→ Se o app **fecha** (SIGSEGV/SIGABRT/SIGTRAP), é dentro de
`libllama.so`/`libggml-*.so`/`libaijni.so`, antes de voltar pro Java.

### 2. `EngineManager.load` — cache e normalização de "null": CORRETOS
Bytecode verificado (`load(String,String,int,int,int,boolean)J`):
- Normaliza `mmprojPath`: `""` → `null`, string `"null"` → `null`, caminho real é mantido.
- Reusa o handle só quando **modelo E mmproj batem exatamente**; senão recria o motor.
- Fallback GPU→CPU: se `create(gpuLayers≠0)` falha, tenta `create(gpuLayers=0)`.

### 3. BUG (menor): `GenerationService.runGeneration` não trata falha do load
`EngineManager.load(...)` é chamado **fora** do `try/catch` (só o WebSearch está
protegido). Se o load lançar exceção (modelo falhou 2×), ela não é capturada no
worker thread `gguf-generate` → o thread morre **sem** enviar `broadcastDone/Error`
→ a conversa fica em "Gerando…" para sempre (travamento de UX, não crash).

### 4. ACHADO IMPORTANTE: `Native.create` IGNORA o mmproj e fixa n_ctx=4096
Disassembly de `Java_com_ggufchat_app_Native_create` (libaijni.so, x86_64):
- Chama `g_llama_model_load_from_file(model)` — **o `mmprojPath` não é passado a
  nenhuma função llama/mtmd**. O `libllama.so` do APK **não exporta** símbolos
  mtmd/clip (`clip_*`, `mtmd_*` ausentes; a string interna é "CLIP is a
  quant-only stub").
  → O "multimodal" desta compilação é **só de UI**: o projetor é vinculado e
  salvo, mas o motor carrega apenas o GGUF de texto. Visão/áudio não funcionam.
- `llama_new_context_with_model` é chamado com **n_ctx fixo = 0x1000 (4096)** e
  n_batch=0x200 (512) — o `contextSize` da conversa é ignorado; n_threads=4 vem
  do argumento; `gpuLayers` é gravado em `n_gpu_layers`.

### 5. Conclusão
O bug que faz o processo **morrer** está no lado nativo (llama/ggml) e depende do
dispositivo (Vulkan) e do modelo. O único jeito de achar o próximo crash é rodar
o APK de verdade — no emulador GitHub Actions (ver `emu-test.workflow.yml` na raiz
do repo). O bot do Arena não tem permissão para criar `.github/workflows/*`
(403 "Resource not accessible by integration"), então o arquivo precisa ser criado
por você: **1 ação** e eu disparo + monitoro + corrijo o que aparecer.
