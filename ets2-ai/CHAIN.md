# Cadeia de treino 500B — contador ao vivo

| metrica | valor |
|---|---|
| amostras acumuladas | **12,513,164,941** |
| % da meta (500 bilhoes de amostras = ~1,25 bilhao de km) | **2.50%** |
| km simulados equivalentes | ~31,282,912 km |
| certificado 1 BILHAO de km (400 bi de amostras) | ainda nao — faltam 387,486,835,059 amostras (~968,717,088 km) |
| garantia anti-repeticao | semente da sessao = SEED + acumulado — nenhuma sessao repete dados (impressao digital no metrics.json) |
| sessao media | 2x T4, ~11,5 h, FP32 em fluxo |

Cada janela (seg/qui/sab) colhe a sessao anterior, versiona o checkpoint privado (Kaggle) e empurra a proxima. Automatico.
