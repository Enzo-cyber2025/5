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
tokens, configurações e GPU real do emulador. Excluir carregamento/prefill/primeiro
token; excluir warmup e TODA a etapa de verificação. Requer **≥2× contra o
histórico em todos os pares**, sem queda contra o entregue, nos dois estados.

`repacked-weights.yml` compila o shader e as duas arquiteturas, executa a prova
numérica antes das medições e publica inclusive rejeições. Não aprova release
nem troca certificado ou APK entregue. GPU física, imagens, memória/inicialização
e compatibilidade ampla continuam fora da aprovação desta fixture textual.
