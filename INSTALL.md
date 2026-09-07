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
- Assinado com **APK Signature Scheme v2** (RSA-2048 + SHA-256, conforme o
  formato AOSP), válido para Android 7.0 (API 24) em diante.
- Certificado: `CN = GGUF Chat, O = GGUF Chat, C = BR`
- SHA-256 do APK: `947d21a208342ad2eb8199e6eb9611e810608b540ae5616e6b64479fda447e80`

## Funcionalidades
- UI gráfica em português
- Inferência acelerada por **GPU Vulkan** (todas as camadas; ajustável em Ajustes)
- Importação de modelos GGUF direto do armazenamento do aparelho (sem permissões)
- Importação de **2 GGUFs** (modelo de texto + projetor multimodal/mmproj)
- Organização em múltiplas conversas (multi-chat)
- Ferramenta **Thinking** (raciocínio estendido)
- Ferramenta **Busca** (pesquisa na web)
- Geração com a **tela bloqueada** (serviço em primeiro plano + wakelock)

## Download direto
https://github.com/Enzo-cyber2025/5/raw/arena/01a077ef-5/GGUF-Chat.apk
