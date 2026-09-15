# GGUF Chat — resposta pronta com a tela apagada

## [Baixar APK — sem ZIP](https://raw.githubusercontent.com/Enzo-cyber2025/5/f189650ded443bfcdf9f3438c188e1bfde2d9fe9/.delivery/GGUF-Chat-mobile.apk)

**Mesma assinatura do último APK entregue (`eabd0169…`). Atualização por cima dele testada, preservando modelos e conversas.** Não é a mesma assinatura de versões antigas `3dd…`/`9b…`; não desinstale essas versões sem proteger os dados.

28.370.381 bytes · Android 9+ · ARM64/x86_64 · modelos não incluídos.

- **Resposta pronta** quando o modelo termina e salva a resposta com a tela apagada ou bloqueada.
- Toque abre a conversa correta; o aviso permanece após encerrar o serviço e some ao ser tocado.
- Menos trabalho de notificação em segundo plano e uma cópia redundante da resposta eliminada. Motor, caches, conteúdo e tokens/s preservados; nenhum novo percentual de aceleração da inferência alegado.
- Cancelamento não produz falso aviso de sucesso. Permissão do Android, canal e Não Perturbe são respeitados.

**8/8 testes reais no emulador passaram no APK assinado**, incluindo atualização, texto idêntico, notificação real/toque, imagem real durante sono, cache, cancelamento e permissão negada. Não é certificação de todos os celulares ou som físico.

[Relatório e capturas reais](docs/REPLY_NOTIFICATIONS.md) · [Aprovação](.delivery/reply-notification-acceptance.json)

SHA-256: `3baa171c78eb5ee7f6f5c3c212904f53547a13184b9c01ea1d6ec565e2f5152e`.

---
<details>
<summary>Entregas anteriores — avisos de assinatura e medições se referem a cada versão histórica</summary>

# GGUF Chat — menos espera nas continuações

**Assinatura diferente da versão anterior. O Android não permite atualizar por cima dela. Não desinstale o app sem proteger seus dados.**

## [Baixar APK — sem ZIP](https://raw.githubusercontent.com/Enzo-cyber2025/5/c5035bafcee844337dcedb033ae8671a813f5b91/.delivery/GGUF-Chat-mobile.apk)

28.370.376 bytes · Android 9+ · ARM64/x86_64 · modelos não incluídos.

Comparativo real em emulador, mesmas respostas e três pares medidos por versão:

| Etapa da continuação | Antes | Depois |
|---|---:|---:|
| Preparação do histórico | 14,64 s | 1,47 s |
| Preparação + geração no motor | 31,56 s | 18,21 s |

**90% menos preparação e 42% menos tempo nativo total nas continuações medidas.**
Não há ganho relevante comprovado no primeiro prompt nem na geração token a token;
o principal ganho vem de reutilizar o histórico. Não é garantia desses tempos no celular.

Cache de texto e embeddings de imagens; renderização incremental; tokens/s reais
preservados abaixo das respostas. Cancelamento/recuperação, persistência, mudança
de sistema, imagem com tela apagada e invalidação de imagens diferentes testados.
Pesos, quantização e limites escolhidos pelo usuário não foram reduzidos.

[Relatório, limites e capturas reais](docs/RESPONSE_LATENCY.md) ·
[Aprovação verificada](.delivery/latency-acceptance.json).

SHA-256: `eabd016935ac51cdd89063a97fbc1b562f7f9261981f54b5191d37734e7922eb`.
Certificado: `4f75afe8637f28ccb167db407e3b2bc9b260e1cfe6059b7377ea20b0b4dc2ac3`.

---
## Histórico de entregas (assinaturas e instruções abaixo pertencem à respectiva versão)

# GGUF Chat — um botão de importação, seleção múltipla

## [Baixar APK — sem ZIP](https://github.com/Enzo-cyber2025/5/releases/download/gguf-import-ui-368f85e/GGUF-Chat-mobile.apk)

**28.345.800 bytes · Android 9+ · ARM64/x86_64 · modelos não incluídos.**

- Biblioteca vazia → Nova conversa → Importar: apenas **Importar GGUF**.
- **Seleção múltipla habilitada**, sem o botão separado “Importar 2 GGUFs”. A entrada pela tela antiga também usa a tela única.
- Seleções de **dois e três arquivos testadas no Android**; preservadas a unificação dos pares compatíveis e a importação sequencial de lotes maiores.
- **Mesma assinatura do último APK de progresso**; atualização por cima dele testada, preservando dado privado. Sem necessidade de desinstalar essa última versão.
- Percentuais e motor preservados; somente duas classes de navegação mudaram.

[Relatório e capturas reais](docs/SINGLE_IMPORT_UI.md) · [Aprovação](.delivery/import-ui-acceptance.json)

SHA-256: `086a125ae5e503718b3999bff1d2ad98b06498e0edf770471c7db07e8afaa813`.

<details>
<summary>Entrega anterior e histórico</summary>

# GGUF Chat — porcentagens por arquivo e etapa

## [Baixar APK — sem ZIP](https://github.com/Enzo-cyber2025/5/releases/download/gguf-progress-dba56b2/GGUF-Chat-mobile.apk)

**28.349.896 bytes · Android 9+ · ARM64/x86_64 · modelos não incluídos.**

**Mesma assinatura do último APK (`gguf-atomic-5cf14ef`).** Atualização por cima dele testada no Android, mantendo dado privado de teste. Não é necessário desinstalar essa última versão.

- Porcentagem da **importação de cada arquivo**, com seu nome.
- Porcentagens separadas de **identificação, unificação dos pesos e conferência dos tensores**.
- Contadores reais; 100% somente quando a etapa termina. Tamanho desconhecido e carregamento nativo ficam explicitamente indeterminados, sem porcentagens inventadas.
- Progresso também na importação individual, com fechamento correto em caso de erro.
- Mantidos o GGUF físico único, validação nativa e recusa atômica de pares inválidos, sem dois sucessos parciais.

**APK assinado executado no emulador: dois jobs aprovados.** Gemma: todos os 2.012 tensores preservados e respostas Dog / Dog / 4; importação individual visual/textual, negativas, anexos e conteúdo também verificados. Capturas reais do painel foram conferidas.

Vulkan por software no emulador não comprova GPU física. Persistem limitações de qualidade dos modelos pequenos, inclusive eco de instruções e desobediência ao prompt por conversa. Não há aprovação universal de arquiteturas nem transcrição de áudio.

[Relatório e capturas](docs/IMPORT_PROGRESS.md) · [Aprovação](.delivery/progress-acceptance.json)

SHA-256: `afaf22c63022b44320604407246abe47a921c4e4d1fe55694ce7428abb047e86`.

<details>
<summary>Entrega anterior e histórico — as instruções de troca de assinatura abaixo são históricas</summary>

# GGUF Chat — unificação obrigatória e reconhecimento real

## [Baixar APK — sem ZIP](https://github.com/Enzo-cyber2025/5/releases/download/gguf-atomic-5cf14ef/GGUF-Chat-mobile.apk)

**28.341.710 bytes · Android 9+ · ARM64 e x86_64 · modelos não incluídos.**

**NOVA ASSINATURA, conforme alternativa autorizada:** a chave privada anterior não pôde ser recuperada. Este APK não atualiza por cima da versão anterior. Guarde conversas, anexos e modelos fora do app antes de desinstalar qualquer versão.

- **Dois arquivos juntos: um GGUF validado ou rejeição.** Nenhum componente é publicado na biblioteca antes de concluir unificação, conferir todos os bytes dos tensores e carregar linguagem/visão no motor nativo.
- **Um GGUF visual já unificado:** reconhecido como visual pelo conteúdo real, com olho/câmera. **Modelo textual:** sem olho/câmera, independentemente do nome.
- **Testes Android do mesmo APK assinado:** Gemma 4 com 2.012 tensores em um arquivo; `Dog` / `Dog` após reiniciar / `4` sem imagem. GGUF externo independente e texto não visual passaram.
- Dois modelos textuais, dois projetores, arquivo truncado e pesos recusados pelo motor: rejeitados sem novos registros/arquivos e sem modificar originais, biblioteca ou conversas preexistentes.

Isso não torna qualquer par incompatível combinável. Reimporte os dois originais para aplicar a transação a um par antigo; pares legados não são apagados/convertidos silenciosamente. Vulkan foi testado por software no emulador, não em GPU física. Qualidade geral de respostas e transcrição de áudio não são aprovadas.

[Relatório e capturas reais](docs/ATOMIC_IMPORT.md) · [Proveniência dos jobs aprovados](.delivery/atomic-acceptance.json)

SHA-256: `5f7247a5ffe663a583ccf46adf161f2e8f27e64780f3aa3a39f070c8259bd840`.

<details>
<summary>Versões anteriores e histórico — não são as instruções da assinatura atual</summary>

# GGUF Chat — Gemma 4, arquivo único e assinatura preservada

## [Baixar APK — sem ZIP](https://github.com/Enzo-cyber2025/5/releases/download/gguf-gemma4-ca7d8f1/GGUF-Chat-mobile.apk)

**28.341.709 bytes · Android 9+ · ARM64 e x86_64 · modelos não incluídos.**

- **Gemma-4-E2B-it corrigido:** motor nativo atualizado, identificação por parâmetros/tensores e unificação de linguagem + projetor em **um único GGUF físico**.
- Par público autorizado Q3_K_S + mmproj-F16: **2.012 tensores preservados**, saída de 3.431.306.464 bytes. Pode diferir dos arquivos exatos do usuário.
- **Mesmo APK assinado executado no Android:** Gemma respondeu `Dog`, `Dog` após reiniciar e `4` em texto sem anexos. Regressões de documentos, imagens, câmera emulada, prompts e persistência passaram funcionalmente.
- **Mesma assinatura da entrega `gguf-physical-4fa8dbc`**, com atualização mantendo dado privado de teste. Não é necessário desinstalar uma instalação dessa mesma assinatura. Não apague dados para contornar incompatibilidade com outra assinatura sem antes salvá-los fora do app.

**Reimporte o par que falhou anteriormente** em Importar → Importar .gguf. Registros antigos não são automaticamente reunificados; não exclua indiscriminadamente modelos/conversas.

**Limites honestos:** emulador com Vulkan por software, não GPU física; sem homologação de RAM/desempenho de aparelho real. Áudio preservado não significa transcrição testada. Modelos pequenos ainda podem desobedecer à troca de prompt e repetir instruções: PASS funcional não aprova qualidade geral.

[Relatório, arquivos de referência, hashes e capturas reais](docs/GEMMA4.md) · [Proveniência da aceitação](.delivery/gemma4-acceptance.json)

SHA-256 do APK: `f228a5d150348da37b365de541c99021b06fcb4eaa2713712cae816f0c10dbbc`.

<details>
<summary>Entrega anterior e histórico — não são as instruções da atualização atual</summary>

# GGUF Chat — APK assinado, GGUF físico único e prompts

## [Baixar APK diretamente — sem ZIP](https://github.com/Enzo-cyber2025/5/releases/download/gguf-physical-4fa8dbc/GGUF-Chat-mobile.apk)

**21.730.287 bytes · Android 9+ · ARM64 e x86_64 · modelos não incluídos.**

**Assinado com nova chave autorizada e executado no Android: PASS funcional.** O teste utilizou exatamente os bytes assinados desta entrega, sem chave descartável intermediária.

- Linguagem + projetor compatível → **um único GGUF físico**, não dois arquivos sob um cartão. Auditoria independente dos **471 tensores: PASS**.
- Identificação por parâmetros/tensores, não por nome ou apenas tokens de imagem. GGUF completo no layout suportado também pode ser importado sozinho.
- Visão real: reconheceu cão e ônibus. TXT/PDF/DOCX: leu os códigos presentes nos arquivos. Fotos múltiplas, duas capturas pela câmera do emulador, reinício, remoção e erros explícitos passaram.
- Prompts globais e por conversa: editar, cancelar/restaurar, persistir e aplicar na geração. Tela principal → “Prompt de sistema global”; ferramentas da conversa → “Sistema”.

**Teste isolado adicional:** SmolVLM-500M em um único GGUF completo, preparado fora do app; Android limpo, sem importação de par e sem projetor externo. 489 tensores, cão/ônibus, texto e reinício passaram. Não é um download originalmente publicado já unificado. [Resultado e capturas](docs/STANDALONE_500M.md).

**Limitações reais:** o modelo pequeno repetiu o código antigo mesmo recebendo a nova instrução por conversa (**FAIL semântico**); inventou páginas/detalhes/anexo em respostas longas e falhou uma saudação. Não se aprova qualidade geral pelo PASS funcional. Vulkan por software no emulador, não GPU física. Importação externa foi testada com GGUFWriter upstream e pesos reais, não com um download público já unificado encontrado pronto. Leitura não interpreta qualquer formato; limites e formatos não suportados estão no relatório.

**Assinatura diferente da versão anterior:** salve conversas, anexos e originais dos modelos **fora do app antes de desinstalar** a versão antiga. Desinstalar apaga os dados privados. O backup da nova chave, fornecido separadamente, não é backup dos dados do app; guarde-o para futuras atualizações com a mesma assinatura.

SHA-256: `4d1697c2ee9b80ba38a03ee78ab0241dc8aa3d5464c956707e2412be70b11ce6`.

[Teste Android 34892580054 — concluído](https://github.com/Enzo-cyber2025/5/actions/runs/34892580054) · [Relatório da entrega assinada e capturas](docs/SIGNED_PHYSICAL.md) · [Implementação e histórico](docs/PHYSICAL_GGUF.md) · [Resumo integral](ci-results/34892580054-1/summary.json) · [Proveniência](.delivery/mobile-physical-validation.json)

<details>
<summary>Última versão assinada anterior — NÃO contém GGUF físico único nem prompts editáveis</summary>

# GGUF Chat — leitura real de documentos e imagens

## [Baixar APK diretamente — sem ZIP](https://github.com/Enzo-cyber2025/5/releases/download/gguf-inference-e37df03/GGUF-Chat-mobile.apk)

**21,72 MB · Android 9+ · ARM64 e x86_64 · modelos não incluídos.**

- **Fotos:** pixels processados pelo projetor multimodal e avaliados pelo modelo, não apenas nomes/contagem dos anexos. Exige GGUF + mmproj compatíveis com visão.
- **Documentos:** texto de TXT e outros textos válidos, PDF e texto principal de DOCX/ODT entram na geração. Páginas de PDF sem texto são enviadas como imagens quando há visão.
- Formatos não suportados e excesso de contexto produzem erro explícito. **Desativar leitura / Ativar leitura** permite manter o arquivo e retomar a conversa.
- Preservados câmera/clipe à esquerda, fotos múltiplas, câmera desativada no modelo normal, clipe para qualquer tipo, cópia em blocos e anexos privados persistentes.
- Preservados par único GGUF + mmproj com olho, pesos no Vulkan sem retry silencioso da unidade em CPU e ferramentas compactas numa linha com 10px de intervalo.

**Aceitação funcional Android PASS:** [34848915081](https://github.com/Enzo-cyber2025/5/actions/runs/34848915081). Conteúdo de TXT/PDF/DOCX, cão/ônibus, duas fotos, PDF visual, reinício, falhas explícitas e recuperação pela interface. SAF/câmera/armazenamento/unificação também passaram. Vulkan e câmera testados no emulador, não em hardware físico.

**Não é aprovação da qualidade geral:** modelos pequenos acertaram códigos/objetos, mas inventaram detalhes e repetiram instruções. Uma saudação falhou no teste; outra passou apenas pela presença da palavra “hello”, apesar de repetir a pergunta. Os resultados completos estão preservados no [relatório](docs/INFERENCE.md).

**Limites:** importação sem cota artificial, sujeita ao Android/provedor/espaço. Leitura limitada a 131.072 caracteres, imagens preparadas a 8 MP e contexto do motor a 8.192 tokens, com erros em vez de truncamento silencioso. Imagens reduzidas até 1.024px no maior lado. Áudio/vídeo, arquivos compactados genéricos, planilhas, apresentações, Office antigo e outros binários não têm interpretação nesta etapa. Veja particularidades de PDF/Office no relatório.

**Instalação: nova chave autorizada.** Esta assinatura não atualiza por cima das versões anteriores. **Salve conversas/anexos e originais dos modelos fora do app antes de desinstalá-lo.** O backup privado da chave já fornecido não é um backup dos dados do aplicativo.

SHA-256: `3d17116aac387bbda402ddad2f7dc19b42115eec33d7ec89f7c20dde9a87f2c9`.

[Relatório, limites e capturas](docs/INFERENCE.md) · [Evidências](ci-results/34848915081-1/summary.json) · [Histórico de armazenamento](docs/ATTACHMENTS.md)

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

</details>

</details>

</details>

</details>

</details>

</details>
