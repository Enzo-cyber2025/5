# MegaCode

Envio de arquivos por **código visual próprio** (não é QR Code), de alta
densidade, em **preto e branco**, com **vários blocos por imagem 1080p**.
Suporta **qualquer tipo de arquivo** (inclusive pastas e `.gguf` grandes).

O **mesmo código é interoperável** entre todas as plataformas: um PNG gerado
no Windows é lido no Android e vice-versa.

## Binários (apenas compilados)

| Arquivo | Plataforma | O que faz |
|---------|-----------|-----------|
| [`entrega/MegaCode.apk`](entrega/MegaCode.apk) | Android | **Gera** e **lê** códigos; importa PNG da memória; exporta PNG na galeria; leitura pela câmera |
| [`entrega/MegaCode.exe`](entrega/MegaCode.exe) | Windows | Janela nativa (sem terminal/navegador): **gera** e **exporta** PNG, e **lê** PNG |
| [`entrega/MegaCode-linux`](entrega/MegaCode-linux) | Linux | Linha de comando: gera PNG |
| [`entrega/MegaCode-macos`](entrega/MegaCode-macos) | macOS | Linha de comando: gera PNG |
| [`entrega/MegaCode.html`](entrega/MegaCode.html) | Qualquer navegador | Gera e lê (arquivo único, sem instalação) |

> Apenas os **binários compilados** são publicados neste repositório.
> O código-fonte não é distribuído.

Links diretos (branch `arena/01a0588f-5`):
`https://github.com/Enzo-cyber2025/5/raw/arena/01a0588f-5/entrega/<arquivo>`

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
