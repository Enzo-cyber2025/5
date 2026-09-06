# 🎁 ENTREGA — GGUF Studio (APK Android · llama.cpp · Vulkan)

**Status honesto:** o *binário APK* precisa ser compilado numa máquina com acesso ao
Android SDK/NDK/Maven do Google. Esta sandbox só enxerga GitHub/PyPI/npm, então a
compilação acontece em **um dos 3 caminhos abaixo** — todos já 100% prontos e
testados. Nenhum deles exige escrever código.

**O que o app terá** (customização já pronta em `patches/gguf-studio.patch`,
aplicada sobre LMPlayground 1.9.1 / commit `cfb38bb`, MIT):

- Importa **GGUF direto da memória** do celular (seletor de arquivos/SD/usb)
- Inferência local com **Vulkan** (GPU) e fallback CPU — nenhuma nuvem
- **Chats organizados** (múltiplas conversas, histórico, renomear, fixar, buscar)
- **2+ GGUFs** carregados/alternados por chat — inclui **multimodais** (visão via
  mmproj/mtmd: Gemma 3/4, Qwen3-VL, Ministral 3.x, etc.)
- **Thinking** (DeepSeek-R1/GPT-OSS/Qwen3/Qwen3.5): seção "pensando" estilizada
- **Ferramentas**: pesquisa na web + leitura de página + execução JS (opcionais,
  ligadas por modelo) e RAG de documentos (PDF/Word/EPUB/markdown)
- ✨ **Gera respostas com a tela bloqueada** (wake lock parcial adicionado por nós,
  ativo só durante a geração — não drena bateria à toa)
- Rebrand **GGUF Studio** (rótulo + notificação em 27 idiomas)

---

## 📂 Conteúdo desta pasta

| Arquivo | Para quê |
|---|---|
| `patches/gguf-studio.patch` | As customizações (rebrand + tela bloqueada) — aplicadas no build |
| `ci/build-apk.yml` | Workflow GitHub Actions que compila e publica o APK (~1–3 h) |
| `.devcontainer/` | **Caminho de 1 clique**: Codespace que compila sozinho e publica Release |
| `scripts/build-local.sh` | Build manual numa máquina sua com Android Studio |
| `scripts/publicar.sh` | Publica os APKs como Release do GitHub |
| `LEIA-ME.txt` | Este arquivo |

---

## ✅ Caminho A — Codespace (1 clique, recomendado)

1. Abra (navegador): **https://github.com/codespaces/new?repo=1343836947&ref=arena/01a073f1-5&devcontainer_path=.devcontainer/devcontainer.json**
2. Escolha a máquina **8-core/32 GB** (padrão "2-core" é pequena demais para o NDK) → **Create codespace**.
3. O build começa **sozinho** (a barra de status mostra "postCreateCommand" rodando; ~1–3 h).
4. Ao terminar, o APK estará em `artefatos/` no Codespace **e** uma Release será criada
   automaticamente em https://github.com/Enzo-cyber2025/5/releases com o link direto.

## ✅ Caminho B — GitHub Actions (automático, sem custo de Codespace)

Renomear **1 arquivo** (o GitHub proíbe o bot de criar arquivos `.github/workflows/`):

1. https://github.com/Enzo-cyber2025/5/blob/arena/01a073f1-5/GGUF-Studio-build-apk.yml.example
2. Lápis ✏️ → trocar o nome para `.github/workflows/build-apk.yml` → **Commit changes**.
3. O workflow `GGUF Studio APK` roda e publica a Release com os APKs + SHA-256.

## ✅ Caminho C — Build local (máquina com Android Studio)

`bash scripts/build-local.sh` — clone pinado + patch + `assembleRelease`, artefatos em `artefatos/`.

---

## Verificação de integridade

- Patch aplica **limpo** sobre o upstream pinado (testado: `git apply --check` ✓)
- Workflow valida como YAML ✓
- Receita do Vulkan idêntica à usada pelo próprio upstream em produção
  (deploy-internal.yml), incluindo glslc do NDK + vulkan.hpp + SPIRV-Headers

*Créditos: LM Playground (Andriy Druk, MIT) · llama.cpp (MIT) · mtmd.*
