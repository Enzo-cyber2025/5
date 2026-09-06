# LocalAI — GGUF no Android (fonte)

App Android que roda modelos **GGUF** locais no aparelho com o motor nativo
[`llama.cpp`](https://github.com/ggml-org/llama.cpp), organizado em conversas.

## Importante — o que é real e o que NÃO foi possível fazer aqui

Quero ser 100% transparente com você:

- ✅ **O código-fonte completo do app está pronto e publicado neste branch.**
- ❌ **Não consegui compilar o APK neste ambiente.** Motivos técnicos reais:
  1. Este sandbox não tem Android SDK/NDK/JDK e o servidor oficial de download do
     Android (`dl.google.com`) está **bloqueado** daqui — não há como baixar o
     toolchain para compilar localmente.
  2. O token do agente usado aqui **não tem permissão `workflows`** do GitHub,
     então **não consigo gravar um arquivo `.github/workflows/*.yml`** para
     compilar automaticamente nas Actions do seu repositório.
- Não vou te dar um link falso de "APK pronto" — seria um binário que eu **não
  testei** e, portanto, muito provavelmente quebrado. Prefiro entregar a fonte
  completa + a forma exata de gerar o APK, que é o caminho honesto.

> O build do app (nativo C++ do llama.cpp + Vulkan) exige compilar de verdade.
> Qualquer `.apk` gerado precisa ser compilado em um ambiente com Android NDK —
> aqui esse ambiente não existe.

## Como gerar o APK (2 formas)

### Forma A — GitHub Actions (recomendada, te dá um link de download direto)
Este repo contém o workflow pronto em **`ci/localai-build-apk.yml`** (CPU e
Vulkan). Para ativá-lo:

1. Copie-o para `.github/workflows/build-apk.yml` (no seu clone/PC ou direto no
   GitHub web → Add file).
2. Commit/push essa cópia (você tem a permissão `workflows`, o bot não tem).
3. No GitHub → aba **Actions** → **build-apk** → **Run workflow**.
4. Quando terminar, o APK fica em **artifact** e também é publicado no branch
   em `keep/localai-cpu.apk` e `keep/localai-vulkan.apk`, gerando links diretos:
   `https://github.com/<seu-user>/5/raw/<branch>/keep/localai-cpu.apk`

### Forma B — Android Studio (no seu PC)
```
git clone https://github.com/Enzo-cyber2025/5
cd 5
git clone https://github.com/ggml-org/llama.cpp.git llama.cpp
# abre a pasta no Android Studio (NDK 29, CMake 3.31, JDK 17, SDK 36)
# Build → Build APK(s)          (CPU)
# ou:
./gradlew :app:assembleDebug                 # CPU
./gradlew :app:assembleDebug -PggmlVulkan=true  # Vulkan (precisa de Vulkan SDK + glslc no host)
```

## Recursos do app

- Importa `.gguf` da **memória do aparelho** (SAF) em **2 espaços de modelo**
  (até 2 modelos, ex.: text + vision/multimodal, alternando por conversa).
- Inferência local via llama.cpp: build `vulkan` liga `GGML_VULKAN=ON` (GPU)
  com CPU como reserva; build `cpu` usa o backend oficial (SME2/AMX/KleidiAI).
- **Conversas**: criar, renomear, excluir; cada uma com modelo e histórico.
- Ferramentas por mensagem: **Pensar** (chain-of-thought com bloco recolhível) e
  **Pesquisar na web**.
- **Gera com a tela bloqueada** — serviço em primeiro plano + `WakeLock`
  parcial (desligável em Configurações).
- Anexar imagem (mostrada na conversa). **Limitação honesta:** o motor deste
  APK processa apenas texto — alimentar pixels de verdade exigiria o pipeline
  `mmproj`/LLaVA completo em C++, fora do escopo deste build.

## Instalar
Baixe o `.apk` gerado, abra no aparelho (assinado com chave de debug → "Instalar
mesmo assim"), toque em ☰ → **Modelos (GGUF)** → **Importar GGUF**, escolha um
arquivo na memória (ex.: quantizado Q4/Q5 de ~1–4 GB) e converse.

---
*Estrutura: `app/` (UI em Kotlin), `lib/` (binding nativo llama.cpp, baseado no
exemplo oficial `examples/llama.android`), `ci/` (workflow de build).*
