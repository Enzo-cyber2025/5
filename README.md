# GGUF Chat — correções verificáveis

Correções para o **GGUF Chat 2.0 (`com.ggufchat.app`)**, baseadas no APK original da
branch `arena/01a077ef-5`, commit `90b737409db091ca8c4d75a33b9d5d27748dbacb`.
O trabalho desta sessão fica em **`arena/01a09b42-5`**; nenhuma outra branch é modificada.

## O que foi corrigido

- **Conversa perdia o modelo e o projetor:** dois desvios invertidos em
  `Chat.fromJson()` anulavam `modelPath` e `mmprojPath` ao reler uma conversa.
- **Vínculo de visão não persistia:** preservado o patch de `ModelInfo.fromJson()`.
- **Projetor descartado antes da inferência:** outro desvio invertido em
  `EngineManager.load()` apagava um caminho `mmproj` válido antes de `Native.create()`.
- **Configurações ignoradas pelo cache:** contexto, threads, camadas GPU e mmap
  agora fazem parte da chave do motor. Configuração idêntica ainda reutiliza o motor;
  uma alteração o recria. O fallback CPU mantém a configuração solicitada na chave.
- **Arquivo ausente/inválido:** o carregador verifica arquivo, leitura, tamanho
  mínimo, magic GGUF e versão 2/3 antes de chamar a biblioteca nativa. Uma tentativa
  inválida não destrói um motor válido já carregado. Não é validação completa dos tensores.
- **Falha nativa apresentada como sucesso:** `GenerationService` agora verifica o
  booleano de `Native.generate()` e encaminha falhas ao tratamento de erro existente.
- **VerifyError ao abrir:** preservado o patch int/float de `showMmprojPicker()`.

As bibliotecas nativas, recursos, permissões, package name e SDKs do APK original
**não foram trocados**. Apenas `classes.dex` e a assinatura foram alterados.
Este repositório contém o código de reparo; não substitui o APK por uma interface
simulada, nem reimplementa o motor nativo.

## Estado da validação

**APK reconstruído, assinatura v2/v3 verificada pelo `apksigner` oficial e 54 testes
locais aprovados. Ainda não validado de ponta a ponta em Android nesta sessão.**

Os testes de host executam classes reais do APK, traduzidas de DEX para JVM, com
substitutos explícitos de `Native` e `org.json`. Isso permite verificar controle de
fluxo, persistência e cache, mas **não comprova inferência nativa, Vulkan ou câmera**.
Veja [docs/VALIDACAO.md](docs/VALIDACAO.md) para evidências e limites.

O APK gerado é `entrega/GGUF-Chat-repaired.apk` no workspace da sessão, acompanhado
pelo SHA-256. Binários, modelos, dependências e chaves **não são versionados no Git**.
Em uma cópia limpa, gere o APK pelos comandos abaixo ou pelo workflow.

### Instalação com cuidado

O APK usa **uma nova chave local de teste**, diferente da assinatura anterior.
O Android pode recusar atualização por cima da versão instalada. **Não desinstale
sem antes preservar conversas e modelos importantes**: desinstalar apaga dados
privados do aplicativo. Se não puder salvá-los, teste em outro aparelho/emulador.
Não foi feita migração nem recuperação de conversas que já tenham sido salvas com
caminhos nulos; pode ser necessário criar novamente a conversa/importar os modelos.

## Reproduzir o build

Requisitos: Python 3.11+, Node/npm e `gh` conectado ao GitHub para obter o APK original.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
bash scripts/fetch_tools.sh
python3 scripts/fetch_original.py

export JAVA_HOME=$(.venv/bin/python -c 'import jdk4py; print(jdk4py.JAVA_HOME)')
export APKTOOL_JAR="$PWD/.cache/tools/package/lib/apktool.jar"
export APKSIGNER_JAR="$PWD/.cache/tools/package/lib/apksigner.jar"

# Chave LOCAL DE TESTE. Para atualizações futuras, preserve uma keystore própria
# e sua senha fora do Git; não regenere a chave em cada distribuição.
export GGUF_KEYSTORE_PASSWORD=$(openssl rand -hex 32)
bash apk-fix/rebuild_on_runner.sh
```

A saída padrão é `dist/GGUF-Chat-repaired.apk`. Para reutilizar sua keystore, defina
`GGUF_KEYSTORE`, `GGUF_KEY_ALIAS` e `GGUF_KEYSTORE_PASSWORD` corretamente.
Não envie senhas ou chaves ao chat/repositório. O workflow gera chaves descartáveis:
seus artefatos são builds de teste, **não uma sequência de updates assinados igual**.

O build rejeita APK/DEX desconhecidos por SHA-256, usa ferramentas fixadas por hash,
recalcula os checksums DEX, recompila o smali, alinha entradas ZIP não comprimidas,
assina com `apksigner` e compara todos os recursos/libs com o original.
Não há assinatura APK implementada à mão em Python.

## Testes locais

```bash
.venv/bin/python -m pytest -q tests/test_tooling.py
bash scripts/test_host.sh dist/GGUF-Chat-repaired.apk
```

Para reproduzir os bugs anteriores, execute as expectativas de regressão contra o
JAR traduzido do APK original; o relatório registra **21 falhas** nessa comparação.
Os quatro testes da nova classe `GenerationResult` só existem na versão corrigida.

## Testes reais no Android

Use **somente emulador descartável**, Google APIs com `adb root` (não Play Store).
O teste limpa os dados de `com.ggufchat.app`, importa via SAF, exige uma resposta
persistida de `assistant` e o resultado positivo real de `Native.generate()`, tenta
GPU e testa erro de arquivo ausente. Nunca usa textos do seletor como respostas.

```bash
export ANDROID_SERIAL=emulator-5554
export GGUF_TEST_MODEL=/caminho/para/modelo-real.gguf
export GGUF_OUTPUT_APK="$PWD/dist/GGUF-Chat-repaired.apk"
bash .github/emu-test-x86.sh
```

- `GGUF_TEST_VISION` e `GGUF_TEST_MMPROJ`: par compatível opcional para verificar
  importação/vínculo/persistência. Sem esse par, a etapa é marcada **SKIP**.
- `GGUF_REQUIRE_VULKAN=1`: exige evidência de camadas realmente enviadas à GPU;
  carregar uma biblioteca Vulkan ou usar fallback CPU não passa essa exigência.
- Evidências em `evidence/summary.json`, comandos, dumps de UI e logs.
- Qualquer falha obrigatória retorna código diferente de zero, propagado pelos wrappers.

O modelo de workflow está em [`ci/gguf-repair.yml`](ci/gguf-repair.yml).
**Ainda não está ativo:** o GitHub recusou a publicação em `.github/workflows/`
porque a conexão do Arena não possui a permissão `workflows`.

Para executar, no próprio GitHub e na branch `arena/01a09b42-5`, copie esse arquivo
para `.github/workflows/gguf-repair.yml` e salve o commit **nesta mesma branch**.
O evento `push` iniciará o build e o emulador, com download de um modelo real.
Em uma execução manual posterior, marque `run_android` para repetir o emulador.
Isso consome minutos do GitHub Actions. Não há execução em emulador concluída ainda.

O workflow publica **artefatos de Actions**, sem force-push e sem escrever em outras branches.
O workflow antigo do repositório não foi alterado; o erro histórico dos pontos em
`timeout-minutes` já estava resolvido.
