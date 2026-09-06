# LocalAI — GGUF no Android

App Android que roda modelos **GGUF** locais no seu próprio aparelho usando o
motor nativo [`llama.cpp`](https://github.com/ggml-org/llama.cpp), organizado
em **conversas**.

> ⚠️ **Compilar:** não é possível compilar/testar neste ambiente (sem SDK/NDK e
> sem GPU). Por isso o APK é compilado automaticamente pelo **GitHub Actions**
> e o binário pronto fica publicável no branch (link direto abaixo). A única
> coisa que eu consigo validar é se o build do Actions fica verde — o teste em
> aparelho é com você.

## Recursos

- Importa arquivos `.gguf` que estão na **memória do aparelho** (SAF) em **2
  espaços de modelo** (você pode ter 2 modelos multimodais/visão, alternando por
  conversa).
- Inferência local via llama.cpp com backend **Vulkan (GPU)** quando disponível
  e **CPU** como reserva. O build `cpu` usa o backend oficial otimizado
  (SME2/AMX/KleidiAI); o build `vulkan` liga `GGML_VULKAN=ON` (experimental).
- **Conversas**: criar, renomear, excluir, cada uma com seu próprio modelo e
  histórico.
- Ferramentas por mensagem: **Pensar** (chain-of-thought, raciocínio mostrado em
  bloco recolhível) e **Pesquisar na web** (contexto buscado antes de responder).
- **Gera resposta com a tela bloqueada** — serviço em primeiro plano com
  `WakeLock` parcial (desativável em Configurações).
- Anexar imagem (exibida na conversa). *Limitação honesta:* o motor embarcado
  neste APK processa somente o texto da mensagem — alimentar os pixels de
  verdade no modelo exigiria o pipeline `mmproj`/LLaVA completo em C++, fora do
  escopo deste build.

## Instalar

1. Baixe o `.apk` abaixo e abra-o no aparelho (toque em "Instalar mesmo assim",
   pois é assinado com a chave de debug).
2. Toque em ☰ → **Modelos (GGUF)** → **Importar GGUF** e escolha o arquivo da
   memória (ex.: um quantizado Q4/Q5 de ~1–4 GB).
3. Volte, escolha/abra uma conversa e digite.

## Links de download direto (sem login)

Serão publicados neste branch após o build do GitHub Actions:

- **CPU** (garantido): `keep/localai-cpu.apk`
- **Vulkan (GPU, experimental)**: `keep/localai-vulkan.apk`

Link cru (troque nada além do caminho):
`https://github.com/Enzo-cyber2025/5/raw/arena/01a07642-5/keep/localai-cpu.apk`

## Build local / recorrência

```
# precisa de NDK 29, CMake 3.31.6, JDK 17 e o llama.cpp clonado ao lado:
git clone https://github.com/ggml-org/llama.cpp.git llama.cpp
./gradlew :app:assembleDebug                 # CPU
./gradlew :app:assembleDebug -PggmlVulkan=true   # Vulkan (requer Vulkan SDK + glslc no host)
```
