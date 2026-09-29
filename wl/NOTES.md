# Winlator-A55 pre-AOT

Build não-oficial baseada no Winlator 8.0/8.0.1-mod com patch pré-AOT para
Galaxy A55 (Exynos 1480 / Xclipse 530):

- **Box64 DYNAREC persistente** (`BOX64_DYNAREC_PERSISTENT=1`, `BIGBLOCK=3`):
  blocos x86→ARM64 são gravados em `~/.cache/box64/` na primeira execução e
  reutilizados nas próximas (é o mais próximo de "pré-traduzir antes" sem o
  código-fonte do jogo).
- **DXVK forçado** (DX9/10/11 → Vulkan) via `WINEDLLOVERRIDES`.
- **Caches persistentes**: DXVK state cache + Mesa shader cache.
- Recomendado usar container com driver **Turnip** e **DXVK**.

## Como usar

1. Desinstale qualquer outro Winlator (APK assinado com chave de teste).
2. Instale `W.apk`.
3. Crie um container com Turnip+DXVK.
4. Copie sua própria pasta `BeamNG.drive/` pro celular (este APK **não inclui o
   jogo** — BeamNG.drive é software pago).
5. Crie atalho para `BeamNG.drive.x64.exe`.
6. Primeira execução: 3–5 min de carregamento. A partir da segunda, caches
   reutilizados.

## FPS esperado

5–14 FPS em cenários simples. Isto é tradução dinâmica (Box64+Wine+DXVK), não
um port nativo.

## Créditos

Winlator (MIT), Box64 (MIT), Wine (LGPL), DXVK (zlib), Mesa Turnip (MIT),
apktool (Apache-2), uber-apk-signer (Apache-2).
