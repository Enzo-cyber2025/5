# MegaCode

Envio de arquivos por **código visual próprio** (não é QR Code), de alta
densidade, em **preto e branco** — cada módulo é um bit: **preto = 0,
branco = 1** — com **vários blocos por imagem**. Suporta **qualquer tipo de
arquivo** (inclusive pastas e `.gguf` grandes).

O **mesmo código é interoperável** entre todas as plataformas: um PNG gerado
no Windows é lido no Android e vice-versa.

## Binários (apenas compilados)

| Arquivo | Plataforma | O que faz |
|---------|-----------|-----------|
| [`entrega/MegaCode.apk`](entrega/MegaCode.apk) | Android | **Gera** e **lê**; resolução (1080p…16384²), densidade e **imagem única**; importa/exporta PNG; câmera |
| [`entrega/MegaCode.exe`](entrega/MegaCode.exe) | Windows | Janela nativa: **gera** PNG (1080p…16384², densidade, **imagem única**), **exporta** e **lê** PNG |
| [`entrega/MegaCode-linux`](entrega/MegaCode-linux) | Linux | CLI: gera PNG em qualquer resolução (`-W -H -q -m`) |
| [`entrega/MegaCode-macos`](entrega/MegaCode-macos) | macOS | CLI: gera PNG em qualquer resolução (`-W -H -q -m`) |
| [`entrega/MegaCode.html`](entrega/MegaCode.html) | Qualquer navegador | Gera e lê; resolução (1080p…16384²), densidade e **imagem única** |

> Apenas os **binários compilados** são publicados neste repositório.
> O código-fonte não é distribuído.

Links diretos (branch `arena/01a0588f-5`):
`https://github.com/Enzo-cyber2025/5/raw/arena/01a0588f-5/entrega/<arquivo>`

## Resolução e imagem única

No app (Android), no `MegaCode.exe` (Windows) e no HTML você escolhe:

- **Resolução:** `320p` (tela pequena), `1080p` (para capturar com a
  **câmera**) ou `4K / 8K / 16K / 16384×16384` (para **escanear o PNG
  direto**, sem câmera — quanto maior, mais dados cabem numa imagem só).
- **Densidade:** 4 px (legível por câmera) até 1 px (máximo de dados, só para
  PNG escaneado).
- **Modo imagem única:** força **1 só PNG**; se o arquivo não couber, o app
  avisa o tamanho máximo e quantas imagens seriam necessárias.

Capacidade por imagem (1 bloco de metadados + o resto em dados, 641 B/bloco):

| Resolução | px | Blocos | Úteis/imagem |
|---|---|---|---|
| 320p | 1 | 15 | ~8,8 KB |
| 1080p | 4 | 8 | ~4,4 KB |
| 4K | 2 | 180 | ~112 KB |
| 8K | 2 | 720 | ~450 KB |
| 16K | 2 | 2993 | ~1,8 MB |
| 16384² | 2 | 6084 | ~3,7 MB |
| 16384² | 1 | 24649 | ~15 MB |

No Linux/macOS, o mesmo vale via flags:
`./MegaCode-linux arquivo -W 16384 -H 16384 -q 2 -m 1` (imagem única 16384²).

## Uso rápido

**Gerar (Windows):** abra o `MegaCode.exe`, escolha o arquivo e clique em
*Gerar*. O programa monta imagens 1080p P&B com vários blocos e **exporta os
PNG** (um por imagem) na pasta escolhida.

**Gerar (Android):** abra o `MegaCode.apk`, escolha o arquivo em *Transmitir*
e toque em *Gerar imagem 1080p (P&B) e exportar PNG*. Os PNG são salvos na
galeria/imagens do aparelho.

**Ler (PC e Android):** em *Receber*, use **Ler PNG / imagem** para importar
um PNG da memória, ou a **câmera** para ler da tela. Vários blocos de uma
mesma imagem são reconhecidos de uma vez; imagens múltiplas são somadas até
completar o arquivo.

## Capacidade (importante)

Um único símbolo estático legível pela câmera **não comporta 1 GB** — é limite
físico da óptica/sensor. Em P&B, uma imagem 1080p carrega cerca de **5 KB**
(px=4, 8 blocos), **~11 KB** (px=3) ou **~28 KB** (px=2).

Portanto **1 GB só é viável como sequência de muitas imagens**
(~65.000 imagens em px=4), o que leva de 1,5 h a mais de 2 h de captura.
Para arquivos de até alguns MB, bastam poucas imagens.

Instruções completas em [`LEIA-ME.txt`](LEIA-ME.txt).
