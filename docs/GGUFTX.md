# GGUFTX — trabalho em andamento

**GGUFTX** é o nome pedido para a próxima identidade do GGUF Chat. Esta alteração
melhora a camada-fonte da pesquisa web existente; não é um APK compilado, assinado
ou validado em aparelho.

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
a leitura das fontes originais. O código ainda precisa ser compilado e testado no
APK real com conectividade ativa; esta checkout não contém o toolchain Android nem
uma prova de aceitação para essa mudança.

## Limites e segurança

- **Termux não foi embutido como runtime.** Há agora um hand-off opcional para o
  aplicativo Termux instalado separadamente: o botão lê um bloco `bash`/`sh` da
  última resposta, mostra o comando completo e só o envia ao Termux após confirmação
  explícita. Requer Termux com `RUN_COMMAND`/“Allow external apps” habilitado; a
  saída fica no próprio Termux e não é devolvida automaticamente à IA. O hand-off
  ainda precisa de teste em Android com Termux instalado e a permissão concedida.
  A execução arbitrária silenciosa continua desativada: comandos podem apagar
  dados, expor credenciais ou instalar software.
- **Contexto e tokens não podem ser ilimitados.** São limitados pela arquitetura
  do modelo, pelo arquivo GGUF, pela memória/VRAM e pelo próprio Android. Remover
  as verificações pode causar OOM, travamentos ou perda de dados. Os limites
  existentes continuam explícitos e configuráveis quando o motor/modelo permite.
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
