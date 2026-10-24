# Cadeia de treino 500B — contador ao vivo

| metrica | valor |
|---|---|
| amostras acumuladas | **29,388,869,861** |
| % da meta (500 bilhoes de amostras = ~1,25 bilhao de km) | **5.88%** |
| km simulados equivalentes | ~73,472,175 km |
| certificado 1 BILHAO de km (400 bi de amostras) | ainda nao — faltam 370,611,130,139 amostras (~926,527,825 km) |
| garantia anti-repeticao | semente da sessao = SEED + acumulado — nenhuma sessao repete dados (impressao digital no metrics.json) |
| sessao media | 2x T4, ~11,5 h, FP32 em fluxo |

Cada janela (seg/qui/sab) colhe a sessao anterior, versiona o checkpoint privado (Kaggle) e empurra a proxima. Automatico.
