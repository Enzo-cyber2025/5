# GGUF Chat — validação de 13/09/2026

## Artefato

- Original: `GGUF-Chat.apk`, commit `90b737409db091ca8c4d75a33b9d5d27748dbacb` da
  branch `arena/01a077ef-5` de `Enzo-cyber2025/5`.
- SHA-256 original: `02f97871a28936b4374001e0df7352461821181957a5f740207fa5eea4117281`.
- SHA-256 do DEX original: `2ef843184d5ae3b65e7fd79ea06b29cacd0249d6738c353e5d332b9b334e6f2c`.
- Entrega: `GGUF-Chat-repaired.apk`, **90.118.427 bytes** (aprox. 85,9 MiB).
- SHA-256 da entrega: `8cdb56563e820fff109f76b104ba82010577dc79f29439abefabbd84a99fd528`.
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
comparou todos os recursos e bibliotecas nativas com o APK original. Somente o DEX
(e as assinaturas) mudou. As classes de teste não entram na entrega.

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

### 4. Ferramentas e automação — 21 PASS

```text
21 passed
```

Cobertura inclui rejeição de DEX desconhecido/já alterado, checksums, alinhamento ZIP,
preservação de payloads, inserção do tratamento de geração dentro do catch existente,
seleção exata no SAF, recusa de telas do DocumentsUI como chat, validação de resposta
por conversa/prompt/role, vínculos por caminho (sem presumir architecture=llava),
rejeição de modelos duplicados e propagação do exit code de falhas do runner.
O teste destrutivo também recusa um serial de aparelho físico antes de chamar ADB.

### 5. Android/emulador, GPU e multimodal — NÃO EXECUTADOS nesta sessão

Não há `/dev/kvm` nem SDK/emulador Android instalado neste ambiente. O acesso direto
aos repositórios oficiais Android também falhou. Foi possível reconstruir usando
ferramentas fixadas obtidas de um pacote npm, mas isso não fornece um emulador.

Foram preparados testes reais e um workflow opcional, mas **nenhuma execução remota
foi disparada nesta sessão**. Não foi afirmado que a Xclipse 530 está usando Vulkan,
que visão/imagens estão funcionando ou que todos os problemas do app acabaram.

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

1. Testar instalação e fluxos completos em Android real/emulador, especialmente no aparelho alvo.
2. Validar inferência com modelos GGUF reais e um par de visão/projetor compatível.
3. A validação de cabeçalho não detecta todos os tensores corrompidos/incompatíveis;
   falhas internas das bibliotecas nativas existentes ainda são possíveis.
4. Conversas já salvas com caminhos nulos não têm recuperação automática neste reparo.
5. A nova assinatura pode impedir atualização por cima do APK anterior. Preservar dados
   antes de qualquer desinstalação, ou testar em dispositivo separado.
6. A suíte Android reescrita ainda precisa da primeira execução real para validar seus
   seletores nas versões específicas de DocumentsUI do emulador/aparelho.


## Tentativa de iniciar emulador após solicitação do usuário

A publicação do workflow nesta sessão foi recusada pelo GitHub:

```text
refusing to allow a GitHub App to create or update workflow
`.github/workflows/gguf-repair.yml` without `workflows` permission
```

Não foi um erro de compilação nem de teste do app: o workflow não chegou a executar.
O arquivo foi movido para `ci/gguf-repair.yml`, como modelo inativo, para permitir
publicar as correções na branch da sessão sem exigir essa permissão. A ativação
requer ação do usuário no GitHub ou atualização das permissões da conexão do Arena.
O ambiente local continua sem SDK/emulador instalado e sem `/dev/kvm`.
