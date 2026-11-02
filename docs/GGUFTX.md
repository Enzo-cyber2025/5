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
  explícita. Requer Termux com `RUN_COMMAND`/“Allow external apps” habilitado; a
  saída fica no próprio Termux e não é devolvida automaticamente à IA. Comandos
  simples sem fence são limitados a uma linha; scripts multilinha devem vir num
  bloco de código e continuam sujeitos à revisão humana. O teste de emulador do
  candidato de CI usa o APK oficial do Termux e verifica confirmação, permissão
  runtime e arquivo marcador; isso não valida o APK assinado antigo nem comprova
  o fluxo para Gemma 4 E2B/Gemma 3 270M. A execução silenciosa irrestrita continua
  desativada: comandos podem apagar dados, expor credenciais ou instalar software.
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
