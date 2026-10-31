# Cadeia de treino 500B — contador ao vivo

| metrica | valor |
|---|---|
| amostras acumuladas | **45,626,714,820** |
| % da meta (500 bilhoes de amostras = ~1,25 bilhao de km) | **9.13%** |
| km simulados equivalentes | ~114,066,787 km |
| certificado 1 BILHAO de km (400 bi de amostras) | ainda nao — faltam 354,373,285,180 amostras (~885,933,213 km) |
| garantia anti-repeticao | semente da sessao = SEED + acumulado — nenhuma sessao repete dados (impressao digital no metrics.json) |
| sessao media | 2x T4, ~11,5 h, FP32 em fluxo |

Cada janela (seg/qui/sab) colhe a sessao anterior, versiona o checkpoint privado (Kaggle) e empurra a proxima. Automatico.
