"""Traces REAIS de gameplay do ETS2 (dataset publico do Hugging Face).

Fonte: yinhuankuang/rl-game-traces-euro-truck-simulator-2
       (https://huggingface.co/datasets/yinhuankuang/rl-game-traces-euro-truck-simulator-2)
       36 sessoes de jogo REAL gravadas por um humano — eventos de
       teclado/mouse com timestamp (macroEvents.jsonl) + fps.jsonl.

O que a IA ganha com isso: o timing das teclas deixa de ser fixo
(60 ms de tap / 150 ms entre teclas de menu) e passa a usar os
PERCENTUAIS REAIS de um humano jogando ETS2 de verdade:

  - traces.tap_hold()  -> duracao do pressionamento (KeyInjector.tap)
  - traces.menu_gap()  -> intervalo entre teclas (press_menu)

Formato do evento (macroEvents.jsonl, uma linha por evento):
  {"type": <int>, "mouseX": <int>, "mouseY": <int>,
   "time": <segundos float do relogio da sessao>,
   "keyCode": <int — so nos eventos de teclado>,
   "mouseButton": <str — so nos eventos de botao>,
   "fps": <float — em alguns eventos>}

Tipos observados: 3 = movimento relativo do mouse; os codigos de
down/up de teclado sao descobertos no CI (dump no log do job
traces-hf) — o pareamento abaixo e robusto a ordem: o PRIMEIRO
evento de uma tecla numa sessao e um pressionamento (ninguem solta
uma tecla antes de aperta-la).

Calibracao salva em ets2ai/dados/traces-hf.json (gerado pelo job
traces-hf; committado no repo; embutido no EXE via --add-data).
"""

import json
import os
import statistics
import sys
from pathlib import Path

TAP_HOLD_PADRAO = 0.06     # 60 ms (valor historico, sem dados reais)
MENU_GAP_PADRAO = 0.15     # 150 ms (valor historico, sem dados reais)
TAP_HOLD_MIN, TAP_HOLD_MAX = 0.03, 0.30
MENU_GAP_MIN, MENU_GAP_MAX = 0.05, 0.60
HOLD_MAX = 5.0             # pares acima disso = tecla presa/afk, descarta

# Enter e setas nos DOIS convencoes possiveis (VK do Windows e scancode)
CODIGOS_ENTER = (13, 28)
CODIGOS_MENU = (13, 28, 38, 40, 200, 208)

ARQUIVO = "traces-hf.json"


def caminhos():
    """Candidatos de onde ler a calibracao (dev, repo, EXE _MEIPASS)."""
    cands = [Path(__file__).resolve().parent / "dados" / ARQUIVO]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cands.append(Path(meipass) / "ets2ai" / "dados" / ARQUIVO)
        cands.append(Path(meipass) / "dados" / ARQUIVO)
    return cands


def arquivo_existe():
    return any(c.is_file() for c in caminhos())


def carregar():
    """Dict da calibracao real, ou None se os dados ainda nao existem."""
    for c in caminhos():
        try:
            if c.is_file():
                return json.loads(c.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return None


def parse_eventos(linhas):
    """Linhas do macroEvents.jsonl -> lista de dicts (tolerante a campos)."""
    out = []
    for ln in linhas:
        ln = ln.strip()
        if not ln:
            continue
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        if isinstance(ev, dict) and "time" in ev:
            out.append(ev)
    return out


def _pct(vals, p):
    if not vals:
        return None
    vals = sorted(vals)
    k = min(len(vals) - 1, max(0, int(round((p / 100.0) * (len(vals) - 1)))))
    return vals[k]


def _tipo_down_por_tecla(eventos):
    """Primeiro evento de cada keyCode e um DOWN -> mapeia keyCode->tipo_down."""
    primeiro = {}
    for ev in eventos:
        kc = ev.get("keyCode")
        if kc is None:
            continue
        kc = int(kc)
        if kc not in primeiro:
            primeiro[kc] = ev.get("type")
    return primeiro


def holds_por_tecla(eventos):
    """{keyCode: [duracao de cada pressionamento, em segundos]}.

    Pareia eventos consecutivos de mesma tecla com tipos diferentes
    (down->up). O tipo 'down' e inferido pelo primeiro evento da tecla.
    """
    down_de = _tipo_down_por_tecla(eventos)
    abertos = {}
    holds = {}
    for ev in eventos:
        kc = ev.get("keyCode")
        if kc is None:
            continue
        kc = int(kc)
        t = ev.get("type")
        if t == down_de.get(kc):
            abertos[kc] = float(ev["time"])          # down (ou re-down)
        elif kc in abertos:
            d = float(ev["time"]) - abertos.pop(kc)  # up
            if 0.0 <= d <= HOLD_MAX:
                holds.setdefault(kc, []).append(d)
    return holds


def intervalos_entre_teclas(eventos):
    """Intervalos (s) entre eventos de teclado consecutivos (qualquer tecla)."""
    tempos = [float(ev["time"]) for ev in eventos if ev.get("keyCode") is not None]
    return [b - a for a, b in zip(tempos, tempos[1:]) if 0.0 <= b - a <= 10.0]


def janelas_enter(eventos, gap_max=3.0):
    """Sequencias de Enter em rajada (dialogos do jogo — balsa/trem/frete).

    Retorna listas com os TEMPOS de cada Enter de cada janela — e o
    comportamento REAL de um humano navegando dialogs do ETS2.
    """
    enters = [float(ev["time"]) for ev in eventos
              if ev.get("keyCode") is not None
              and int(ev["keyCode"]) in CODIGOS_ENTER]
    janelas, atual = [], []
    for t in enters:
        if atual and t - atual[-1] > gap_max:
            if len(atual) >= 2:
                janelas.append(atual)
            atual = []
        atual.append(t)
    if len(atual) >= 2:
        janelas.append(atual)
    return janelas


def calibrar(eventos):
    """Eventos -> dict de calibracao (deterministico, sem timestamps)."""
    holds = holds_por_tecla(eventos)
    teclas = {}
    for kc, ds in sorted(holds.items()):
        if len(ds) < 3:
            continue
        teclas[str(kc)] = {
            "n": len(ds),
            "hold_p10": round(_pct(ds, 10), 4),
            "hold_p50": round(_pct(ds, 50), 4),
            "hold_p90": round(_pct(ds, 90), 4),
        }
    todos = [d for ds in holds.values() for d in ds]
    gaps = intervalos_entre_teclas(eventos)
    jen = janelas_enter(eventos)
    gaps_menu = []
    for j in jen:
        gaps_menu += [b - a for a, b in zip(j, j[1:]) if 0.0 <= b - a <= 10.0]
    tipos = {}
    for ev in eventos:
        tipos[str(ev.get("type"))] = tipos.get(str(ev.get("type")), 0) + 1
    return {
        "fonte": "huggingface.co/datasets/yinhuankuang/"
                 "rl-game-traces-euro-truck-simulator-2",
        "n_eventos": len(eventos),
        "n_teclado": sum(1 for ev in eventos if ev.get("keyCode") is not None),
        "tipos": tipos,
        "teclas": teclas,
        "hold_p50_global": round(_pct(todos, 50), 4) if todos else None,
        "menu_gap_p50": round(_pct(gaps_menu, 50), 4) if gaps_menu else None,
        "teclas_gap_p50": round(_pct(gaps, 50), 4) if gaps else None,
        "n_janelas_enter": len(jen),
        "enter_janelas_exemplo": [[round(t, 3) for t in j] for j in jen[:8]],
    }


def _hold_da_tecla(cal, codigos):
    if not cal:
        return None
    for kc in codigos:
        info = (cal.get("teclas") or {}).get(str(kc))
        if info and info.get("hold_p50") is not None:
            return info["hold_p50"]
    return None


def tap_hold(cal=None):
    """Duracao (s) do tap da IA — p50 REAL do Enter, senao global."""
    v = _hold_da_tecla(cal if cal is not None else carregar(), CODIGOS_ENTER)
    if v is None and cal:
        v = cal.get("hold_p50_global")
    if v is None:
        v = TAP_HOLD_PADRAO
    return max(TAP_HOLD_MIN, min(TAP_HOLD_MAX, float(v)))


def menu_gap(cal=None):
    """Intervalo (s) entre teclas de menu — p50 REAL das rajadas de Enter."""
    cal = cal if cal is not None else carregar()
    v = cal.get("menu_gap_p50") if cal else None
    if v is None and cal:
        v = cal.get("teclas_gap_p50")
    if v is None:
        v = MENU_GAP_PADRAO
    return max(MENU_GAP_MIN, min(MENU_GAP_MAX, float(v)))


def salvar(cal, caminho):
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cal, sort_keys=True, ensure_ascii=False,
                            indent=1), encoding="utf-8")
    return p
