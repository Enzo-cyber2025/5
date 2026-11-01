# Cadeia de treino 500B — contador ao vivo

| metrica | valor |
|---|---|
| amostras acumuladas | **50,716,720,395** |
| % da meta (500 bilhoes de amostras = ~1,25 bilhao de km) | **10.14%** |
| km simulados equivalentes | ~126,791,801 km |
| certificado 1 BILHAO de km (400 bi de amostras) | ainda nao — faltam 349,283,279,605 amostras (~873,208,199 km) |
| garantia anti-repeticao | semente da sessao = SEED + acumulado — nenhuma sessao repete dados (impressao digital no metrics.json) |
| sessao media | 2x T4, ~11,5 h, FP32 em fluxo |

Cada janela (seg/qui/sab) colhe a sessao anterior, versiona o checkpoint privado (Kaggle) e empurra a proxima. Automatico.
