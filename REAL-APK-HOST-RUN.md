# Execução REAL do APK no host (Java + nativo) — sem emulador

**Data:** 2026-09-12 · **APK:** `GGUF-Chat.apk` (90.344.760 bytes)

Como o emulador continua inacessível deste sandbox (sem KVM, rede bloqueada,
token sem permissão `workflows` — ver `EMULATOR.md`), o APK **real** foi
executado no próprio host, em duas camadas:

1. **Java real:** o `classes.dex` do APK (88 classes) convertido para bytecode
   JVM (`enjarify` → `/tmp/app.jar`), rodado num **JDK 8** obtido localmente
   (`aosp-mirror-neo/platform_prebuilts_jdk_jdk8`, sparse checkout).
2. **Nativo real:** as `.so` x86_64 do APK (`libaijni.so` → `libggml*` →
   `libllama.so`) carregadas via JNI real (`System.loadLibrary("aijni")`), com
   stubs mínimos de `android.content.Context/ContentResolver`,
   `android.database.Cursor` e `android.net.Uri`.

### Comando

```
LD_LIBRARY_PATH=/tmp/android-run \
$JDK/bin/java -Djava.library.path=/tmp/android-run \
  -cp out:/tmp/app.jar RunApp /tmp/tiny-llama.gguf /tmp/tiny-mmproj.gguf
```

`RunApp.java` dirige as classes REAIS do app (`GGUFImport`, `GGUFMeta`,
`ModelInfo`, `ModelStore`, `EngineManager`, `Native`) na sequência do fluxo
real de importação → fusão → carregamento nativo.

### Resultado (resumo do log real, `/tmp/run_appjvm.log`)

```
importado: tiny-llama.gguf -> /tmp/appdata/models/tiny-llama.gguf   (GGUFImport.copyIntoModels)
meta do GGUF: architecture=llama name=tiny-llama                    (GGUFMeta.read)
mmproj: architecture=clip projector=mlp                             (GGUFMeta.read)
[android:GGUFChatNative] libggml-vulkan.so backend init returned NULL
[android:GGUFChatNative] registered CPU backend (best score 1)
[android:GGUFChatNative] engine loaded: libllama.so (Vulkan-ready)
[android:GGUFChatNative] model loaded: n_ctx=256 n_params=26912 gpu_offload=0
handle=139871516984016 backend=libllama.so                          (Native.backendName)
tokenize("Hello world") = 17 tokens
generate("Ola", 32, temp=0.8) -> [onDone false], ret=false (0 tokens)
destroy() OK
EXIT=0
```

- **Importação real:** `GGUFImport.copyIntoModels` copiou os dois GGUFs para
  `models/`.
- **Metadados reais:** `GGUFMeta` leu `architecture`/`name`/`projector`.
- **Nativo real:** `libllama.so` carregou o modelo, registrou o backend CPU
  (`backendName = 'libllama.so'`), sem crash, `EXIT=0`.

### O que isso permitiu encontrar

- **BUG real (Java):** `ModelInfo.fromJson()` anula o `mmprojPath` ao recarregar
  `models.json` → a fusão não persiste. Prova + bytecode:
  [`BUG-FUSAO-MODELINFO-FROMJSON.md`](BUG-FUSAO-MODELINFO-FROMJSON.md).
- `generate=false` / `detokenize=null` vieram do **fixture sintético**
  (vocab incompleto, `vocab type = unknown`), não do APK — confirmado no
  disassembly do `libaijni.so`/`libllama.so` (as chamadas JNI passam o
  `llama_vocab*` corretamente para a API nova do llama.cpp).

> Isto **não** substitui o teste pela UI gráfica no emulador arm64 (critério
> ainda em aberto), mas executa o código REAL do APK e já expôs um defeito real
> de persistência da fusão.
