# GGUF Studio — entrega do APK (Android, llama.cpp + Vulkan)

App Android **100% offline** para rodar modelos **GGUF** importados da memória do aparelho:
UI em chats organizados, aceleração **Vulkan** (com fallback CPU), modelos **multimodais** (visão/mmproj),
exibição de **thinking**, ferramentas de **pesquisa na web** e leitura de páginas, e geração contínua
**com a tela bloqueada** (wake lock parcial ativo só durante a geração).

## O que tem neste repositório (branch `arena/01a073f1-5`)

| Arquivo | Descrição |
|---|---|
| `patches/gguf-studio.patch` | Customizações (rebrand + wake lock p/ tela bloqueada) sobre o upstream LMPlayground (MIT), commit pinado `cfb38bb` |
| `GGUF-Studio-build-apk.yml.example` | Workflow de build — **renomear para `.github/workflows/build-apk.yml`** |
| `README.md` | Este arquivo |

> **Sem código-fonte do app aqui**: a compilação busca o upstream pinado, aplica o patch e gera o APK.
> Motivo do passo manual: o GitHub proíbe apps/bots de criar arquivos em `.github/workflows/` (regra da plataforma).

## Passo único (dono da conta)

1. Abrir: <https://github.com/Enzo-cyber2025/5/blob/arena/01a073f1-5/GGUF-Studio-build-apk.yml.example>
2. Clicar no lápis ✏️ (Editar)
3. Trocar o nome do arquivo para: `.github/workflows/build-apk.yml`
4. **Commit changes** (branch `arena/01a073f1-5`)

O build dispara sozinho (~1–3 h nos runners do GitHub) e publica uma **Release** com:
`app-universal-release.apk`, `app-arm64-v8a-release.apk`, `app-x86_64-release.apk` + SHA-256.

Link da release (após o build): <https://github.com/Enzo-cyber2025/5/releases>
