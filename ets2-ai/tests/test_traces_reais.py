"""IA calibrada por TRACES REAIS de ETS2 (dataset publico do HF).

Duas camadas:
  1. SEM dados (unit, roda sempre): parser de eventos, pareamento de
     holds, janelas de Enter, defaults do timing da IA.
  2. COM dados (dados/traces-hf.json gerado pelo job traces-hf do CI):
     gates de que o timing da IA (tap/menu) esta DENTRO do intervalo
     REAL de um humano jogando ETS2 — o "treino alimentado pelo jogo
     real" vira teste permanente do repositorio.
"""

import json

import pytest

from ets2ai import traces


# ---------------------------------------------------------------- camada 1

def _ev(t, tipo, kc=None, **kw):
    ev = {"type": tipo, "time": t}
    if kc is not None:
        ev["keyCode"] = kc
    ev.update(kw)
    return ev


def test_parse_eventos_tolera_linhas_sujas():
    linhas = [
        json.dumps(_ev(1.0, 3, mouseX=-1, mouseY=0)),
        "",
        "lixo {{{",
        json.dumps(_ev(2.0, 1, kc=87)),
    ]
    evs = traces.parse_eventos(linhas)
    assert len(evs) == 2
    assert evs[1]["keyCode"] == 87


def test_holds_por_tecla_pareia_down_up():
    # type 1 = down (primeiro evento), type 2 = up
    evs = [
        _ev(10.00, 1, kc=87), _ev(10.08, 2, kc=87),   # hold 80 ms
        _ev(12.00, 1, kc=65), _ev(12.30, 2, kc=65),   # hold 300 ms
        _ev(13.00, 1, kc=87), _ev(13.05, 2, kc=87),   # hold 50 ms
        _ev(14.00, 2, kc=83),                          # up solto: ignora
    ]
    holds = traces.holds_por_tecla(evs)
    assert holds[87] == pytest.approx([0.08, 0.05])
    assert holds[65] == pytest.approx([0.30])
    assert 83 not in holds


def test_holds_descarta_tecla_presa():
    evs = [_ev(1.0, 1, kc=87), _ev(99.0, 2, kc=87)]   # 98 s = presa/afk
    assert traces.holds_por_tecla(evs) == {}


def test_janelas_enter_agrupa_dialogos():
    evs = [
        _ev(100.0, 1, kc=13), _ev(101.2, 2, kc=13),   # janela 1 (2 enters)
        _ev(102.0, 1, kc=13), _ev(102.1, 2, kc=13),
        _ev(500.0, 1, kc=13), _ev(501.0, 2, kc=13),   # janela 2 (1+ enters)
        _ev(502.0, 1, kc=28),                          # scancode 28 = Enter tb
    ]
    j = traces.janelas_enter(evs)
    assert len(j) == 2
    # cada pressionamento entra 2x (down+up): janela 1 = 4 eventos
    assert j[0] == pytest.approx([100.0, 101.2, 102.0, 102.1])
    assert j[1] == pytest.approx([500.0, 501.0, 502.0])


def test_defaults_sem_dados():
    assert traces.tap_hold(None) == traces.TAP_HOLD_PADRAO
    assert traces.menu_gap(None) == traces.MENU_GAP_PADRAO


def test_tap_hold_calibrado_pelo_enter_real():
    cal = {"teclas": {"13": {"n": 50, "hold_p50": 0.11,
                             "hold_p10": 0.05, "hold_p90": 0.40}}}
    assert traces.tap_hold(cal) == 0.11


def test_tap_hold_clampa_limites():
    assert traces.tap_hold({"teclas": {}, "hold_p50_global": 9.9}) == \
        traces.TAP_HOLD_MAX
    assert traces.tap_hold({"teclas": {}}) == traces.TAP_HOLD_PADRAO


def test_menu_gap_calibrado_e_clampado():
    assert traces.menu_gap({"menu_gap_p50": 0.42}) == 0.42
    assert traces.menu_gap({"menu_gap_p50": 5.0}) == traces.MENU_GAP_MAX


def test_salvar_e_carregar_roundtrip(tmp_path):
    cal = traces.calibrar([_ev(1.0, 1, kc=87), _ev(1.1, 2, kc=87)] * 5)
    p = traces.salvar(cal, tmp_path / "d" / traces.ARQUIVO)
    assert p.is_file()
    dados = json.loads(p.read_text(encoding="utf-8"))
    assert dados["n_teclado"] == 10


# ---------------------------------------------------------------- camada 2
# Gates de dados REAIS — so rodam depois que o job traces-hf do CI baixa
# os traces do HF e committa ets2ai/dados/traces-hf.json no repo.

@pytest.mark.skipif(not traces.arquivo_existe(),
                    reason="traces reais do HF ainda nao baixados "
                           "(job traces-hf do CI)")
class TestDadosReaisHF:
    def test_traces_reais_presentes(self):
        cal = traces.carregar()
        assert cal and cal["n_teclado"] >= 1000, \
            "poucos eventos de teclado nos traces reais"

    def test_hold_do_enter_real(self):
        cal = traces.carregar()
        hold = traces._hold_da_tecla(cal, traces.CODIGOS_ENTER)
        if hold is not None:
            assert 0.02 <= hold <= 2.0, "hold de Enter fora do humano"

    def test_tap_da_ia_dentro_do_intervalo_real(self):
        cal = traces.carregar()
        escolhido = traces.tap_hold(cal)
        info = None
        for kc in traces.CODIGOS_ENTER:
            info = (cal.get("teclas") or {}).get(str(kc))
            if info:
                break
        if info:
            assert info["hold_p10"] - 0.01 <= escolhido <= info["hold_p90"] + 0.01

    def test_menu_gap_dentro_do_real(self):
        cal = traces.carregar()
        if cal.get("n_janelas_enter"):
            assert traces.MENU_GAP_MIN <= traces.menu_gap(cal) <= \
                traces.MENU_GAP_MAX

    def test_janelas_de_dialogo_registradas(self):
        cal = traces.carregar()
        if cal["n_eventos"] > 200000:
            assert cal["n_janelas_enter"] >= 1, \
                "nenhuma rajada de Enter em sessao longa de jogo real"
