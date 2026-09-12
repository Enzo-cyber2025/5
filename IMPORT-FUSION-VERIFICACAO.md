# Verificação do fluxo de importação (GGUF + mmproj "fundidos") — bytecode real

Análise feita em 2026-09-12 sobre o `classes.dex` REAL extraído de `GGUF-Chat.apk`
(90.344.760 bytes, SHA-256 `02f97871…`). Ferramenta: androguard 4.1.4 (dex
disassembly), classe por classe, método por método.

## O que o usuário pediu
- Importar uma IA com mmproj pela UI gráfica (usando swap no emulador).
- O modelo principal e o GGUF/mmproj devem ser **fundidos na importação**.

## O que o bytecode mostra (fluxo real, não suposição)

### 1. Dois pontos de entrada de importação
- **Aba "📁 Importar" (MainActivity)**: um botão "Importar .gguf" →
  `openImportPicker(REQ_IMPORT_SINGLE=11)` → `ACTION_OPEN_DOCUMENT` com
  `EXTRA_ALLOW_MULTIPLE=true` (multi-seleção). `onActivityResult` coleta todos
  os URIs (ClipData ou `getData()`) e importa **em cadeia**
  (`MainActivity$26` → importa o próximo URI). Ao final, chama `linkMmprojs()`.
- **Tela "AI Modelos" (ModelsActivity)**: dois botões:
  - "Importar modelo GGUF" → `openPicker(1)` (arquivo único).
  - "Importar 2 GGUFs (texto + mmproj)" → `openPicker(2)` (texto) → depois de
    copiar, `ModelsActivity$6` mostra "Agora escolha o modelo multimodal
    (mmproj)…" → `openPicker(3)` (mmproj).

### 2. A cópia é segura (GGUFImport)
`copyIntoModels`: copia para `models/<nome>.part` (buffer 1 MiB, progresso
`onProgress`), e só então `renameTo` para o nome final; em erro apaga o `.part`
e retorna `null` → UI mostra "Falha ao importar o arquivo." (sem crash).

### 3. Metadados lidos do GGUF (GGUFMeta → ModelInfo)
Cada arquivo vira um `ModelInfo{id, name, architecture, fileName, path, size,
mmprojPath, multimodal, importedAt}`. `architecture` vem de
`general.architecture`; `name` de `general.name` (fallback `general.basename`,
fallback nome do arquivo). O nome do arquivo é sanitizado
(`[^A-Za-z0-9._-]`→`_`, máx 96 chars, prefixo timestamp).

### 4. A FUSÃO existe e é persistida
- `mergeAndCreate(textModel, mmproj)`:
  `textModel.mmprojPath = mmproj.path; textModel.multimodal = true;`
  persiste em `models.json` (ModelStore.save → writeAtomic com `FileDescriptor.sync()`).
- `linkMmprojs()` (auto-vínculo após importação em lote): para cada entrada
  mmproj ainda não referenciada, acha o modelo de visão cujo nome de arquivo
  casa (retirando a substring "mmproj"); se não casar, vincula ao 1º modelo de
  visão sem mmproj. Salva e avisa "Projetor (mmproj) vinculado automaticamente."
- `finishNewChat(model)` (ao tocar num modelo):
  1. se `model.mmprojPath != null` → `mergeAndCreate(model, byPath(mmprojPath))`.
  2. senão, se é modelo de visão (`llava/mllama/minicpm/qwen*_vl/internvl/pixtral/gpt-oss`)
     → `findMmprojFor()` (heurística de nome) e `mergeAndCreate`.
  3. senão, se há mmprojs importados → `showMmprojPicker()` (dialog
     "Selecione o projetor (mmproj)" com opção "Sem projetor (só texto)").
  4. senão → conversa só-texto.
- Detecção de mmproj: `isMmproj` = nome contém "mmproj" OU arquitetura contém
  "clip". (mmproj GGUF reais têm `general.architecture = "clip"`.)

### 5. A fusão chega até a camada nativa
`Chat{modelPath, mmprojPath, contextSize, nThreads, gpuLayers, useMmap, …}`.
`ChatActivity$16` → `EngineManager.load(modelPath, mmprojPath, ctx, threads,
gpu, mmap)` → `Native.create(modelPath, mmprojPath, ctx, gpu, threads, mmap)`
(o mmproj vazio/"null" vira `null` antes do call). `EngineManager` cacheia o
handle por (path, mmproj) e recarrega/destrói quando muda.

## Conclusão
- A "fusão" exigida **existe e é persistida** em dois níveis: `ModelInfo`
  (`mmprojPath`+`multimodal`) e `Chat` (`modelPath`+`mmprojPath`).
- **Não foi encontrado bug de crash** no caminho importação→fusão→abrir chat.
- Observação menor (não-crash): `linkMmprojs()` cai num fallback que vincula ao
  1º modelo de visão quando os nomes não casam — com múltiplos modelos de visão
  + múltiplos mmprojs pode parear errado (é o fluxo automático; o seletor
  manual `showMmprojPicker` cobre o caso).

## Bloqueio do teste PELA UI (emulador) — estado em 2026-09-12
1. **Host x86_64 sem KVM** + imagem Android **arm64** só existe nos hosts
   bloqueados pela rede (`dl.google.com`, `ci.android.com`,
   `storage.googleapis.com`, gitlab.com = HTTP 000). O QEMU-system aarch64
   (npm, acessível) e o adb (git) já foram montados; falta SÓ a partição
   `system` (submodule gitlab bloqueado do AluminiumOS).
2. **GitHub Actions**: o token desta sessão (`arena-ai-coding-agent[bot]`) tem
   `contents:write` (o push do código funciona), mas **não tem `workflows`**:
   o push de `.github/workflows/*.yml` é rejeitado com
   "refusing to allow a GitHub App to create or update workflow … without
   `workflows` permission" (testado hoje). Sem isso o runner `macos-14` (host
   arm64) não dispara.
```
