# Cadeia de treino 500B — contador ao vivo

| metrica | valor |
|---|---|
| amostras acumuladas | **38,859,518,062** |
| % da meta (500 bilhoes de amostras = ~1,25 bilhao de km) | **7.77%** |
| km simulados equivalentes | ~97,148,795 km |
| certificado 1 BILHAO de km (400 bi de amostras) | ainda nao — faltam 361,140,481,938 amostras (~902,851,205 km) |
| garantia anti-repeticao | semente da sessao = SEED + acumulado — nenhuma sessao repete dados (impressao digital no metrics.json) |
| sessao media | 2x T4, ~11,5 h, FP32 em fluxo |

Cada janela (seg/qui/sab) colhe a sessao anterior, versiona o checkpoint privado (Kaggle) e empurra a proxima. Automatico.
