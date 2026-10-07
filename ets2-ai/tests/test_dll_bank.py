"""Banco de DLLs de telemetria: TODAS as releases oficiais embutidas no
.exe; analise do jogo (arquitetura + versao pelo steam.inf) escolhe a DLL
ideal; verificacao por hash SHA-256 detecta corrupcao e repara sozinha.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ets2ai import telemetry as T                    # noqa: E402


# --------------------------------------------------------------------------- #
# analise do jogo
# --------------------------------------------------------------------------- #
def _game(tmp_path, steam_inf=None, x86=False):
    n = getattr(_game, "_n", 0) + 1
    _game._n = n
    g = tmp_path / f"ETS2-{n}"
    sub = "win_x86" if x86 else "win_x64"
    (g / "bin" / sub).mkdir(parents=True, exist_ok=True)
    if steam_inf is not None:
        (g / "steam.inf").write_text(steam_inf, encoding="utf-8")
    return g


def test_game_version_steam_inf(tmp_path):
    assert T.game_version(_game(tmp_path, "exe_version_info=1.53.0.4s\n")) \
        == (1, 53)
    assert T.game_version(_game(tmp_path, "PatchVersion=1.35.2.2;\n")) \
        == (1, 35)
    assert T.game_version(_game(tmp_path, "exe_version_info=1.45.1.1s")) \
        == (1, 45)
    assert T.game_version(_game(tmp_path)) is None      # sem steam.inf


def test_game_arch(tmp_path):
    assert T.game_arch(_game(tmp_path)) == "x64"
    assert T.game_arch(_game(tmp_path, x86=True)) == "x86"
    g = tmp_path / "vazio"; g.mkdir()
    assert T.game_arch(g) is None


def test_pick_dll_por_versao_do_jogo():
    avail = {(r, t, a) for r, t, _ in T.DLL_BANK for a in ("x64", "x86")}
    mapa = {
        (1, 53): "V.1.12.1", (1, 46): "V.1.12.1", (1, 45): "V.1.11.1",
        (1, 42): "V.1.11", (1, 41): "V.1.11", (1, 37): "V.1.10.6",
        (1, 36): "V.1.10.6", (1, 33): "v.1.9.0", (1, 32): "v.1.9.0",
        (1, 20): "revision_5_rel_1_4_0", (1, 17): "revision_5_rel_1_4_0",
        (1, 12): "revision_3_rel_1_2_1",
    }
    for ver, want in mapa.items():
        repo, tag = T.pick_dll(ver, "x64", avail)
        assert tag == want, f"{ver}: {tag} != {want}"
    # desconhecida -> a mais nova; pre-historica -> a mais antiga
    assert T.pick_dll(None, "x64", avail)[1] == "V.1.12.1"
    assert T.pick_dll((0, 9), "x64", avail)[1] == "revision_1"
    # arquitetura sem banco -> None
    assert T.pick_dll((1, 53), "arm", avail) is None


# --------------------------------------------------------------------------- #
# banco falso + instalar a IDEAL por versao
# --------------------------------------------------------------------------- #
@pytest.fixture
def bank(tmp_path, monkeypatch):
    """Banco com algumas releases (conteudos distintos por tag)."""
    root = tmp_path / "bank"
    for repo, tag, _min in T.DLL_BANK:
        d = root / repo / tag / "x64"
        d.mkdir(parents=True, exist_ok=True)
        (d / "scs-telemetry.dll").write_bytes(f"DLL-{repo}-{tag}".encode())
    monkeypatch.setattr(T, "dll_dirs", lambda: [root])
    return root


def test_ensure_plugin_instala_dll_ideal_da_versao(tmp_path, bank,
                                                   monkeypatch):
    monkeypatch.setattr(T, "find_bundled_dll", lambda: None)  # so o banco
    game = _game(tmp_path, "exe_version_info=1.41.2.1s\n")    # 1.41
    r = T.ensure_plugin(log=lambda m: None, game_dir=game)
    dst = game / "bin" / "win_x64" / "plugins" / "scs-telemetry.dll"
    assert r["agora_instalou"] is True and r["tag"] == "V.1.11"
    assert dst.read_bytes() == b"DLL-rencloud-V.1.11"
    # idempotente: mesma DLL -> nao reescreve
    mtime = dst.stat().st_mtime_ns
    r2 = T.ensure_plugin(log=lambda m: None, game_dir=game)
    assert r2["agora_instalou"] is False
    assert dst.stat().st_mtime_ns == mtime


def test_ensure_plugin_jogo_novo_usa_release_mais_recente(tmp_path, bank,
                                                           monkeypatch):
    monkeypatch.setattr(T, "find_bundled_dll", lambda: None)
    game = _game(tmp_path, "exe_version_info=1.53.0.4s\n")
    r = T.ensure_plugin(log=lambda m: None, game_dir=game)
    assert r["tag"] == "V.1.12.1"
    assert (game / "bin" / "win_x64" / "plugins" / "scs-telemetry.dll"
            ).read_bytes() == b"DLL-rencloud-V.1.12.1"


# --------------------------------------------------------------------------- #
# verificacao (botao VERIFICAR DLL): ausente / corrompida / outra versao / ok
# --------------------------------------------------------------------------- #
def _installed(game):
    return game / "bin" / "win_x64" / "plugins" / "scs-telemetry.dll"


def test_verify_ausente_repara(tmp_path, bank, monkeypatch):
    monkeypatch.setattr(T, "find_bundled_dll", lambda: None)
    game = _game(tmp_path, "exe_version_info=1.53.0.4s\n")
    logs = []
    r = T.verify_plugin(log=logs.append, game_dir=game, repair=True)
    assert r["status"] == "ausente" and r["reparada"] is True
    assert _installed(game).exists()          # reparou sozinho


def test_verify_corrompida_repara(tmp_path, bank, monkeypatch):
    monkeypatch.setattr(T, "find_bundled_dll", lambda: None)
    game = _game(tmp_path, "exe_version_info=1.53.0.4s\n")
    T.ensure_plugin(log=lambda m: None, game_dir=game)
    _installed(game).write_bytes(b"DLL TRUNCADA/CORROMPIDA")   # estraga
    logs = []
    r = T.verify_plugin(log=logs.append, game_dir=game, repair=True)
    assert r["status"] == "corrompida" and r["reparada"] is True
    assert _installed(game).read_bytes() == b"DLL-rencloud-V.1.12.1"
    assert any("CORROMPIDA" in l for l in logs)


def test_verify_versao_diferente_ajusta(tmp_path, bank, monkeypatch):
    monkeypatch.setattr(T, "find_bundled_dll", lambda: None)
    game = _game(tmp_path, "exe_version_info=1.41.2.1s\n")     # ideal V.1.11
    T.ensure_plugin(log=lambda m: None, game_dir=game)
    # sobrescreve com OUTRA release (simula DLL velha/manual)
    _installed(game).write_bytes(b"DLL-rencloud-V.1.12.1")
    r = T.verify_plugin(log=lambda m: None, game_dir=game, repair=True)
    assert r["status"] == "versao_diferente" and r["reparada"] is True
    assert _installed(game).read_bytes() == b"DLL-rencloud-V.1.11"


def test_verify_ok(tmp_path, bank, monkeypatch):
    monkeypatch.setattr(T, "find_bundled_dll", lambda: None)
    game = _game(tmp_path, "exe_version_info=1.53.0.4s\n")
    T.ensure_plugin(log=lambda m: None, game_dir=game)
    r = T.verify_plugin(log=lambda m: None, game_dir=game, repair=True)
    assert r["status"] == "ok" and r["reparada"] is False
