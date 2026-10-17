# Cadeia de treino 500B — contador ao vivo

| metrica | valor |
|---|---|
| amostras acumuladas | **18,893,836,176** |
| % da meta (500 bilhoes de amostras = ~1,25 bilhao de km) | **3.78%** |
| km simulados equivalentes | ~47,234,590 km |
| certificado 1 BILHAO de km (400 bi de amostras) | ainda nao — faltam 381,106,163,824 amostras (~952,765,410 km) |
| garantia anti-repeticao | semente da sessao = SEED + acumulado — nenhuma sessao repete dados (impressao digital no metrics.json) |
| sessao media | 2x T4, ~11,5 h, FP32 em fluxo |

Cada janela (seg/qui/sab) colhe a sessao anterior, versiona o checkpoint privado (Kaggle) e empurra a proxima. Automatico.
