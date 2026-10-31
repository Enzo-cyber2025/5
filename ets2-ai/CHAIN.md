# Cadeia de treino 500B — contador ao vivo

| metrica | valor |
|---|---|
| amostras acumuladas | **41,115,540,338** |
| % da meta (500 bilhoes de amostras = ~1,25 bilhao de km) | **8.22%** |
| km simulados equivalentes | ~102,788,851 km |
| certificado 1 BILHAO de km (400 bi de amostras) | ainda nao — faltam 358,884,459,662 amostras (~897,211,149 km) |
| garantia anti-repeticao | semente da sessao = SEED + acumulado — nenhuma sessao repete dados (impressao digital no metrics.json) |
| sessao media | 2x T4, ~11,5 h, FP32 em fluxo |

Cada janela (seg/qui/sab) colhe a sessao anterior, versiona o checkpoint privado (Kaggle) e empurra a proxima. Automatico.
