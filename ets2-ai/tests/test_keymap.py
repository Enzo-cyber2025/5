"""Mapeamento das configuracoes ORIGINAIS do jogo (controls.sii)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ets2ai.keys import load_keymap, KEYMAP, SII_TOKENS  # noqa: E402

SAMPLE = """
config_lines[319]: "mix dsteerleft `keyboard.larrow?0 | keyboard.a?0`"
config_lines[320]: "mix dsteerright `keyboard.rarrow?0 | keyboard.d?0`"
config_lines[321]: "mix dforward `keyboard.uarrow?0 | keyboard.w?0`"
config_lines[322]: "mix dbackward `keyboard.darrow?0 | keyboard.s?0`"
config_lines[331]: "mix parkingbrake `keyboard.space?0`"
config_lines[332]: "mix engine `keyboard.e?0`"
config_lines[334]: "mix lblinker `keyboard.lbracket?0`"
config_lines[335]: "mix rblinker `keyboard.rbracket?0`"
config_lines[340]: "mix activate `keyboard.enter?0`"
"""


def test_mapeia_controls_sii_do_jogo(tmp_path):
    prof = tmp_path / "profiles" / "ABC123"
    prof.mkdir(parents=True)
    (prof / "controls.sii").write_text(SAMPLE, encoding="utf-8")
    km, macros, src = load_keymap(str(tmp_path))
    assert "controls.sii" in src
    # com seta E letra ligadas ao mesmo mix, PREFERE a letra (WASD)
    assert km["left"] == SII_TOKENS["a"] and km["right"] == SII_TOKENS["d"]
    assert km["accel"] == SII_TOKENS["w"] and km["brake"] == SII_TOKENS["s"]
    # macros do jogo: freio de mao no espaco, setas em [ ]
    assert macros["park_brake"][0] == SII_TOKENS["space"]
    assert macros["ind_left"][0] == SII_TOKENS["lbracket"]
    assert macros["ind_right"][0] == SII_TOKENS["rbracket"]
    assert macros["engine"][0] == SII_TOKENS["e"]
    assert macros["ok"][0] == SII_TOKENS["enter"]


def test_fallback_wasd_sem_controls_sii(tmp_path):
    km, macros, src = load_keymap(str(tmp_path / "nao_existe"))
    assert src == "padrao WASD"
    assert km == {"left": 0x1E, "right": 0x20, "accel": 0x11, "brake": 0x1F}
    assert KEYMAP == km          # padrao do modulo = WASD
    # macros fallback existem para todos os papéis
    for k in ("engine", "park_brake", "ind_left", "ind_right", "ok", "dock"):
        assert k in macros and len(macros[k]) == 2
