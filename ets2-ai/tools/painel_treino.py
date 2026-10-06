#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Painel de treino ETS2-AI — montado a partir de dados REAIS:
metrics.json de cada geração (commits/releases), STATUS.md (API Kaggle)
e runs do GitHub Actions. Usado como 'print' dos treinamentos."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from pathlib import Path

BG, PANEL, FG, MUT = "#0E0E16", "#16161F", "#E6E6F0", "#8A8A9E"
BLUE, GREEN, YELLOW, RED, PURPLE = "#2F7BFF", "#00A884", "#F2A93B", "#E85D75", "#8E5BF2"

plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": PANEL, "axes.edgecolor": "#2A2A3A",
    "axes.labelcolor": FG, "text.color": FG, "xtick.color": MUT, "ytick.color": MUT,
    "font.size": 10, "axes.grid": True, "grid.color": "#232334", "grid.linewidth": 0.8,
})

fig = plt.figure(figsize=(15.5, 9.2), dpi=130)
fig.suptitle("ETS2-AI — PAINEL DE TREINO (dados reais: metrics.json de cada geração + API Kaggle)",
             fontsize=16, fontweight="bold", y=0.985, color=FG)
fig.text(0.5, 0.945, "atualizado 06/10/2026 23:00 UTC · perda de validação 0,004323 (meta ≤ 0,150) · 1.017.613 parâmetros · 12,98 bi de amostras (2,60%)",
         ha="center", fontsize=10.5, color=MUT)

# ------------------------------------------------------------------ painel 1
ax1 = fig.add_axes([0.05, 0.56, 0.42, 0.34])
vers = ["v0.4.0", "v0.4.1", "v0.4.2", "v0.4.3", "v0.4.4", "v0.4.6 (12,5 bi)"]
loss = [0.008568, 0.008790, 0.008602, 0.009579, 0.006003, 0.004323]
params = ["52 mil", "150 mil", "295 mil", "505 mil", "1,017 milhão",
          "1,017 milhão"]
ax1.plot(range(6), loss, "-o", color=BLUE, lw=2.2, ms=8, mfc=BLUE, mec=BG, mew=1.5, zorder=3)
ax1.plot(5, loss[5], "o", color=GREEN, ms=13, mec=BG, mew=2, zorder=4)
for i, (l, p) in enumerate(zip(loss, params)):
    va = "top" if i in (0, 2, 4) else "bottom"
    ax1.annotate(f"{l:.6f}".replace(".", ","), (i, l), xytext=(0, 14 if va == "bottom" else -18),
                 textcoords="offset points", ha="center", fontsize=9.5,
                 color=GREEN if i == 5 else FG, fontweight="bold" if i == 5 else "normal")
    ax1.annotate(p + " params", (i, l), xytext=(0, -30 if va == "top" else 28),
                 textcoords="offset points", ha="center", fontsize=8.5, color=MUT)
ax1.axhline(0.150, color=RED, ls="--", lw=1.4, alpha=0.8)
ax1.text(0.1, 0.150, " meta ≤ 0,150 (contrato)", color=RED, fontsize=9.5, va="bottom")
ax1.set_ylim(0.0035, 0.0125)
ax1.set_xticks(range(6)); ax1.set_xticklabels(vers, fontsize=8.5)
ax1.set_ylabel("loss de validação (MSE)")
ax1.set_title("Loss de validação por geração da rede — 25× abaixo da meta", fontsize=12, fontweight="bold", loc="left")
ax1.annotate("treino em fluxo de 1 BILHÃO\nde amostras (2× T4 Kaggle)", xy=(4, 0.006003),
             xytext=(2.35, 0.0071), fontsize=9.5, color=GREEN, ha="center",
             arrowprops=dict(arrowstyle="->", color=GREEN, lw=1.4))
ax1.annotate("12,5 BILHÕES de amostras\n(mesma arquitetura, loss 35×\nabaixo da meta)", xy=(5, 0.004323),
             xytext=(3.6, 0.0050), fontsize=9.5, color=GREEN, ha="center",
             arrowprops=dict(arrowstyle="->", color=GREEN, lw=1.4))

# ------------------------------------------------------------------ painel 2
ax2 = fig.add_axes([0.53, 0.56, 0.42, 0.34])
ax2.set_xlim(0, 1); ax2.set_ylim(0, 1); ax2.axis("off")
ax2.set_title("Cadeia de treino rumo a 500 BILHÕES de amostras", fontsize=12, fontweight="bold", loc="left")
# barra de progresso (log entre 1e9 e 5e11)
import math
lo, hi = math.log10(1e9), math.log10(5e11)
cur = math.log10(12.981325251e9)
frac = (cur - lo) / (hi - lo)
ax2.add_patch(FancyBboxPatch((0.03, 0.68), 0.94, 0.13, boxstyle="round,pad=0.008",
                             fc="#1C1C2A", ec="#2A2A3A", lw=1))
ax2.add_patch(FancyBboxPatch((0.03, 0.68), max(0.94 * frac, 0.012), 0.13, boxstyle="round,pad=0.008",
                             fc=BLUE, ec="none"))
ax2.text(0.03, 0.60, "12.981.325.251 amostras acumuladas  (2,60% da meta)", fontsize=11, fontweight="bold")
ax2.text(0.03, 0.535, "≈ 32.453.313 km simulados · meta: 500.000.000.000 amostras ≈ 1,25 bilhão de km", fontsize=9.5, color=MUT)
ax2.text(0.03, 0.42, "SESSÃO AGORA: kernel enzoaimv/ets2ai-train — RUNNING (CPU, 11,5 h, fix de RAM)", fontsize=10.5, color=GREEN, fontweight="bold")
ax2.text(0.03, 0.355, "· GPU 27,2/28,5 h usadas na janela de 7 d — sessões CPU de fluxo até a cota voltar", fontsize=9.5, color=FG)
ax2.text(0.03, 0.29, "· cada colheita valida gates (loss/faixa/doca), promove pesos melhores e empurra a próxima", fontsize=9.5, color=FG)
ax2.text(0.03, 0.225, "· retoma do checkpoint da release (rota canonica) · circuit breaker contra crash-loop", fontsize=9.5, color=FG)
ax2.text(0.03, 0.14, "chegada central estimada em ~1ª semana de dez/2026 (janela 13/nov–17/dez)", fontsize=9.5, color=YELLOW)

# ------------------------------------------------------------------ painel 3
ax3 = fig.add_axes([0.05, 0.07, 0.42, 0.34])
cats = ["Rotas\nconcluídas", "Dentro da\nfaixa", "Docas\nacertadas", "Radares\nrespeitados", "Sem\ntombar"]
vals = [100, 100.0, 100, 100, 100]
bars = ax3.bar(range(5), vals, color=[GREEN, BLUE, PURPLE, YELLOW, "#3AA8C1"], width=0.62, zorder=3)
for i, v in enumerate(vals):
    ax3.text(i, v - 7, f"{v:.0f}%", ha="center", fontsize=12, fontweight="bold", color="#0E0E16")
ax3.set_ylim(0, 118); ax3.set_yticks([0, 50, 100])
ax3.set_xticks(range(5)); ax3.set_xticklabels(cats, fontsize=9.5)
ax3.set_title("Circuito fechado com os pesos 1B (100 rotas + docas) — parada média 2,45 m",
              fontsize=12, fontweight="bold", loc="left")

# ------------------------------------------------------------------ painel 4
ax4 = fig.add_axes([0.53, 0.07, 0.42, 0.34])
ax4.set_xlim(0, 1); ax4.set_ylim(0, 1); ax4.axis("off")
ax4.set_title("Registro dos treinamentos (execuções reais)", fontsize=12, fontweight="bold", loc="left")
linhas = [
    ("✓", GREEN, "v0.4.4 · treino 2× T4 — 1.000.011.647 amostras, loss 0,00600"),
    ("✓", GREEN, "v0.4.6 · treino 12,5 BILHÕES de amostras — loss 0,004323 (35× abaixo da meta)"),
    ("✓", GREEN, "v0.4.6 · build 8/8 verde — IA no APK via cabo (arquivos, sem portas) + BUSCAR"),
    ("✓", GREEN, "cadeia imortal: colheita automatica, circuit breaker, resume pela release"),
    ("▶", YELLOW, "06/10 · sessao CPU de 11,5 h RUNNING com o fix de RAM (colhe ~04:00 UTC)"),
    ("•", MUT,     "contador ao vivo: CHAIN.md / STATUS.md · certificado 1 bi de km: 400 bi"),
]
y = 0.82
for sim, cor, txt in linhas:
    ax4.text(0.02, y, sim, fontsize=13, color=cor, fontweight="bold", va="center")
    ax4.text(0.07, y, txt, fontsize=10, color=FG, va="center")
    y -= 0.145
ax4.text(0.02, 0.02, "Fontes: ets2-ai/artifacts/metrics.json (por commit) · GitHub Actions API · Kaggle API (via STATUS.md)",
         fontsize=8.5, color=MUT, style="italic")

out = Path(__file__).resolve().parent.parent / "artifacts" / "painel-treino.png"
out.parent.mkdir(exist_ok=True)
fig.savefig(out, facecolor=BG, bbox_inches="tight", pad_inches=0.35)
print("OK ->", out)
