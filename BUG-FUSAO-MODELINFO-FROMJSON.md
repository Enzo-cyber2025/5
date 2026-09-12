# BUG REAL encontrado: fusão mmproj é perdida ao recarregar `models.json`

**Data:** 2026-09-12 · **APK analisado:** `GGUF-Chat.apk` (90.344.760 bytes)
**Método:** execução do bytecode Java REAL do APK (`classes.dex` → `/tmp/app.jar`, 88 classes)
+ bibliotecas nativas REAIS (`libaijni.so` → `libllama.so` x86_64) num JDK 8 local.

---

## 1. O bug (resumo)

`ModelInfo.fromJson()` tem um desvio **invertido** no tratamento do campo
`mmprojPath`. Resultado: o `mmprojPath` é **gravado** corretamente no
`models.json` (`toJson()`), mas é **anulado** quando o arquivo é relido
(`fromJson()`).

Ou seja: a fusão modelo principal + projetor (mmproj) **não sobrevive a um
reload** — ela se perde a cada `ModelStore.load()` (que roda em
`refreshImportList`, `startNewChatFlow`, `finishNewChat`, `linkMmprojs`,
`onCreate`, etc.).

---

## 2. Prova empírica (round-trip com o bytecode REAL)

Rodando `ModelInfo.toJson()` → `ModelInfo.fromJson()` com as classes reais:

```
toJson   = {"path":"/tmp/appdata/models/tiny-llama.gguf","fileName":null,
            "importedAt":1789221109253,"size":0,
            "mmprojPath":"/tmp/appdata/models/tiny-mmproj.gguf",
            "name":"tiny-llama","multimodal":true,
            "id":"1a095e37e05","architecture":"llama"}

fromJson = mmprojPath=null  multimodal=true   ← o path virou null!
```

O `toJson` escreve `"mmprojPath":"/tmp/appdata/models/tiny-mmproj.gguf"` (correto),
mas o `fromJson` devolve `mmprojPath=null` para o MESMO JSON.

---

## 3. Causa exata (bytecode)

### 3.1 Smali do `classes.dex` real (androguard)

```
const-string     v1, "mmprojPath"
invoke-virtual   v5, v1, v4, Lorg/json/JSONObject;->optString(...)Ljava/lang/String;
move-result-object v1                 ; v1 = valor lido
if-eqz           v1, +013h            ; se null → guarda null (ok)
const-string     v2, "null"
invoke-virtual   v1, v2, Ljava/lang/String;->equals(...)Z
move-result      v2                   ; v2 = (v1 == "null") ? 1 : 0
if-nez           v2, +004h            ; ← INVERTIDO (deveria ser if-eqz)
const/4          v1, 0                ; v1 = null
goto             +8h
invoke-virtual   v1, Ljava/lang/String;->isEmpty()Z
move-result      v2
if-eqz           v2, +003h
const/4          v1, 0
iput-object      v1, v0, ...mmprojPath
```

### 3.2 Tradução fiel do enjarify (bytecode JVM)

```
118: aload_0
119: ldc  "mmprojPath"
121: aconst_null
122: optString          → aload_3   ; v1 = path
126: ifnull 169                     ; null → guarda null
130: ldc "null"
133: aload_3
135: String.equals
140: iload 6
142: ifne 153                       ; ← se é "null" (TRUE) → isEmpty
145: iconst_0
148: aconst_null
149: astore_3                       ; v1 = null   ← cai aqui quando o path é VÁLIDO!
150: goto 169
153: isEmpty ...
161: ifeq 169                       ; não-vazio → mantém
...
169: putfield mmprojPath
```

### 3.3 Comportamento real resultante

| Valor em `models.json` | Resultado de `fromJson` | Esperado |
|---|---|---|
| `/caminho/real/mmproj.gguf` | **`null`** ❌ | o próprio path |
| `"null"` (string) | **`"null"`** ❌ (mantém a string) | `null` |
| `null` | `null` ✓ | `null` |
| `""` (vazio) | `null` ✓ (por acaso) | `null` |

A lógica pretendida era claramente:

```java
String p = obj.optString("mmprojPath", null);
if (p == null || p.equals("null") || p.isEmpty()) p = null;
info.mmprojPath = p;
```

O branch foi compilado com a condição trocada (`if-nez` no lugar de `if-eqz`),
então **todo path válido vira `null`** e a string literal `"null"` é mantida.

---

## 4. Impacto no app (fluxo real)

O `toJson()` grava a fusão certa em `models.json`:

```json
[{"path":"/tmp/appdata/models/tiny-llama.gguf",
  "mmprojPath":"/tmp/appdata/models/tiny-mmproj.gguf",
  "name":"tiny-llama","multimodal":true,"architecture":"llama", ...}]
```

Mas `MainActivity` chama `ModelStore.load()` em vários pontos
(`refreshImportList`, `startNewChatFlow`, `finishNewChat`, `linkMmprojs`) e a
cada reload o `fromJson` anula o `mmprojPath`. Consequência prática:

- Ao **reabrir o app** (ou reentrar na tela), o vínculo multimodal some:
  o modelo de visão volta a aparecer como só-texto, `finishNewChat` cai no
  `findMmprojFor()`/`showMmprojPicker()` de novo (ou abre sem projetor).
- A fusão **não persiste** — viola o critério de aceite “modelo + mmproj
  fundidos na importação” com padrão “zero bugs”.

---

## 5. O que NÃO é bug (resultado da investigação nativa)

Durante a execução real também se observou `Native.generate(...) → false` e
`Native.detokenize(...) → null` com o modelo sintético de 114 KB. Investigação
no disassembly do `libaijni.so`/`libllama.so` mostrou que **não é bug do APK**:

- O handle do APK é `{ [0]=model, [8]=ctx, [0x10]=vocab, [0x18]=sampler }`.
- As funções `llama_tokenize`/`llama_detokenize`/`llama_token_to_piece`/… desta
  versão do llama.cpp recebem `llama_vocab*` (o 1º campo é o `impl`, por isso o
  wrapper faz `mov rdi,[rdi]`). O JNI passa `[handle+0x10]` = vocab para todas,
  de forma **consistente e correta**.
- O fixture sintético tem vocab incompleto (`vocab type = unknown`, sem merges
  BPE), então `detokenize` devolve vazio e o `llama_decode` do `generate` falha.
  É limitação do modelo de teste, não defeito do APK.

---

## 6. Correção sugerida

Trocar, no `ModelInfo.fromJson`, o desvio `if-nez` pelo `if-eqz` (ou seja,
só anular quando `equals("null")` for verdadeiro), ficando:

```java
String p = obj.optString("mmprojPath", null);
if (p == null || p.equals("null") || p.isEmpty()) p = null;
info.mmprojPath = p;
```

Isso faz o `mmprojPath` persistir e a fusão sobreviver ao reload.
