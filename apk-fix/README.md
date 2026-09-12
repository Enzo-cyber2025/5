# Correção do bug de persistência da fusão (ModelInfo.fromJson)

## O bug
`ModelInfo.fromJson()` tinha o desvio do `mmprojPath` **invertido**
(`if-nez` no lugar de `if-eqz`), então qualquer path válido virava `null` ao
recarregar `models.json` — a fusão modelo+mmproj não sobrevivia ao reload.
Detalhes: [`../BUG-FUSAO-MODELINFO-FROMJSON.md`](../BUG-FUSAO-MODELINFO-FROMJSON.md).

## A correção
Troca de **1 byte** no `classes.dex` (opcode `0x39` → `0x38` no offset `0x11C28`),
sem alterar assinaturas de métodos nem recursos.

```
ModelInfo.fromJson:  if-nez v2, +004h  →  if-eqz v2, +004h
```

## Arquivos
- `patch_fusion_bug.py` — aplica o patch no `classes.dex` (idempotente, recalcula
  checksum/signature do header dex).
- `rebuild_and_sign.py` — reconstrói o APK (troca `classes.dex`, remove assinatura
  antiga) e assina **v1 (JAR, via `jarsigner`) + v2 (APK Signature Scheme v2,
  implementado em Python)**.
- `key.p12` / `key.pem` / `cert.pem` — chave de teste RSA-2048 auto-assinada
  (CN=GGUF-Chat Fix). **É uma chave descartável de teste**, sem identidade real.
  Gerada por `keytool`; o script regenera se ausente.

## Como usar
```bash
# 1) corrige o dex
python3 apk-fix/patch_fusion_bug.py GGUF-Chat.apk /tmp/classes-fixed.dex

# 2) reconstrói + assina v1/v2
python3 apk-fix/rebuild_and_sign.py GGUF-Chat.apk /tmp/classes-fixed.dex GGUF-Chat-fixed.apk
```

## Validação feita
1. **Round-trip** (bytecode real em JDK 8): `toJson()` grava
   `"mmprojPath":"/.../tiny-mmproj.gguf"` e `fromJson()` devolve o **mesmo path**
   (antes devolvia `null`).
2. **Fluxo completo** (import→fuse→save→reload): a fusão **persiste**
   (`FUSAO: tiny-llama mmprojPath=/tmp/appdata/models/tiny-mmproj.gguf multimodal=true`).
3. **Formato v2**: o parser/escritor foi validado byte a byte contra o bloco v2 do
   APK original (assinatura RSA verificada com o certificado embutido
   `CN=GGUF Chat,O=ggufchat,C=BR`).

## Ainda pendente
- Teste **pela UI num emulador** (o sandbox não tem imagem Android 7+ acessível e
  o token do GitHub App não tem permissão `workflows` para disparar o runner arm64).
  No runner, re-assinar com o `apksigner` oficial do SDK é trivial se necessário.
