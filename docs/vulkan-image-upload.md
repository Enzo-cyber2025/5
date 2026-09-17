# Entrada de imagens: reorganização RGB em Vulkan (experimental)

## O que foi implementado

O caminho opt-in `GGUF_VULKAN_IMAGE_PACK=1` recebe os pixels F32 preparados no
layout RGB intercalado já existente. Faz upload diretamente desses buffers e usa
um `PERMUTE` de metadados seguido de `CONT` no grafo Vulkan para produzir o layout
planar exigido pelo projetor. Isso evita o vetor planar temporário e o laço de
reorganização de pixels na CPU. A operação é cópia/reordenação, não aritmética:
não troca dtype, normalização, resolução, canais ou conteúdo.

Não basta entregar um tensor HWC como se fosse CHW: o shader im2col fixado espera
pixels planares contíguos. Por isso há uma operação de cópia real na GPU.

A opção exige um grafo RGB de visão e o escopo Vulkan estrito. Caso não haja
entrada compatível, o experimento falha explicitamente. Áudio não é modificado.
Sem a variável, permanece o caminho anterior. **Ainda está desativado por padrão**
e não foi liberado em um novo APK de entrega.

## O que continua na CPU

- Seleção/importação e leitura dos arquivos, além do gerenciamento do Android.
- Decodificação pelo ImageDecoder/stb, orientação e preparação de cor existentes.
- Redimensionamento, recortes e normalização atuais do mtmd.
- Orquestração do upload e eventuais cópias host do driver.

Portanto, **não é envio ou pré-processamento inteiramente GPU**. O modelo e o
projetor continuam sujeitos à política de cálculo tensorial em Vulkan sem
fallback CPU. O Android também pode usar GPU para compor a interface; não há
reserva física exclusiva de GPU para o modelo.

## Correção, medição e limites

`GGUF_VERIFY_IMAGE_PACK=1` mantém o tensor planar vivo, lê seu resultado da GPU
e compara cada float por seus bytes com o mapeamento RGB de referência. Também
registra SHA-256 de todos os bytes dos embeddings produzidos pelo projetor, nos
dois modos. Esses hashes existem apenas no diagnóstico, não no uso normal.

O teste Android usa o **mesmo APK** nos dois modos, a mesma foto pública, o mesmo
GGUF e parâmetros. O cache de embeddings é desativado nos dois, para não pular a
operação que se pretende testar. Compara a lista de hashes dos embeddings e a
resposta bruta persistida, sem aparar espaços. Readback/verificação acrescentam
trabalho: tempos desse ensaio não são aprovação de velocidade.

Testes host compilam o grafo real ggml e comparam layouts 1×1, 5×3 com batch 2,
32×17 com batch 3 e 384×384, incluindo zero negativo. A execução desses testes
usa CPU explicitamente; não é prova de execução Vulkan. O CI faz essa prova no
Android por Vulkan de software, que também não certifica GPU física.

O build passa a restaurar os arquivos rastreados da dependência fixada antes de
reaplicar os patches desta versão. Isso impede que um cache de compilação traga
silenciosamente alterações de outro experimento. Não apaga modelos, dados do app
ou arquivos do repositório principal.

O workflow de entrada RGB tem grupo de concorrência próprio: não substitui nem
cancela o experimento integrado anterior `35252559185` (fonte `81bc70c`).

Sem resultado Android concluído, não há comprovação de equivalência no dispositivo,
ganho de velocidade, aprovação de release ou cumprimento do objetivo de levar
todo o pré-processamento para a GPU.
