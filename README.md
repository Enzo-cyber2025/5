# GGUF Chat

Aplicativo Android para conversar com modelos **GGUF** locais, com inferência via
**llama.cpp** (engine **llamarn 0.10.5**) e aceleração por **GPU Vulkan**.

## Instalação

Baixe o APK diretamente:

```
https://github.com/Enzo-cyber2025/5/raw/arena/01a077ef-5/GGUF-Chat.apk
```

- Android **7.0 (API 24)** ou superior (arm64-v8a; x86_64 para emuladores/ChromeOS)
- Requisitos, instruções de instalação, assinatura e histórico de correções:
  veja **[INSTALL.md](INSTALL.md)**

## Sobre esta compilação

- **Correção da causa raiz do crash ao abrir conversa (Vulkan/arm64)**: a função
  `ggml_backend_vk_host_buffer_type_alloc_buffer` seguia adiante com um ponteiro
  **nulo** quando a alocação de memória "pinned" da GPU falhava sem exceção. O
  binário nativo (`libggml-vulkan.so`, arm64) foi corrigido por patch binário
  para cair no fallback de **CPU** nesse caso.
- Assinado em **APK Signature Scheme v2** (RSA-2048 + SHA-256). A assinatura usa o
  algoritmo exato do AOSP `apksig` (digest de conteúdo em 3 segmentos + EOCD com
  offset apontando para o início do bloco de assinatura), validado bit a bit contra
  uma assinatura real do `apksigner` e verificado de forma independente.
- **Correção da instalação**: a compilação anterior falhava na instalação
  ("App não instalado") por digest v2 inválido; corrigido nesta compilação.
  SHA-256 do APK: `7c64d6223ee5259274f9061184069c1e3488d5dc86e79c10deb16b41c74e4a72`

> **Atenção:** esta compilação usa uma **keystore nova** (a anterior foi
> perdida). Se já houver uma versão antiga instalada, **desinstale antes de
> instalar esta**.
