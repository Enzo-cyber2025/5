"""Telemetria RenCloud: layout travado + parse de snapshot sintetico."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ets2ai import telemetry as T


def _buf(**kw):
    buf = bytearray(T.MMF_SIZE)
    m = T.TelemetryMap.from_buffer(buf)
    m.sdk_active = True
    m.plugin_revision = 12
    for k, v in kw.items():
        setattr(m, k, v)
    return bytes(buf)


def test_layout_travado():
    # os 39 offsets-chave do cabecalho oficial (scs-telemetry-common.hpp)
    T.check_layout()


def test_parse_snapshot():
    sn = T.parse(_buf(
        paused=False, game_id=1, speed=21.7, engine_rpm=1450.0, gear=8,
        user_steer=0.22, user_throttle=0.8, user_brake=0.0,
        fuel=431.5, fuel_capacity=600.0, route_distance=98765.0,
        speed_limit=22.2, world_x=15391.5, world_z=-8234.25,
        park_brake=False, engine_enabled=True, on_job=True,
        cargo=b"Combustivel", city_src=b"Goteborg", city_dst=b"Oslo"))
    assert sn["game"] == "ets2"
    assert abs(sn["speed"] - 21.7) < 1e-4
    assert abs(sn["user_steer"] - 0.22) < 1e-4
    assert sn["fuel"] / sn["fuel_capacity"] == pytest_approx(0.719, 2)
    assert sn["route_distance"] == 98765.0
    assert sn["cargo"] == "Combustivel" and sn["city_dst"] == "Oslo"
    assert sn["on_job"] is True


def pytest_approx(v, nd):
    class A:
        def __eq__(self, o):
            return abs(o - v) < 10 ** -nd
    return A()


def test_parse_recusa_plugin_antigo():
    try:
        T.parse(_buf(plugin_revision=10))
        assert False, "devia recusar layout antigo"
    except RuntimeError as e:
        assert "12" in str(e)


def test_parse_recusa_jogo_fechado():
    buf = bytearray(T.MMF_SIZE)          # tudo zerado: sdk_active=False
    try:
        T.parse(bytes(buf))
        assert False, "devia recusar telemetria inativa"
    except RuntimeError as e:
        assert "plugin" in str(e) or "game.log" in str(e)


def test_reader_fora_do_windows():
    import pytest
    import os
    if os.name == "nt":
        pytest.skip("so faz sentido fora do Windows")
    with pytest.raises(RuntimeError):
        T.TelemetryReader()


def test_game_root_de_exe_repack():
    """Versoes alternativas (repack optijuegos): caminho do processo ->
    raiz da instalacao, independente de Steam/registro."""
    from ets2ai.telemetry import game_root_from_exe
    exe = r"D:\Jogos\ETS2.Repack-OptiJuegos\bin\win_x64\eurotrucks2.exe"
    assert game_root_from_exe(exe) == Path(r"D:\Jogos\ETS2.Repack-OptiJuegos")
    exe2 = r"C:\Steam\steamapps\common\Euro Truck Simulator 2\bin\win_x64\eurotrucks2.exe"
    assert game_root_from_exe(exe2) == Path(
        r"C:\Steam\steamapps\common\Euro Truck Simulator 2")
    assert game_root_from_exe(r"C:\random\eurotrucks2.exe") is None


def test_dir_looks_like_game(tmp_path):
    from ets2ai.telemetry import dir_looks_like_game
    (tmp_path / "bin" / "win_x64").mkdir(parents=True)
    assert dir_looks_like_game(tmp_path) is True
    assert dir_looks_like_game(tmp_path / "nao_existe") is False


def test_varredura_completa_todos_os_discos(tmp_path):
    """Busca em TODOS os arquivos/pastas: acha o jogo em qualquer lugar
    (repack com nome qualquer), podando pastas de sistema."""
    from ets2ai.telemetry import _iter_game_roots
    game = tmp_path / "Downloads" / "ETS2.Repack.OptiJuegos"   # nome qq
    (game / "bin" / "win_x64").mkdir(parents=True)
    (game / "bin" / "win_x64" / "eurotrucks2.exe").write_bytes(b"x")
    (tmp_path / "Windows" / "System32").mkdir(parents=True)
    (tmp_path / "$RECYCLE.BIN").mkdir()
    (tmp_path / "System Volume Information").mkdir()
    achou = list(_iter_game_roots([tmp_path], budget_s=30, log=None))
    assert achou == [game]


def test_extrai_caminho_do_atalho_lnk():
    """Ultimo caso: atalho .lnk (bytes) -> caminho do eurotrucks2.exe."""
    from ets2ai.telemetry import _paths_from_lnk
    BS = chr(92)
    path = BS.join(["D:", "Jogos", "Meu ETS2", "bin", "win_x64",
                    "eurotrucks2.exe"])
    assert _paths_from_lnk(b"x" * 30 + path.encode("latin-1")) == [path]
    w = path.encode("utf-16-le")
    assert _paths_from_lnk(b"x" * 7 + w) == [path]
    assert _paths_from_lnk(b"nada aqui") == []


def test_cascata_de_descoberta_ordem(tmp_path, monkeypatch):
    """Ordem: --game-dir > processo > Steam > TODOS os discos > rastros do
    jogo (.lnk/registro) > config PADRAO. Simulada com stubs."""
    import ets2ai.telemetry as t
    game = tmp_path / "repack"
    (game / "bin" / "win_x64").mkdir(parents=True)
    ordem = []

    def fake_scan_all(log=print, budget_s=1.0):
        ordem.append("discos")
        return []

    def fake_hints():
        ordem.append("rastros")
        return []

    def fake_running():
        ordem.append("processo")
        return None

    monkeypatch.setattr(t, "_scan_all_disks", fake_scan_all)
    monkeypatch.setattr(t, "_game_hints", fake_hints)
    monkeypatch.setattr(t, "_running_game_root", fake_running)
    monkeypatch.setattr(t, "_os", type("M", (), {"name": "nt"}))
    got = t.game_install_dirs(str(game))
    assert got[0] == game                     # --game-dir primeiro
    assert ordem == ["processo", "discos", "rastros"]
    assert any("repack" not in str(p) or p == game for p in got)
