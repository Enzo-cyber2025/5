# GGUF Chat — APK de instalação direta

Aplicativo Android para conversar com modelos **GGUF** locais, com inferência via
**llama.cpp** (engine **llamarn 0.10.5**) e aceleração por **GPU Vulkan**
(com fallback automático para CPU nos aparelhos sem driver Vulkan).

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
3. Abra o app, importe seus modelos GGUF em **Modelos** e crie conversas.

> **Atenção:** esta versão é assinada com uma chave nova (v2). Se você tinha a
> versão anterior instalada e a instalação acusar conflito de assinatura,
> desinstale a versão antiga e instale esta.

## Assinatura
- Assinado com o **apksigner oficial** em **APK Signature Scheme v2 + v3**
  (RSA-2048 + SHA-256), válido para Android 7.0 (API 24) em diante.
- APK **zipalignado** (todas as entradas STORED alinhadas a 4 bytes, incluindo
  `resources.arsc`, exigência do Android 11+/targetSdk 30+).
- Certificado: `CN = GGUF Chat, O = GGUF Chat, C = BR`
- SHA-256 do certificado: `41:FC:35:A2:3F:E4:79:B9:D1:75:B0:1E:7E:03:1B:C6:62:91:88:41:81:D7:9B:BC:80:1B:7A:88:D5:B6:6B:AB`
- SHA-256 do APK: `9e6f0bba2fea02a9be81a754ab31dcfa4b052f7f35fb1d2f7a5000d246baeb0d`

## Funcionalidades
- UI gráfica em português
- Inferência acelerada por **GPU Vulkan** (todas as camadas; ajustável em Ajustes)
- Importação de modelos GGUF direto do armazenamento do aparelho (sem permissões)
- Importação de **2 GGUFs** (modelo de texto + projetor multimodal/mmproj)
- Organização em múltiplas conversas (multi-chat)
- Ferramenta **Thinking** (raciocínio estendido)
- Ferramenta **Busca** (pesquisa na web)
- Anexar **qualquer arquivo** à conversa (botão **Anexar** na barra de envio:
  abre o seletor de documentos com `*/*`; arquivos de texto/código têm o
  conteúdo lido e enviado junto com a mensagem; binários são anexados pelo
  nome para o modelo responder sobre eles)
- **Ajustes** agora inclui os padrões das ferramentas (`Thinking` / `Busca`),
  aplicados a toda nova conversa criada
- Geração com a **tela bloqueada** (serviço em primeiro plano + wakelock)

## Download direto
https://github.com/Enzo-cyber2025/5/raw/arena/01a077ef-5/GGUF-Chat.apk
