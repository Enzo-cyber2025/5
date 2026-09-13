# GGUF Chat — modelo único, olho e Vulkan

## [Baixar APK diretamente — sem ZIP](https://github.com/Enzo-cyber2025/5/releases/download/gguf-unified-72d4429/GGUF-Chat-mobile.apk)

**16,7 MB · Android 9+ · ARM64 e x86_64 · mesma assinatura fixa da revisão mobile anterior.**

- GGUF + mmproj selecionados juntos viram **um único registro no armazenamento privado**, com tamanho total e ícone de olho.
- GGUF importado sozinho fica **sem olho**. Os arquivos permanecem GGUFs válidos; não são concatenados.
- Carregamento Vulkan para linguagem **e projetor**, sem fallback automático para CPU. CPU continua como escolha explícita.
- Exclusão conjunta dos componentes, reimportação independente e migração dos pares antigos sem mudar caminhos.
- Barra compacta preservada: chave inglesa ao lado de Enviar, ferramentas inicialmente recolhidas, uma linha e 10 px de intervalo.

**Teste Android aprovado:** [34788194324](https://github.com/Enzo-cyber2025/5/actions/runs/34788194324). SAF real, registro único, olho/sem olho, 31/31 camadas de linguagem e 198 tensores de projetor no Vulkan, duas respostas salvas com PID preservado, reimportação e exclusão.

**Limites:** Vulkan por software Mesa/Lavapipe em emulador x86_64, não GPU física. Carregamento do projetor e geração de texto não comprovam reconhecimento de imagens; não foi acrescentada avaliação de anexos. O olho identifica a união com projetor, não valida essa função de imagem.

**Atualização:** usa o mesmo certificado da versão `gguf-mobile-120e7dc`; não é necessário desinstalá-la por mudança de assinatura. A versão mais antiga `gguf-apk-f6dc954` tem outro certificado: exporte seus dados antes de desinstalá-la.

[Relatório e hashes](docs/UNIFIED.md) · [Evidências originais](ci-results/34788194324-1/summary.json) · [Relatório da revisão mobile anterior](docs/MOBILE.md)

<details>
<summary>Histórico das builds anteriores (não descreve o APK mobile acima)</summary>

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
- **Fim pelo limite de tokens informado como falha:** corrigidos os caminhos
  nativos x86_64/ARM64 para concluir normalmente após todos os decodes solicitados.
  Erros de decode e cancelamentos continuam falhando; não foi removida a checagem.
- **VerifyError ao abrir:** preservado o patch int/float de `showMmprojPicker()`.

- **Modelos ocultos ao criar conversa:** corrigido filtro invertido de `mmproj`.
- **Crash na tela da conversa:** oito acessos privados ilegais em workers foram
  substituídos por accessors sintéticos, preservando os membros privados.
- **Enviar não fazia nada:** corrigido guarda que rejeitava conversas não nulas.
- **Motor não carregava:** adicionada dependência ELF `libdl.so` à ponte JNI nas
  duas arquiteturas. Código executável, `.rodata`, `.data` e SONAME são conferidos.

Recursos, permissões, package name e SDKs não foram trocados. Os reparos anteriores
alteraram DEX, dependências da ponte JNI e assinatura. A etapa Vulkan substitui
`libc++_shared.so` pelo runtime oficial NDK r28c, acrescenta diagnóstico nativo e
um adaptador para a extensão de armazenamento de 16 bits promovida ao Vulkan 1.1.
Nas duas `libggml-vulkan.so`, só 14 bytes de imports/dependência mudam por ABI;
código, shaders e dados protegidos são conferidos. As demais bibliotecas llama/ggml
permanecem iguais. A ponte JNI recebe também o patch limitado de conclusão
por tokens, guardado pelo SHA-256 original. Não há interface nem inferência simulada.

## Estado da validação

**Geração nativa comprovada; qualidade das respostas REPROVADA.**

A execução [34769745227](https://github.com/Enzo-cyber2025/5/actions/runs/34769745227)
aprovou build, assinatura, **37 testes de ferramentas + 33 JVM**, instalação e duas
respostas reais em CPU no Android 11 x86_64, incluindo reinício do processo.
Cada resposta exigiu `Native.generate()` concluído e mensagem de assistant persistida.

**Isso não aprovou a pertinência:** a pergunta “2 + 2” recebeu uma frase sem relação
com a pergunta. Também foi observado erro UTF-8 com acentos numa tentativa anterior.
Importação SAF, português, visão e aparelho ARM64 continuam sem aprovação.
O modelo real foi preparado diretamente no emulador, não importado pelo seletor.

Veja [o relatório de geração e as respostas reais](docs/GERACAO.md).
A automação agora também exige uma verificação básica de pertinência. Essa nova
verificação foi testada localmente e reprovou as saídas gravadas; ainda não houve
novo teste Android em modo CPU após adicioná-la. **Não interprete o run verde anterior como aprovação completa.**

**Teste Vulkan aprovado no emulador:** no [run 34778868262](https://github.com/Enzo-cyber2025/5/actions/runs/34778868262),
revisão `f6dc954`, passaram build/assinatura, **94 testes de ferramentas + 33 JVM**,
controle ABI, **offload de 31/31 camadas**, conclusão nativa e assistant persistido.
O erro restante era o retorno falso ao alcançar o limite de tokens, corrigido sem
aceitar erros de decode/cancelamento como sucesso. Critérios de integração mantidos.
**Vulkan por software (llvmpipe), não aprovação de GPU física ou de qualidade.**
Veja [correção, provas e limites](docs/VULKAN.md).

Os testes de host executam classes reais do APK, traduzidas de DEX para JVM, com
substitutos explícitos de `Native` e `org.json`. Isso permite verificar controle de
fluxo, persistência e cache, mas **não comprova inferência nativa, Vulkan ou câmera**.
Veja [docs/VALIDACAO.md](docs/VALIDACAO.md) para evidências e limites.

**[Baixar o APK testado diretamente, sem ZIP](https://github.com/Enzo-cyber2025/5/releases/download/gguf-apk-f6dc954/GGUF-Chat-repaired.apk)** — arquivo
`GGUF-Chat-repaired.apk`, SHA-256
`b3ae6a0df9c9cd38f947f67df6c19fe01ea6dfd39eb4f39979cd13009c62a0f6`.
O link direto usa o APK exato publicado como anexo da pré-release de teste. O download para este sandbox falhou no
armazenamento do Actions (EOF), portanto não há cópia local deste APK confirmada.
Não use um APK antigo de `entrega/` como se fosse o binário aprovado nesta execução.
Binários, modelos, dependências e chaves não são versionados no Git.

### Instalação com cuidado

O APK usa **uma chave descartável de teste do CI**, diferente da assinatura anterior.
O Android pode recusar atualização por cima da versão instalada. **Não desinstale
sem antes preservar conversas e modelos importantes**: desinstalar apaga dados
privados do aplicativo. Se não puder salvá-los, teste em outro aparelho/emulador.
Não foi feita migração nem recuperação de conversas que já tenham sido salvas com
caminhos nulos; pode ser necessário criar novamente a conversa/importar os modelos.

## Reproduzir o build

Requisitos: Python 3.11+, Node/npm, Android NDK **28.2.13676358** (Linux x86_64)
e `gh` conectado ao GitHub para obter o APK original.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
bash scripts/fetch_tools.sh
python3 scripts/fetch_original.py

# Android SDK command-line tools precisam estar no PATH.
sdkmanager --install "ndk;28.2.13676358"
export ANDROID_NDK_HOME="$ANDROID_HOME/ndk/28.2.13676358"

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
assina com `apksigner` e compara os recursos/libs com o original, exceto a alteração verificada de dependência JNI.
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
O modo completo limpa os dados de `com.ggufchat.app`, importa via SAF e exige uma resposta
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

O workflow está **ativo** em [`.github/workflows/gguf-repair.yml`](.github/workflows/gguf-repair.yml),
com cópia em [`ci/gguf-repair.yml`](ci/gguf-repair.yml). A autorização para publicá-lo
foi resolvida; não é necessário criar arquivos manualmente.

O evento `push` nesta branch inicia build e teste de geração com um modelo real,
preparado diretamente (`GGUF_MODEL_SETUP=provisioned`). Agora o padrão exige Vulkan
(`GGUF_VULKAN_ONLY=1`, `GGUF_REQUIRE_VULKAN=1`): fallback CPU reprova o teste.
Esse modo não executa SAF, arquivo ausente nem avaliação de pertinência.
Na execução manual, marque `run_android` e escolha `android_mode=vulkan` ou `cpu`.
O modo CPU exige duas gerações e a verificação básica de pertinência.
Isso consome minutos do GitHub Actions.

Os artefatos de Actions contêm o APK e as evidências, inclusive em falha. O workflow
também publica apenas resumos/capturas limitados em `ci-results/` **nesta mesma branch**,
com `[skip ci]` para evitar repetição automática. Sem force-push nem outras branches.
O workflow antigo do repositório não foi alterado; o erro histórico dos pontos em
`timeout-minutes` já estava resolvido.

</details>
