# GGUFTX — trabalho em andamento

**GGUFTX** é o nome pedido para a próxima identidade do GGUF Chat. O CI já compilou
candidatos unsigned, mas a aceitação física ainda falha na resposta visual
`CERO EMIOFSELLA.` (run 41243844107); não é release validada. Os checks de
persistência e inferência com o mesmo GGUF passaram nesse run.

## Logo

A nova logo mantém o formato do ícone original: fundo externo branco, painel
central preto e o texto branco `>sudo do anythink`. Os PNGs estão em
`apk-fix/assets/gguftx-logo-*.png`; o build do APK troca os cinco recursos de
launcher (`mdpi` a `xxxhdpi`) e verifica os bytes incluídos. O rótulo/nome mostrado
sob o ícone não foi alterado por esta troca de arte.

## Pesquisa web

O botão de pesquisa já existente continua sendo o acionamento explícito. O helper
`apk-fix/java/com/ggufchat/app/WebSearch.java` foi refeito para:

- consultar resultados reais do DuckDuckGo em português e tentar a página Lite se
a resposta HTML principal não puder ser interpretada;
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
a leitura das fontes originais. A inspeção do DEX do último candidato confirmou que
`GenerationService` chama `WebSearch.search()` quando `chat.webSearch=true` e inclui
`toPromptText()` no fluxo do modelo. Porém, a execução 41243844107 deixou essa opção
em `false`; portanto não é prova de uma consulta real. O novo teste de emulador
verifica a busca ao vivo em português e inglês, mas ainda aguarda CI.

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
  bloco de código e continuam sujeitos à revisão humana. Os runs [41544525019](https://github.com/Enzo-cyber2025/5/actions/runs/41544525019)
  e [41554605496](https://github.com/Enzo-cyber2025/5/actions/runs/41554605496)
  agora exercitam o candidato atual com Gemma 4 E2B e Gemma 3 270M, respectivamente,
  por texto e sem exigir chamadas nativas de ferramentas. Para ambos, o CI observou
  a revisão do comando, a confirmação de permissão Android e execução do build do
  APK no Termux; o APK de teste instalou e converteu `A` em `01000001`. Gemma 4
  também executou o comando de leitura da pasta; Gemma 3 não chegou a esse comando
  porque a inferência expirou. O instalador Box64 foi tentado por ambos, mas o
  Termux x86_64 não encontrou o pacote (`exit 100`). Como Box64 é um emulador de
  x86_64 sobre ARM64, foi acrescentado um workflow separado para testar em
  Termux/Android ARM64 o release comunitário `v0.4.5-termux.1`; o script reduzido
  foi revisado, fixa o SHA-256 `0dae8257ac7396db4766721e5e4f317679b2080752d32e90d4e6e6fdfee467cf`
  e instala apenas `box64` (não o launcher comercial `dragon`). Até o workflow
  concluir, isso é apenas uma tentativa pendente — não prova de instalação. Esse
  teste arquitetural separado não será apresentado como ação feita pelo modelo.
  Uma atualização de espelho Termux trouxe `aapt2` antigo (13.x) no job Gemma 4,
  que recusou o `android.jar` API 35; o script de build agora fixa o endpoint oficial
  `packages-cf.termux.dev` e atualiza os índices antes de instalar, aguardando nova
  validação. O CI automatiza os toques nos controles explícitos de confirmação;
  isso não é
  uma ação silenciosa. Os APKs
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
no manifesto base, instalar o APK em Android real/emulador com rede, validar buscas
em português e inglês, sem rede, resposta HTTP vazia/limitada e busca desativada;
confirmar URLs e citações visíveis; e executar a regressão completa antes de assinar.
Se também for desejado trocar o nome mostrado sob o ícone, a label do aplicativo
precisa ser alterada separadamente; esta etapa substitui só os PNGs do launcher.
