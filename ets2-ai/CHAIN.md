# Cadeia de treino 500B — contador ao vivo

| metrica | valor |
|---|---|
| amostras acumuladas | **19,138,580,156** |
| % da meta (500 bilhoes de amostras = ~1,25 bilhao de km) | **3.83%** |
| km simulados equivalentes | ~47,846,450 km |
| certificado 1 BILHAO de km (400 bi de amostras) | ainda nao — faltam 380,861,419,844 amostras (~952,153,550 km) |
| garantia anti-repeticao | semente da sessao = SEED + acumulado — nenhuma sessao repete dados (impressao digital no metrics.json) |
| sessao media | 2x T4, ~11,5 h, FP32 em fluxo |

Cada janela (seg/qui/sab) colhe a sessao anterior, versiona o checkpoint privado (Kaggle) e empurra a proxima. Automatico.
