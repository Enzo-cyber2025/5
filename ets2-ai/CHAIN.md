# Cadeia de treino 500B — contador ao vivo

| metrica | valor |
|---|---|
| amostras acumuladas | **41,224,795,370** |
| % da meta (500 bilhoes de amostras = ~1,25 bilhao de km) | **8.24%** |
| km simulados equivalentes | ~103,061,988 km |
| certificado 1 BILHAO de km (400 bi de amostras) | ainda nao — faltam 358,775,204,630 amostras (~896,938,012 km) |
| garantia anti-repeticao | semente da sessao = SEED + acumulado — nenhuma sessao repete dados (impressao digital no metrics.json) |
| sessao media | 2x T4, ~11,5 h, FP32 em fluxo |

Cada janela (seg/qui/sab) colhe a sessao anterior, versiona o checkpoint privado (Kaggle) e empurra a proxima. Automatico.
