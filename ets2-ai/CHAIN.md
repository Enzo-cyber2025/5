# Cadeia de treino 500B — contador ao vivo

| metrica | valor |
|---|---|
| amostras acumuladas | **22,545,070,657** |
| % da meta (500 bilhoes de amostras = ~1,25 bilhao de km) | **4.51%** |
| km simulados equivalentes | ~56,362,677 km |
| certificado 1 BILHAO de km (400 bi de amostras) | ainda nao — faltam 377,454,929,343 amostras (~943,637,323 km) |
| garantia anti-repeticao | semente da sessao = SEED + acumulado — nenhuma sessao repete dados (impressao digital no metrics.json) |
| sessao media | 2x T4, ~11,5 h, FP32 em fluxo |

Cada janela (seg/qui/sab) colhe a sessao anterior, versiona o checkpoint privado (Kaggle) e empurra a proxima. Automatico.
