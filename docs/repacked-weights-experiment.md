# Segunda hipótese para 2×: layout Q5 → Q8 sem mudar valores

A expansão F32 de `35402357865` foi rejeitada. Os 537.919.488 bytes de valores
foram verificados, mas os resultados pareados foram ~+3,97% ON e **−23,18% OFF**
contra o histórico, com 538.738.176 bytes adicionais de GPU. Não habilitar essa
via nem usar os 7,38 T/s do segundo runner contra os 3,98 T/s de outro runner.
Não alcançou 2× nem passou o controle de regressão.

Nova hipótese: os blocos Q5_0 gastam instruções extraindo bits. Um shader Vulkan
reorganiza **dois blocos de 22 bytes em dois de 34 bytes**, copiando literalmente
os bits das escalas FP16 e expandindo apenas os inteiros assinados de 5 para 8
bits. Não roda um quantizador Q8 comum: ele escolheria outra escala e mudaria os
pesos. Não altera arquivo GGUF, precisão dos valores, modelo ou sampling.

- Preparação executada na GPU, somente operações inteiras no shader.
- Ativada apenas por build `GGUF_EXPERIMENT_REPACKED_WEIGHTS=1` e ambiente
  `GGUF_REPACK_WEIGHTS=1`. OFF por padrão, mutuamente exclusiva com F32.
- Apenas pesos Q5_0 contíguos, com número de elementos múltiplo de 64 e dentro
  do limite de dispatch. Q4_K, Q6_K, Q8_0, normas e demais tensores preservados.
- Não muda kernels existentes de matvec, não quantiza ativações nem liga MMVQ.
  Primeiro teste somente llvmpipe com fp16:0 e int dot:0; hardware móvel requer
  qualificação separada.
- Preparação transacional: mudar ponteiros/tipos somente após todas as
  alocações/conversões/verificações, mantendo o limite conservador do experimento.
- Verificação fora das medições: conferir **cada escala e cada inteiro**
  produzido na GPU contra os bytes Q5 originais, além de comparar bit a bit os
  valores F32 interpretados por referências independentes Q5 e Q8. Referências
  CPU não fornecem pesos à inferência; apenas conferem o resultado da GPU.
- Previsão de custo: layout Q5 ocupa ~54,5% mais bytes que esses blocos originais
  (e estes continuam residentes). Não prometer que será mais rápido antes de medir.

Mesmo protocolo de três trios alternados do experimento F32: pré-aceleração
0c45fd2e, entregue bd7c45d3 e candidato. Mesmos prompts completos, GGUF, 128
tokens, configurações e Vulkan via llvmpipe no emulador. Excluir carregamento/prefill/primeiro
token; excluir warmup e TODA a etapa de verificação. Requer **≥2× contra o
histórico em todos os pares**, sem queda contra o entregue, nos dois estados.

`repacked-weights.yml` compila o shader e as duas arquiteturas, executa a prova
numérica antes das medições e publica inclusive rejeições. Não aprova release
nem troca certificado ou APK entregue. GPU física, imagens, memória/inicialização
e compatibilidade ampla continuam fora da aprovação desta fixture textual.


## Resultado final: 35404555171 rejeitado

Compilação nativa e prova de valores passaram; ambos os estados completaram
observações válidas, mas retornaram **TWO_TIMES_TARGET_NOT_MET**. Fonte
`568af56a3db44ab28278b6c708754ee9334ff66d`; APK experimental
`365982a91b5f25b122d7f74db59420ebbe85c478e7d044ecdfe287c4f63c9a72`.
166 tensores convertidos, 312.311.808 bytes de valores F32 interpretados
verificados, além de escalas/inteiros; 82.957.824 bytes adicionais de buffers.

| Tela | Histórico T/s mediano | Entregue T/s mediano | Candidato T/s mediano | Ganho pareado mediano vs histórico | vs entregue |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ligada | 6.969238311 | 6.904573260 | 6.184322713 | -10.318858% | -10.279705% |
| Apagada | 8.796873054 | 8.871023776 | 8.198547015 | -6.415037% | -7.580599% |

Os seis pares históricos e os seis pares contra o entregue foram regressões.
Não habilitar nem entregar. Estados em runners diferentes: as taxas absolutas
não medem o efeito de apagar a tela. Prova fora do tempo; Vulkan por software,
não a GPU física do telefone. APK entregue intacto.

Após reconexão, evidências recuperadas por Git autenticado no commit
`186f7f795b820bca682e553c35483864593497db`; ambos os resumos foram reavaliados
localmente, com igualdade integral aos relatórios publicados. A tentativa
anterior por página pública não é mais a única fonte disponível.

A nova meta solicitada é **+200% = 3×**. Isso não altera retroativamente os
relatórios 2× rejeitados. A próxima hipótese separada está documentada em
[row-tile-experiment.md](row-tile-experiment.md).
