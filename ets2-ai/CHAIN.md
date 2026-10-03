# Cadeia de treino 100B — contador ao vivo

| metrica | valor |
|---|---|
| amostras acumuladas | **1.000.011.647** |
| % da meta (100 bilhoes) | **1.0%** |
| km simulados equivalentes | ~2.500.029 km |
| sessao media | 2x T4, ~11,5 h, FP32 em fluxo |

Cada janela (seg/qui, workflow `ets2-ai-chain.yml`) colhe a sessao
anterior, versiona o checkpoint privado (Kaggle) e empurra a proxima —
retomando exatamente de onde parou. Totalmente automatico.
