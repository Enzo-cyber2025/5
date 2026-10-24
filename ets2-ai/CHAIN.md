# Cadeia de treino 500B — contador ao vivo

| metrica | valor |
|---|---|
| amostras acumuladas | **35,309,394,239** |
| % da meta (500 bilhoes de amostras = ~1,25 bilhao de km) | **7.06%** |
| km simulados equivalentes | ~88,273,486 km |
| certificado 1 BILHAO de km (400 bi de amostras) | ainda nao — faltam 364,690,605,761 amostras (~911,726,514 km) |
| garantia anti-repeticao | semente da sessao = SEED + acumulado — nenhuma sessao repete dados (impressao digital no metrics.json) |
| sessao media | 2x T4, ~11,5 h, FP32 em fluxo |

Cada janela (seg/qui/sab) colhe a sessao anterior, versiona o checkpoint privado (Kaggle) e empurra a proxima. Automatico.
