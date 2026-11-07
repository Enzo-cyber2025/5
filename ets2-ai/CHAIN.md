# Cadeia de treino 500B — contador ao vivo

| metrica | valor |
|---|---|
| amostras acumuladas | **56,705,701,522** |
| % da meta (500 bilhoes de amostras = ~1,25 bilhao de km) | **11.34%** |
| km simulados equivalentes | ~141,764,254 km |
| certificado 1 BILHAO de km (400 bi de amostras) | ainda nao — faltam 343,294,298,478 amostras (~858,235,746 km) |
| garantia anti-repeticao | semente da sessao = SEED + acumulado — nenhuma sessao repete dados (impressao digital no metrics.json) |
| sessao media | 2x T4, ~11,5 h, FP32 em fluxo |

Cada janela (seg/qui/sab) colhe a sessao anterior, versiona o checkpoint privado (Kaggle) e empurra a proxima. Automatico.
