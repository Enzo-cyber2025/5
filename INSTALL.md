# GGUF Chat — APK de instalação direta

Aplicativo Android para conversar com modelos **GGUF** locais, com inferência via
**llama.cpp** (engine **llamarn 0.10.5**) e aceleração por **GPU Vulkan**.

## Requisitos
- Android **7.0 (API 24)** ou superior
- Arquitetura **arm64-v8a** (todos os celulares reais) — suportado desde API 24
- Arquitetura **x86_64** (emuladores/ChromeOS) — recomendado API 29+ para o
  motor nativo; use um emulador com Android 10 (API 29) ou mais recente
- Pelo menos ~4 GB de RAM para modelos de 3B–7B (varia com o modelo)
- Para acelerar na GPU: aparelho com suporte a **Vulkan**

## Instalação
1. Baixe o arquivo **`GGUF-Chat.apk`** (link direto abaixo).
2. No celular, toque no arquivo baixado e autorize a instalação de
   "fontes desconhecidas" quando solicitado.
3. Abra o app, importe seus modelos GGUF em **Importar** / **AI Modelos** e
   crie conversas.

> **Atenção (assinatura nova):** esta compilação é assinada com uma **chave
> nova**, pois a keystore da compilação anterior não existe mais. Se o aparelho
> já tem uma versão antiga do app instalada, **desinstale a versão antiga antes
> de instalar esta** (o Android bloqueia atualização com assinatura diferente).

## Assinatura
- Assinado em **APK Signature Scheme v2** (RSA-2048 + SHA-256, algoritmo
  `0x0103` = RSASSA-PKCS1-v1_5 com SHA-256), válido para Android 7.0 (API 24)
  em diante — exatamente o `minSdkVersion` deste APK.
- A assinatura foi gerada com um **assinador v2 escrito em Python puro**
  (implementação fiel da especificação AOSP `apksig`: bloco "APK Sig Block 42",
  digestão SHA-256 em blocos de 1 MiB com os prefixos `0xa5`/`0x5a` e
  assinatura RSA sobre o `signed data`) e verificada de forma independente
  (recomputação do digest + verificação RSA + parser v2 do androguard).
- APK **zipalignado**: entradas `STORE` alinhadas e bloco de assinatura múltiplo
  de 4096 bytes, preservando o layout de memória das bibliotecas nativas.
- Certificado: `CN = GGUF Chat, O = ggufchat, C = BR`
- SHA-256 do certificado: `47fb4107ed9069d840da269d720f9bc2340186274227fe1b0eeedcd527c1251f`
- SHA-1 do certificado: `a7ac8a4ae4cdf32416206917fa210847c1acf62f`
- SHA-256 do APK: `7c64d6223ee5259274f9061184069c1e3488d5dc86e79c10deb16b41c74e4a72`

> **Correção da instalação ("App não instalado"):** a compilação anterior falhava na
> instalação porque o digest de conteúdo da assinatura v2 era calculado com o campo
> de offset do EOCD errado (o verificador do Android usa `block_start`, não
> `block_end`). A assinatura foi refeita com o algoritmo exato do AOSP `apksig`
> (verificado bit a bit contra uma assinatura real do `apksigner`) e confirmada de
> forma independente: digest de conteúdo idêntico, assinatura RSA verificada e
> estrutura do bloco validada.

> **Aviso honesto sobre a assinatura:** a keystore das compilações anteriores
> foi perdida na reinicialização do ambiente e **não é recuperável** sem a
> chave original. Esta compilação usa uma **keystore nova (RSA-2048)** e é
> assinada **somente em v2** (sem v3), portanto a assinatura **NÃO é a mesma**
> da versão anterior. Instalações antigas precisam ser **desinstaladas** antes
> de instalar esta. Se você fornecer a keystore original (`.jks`/`.keystore` +
> senhas), eu reassino com a mesma assinatura.

## Correções desta compilação
- **Crash ao abrir conversa em aparelho real (arm64) — correção nativa da causa
  raiz**: a função `ggml_backend_vk_host_buffer_type_alloc_buffer` seguia
  adiante com um **ponteiro nulo** quando a alocação de **memória "pinned" da
  GPU** falhava sem lançar exceção (comum em celulares ao carregar modelos
  grandes com todas as camadas na GPU). O binário `libggml-vulkan.so` (arm64)
  foi corrigido por **patch binário** para, nesse caso, cair no fallback de
  **CPU** (`ggml_backend_cpu_buffer_type` / `ggml_backend_buft_alloc_buffer`)
  em vez de usar o ponteiro nulo. Com isso a falha vira um caminho tratável:
  o carregamento prossegue em **CPU** e a conversa abre em vez de derrubar o
  app. O Vulkan continua sendo o caminho padrão quando o aparelho aguenta.
- **Unificação automática ainda mais abrangente (modelo + mmproj)**: além do
  casamento por nome, o app agora reconhece o projetor também pela
  **arquitetura `clip`** (arquivos mmproj que não têm "mmproj" no nome) e
  **auto-unifica qualquer modelo já marcado como multimodal**, mesmo que a
  arquitetura não esteja na lista de visão. Sempre que houver um projetor
  compatível, os dois modelos selecionados são **fundidos automaticamente em
  um só** ao criar a conversa — sem diálogo extra.
- **Unificação automática dos dois modelos selecionados (modelo + mmproj)**: ao
  criar uma conversa com um modelo de visão, o app agora **procura e vincula o
  projetor (mmproj) sozinho, sem diálogo extra**, sempre que existe um mmproj
  correspondente — os dois são **fundidos em um único modelo multimodal** e
  carregados **juntos**. O seletor manual de mmproj só aparece quando há mmproj
  importado mas nenhum corresponde ao modelo escolhido. Além disso, a
  comparação de `id` durante a fusão ganhou **proteção contra `null`** (evita
  `NullPointerException` ao trocar o modelo vinculado na lista).
- **Fallback defensivo de GPU → CPU ao carregar**: se a criação do motor com
  offload Vulkan falhar (aparelho sem Vulkan utilizável), o app tenta recriar o
  motor com **0 camadas na GPU (CPU)** antes de mostrar erro — em vez de
  fechar/derrubar o app na abertura da conversa.
- **Crash ao abrir conversa — correção definitiva do cache do motor**: a
  comparação do projetor no cache do motor estava **invertida** para conversas
  **sem projetor**. Com isso, o app **recriava o motor nativo a cada abertura
  de conversa** (e chegava a reutilizar um motor sem projetor quando o projetor
  era necessário), o que podia travar o processo nativo (Vulkan) ao abrir a
  conversa. Agora o motor é **reutilizado** quando modelo e projetor batem
  exatamente (inclusive o caso "sem projetor") e recarregado **apenas** quando
  mudam.
- **Abertura de conversa nunca mais derruba o app por erro nativo**: o
  pré-carregamento do modelo em segundo plano agora captura **qualquer erro**
  (`Throwable`, inclusive `UnsatisfiedLinkError` e falhas do motor nativo) e
  mostra uma mensagem amigável em vez de fechar o app.
- **Dois modelos selecionados viram um só (unificação automática)**: ao criar
  uma conversa com um modelo de visão, o app abre o seletor de **projetor
  (mmproj)** para você escolher o segundo arquivo. Ao escolher, os dois são
  **fundidos em um único modelo multimodal** — o caminho do projetor é gravado
  no modelo e ele é marcado como multimodal — e a conversa passa a usar os dois
  **juntos** em uma única carga. Se o modelo já tem projetor vinculado, a
  união é feita automaticamente, sem diálogo extra.
- **Projetor (mmproj) nunca vira o modelo principal**: o projetor de visão
  (mmproj) não é mais selecionável nem aparece na lista de modelos da aba
  **AI Modelos** — ele só aparece na aba **Importar → Downloads** (onde pode
  ser excluído). Tocar no card de um mmproj, tentar criar conversa com ele ou
  a seleção automática de modelo agora é bloqueada com um aviso, impedindo que
  o app tente carregar o projetor como modelo de texto (o que travava o app).
- **Travamento ao abrir conversa corrigido (caminho "null")**: ao salvar uma
  conversa sem projetor, o campo era gravado como `null` do JSON e, ao reler,
  virava a **string** `"null"` — o motor tentava carregar um arquivo chamado
  "null" como projetor e a conversa não abria/travava. Agora `modelPath` e
  `mmprojPath` são normalizados para `null` de verdade ao carregar conversas e
  modelos (e também dentro do motor), evitando o erro.
- **Vínculo do projetor mais seguro**: a associação automática do mmproj agora
  só é feita para modelos que são realmente de visão (nunca para o próprio
  projetor ou para modelos só de texto).
- **Ícone de olho corrigido**: o 👁 (multimodal/visão) aparecia em todos os
  modelos, inclusive nos de texto; agora só aparece nos modelos de visão com
  projetor vinculado.
- **Importação corrigida**: a guarda `isEmpty()` do seletor múltiplo estava
  invertida — importar 1 ou vários `.gguf` não fazia nada (ou podia travar).
  Agora a importação de um ou vários arquivos funciona de verdade.
- **Envio com anexo corrigido**: mensagem com texto + anexo não era enviada, e
  enviar sem texto criava mensagem vazia. Corrigido.
- **Vínculo automático do mmproj corrigido**: a comparação de id estava
  invertida e o projetor não era encontrado ao criar conversa nova.
- **Sem travamento ao abrir conversa inexistente**: agora a tela fecha em vez
  de lançar `NullPointerException`.
- **Permissão de notificações** solicitada em tempo de execução (Android 13+),
  para a notificação da geração em segundo plano aparecer.
- **Crash no Android 14 corrigido**: o receiver da tela de conversa agora é
  registrado com `RECEIVER_NOT_EXPORTED` (obrigatório a partir do Android 14);
  antes o app podia fechar com `SecurityException` ao abrir uma conversa.
- **Anexos de texto lidos como UTF-8**: textos/códigos anexados eram decodificados
  com o charset padrão do aparelho; agora sempre em UTF-8 (acentos e emojis
  corretos).
- **Proteção extra**: nome de arquivo nulo e resumo de conversa com conteúdo
  nulo não causam mais travamento; entidades HTML (`&#36;`, `&#92;`) em
  resultados de busca não derrubam mais o app.
- **Seleção do modelo tocando no card**: na aba **AI Modelos** os botões
  "Usar"/"Excluir" foram removidos; agora basta **tocar no card do modelo**
  para selecioná-lo (fica marcado com ✓). A lista recolhida continua mostrando
  só o modelo em uso.
- **Exclusão na aba Importar (Downloads)**: a aba **Importar** agora tem a
  seção **Downloads** listando todos os modelos baixados, cada um com o botão
  **Excluir**; a lista é atualizada automaticamente ao importar/excluir.
- **Ícones ainda menores**: olho (👁) e marca de seleção (✓) nos cards de
  modelo e a seta (▼) de recolher agora são bem discretos — os botões de
  **criar conversa** ("+ Nova conversa", anexos etc.) **não** foram reduzidos.
- **Travamento ao excluir modelo corrigido**: ao apagar um modelo que estava
  selecionado/em uso, o app podia fechar por referência inválida. Corrigido.
- **Travamento ao renomear/gravar arquivos corrigido**: a gravação atômica de
  `chats.json`/`models.json` usava `File.renameTo` (que falha silenciosamente
  em alguns aparelhos/volumes); agora há fallback que garante a persistência.
- **Leitura de metadados GGUF robusta**: o leitor de metadados encerrava na
  primeira leitura curta (0 bytes), causando malformação; agora só para em EOF
  real, evitando nomes/metadados corrompidos em modelos válidos.
- **Mensagem de erro ao carregar modelo**: se um arquivo GGUF estiver
  corrompido/incompleto, o app avisa em vez de girar eternamente na tela de
  carregamento.
- **Projetor (mmproj) não fica mais “preso” no cache**: ao abrir uma conversa
  do mesmo modelo com projetor diferente (ou sem projetor), o motor agora
  recarrega o modelo corretamente em vez de reutilizar o projetor antigo.
- **Carregamento do modelo + projetor juntos e cache corrigido (crash ao abrir
  conversa)**: a comparação do projetor no cache do motor estava com a lógica
  invertida para modelos sem projetor — isso fazia o app **recriar o motor a
  cada abertura de conversa** (e reutilizar um motor sem projetor quando o
  projetor era necessário), podendo travar o processo. Agora o cache só reusa o
  motor quando **modelo e projetor batem exatamente** (incluindo o caso
  "sem projetor"); caso contrário, o GGUF principal e o mmproj são carregados
  **juntos** em uma única carga.
- **Importação não falha em silêncio**: a renomeação final do arquivo copiado
  agora tem fallback (apagar destino + renomear) e, se ainda falhar, a
  importação é reportada como erro em vez de deixar um modelo quebrado.
- **Lista de modelos mais fluida**: a checagem de “modelo de visão” não
  reabre/reparseia o GGUF na thread de interface a cada card; agora usa os
  dados já salvos (multimodal/mmproj/arquitetura), evitando travamentos na
  rolagem.

## Funcionalidades
- Tema escuro estilo “Off Grid AI”: fundo quase preto com toque de verde,
  superfícies verdes-escuras e acento **verde-esmeralda**
- UI gráfica em português, reorganizada em **3 abas inferiores**:
  **💬 Chat** (lista de conversas), **📁 Importar** (importar GGUFs) e
  **AI Modelos** (gerenciar modelos)
- Na aba **AI Modelos**, o nome do modelo selecionado aparece no topo com uma
  **seta (▼)**; tocar na seta **expande/recolhe** a lista — recolhida, mostra
  **apenas o modelo em uso**
- **Seleção por toque**: tocar em qualquer card de modelo (na aba AI Modelos)
  seleciona o modelo; a marca ✓ indica o modelo em uso
- Modelos **multimodais** (visão) exibem um **ícone de olho (👁)** ao lado do
  nome na lista de modelos
- Ícones menores e mais discretos (olho, marca de seleção e seta)
- Aba **Importar** com seção **Downloads**: lista todos os modelos baixados e
  permite **excluir** cada um diretamente ali
- Ao abrir uma conversa, o modelo selecionado **carrega automaticamente na
  memória** mostrando o **nome do modelo + porcentagem de carregamento**;
  quando termina, fica visível **apenas o nome do modelo**
- Inferência acelerada por **GPU Vulkan** (todas as camadas; ajustável em Ajustes)
- Importação de modelos GGUF direto do armazenamento do aparelho (sem permissões)
- Botão único **Importar .gguf** com **seleção múltipla** no seletor de arquivos:
  selecione o modelo de texto e o projetor (mmproj) de uma vez; o mmproj é
  **vinculado automaticamente** ao modelo de visão
- **Associação automática** do mmproj: ao criar uma conversa, o app localiza o
  projetor correspondente pelo nome/arquitetura e o usa sem perguntar
- **Nova conversa** simplificada: escolha o modelo de texto e a conversa é
  criada na hora. Para modelos de **visão**, um segundo passo opcional deixa
  você escolher o **projetor (mmproj)**; os dois são **fundidos em um único
  modelo multimodal** (com opção "Sem projetor" para usar só texto)
- Importação **mais estável e mais rápida** (buffer de 1 MB, tratamento de
  erros: arquivos inválidos não travam mais o app)
- Organização em múltiplas conversas (multi-chat)
- Ferramenta **Thinking** (raciocínio estendido)
- Ferramenta **Busca** (pesquisa na web)
- Barra de anexos com **botões dedicados**: **Foto**, **Vídeo**, **Áudio**,
  **Arquivo** e **Ferramentas** (abre o diálogo de ferramentas Thinking/Busca)
- Anexar **qualquer arquivo de qualquer tamanho, sem limite**: arquivos de
  texto/código são lidos **por inteiro** e enviados junto com a mensagem;
  fotos/vídeos/áudios e binários são anexados com tipo e tamanho (o motor não
  tem visão/áudio, então entram como metadados para o modelo responder sobre
  eles)
- **Ajustes** inclui os padrões das ferramentas (`Thinking` / `Busca`),
  aplicados a toda nova conversa criada
- Geração com a **tela bloqueada** (serviço em primeiro plano + wakelock)

## Download direto
https://github.com/Enzo-cyber2025/5/raw/arena/01a077ef-5/GGUF-Chat.apk
