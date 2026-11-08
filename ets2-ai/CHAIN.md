# Cadeia de treino 500B — contador ao vivo

| metrica | valor |
|---|---|
| amostras acumuladas | **56,850,408,605** |
| % da meta (500 bilhoes de amostras = ~1,25 bilhao de km) | **11.37%** |
| km simulados equivalentes | ~142,126,022 km |
| certificado 1 BILHAO de km (400 bi de amostras) | ainda nao — faltam 343,149,591,395 amostras (~857,873,978 km) |
| garantia anti-repeticao | semente da sessao = SEED + acumulado — nenhuma sessao repete dados (impressao digital no metrics.json) |
| sessao media | 2x T4, ~11,5 h, FP32 em fluxo |

Cada janela (seg/qui/sab) colhe a sessao anterior, versiona o checkpoint privado (Kaggle) e empurra a proxima. Automatico.
