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
- Assinado com o **apksigner oficial** em **APK Signature Scheme v2 + v3**
  (RSA-2048 + SHA-256), válido para Android 7.0 (API 24) em diante.
- APK **zipalignado**: todas as entradas STORED alinhadas a 4 bytes (incluindo
  `resources.arsc`) e bibliotecas `lib/*.so` alinhadas à página (4096), como
  exige o Android 11+/targetSdk 30+.
- Certificado: `CN = GGUF Chat, OU = Mobile, O = GGUF Chat, L = Barbacena,
  ST = Minas Gerais, C = BR`
- SHA-256 do certificado: `221e922ad2d01ef7e59f311afaf1a9ebd9860d962a0b36c598e8de31ac813703`
- SHA-256 do APK: `85e5f62f63807dbb5ebce486fd22001422f9e6cd99c6b42f95dafa8f31f232cd`

## Funcionalidades
- Tema escuro estilo “Off Grid AI”: fundo quase preto com toque de verde,
  superfícies verdes-escuras e acento **verde-esmeralda**
- UI gráfica em português, reorganizada em **3 abas inferiores**:
  **💬 Chat** (lista de conversas), **📁 Importar** (importar GGUFs) e
  **AI Modelos** (gerenciar modelos)
- Na aba **AI Modelos**, o nome do modelo selecionado aparece no topo com uma
  **seta (▼)**; tocar na seta **expande/recolhe** a lista — recolhida, mostra
  **apenas o modelo em uso**
- Modelos **multimodais** (visão) exibem um **ícone de olho (👁)** ao lado do
  nome na lista de modelos
- Ícones menores e mais discretos (olho, marca de seleção e seta)
- Ao abrir uma conversa, o modelo selecionado **carrega automaticamente na
  memória** mostrando o **nome do modelo + porcentagem de carregamento**;
  quando termina, fica visível **apenas o nome do modelo**
- Inferência acelerada por **GPU Vulkan** (todas as camadas; ajustável em Ajustes)
- Importação de modelos GGUF direto do armazenamento do aparelho (sem permissões)
- Importação de **2 GGUFs** (modelo de texto + projetor multimodal/mmproj) com
  **vinculação automática** do mmproj ao modelo principal
- **Associação automática** do mmproj: ao criar uma conversa, o app localiza o
  projetor correspondente pelo nome/arquitetura e o usa sem perguntar
- **Nova conversa** simplificada: escolha o modelo e a conversa é criada na
  hora (sem diálogo extra de multimodal), com o mmproj associado automaticamente
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
