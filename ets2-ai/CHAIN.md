# Cadeia de treino 500B — contador ao vivo

| metrica | valor |
|---|---|
| amostras acumuladas | **1,000,011,647** |
| % da meta (500 bilhoes de amostras = ~1,25 bilhao de km) | **0.20%** |
| km simulados equivalentes | ~2,500,029 km |
| certificado 1 BILHAO de km (400 bi de amostras) | ainda nao — faltam 398.999.988.353 amostras (~997.499.971 km) |
| sessao media | 2x T4, ~11,5 h, FP32 em fluxo |

Cada janela (seg/qui) colhe a sessao anterior, versiona o checkpoint privado (Kaggle) e empurra a proxima. Automatico.

Status ao vivo da sessao: [STATUS.md](STATUS.md)
