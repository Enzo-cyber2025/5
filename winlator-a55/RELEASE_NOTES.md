# Winlator-A55 (Box64 pré-traduzido para Galaxy A55)

Build não-oficial derivada de Winlator 8.0.1-mod (brunovalads), com patch para
o Galaxy A55 (Exynos 1480 / Xclipse 530). O patch **não recompila o jogo**, mas
liga o **cache persistente do dynarec do Box64**: blocos x86 traduzidos para
ARM64 são gravados em `~/.cache/box64/` na primeira execução e reaproveitados
nas próximas. Isso é o mais próximo que existe de "pré-traduzir antes" sem o
código-fonte do jogo — a primeira abertura ainda tem custo de tradução dos
blocos frios, as próximas entram mais rápido e rodam mais estáveis.

Também vem com:
- DXVK forçado (WineD3D desativado) para d3d9/10/11
- Caches persistentes de shaders DXVK/Mesa/Turnip
- `BIGBLOCK=3` (blocos ARM64 maiores, menos overhead de trampolim)
- Variáveis padrão do Wine/Box64 ajustadas para menos ruído de log.

## Como usar

1. Instale o APK (assinado com chave de teste — desinstale qualquer outro
   Winlator antes).
2. Abra o app, crie um container com driver **Turnip** e DX Component **DXVK**
   (padrão de versões recentes do Winlator).
3. Copie a pasta do seu BeamNG.drive extraído para `Download/BeamNG.drive/`.
4. Crie um atalho para `BeamNG.drive.x64.exe`.
5. Na **primeira** execução, o Box64 traduz e grava os blocos (espera de 2–5 min
   com possível tela preta / compilação de shaders). Na **segunda** em diante,
   os blocos são carregados do cache e o jogo abre mais rápido.

## FPS esperado

5–14 FPS em cenários simples no A55. Não espere jogabilidade fluida — é uma
camada de tradução e não um port nativo. É o que o hardware consegue com um
executable de PC.

## Arquivos não inclusos

Nenhum arquivo da BeamNG GmbH é distribuído neste APK. Você usa sua própria
cópia extraída do 7z que você subiu no HuggingFace.

## Créditos

Winlator (MIT), Box64 (MIT), Wine (LGPL), DXVK (zlib), Mesa Turnip (MIT),
apktool (Apache 2), uber-apk-signer (Apache 2).
