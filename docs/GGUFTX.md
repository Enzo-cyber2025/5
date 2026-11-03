# GGUFTX — trabalho em andamento

**GGUFTX** é o nome pedido para a próxima identidade do GGUF Chat. O CI compilou
candidatos unsigned e validou pesquisa web real, hand-off protegido do Termux e
zeros com limites finitos no run [41695739950](https://github.com/Enzo-cyber2025/5/actions/runs/41695739950).
A aceitação Android completa desse run falhou depois, com a resposta `CERO
EMIOFSELLA.` em um check de inferência; portanto ainda não é uma release validada.
Os checks de integridade física, persistência após reinício e inferência visual
com Vulkan passaram nesse run.

## Logo

A nova logo mantém o formato do ícone original: fundo externo branco, painel
central preto e o texto branco `>sudo do anythink`. Os PNGs estão em
`apk-fix/assets/gguftx-logo-*.png`; o build do APK troca os cinco recursos de
launcher (`mdpi` a `xxxhdpi`) e verifica os bytes incluídos. O rótulo/nome mostrado
sob o ícone não foi alterado por esta troca de arte.

## Pesquisa web

O botão de pesquisa já existente continua sendo o acionamento explícito. O helper
`apk-fix/java/com/ggufchat/app/WebSearch.java` foi refeito para:

- consultar DuckDuckGo HTML/Lite e, se o provider ou o parser estiver vazio,
  tentar uma segunda fonte em RSS (Bing), preservando timeouts, limite de resposta
  e citações;
- limitar a consulta, resposta recebida (1 MiB), quantidade de resultados e tempos
de conexão/leitura;
- extrair título, trecho e URL de citação, decodificar entidades HTML e resolver
links de redirecionamento do provedor;
- marcar resultados como conteúdo externo não confiável, para reduzir o risco de
instruções maliciosas em páginas virarem instruções do sistema;
- continuar a inferência local sem travar a conversa quando a rede, o provedor ou
a análise HTML falhar. Nessa situação, a resposta deve admitir que não conseguiu
confirmar fatos atuais.

A pesquisa precisa de internet e pode sofrer bloqueios, mudanças de HTML,
limitação de tráfego ou indisponibilidade do provedor. Os snippets não substituem
a leitura das fontes originais. A inspeção do DEX confirmou que
`GenerationService` chama `WebSearch.search()` quando `chat.webSearch=true` e inclui
`toPromptText()` no fluxo do modelo. A execução anterior [41450467967](https://github.com/Enzo-cyber2025/5/actions/runs/41450467967)
ativou a opção, mas retornou zero resultados/citações. Após adicionar Bing RSS como
fallback, o teste Android real [41695739950](https://github.com/Enzo-cyber2025/5/actions/runs/41695739950)
registrou um resultado e uma citação (`[5]`) tanto na consulta em português quanto
na consulta em inglês. Isso comprova a recuperação e inclusão de uma citação no
prompt; não valida a exatidão factual da resposta gerada nem a URL da fonte. O run
falhou depois em outro check de inferência (`CERO EMIOFSELLA.`), não no teste de
busca. A regressão local do parser passou (10 testes; 1 teste Java ignorado por
falta de `javac`).

## Limites e segurança

- **Termux não foi embutido como runtime.** Há um hand-off opcional para o
  aplicativo Termux instalado separadamente. Não depende de chamadas nativas de
  ferramentas/funções: lê um bloco Markdown `bash`/`sh`/`shell`/`termux` ou uma
  linha simples reconhecida (incluindo `bash ~/script.sh`) da última resposta,
  mostra exatamente o comando selecionado e só o envia ao Termux após confirmação
  explícita. O harness Android agora tenta novamente uma inferência curta para
  leitura/descrição da pasta em um chat novo se a primeira expira, mas continua
  aceitando apenas o comando exato allow-listed produzido pelo modelo: retry não
  simula a resposta nem executa shell pelo harness. Requer Termux com
  `RUN_COMMAND`/“Allow external apps” habilitado; a
  saída fica no próprio Termux e não é devolvida automaticamente à IA. Comandos
  simples sem fence são limitados a uma linha; scripts multilinha devem vir num
  bloco de código e continuam sujeitos à revisão humana. No rerun [41691161767](https://github.com/Enzo-cyber2025/5/actions/runs/41691161767), Gemma 4 E2B e Gemma 3 270M usaram texto simples, leram a pasta isolada de um TXT e descreveram seu identificador. Os dois builds no Termux terminaram com `exit 0`, instalaram o APK de teste e converteram `A` em `01000001`. Os relatórios funcionais continuam `PARTIAL` porque `pkg install box64` falhou com `exit 100` em Termux x86_64.

  No teste Android [41695739950](https://github.com/Enzo-cyber2025/5/actions/runs/41695739950), um modelo propôs o comando allow-listed, o app mostrou o diálogo de revisão e o Android exibiu a permissão oficial `RUN_COMMAND`; o teste automatizado tocou nos botões para comprovar o caminho, e o comando executou no Termux oficial instalado à parte. **Isso não é confirmação por uma pessoa real**: o relatório antigo dizia `user_review_and_confirmation=true`, mas a inspeção do harness revelou que a confirmação foi um toque automatizado. O relatório foi corrigido para distinguir automação de ação humana. Em uso real, cabe à pessoa revisar e confirmar no dispositivo. A saída do shell não foi retornada automaticamente à IA.

  Os zeros não são infinitos: o mesmo run carregou um contexto máximo finito de 8.192 tokens para o modelo compacto, reservando 8.130 tokens para saída. No run Gemma, os contextos observados foram 131.072 (Gemma 4) e 32.768 (Gemma 3). O histórico/configuração do chat sobreviveu ao reinício, mas não há opção de armazenamento explícito do contexto nem prova de persistência do KV cache.

  Box64 precisa de host ARM64 para emular x86_64. O workflow separado fixa o release comunitário ARM64 `v0.4.5-termux.1` e SHA-256 `0dae8257ac7396db4766721e5e4f317679b2080752d32e90d4e6e6fdfee467cf`, depois executa apenas `box64 --version` (não instala o launcher comercial `dragon`). As tentativas [41688469902](https://github.com/Enzo-cyber2025/5/actions/runs/41688469902) (host x86) e [41692500040](https://github.com/Enzo-cyber2025/5/actions/runs/41692500040) (host macOS ARM64) expiraram antes do boot do emulador Android ARM64; não comprovam instalação. Esse teste arquitetural separado não será apresentado como ação feita pelo modelo.
  Uma atualização de espelho Termux trouxe `aapt2` antigo (13.x) no job Gemma 4,
  que recusou o `android.jar` API 35; o script de build fixa o endpoint oficial
  `packages-cf.termux.dev` e atualiza os índices antes de instalar, correção validada
  no run [41691161767](https://github.com/Enzo-cyber2025/5/actions/runs/41691161767).
  O CI automatiza os toques nos controles explícitos de confirmação; isso não é
  uma ação silenciosa nem confirmação humana em ambiente real. Os APKs
  testados foram candidatos unsigned com assinatura descartável só para emulador,
  não atualizações assinadas para instalação pública. A saída do Termux continua
  sem retorno automático ao modelo. A execução irrestrita continua desativada:
  comandos podem apagar dados, expor credenciais ou instalar software.
- **`contextSize=0` e `nPredict=0` agora significam “usar o máximo finito disponível”**:
  o contexto 0 pede ao llama.cpp o contexto de treino declarado no GGUF; saída 0
  consome o espaço restante desse contexto até EOS, cancelamento ou esgotamento.
  Não são infinitos: arquitetura/modelo definem o teto, e pedir o contexto máximo
  pode causar falta de memória. Em conversas antigas, valores salvos continuam
  valendo até serem alterados; novos chats usam os defaults zero.
- **Não há alegação de +50% de velocidade.** Pesquisa de rede não acelera a
  inferência local. Um ganho desse tamanho só pode ser afirmado após benchmark
  pareado, no mesmo dispositivo, modelo, prompt, contexto e backend; nenhuma medição
  desse tipo foi feita nesta alteração.

## Para uma release

Compilar o helper com `apk-fix/build_mobile.py`, verificar a permissão de internet
no manifesto base e executar a regressão completa antes de assinar. Buscas ao vivo
em português e inglês já produziram uma citação cada no emulador (run 41695739950);
ainda faltam os cenários sem rede, HTTP vazio/limitado, busca desativada e inspeção
da URL e do conteúdo da fonte exibida ao usuário. A assinatura do workflow foi
apenas efêmera para o emulador, não uma chave de atualização pública.
Se também for desejado trocar o nome mostrado sob o ícone, a label do aplicativo
precisa ser alterada separadamente; esta etapa substitui só os PNGs do launcher.
