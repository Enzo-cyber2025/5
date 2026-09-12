# Correções de bytecode do GGUF-Chat.apk

Dois bugs no `classes.dex` do APK original, corrigidos por patch de bytes
(offsets absolutos, verificados com asserção de bytes antes de gravar):

## 1) Fusão não persistia — `ModelInfo.fromJson`
O desvio do campo `mmprojPath` estava **invertido** (`if-nez` no lugar de
`if-eqz`), então qualquer path válido virava `null` ao recarregar `models.json`
— a fusão modelo+mmproj não sobrevivia ao reload.
Detalhes: [`../BUG-FUSAO-MODELINFO-FROMJSON.md`](../BUG-FUSAO-MODELINFO-FROMJSON.md).

```
offset 0x11C28:  0x39 (if-nez)  →  0x38 (if-eqz)
```

## 2) Crash no launch — `MainActivity.showMmprojPicker` (VerifyError)
O ART rejeitava a classe na inicialização:

```
java.lang.VerifyError: Verifier rejected class com.ggufchat.app.MainActivity:
void ...showMmprojPicker(ModelInfo, ArrayList) failed to verify:
[0x58] register v1 has type Integer but expected Float
```

Causa: `Ui.dp(Context;F)I` era chamado com registrador **int** — o compilador
reusou `v1`/`v6` depois de `move-result` (que passa a guardar int). Os dois
`invoke-static` redundantes foram substituídos por `move`, mantendo exatamente
os mesmos valores de padding:

```java
row.setPadding(dp(14), dp(10), dp(14), dp(10));
```

```
offset 0x11190 (16 bytes):
  71 20 42 02 1b 00 0a 07   invoke-static {v1,v11}, Ui.dp ; move-result v7
  71 20 42 02 6b 00 0a 08   invoke-static {v6,v11}, Ui.dp ; move-result v8
  ↓
  01 17 00 00 00 00         move v7, v1   ; right = left  (dp(14))
  01 68 00 00 00 00         move v8, v6   ; bottom = top (dp(10))
  00 00 00 00               nop (mantém o tamanho do método intacto)
```

O tamanho do método não muda, então os desvios de `goto`/`if` continuam válidos.

## Arquivos
- `patch_dex.py` — aplica **os dois patches** no `classes.dex` (com asserção dos
  bytes originais; recalcula checksum/signature do header dex). É o que o CI usa
  (embutido no workflow `emu-test-arm64.yml`).
- `patch_fusion_bug.py` — versão antiga, só o patch 1 (mantida por histórico).
- `rebuild_and_sign.py` — reconstrói o APK e assina v1+v2 em Python. **Não é mais
  usado pelo CI** (o runner usa o `apksigner` oficial do SDK, mais confiável).

## Validação do patch 2 (showMmprojPicker)
- Verificador de tipos local (dataflow int/float/ref estilo ART) sobre o
  `classes.dex` original: reporta **exatamente** os 2 erros em code-unit `0x58`
  e `0x5c` — idêntico à mensagem do ART — e nada mais no dex inteiro.
- Sobre o dex corrigido: **0 erros** e 0 registradores indefinidos.
- A validação de verdade é o emulador no CI (launch + importação via UI).
