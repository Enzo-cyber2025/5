# Cadeia de treino 500B — contador ao vivo

| metrica | valor |
|---|---|
| amostras acumuladas | **12,981,325,251** |
| % da meta (500 bilhoes de amostras = ~1,25 bilhao de km) | **2.60%** |
| km simulados equivalentes | ~32,453,313 km |
| certificado 1 BILHAO de km (400 bi de amostras) | ainda nao — faltam 387,018,674,749 amostras (~967,546,687 km) |
| garantia anti-repeticao | semente da sessao = SEED + acumulado — nenhuma sessao repete dados (impressao digital no metrics.json) |
| sessao media | 2x T4, ~11,5 h, FP32 em fluxo |

Cada janela (seg/qui/sab) colhe a sessao anterior, versiona o checkpoint privado (Kaggle) e empurra a proxima. Automatico.
