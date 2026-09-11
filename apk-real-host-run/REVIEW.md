# Revisão do caminho de abertura/crash do GGUF-Chat.apk (Java + nativo)

Fonte: `classes.dex` real (androguard) + `libaijni.so` x86_64 (disassembly/objdump) +
execução REAL do bytecode do APK numa JVM (`jvm-harness`) e da camada nativa REAL
(`apk-real-host-run/RUN.md`).

## O que roda ANTES da primeira tela (fluxo de abertura)

```
Processo Android inicia
  └─ com.ggufchat.app.App.onCreate()               (Application)
       └─ super.onCreate()
       └─ if (Build.VERSION.SDK_INT >= 26) {        // GUARD OK (verificado no DEX)
            new NotificationChannel("geracao", ...)   // API 26+, protegido
            getSystemService("notification").createNotificationChannel(...)
          }
  └─ MainActivity.onCreate()                        (LAUNCHER)
       └─ super.onCreate()
       └─ if (SDK_INT >= 33) check/request POST_NOTIFICATIONS   // guard OK
       └─ UI 100% programática: Ui.vbox/hbox/tv/btn/spacer + navButton×3 + FrameLayout
       └─ setContentView(root)                     // SEM layout XML
       └─ buildChatPage(); buildImportPage(); buildModelsPage(); showTab(0)
  └─ MainActivity.onResume()
       └─ refresh()          → ChatStore.load() + ModelStore.load()   (IO/JSON)
       └─ refreshModels()    → ModelStore.load()
       └─ ensureSelectedModelId() → ModelStore.load()
```

## Achados (verificados no bytecode REAL)

### 1. NADA no caminho de abertura crasha por código Java
- `App.onCreate` **tem guard de versão** (`sget Build.VERSION.SDK_INT` + `if-lt 26`).
  Reproduzido no `jvm-harness` (bytecode REAL do APK): `App.onCreate()` roda sem erro
  com SDK_INT=25 (sem `NotificationChannel` no runtime) e com SDK_INT=33. **Descartada**
  a hipótese de `NoClassDefFoundError` por `NotificationChannel`.
- `MainActivity.onCreate` é **100% programático** — o APK **não tem nenhum layout XML**
  (res/ tem só 5 `ic_launcher.png`; `resources.arsc` = 1.336 bytes). Não há inflate
  para falhar. Guard de `POST_NOTIFICATIONS` (API 33) correto.
- Tema do app = `android:Theme.Material.NoActionBar` (0x0103022e, existe desde API 21).

### 2. NENHUM método do boot toca em Native/EngineManager
Varredura de invokes no `MainActivity`: `onCreate`, `buildChatPage`, `buildImportPage`,
`buildModelsPage`, `showTab`, `refresh`, `refreshModels`, `ensureSelectedModelId`,
`updateModelHeader`, `buildAllModelsPage` **não** referenciam `Native`/`EngineManager`/
`GenerationService`/`loadLibrary`. Só `ModelStore.load`/`ChatStore.load` (IO/JSON).
→ A lib nativa (`System.loadLibrary("aijni")`) só é carregada quando um modelo é
carregado: `ChatActivity.beginModelLoad()` (thread "model-preload") ou `GenerationService`.

### 3. ModelStore.load / ChatStore.load TÊM try/catch (correção)
A tabela de exceção REAL do DEX mostra que ambos capturam `org.json.JSONException` +
`java.io.IOException` + catchall. JSON corrompido em `models.json`/`chats.json` **não**
derruba a abertura (vira lista vazia). A hipótese anterior de "crash por JSON sem
try/catch" estava **errada**.

### 4. `Native.create` IGNORA o mmproj e fixa n_ctx=4096  (bug real de funcionalidade)
Disassembly de `Java_com_ggufchat_app_Native_create`:
- Chama `g_llama_model_load_from_file(model)`; o `mmprojPath` **não é usado**.
  `libllama.so` do APK não exporta símbolos mtmd/clip (string interna "CLIP is a
  quant-only stub"). → o "multimodal" desta compilação é só de UI; visão não funciona.
- `llama_new_context_with_model` com n_ctx **fixo 0x1000 (4096)** e n_batch 0x200 (512):
  o `contextSize` da conversa é ignorado; gpuLayers→n_gpu_layers; threads=4 do arg.
- `create` **checa NULL** após `llama_model_load_from_file` e retorna 0 com `set_err`:
  modelo inexistente NÃO é SIGSEGV (o EXIT=139 do host run era artefato glibc de
  desenrolar exceção, não do app).

### 5. `EngineManager.load` — cache/normalização/fallback CORRETOS
- Normaliza mmproj (`""`/`"null"` → null), reusa handle só se modelo+mmproj batem,
  fallback GPU→CPU (se create(gpu≠0) falha, tenta create(gpu=0)).

### 6. BUG (menor): `GenerationService.runGeneration` não trata falha do load
`EngineManager.load(...)` chamado **fora** do try/catch (só o WebSearch é protegido).
Se o load lançar (modelo falhou 2×), o worker `gguf-generate` morre sem
`broadcastDone/Error` → a conversa fica em "Gerando…" para sempre (UX, não crash).

## Conclusão
- O código Java de abertura do APK **não crasha**; o único ponto em que o processo
  pode MORRER é o carregamento nativo do modelo (llama/ggml), e isso só acontece ao
  abrir uma conversa/gerar — não "antes de abrir".
- Reproduzir o crash "antes de abrir" do dispositivo do usuário exige o **logcat** e a
  **versão do Android** do aparelho (ou um emulador). Ver `EMULATOR.md` para o estado
  do emulador (bloqueio de rede/permissão) e `apk-real-host-run/RUN.md` para a execução
  nativa REAL já concluída.
