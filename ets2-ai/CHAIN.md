# Cadeia de treino 500B — contador ao vivo

| metrica | valor |
|---|---|
| amostras acumuladas | **23,265,545,622** |
| % da meta (500 bilhoes de amostras = ~1,25 bilhao de km) | **4.65%** |
| km simulados equivalentes | ~58,163,864 km |
| certificado 1 BILHAO de km (400 bi de amostras) | ainda nao — faltam 376,734,454,378 amostras (~941,836,136 km) |
| garantia anti-repeticao | semente da sessao = SEED + acumulado — nenhuma sessao repete dados (impressao digital no metrics.json) |
| sessao media | 2x T4, ~11,5 h, FP32 em fluxo |

Cada janela (seg/qui/sab) colhe a sessao anterior, versiona o checkpoint privado (Kaggle) e empurra a proxima. Automatico.
