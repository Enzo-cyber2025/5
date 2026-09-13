# GGUF Chat — validação de 13/09/2026

## Estado atual

**Geração técnica PASS; pertinência FAIL; validação integral NÃO aprovada.**
Veja [GERACAO.md](GERACAO.md) para a execução real mais recente, as respostas, os
novos reparos e as limitações. O histórico de falhas SAF abaixo continua relevante,
mas já houve inferência nativa posterior com preparação direta do modelo.

## Artefato

- Original: `GGUF-Chat.apk`, commit `90b737409db091ca8c4d75a33b9d5d27748dbacb` da
  branch `arena/01a077ef-5` de `Enzo-cyber2025/5`.
- SHA-256 original: `02f97871a28936b4374001e0df7352461821181957a5f740207fa5eea4117281`.
- SHA-256 do DEX original: `2ef843184d5ae3b65e7fd79ea06b29cacd0249d6738c353e5d332b9b334e6f2c`.
- Entrega: `GGUF-Chat-repaired.apk`, **90.175.777 bytes**.
- SHA-256 da entrega: `113ecfb6aefa08450cc5a65b00ec4c13dc3550e72a3386a45f2cbbc5116e1c2e`.
- Package: `com.ggufchat.app`; versão 2.0; minSdk 24; targetSdk 34, preservados.
- Certificado de teste SHA-256:
  `4826e7eca2928a404e027a75f3e69e2aa077a49d5b566609104a667519b0e5f1`.

Esse hash identifica o artefato desta sessão. Novos builds com outra chave ou
metadados ZIP diferentes podem ter outro hash. Chaves de teste não são publicadas.

## Resultado efetivamente observado

### 1. Build e assinatura — PASS

Apktool 2.9.3 recompilou o DEX. O `apksigner` oficial retornou sucesso:

```text
Verifies
Verified using v2 scheme (APK Signature Scheme v2): true
Verified using v3 scheme (APK Signature Scheme v3): true
Number of signers: 1
Signer #1 key size (bits): 3072
```

A verificação não reportou uso do esquema v1. Não é necessário para minSdk 24 quando
v2 está válido. Nenhum targetSdk foi reduzido para contornar assinatura.

A rotina de build conferiu o alinhamento de 4 bytes dos dados ZIP não comprimidos e
comparou os recursos e bibliotecas com o APK original. Além do DEX e assinatura,
foram corrigidos metadados ELF de dependência nas duas pontes `libaijni.so`, sem
alterar suas seções de código executável. As demais libs permanecem byte a byte iguais. As classes de teste não entram na entrega.

### 2. Regressões das classes reais no host — 33 PASS

Enjarify, commit `f2db0563aa83885ce6e6acd5b7dc9a8a1a1e1987`, traduziu o APK final:

```text
89 classes translated successfully, 0 classes had errors
33 passed
```

As classes `Chat`, `ModelInfo`, `EngineManager` e `GenerationResult` do artefato final
foram executadas em JVM com `-Xverify:all`. Os testes verificaram:

- Round-trip JSON dos caminhos do modelo/projetor, repetido três vezes em conversas.
- Normalização de null, vazio e string `"null"`.
- Encaminhamento do mmproj para `Native.create`.
- Reutilização do motor somente com parâmetros idênticos.
- Recriação quando contexto, threads, GPU, mmap ou projetor mudam.
- Fallback CPU sem perder o projetor nem invalidar a chave do cache.
- Rejeição de arquivo inexistente, diretório, vazio, truncado, magic ou versão inválida.
- Preservação de motor válido quando um novo projetor é inválido.
- Recuperação após falha de carregamento.
- Tratamento do booleano false de geração como erro, não resposta concluída.

**Limite importante:** Native e org.json são substitutos explícitos de teste.
Arquivos mínimos com apenas cabeçalho são usados exclusivamente nesses testes.
Não houve inferência nativa nem execução de Android nesse procedimento. Enjarify/JVM
não substituem o verificador ART nem validam integralmente as Activities Android.

### 3. Controle negativo no APK original — bugs reproduzidos

As mesmas expectativas de persistência/cache/validação foram executadas contra as
classes traduzidas do APK original (os quatro testes da classe nova foram excluídos):

```text
21 failed, 8 passed, 4 deselected
```

As falhas reproduzem os caminhos válidos virando null, perda do mmproj no carregador,
cache ignorando configurações e ausência das novas proteções de arquivos. Não se
trata de 21 bugs independentes: há múltiplos casos para cada defeito.

### 4. Ferramentas e automação — 40 PASS locais; 37 na última execução CI

```text
40 passed
```

Cobertura inclui rejeição de DEX desconhecido/já alterado, checksums, alinhamento ZIP,
preservação de payloads, inserção do tratamento de geração dentro do catch existente,
seleção exata no SAF, recusa de telas do DocumentsUI como chat, validação de resposta
por conversa/prompt/role, vínculos por caminho (sem presumir architecture=llava),
rejeição de modelos duplicados e propagação do exit code de falhas do runner.
O teste destrutivo também recusa um serial de aparelho físico antes de chamar ADB.

### 5. Android/emulador — EXECUTADO, aprovação parcial

A autorização do workflow foi resolvida e houve execuções reais no GitHub Actions,
com Android 11/API 30, Google APIs, x86_64 e modelo SmolLM2-135M-Instruct Q4_K_M.
O ambiente local permanece sem SDK/KVM; os testes Android foram executados no runner.

Execução [34766875032](https://github.com/Enzo-cyber2025/5/actions/runs/34766875032):

- Build e assinatura: **PASS**; 26 testes de ferramentas e 33 JVM: **PASS**.
- Emulador: **BOOTED x86_64**; instalação: **PASS**; abertura do aplicativo: **PASS**.
- Seleção SAF: **FAIL**, sem presumir importação ou resposta.

A tentativa [34767096056](https://github.com/Enzo-cyber2025/5/actions/runs/34767096056)
confirmou esses resultados. O diagnóstico mostrou que o XML do DocumentsUI inclui
controles atrás do menu lateral: “Downloads” podia selecionar o breadcrumb encoberto,
não a raiz do menu. A automação passou a diferenciar os controles pelo resource-id e
não tocar em arquivos atrás do menu, mas esse ajuste **não resolveu a seleção completa**.

Resultado mais recente, [34767511976](https://github.com/Enzo-cyber2025/5/actions/runs/34767511976),
commit de origem `c827d23`: **33 JVM + 27 ferramentas PASS**; Android **FAIL**.
Emulador/instalação/abertura passaram; seleção SAF falhou novamente. O arquivo real
aparece no seletor, mas a importação não foi confirmada no aplicativo.

- [App aberto: captura real](../ci-results/34767511976-1/launch.png).
- [Tela do seletor ao encerrar](../ci-results/34767511976-1/final-screen.png).
- [Resumo efetivo](../ci-results/34767511976-1/summary.json).
- SHA-256 desse APK CI: `318c562de2babbbb7051a01682a36485b85e5f5aec40ce39839f6b1300a8c934`.

Uma tentativa intermediária (`34767418982`) também registrou desconexão transitória
em `adb root`, antes da instalação. Isso é uma falha da execução do teste, não prova
de falha do APK. Não há execução completa aprovada nesta sessão.

O histórico acima antecede a execução posterior de geração técnica CPU, que passou
no run `34769745227`. A pertinência das respostas reprovou a avaliação; GPU/Vulkan,
visão e fluxos completos continuam sem aprovação. Veja [GERACAO.md](GERACAO.md).
Os APKs do CI usam chaves descartáveis e hashes próprios, registrados nos resumos;
não são o mesmo binário assinado localmente descrito no início deste documento.

## Correção da automação antiga

As evidências anteriores tinham resumos vazios, textos `Images/Audio/Documents`
classificados como resposta, e `NONEXISTENT_CRASH` baseado apenas em ausência de PID.
Isso não sustentava aprovação de geração nem diagnóstico definitivo de crash nativo.

A nova suíte:

- Registra resultado/saída de cada comando ADB e falha em operações obrigatórias.
- Descarta dumps antigos de UI; exige seletor/app correto e seleção exata de arquivo.
- Confirma importação no `models.json`; não presume que um toque importou o arquivo.
- Confere a identidade do chat e `modelPath` e requer mensagem de assistant após o prompt.
- Exige marcador emitido só após `Native.generate()` retornar true, além da resposta salva.
- Diferencia GPU offload de mero carregamento de uma biblioteca Vulkan/fallback CPU.
- Salva summary.json e diagnósticos inclusive em falha; não publica binário como aprovado
  por emulador quando apenas os testes do host passaram.
- Não faz force-push nem escreve em `evidence-x86`/outras branches.

O erro histórico `timeout-minutes: 52.560.000` já estava corrigido pelo usuário.
Não foi tratado como bug pendente e o workflow antigo não foi modificado.

## Pendências / limites da correção

1. Completar os fluxos de importação/geração no emulador e testar no aparelho alvo.
   Instalação e abertura já passaram no emulador x86_64.
2. Corrigir/investigar a pertinência das respostas e a conversão UTF-8. A inferência
   CPU com modelo real já produziu e salvou respostas; visão continua sem validação.
3. A validação de cabeçalho não detecta todos os tensores corrompidos/incompatíveis;
   falhas internas das bibliotecas nativas existentes ainda são possíveis.
4. Conversas já salvas com caminhos nulos não têm recuperação automática neste reparo.
5. A nova assinatura pode impedir atualização por cima do APK anterior. Preservar dados
   antes de qualquer desinstalação, ou testar em dispositivo separado.
6. Resolver a seleção SAF que continuou falhando no teste completo; testes JVM não substituem
   inferência real, e abertura da tela inicial não aprova todas as Activities.

## Infraestrutura e evidências

O bloqueio anterior de permissão `workflows` foi resolvido após a autorização do usuário.
O workflow já foi publicado e executado, sem precisar de token colado no chat.
O download binário do APK original foi corrigido mantendo a validação SHA-256.
A chamada de abertura usa flags numéricas aceitas no Android 11.

`ci-results/<run-id>-<attempt>/` recebe resumos e capturas limitadas das execuções novas,
na branch da sessão, sem APKs, modelos ou chaves. Artefatos completos permanecem no
GitHub Actions por 7 dias. Avisos curtos no Checks API evitam truncar o diagnóstico.
