# Cadeia de treino 500B — contador ao vivo

| metrica | valor |
|---|---|
| amostras acumuladas | **60,536,746,152** |
| % da meta (500 bilhoes de amostras = ~1,25 bilhao de km) | **12.11%** |
| km simulados equivalentes | ~151,341,865 km |
| certificado 1 BILHAO de km (400 bi de amostras) | ainda nao — faltam 339,463,253,848 amostras (~848,658,135 km) |
| garantia anti-repeticao | semente da sessao = SEED + acumulado — nenhuma sessao repete dados (impressao digital no metrics.json) |
| sessao media | 2x T4, ~11,5 h, FP32 em fluxo |

Cada janela (seg/qui/sab) colhe a sessao anterior, versiona o checkpoint privado (Kaggle) e empurra a proxima. Automatico.
