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
        # DLL UNIVERSAL nossa: 1.36 ate o futuro (1 entrada cobre tudo)
        (1, 61): "universal", (1, 58): "universal", (1, 53): "universal",
        (1, 46): "universal", (1, 45): "universal",
        (1, 42): "universal", (1, 41): "universal", (1, 37): "universal",
        (1, 36): "universal",
        # abaixo de 1.36: matrix oficial do banco
        (1, 35): "v.1.9.0", (1, 33): "v.1.9.0", (1, 32): "v.1.9.0",
        (1, 20): "revision_5_rel_1_4_0", (1, 17): "revision_5_rel_1_4_0",
        (1, 12): "revision_3_rel_1_2_1",
    }
    for ver, want in mapa.items():
        repo, tag = T.pick_dll(ver, "x64", avail)
        assert tag == want, f"{ver}: {tag} != {want}"
    # desconhecida -> a mais nova; pre-historica -> a mais antiga
    assert T.pick_dll(None, "x64", avail)[1] == "universal"
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
    assert r["agora_instalou"] is True and r["tag"] == "universal"
    assert r["repo"] == "ets2ai"
    assert dst.read_bytes() == b"DLL-ets2ai-universal"
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
    assert r["tag"] == "universal"
    assert (game / "bin" / "win_x64" / "plugins" / "scs-telemetry.dll"
            ).read_bytes() == b"DLL-ets2ai-universal"


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
    assert _installed(game).read_bytes() == b"DLL-ets2ai-universal"
    assert any("CORROMPIDA" in l for l in logs)


def test_verify_versao_diferente_ajusta(tmp_path, bank, monkeypatch):
    monkeypatch.setattr(T, "find_bundled_dll", lambda: None)
    game = _game(tmp_path, "exe_version_info=1.41.2.1s\n")     # ideal universal
    T.ensure_plugin(log=lambda m: None, game_dir=game)
    # sobrescreve com OUTRA release (simula DLL velha/manual)
    _installed(game).write_bytes(b"DLL-rencloud-V.1.12.1")
    r = T.verify_plugin(log=lambda m: None, game_dir=game, repair=True)
    assert r["status"] == "versao_diferente" and r["reparada"] is True
    assert _installed(game).read_bytes() == b"DLL-ets2ai-universal"


def test_verify_ok(tmp_path, bank, monkeypatch):
    monkeypatch.setattr(T, "find_bundled_dll", lambda: None)
    game = _game(tmp_path, "exe_version_info=1.53.0.4s\n")
    T.ensure_plugin(log=lambda m: None, game_dir=game)
    r = T.verify_plugin(log=lambda m: None, game_dir=game, repair=True)
    assert r["status"] == "ok" and r["reparada"] is False


# --------------------------------------------------------------------------- #
# rotacao de release (QUALQUER ETS2: jogo recusa a DLL -> proxima do banco)
# --------------------------------------------------------------------------- #
def test_pick_dll_exclui_ja_tentadas():
    avail = {(r, t, "x64") for r, t, _ in T.DLL_BANK}
    # 1.53 ideal = universal; recusada -> V.1.12.1 -> V.1.12...
    got = T.pick_dll((1, 53), "x64", avail, exclude={("ets2ai", "universal")})
    assert got == ("rencloud", "V.1.12.1")
    got2 = T.pick_dll((1, 53), "x64", avail,
                      exclude={("ets2ai", "universal"), ("rencloud", "V.1.12.1"),
                               ("rencloud", "V.1.12"), ("rencloud", "V.1.11.1"),
                               ("rencloud", "V.1.11")})
    assert got2 == ("rencloud", "V.1.10.6")
    # banco esgotado p/ a versao -> None
    tudo = {(r, t) for r, t, _ in T.DLL_BANK}
    assert T.pick_dll((1, 53), "x64", avail, exclude=tudo) is None


def test_ensure_plugin_rotaciona_para_proxima_release(tmp_path, bank,
                                                      monkeypatch):
    monkeypatch.setattr(T, "find_bundled_dll", lambda: None)
    game = _game(tmp_path, "exe_version_info=1.53.0.4s\n")
    r1 = T.ensure_plugin(log=lambda m: None, game_dir=game)
    assert r1["tag"] == "universal"                # 1.36+: a nossa primeiro
    r2 = T.ensure_plugin(log=lambda m: None, game_dir=game,
                         exclude={("ets2ai", "universal")})
    assert r2["tag"] == "V.1.12.1"                 # recusada -> oficial nova
    r3 = T.ensure_plugin(log=lambda m: None, game_dir=game,
                         exclude={("ets2ai", "universal"),
                                  ("rencloud", "V.1.12.1")})
    assert r3["tag"] == "V.1.12" and r3["agora_instalou"] is True
    assert (_installed := game / "bin" / "win_x64" / "plugins"
            / "scs-telemetry.dll").read_bytes() == b"DLL-rencloud-V.1.12"
    # esgotado -> None
    tudo = {(r, t) for r, t, _ in T.DLL_BANK}
    assert T.ensure_plugin(log=lambda m: None, game_dir=game,
                           exclude=tudo) is None


def test_game_log_hints_fora_do_windows():
    assert T.game_log_hints() == []          # no-op seguro em nao-Windows


# --------------------------------------------------------------------------- #
# autoteste do bridge (o mesmo que roda na validacao Windows do CI)
# --------------------------------------------------------------------------- #
def test_run_autoteste_no_repo(tmp_path, monkeypatch):
    import importlib.util as ilu
    bp = Path(__file__).resolve().parents[1] / "bridge" / "ets2_bridge.py"
    spec = ilu.spec_from_file_location("ets2_bridge_at", bp)
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # banco falso + jogo falso 1.41
    root = tmp_path / "bank"
    for repo, tag, _m in T.DLL_BANK:
        d = root / repo / tag / "x64"
        d.mkdir(parents=True, exist_ok=True)
        (d / "scs-telemetry.dll").write_bytes(f"DLL-{repo}-{tag}".encode())
    # run_autoteste importa telemetry por conta propria: patcha no modulo
    import ets2ai.telemetry as tele_mod
    monkeypatch.setattr(tele_mod, "dll_dirs", lambda: [root])
    monkeypatch.setattr(tele_mod, "find_bundled_dll", lambda: None)
    game = _game(tmp_path, "exe_version_info=1.41.2.1s\n")

    out = tmp_path / "autoteste.json"
    logs = []
    ok = mod.run_autoteste(game_dir=str(game), saida=str(out), log=logs.append)
    assert ok["pass"] is True, "\n".join(logs)
    assert ok["arquivo"] == str(out)
    import json
    r = json.loads(out.read_text(encoding="utf-8"))
    assert r["dll_tag"] == "universal" and r["dll_arch"] == "x64"
    assert r["dll_repo"] == "ets2ai"
    assert r["verificacao"] == "ok"
    assert r["telemetria"] == "SKIP"            # Linux; no CI Windows = PASS
    assert r["oficial_inf_s"] >= 50
    assert any("PASS" in l for l in logs)


# --------------------------------------------------------------------------- #
# v0.4.12: pasta protegida (Program Files) -> PERMISSAO DE ADMINISTRADOR (UAC)
# --------------------------------------------------------------------------- #
def test_ensure_plugin_eleva_quando_pasta_protegida(tmp_path, bank,
                                                     monkeypatch):
    """Copia normal negada (PermissionError) -> pede administrador (UAC)
    aceito -> DLL instalada mesmo assim."""
    monkeypatch.setattr(T, "find_bundled_dll", lambda: None)
    game = _game(tmp_path, "exe_version_info=1.53.0.4s\n")
    real_copy = T.shutil.copyfile

    def bloqueada(src, dst):
        if str(dst).startswith(str(game)):    # pasta do jogo e protegida
            raise PermissionError(13, "Acesso negado (Program Files)")
        return real_copy(src, dst)            # copia p/ temp segue ok

    monkeypatch.setattr(T.shutil, "copyfile", bloqueada)

    def uac_aceita(src, dst, log=print, timeout_s=90.0):
        real_copy(src, dst)                   # powershell elevado copiou
        return True

    monkeypatch.setattr(T, "_elevated_copy", uac_aceita)
    msgs = []
    r = T.ensure_plugin(log=msgs.append, game_dir=game)
    dst = game / "bin" / "win_x64" / "plugins" / "scs-telemetry.dll"
    assert r and r["agora_instalou"] is True and r["elevado"] is True
    assert r["tag"] == "universal"
    assert dst.read_bytes() == b"DLL-ets2ai-universal"
    assert any("ADMINISTRADOR" in m for m in msgs)     # avisa ANTES do UAC


def test_ensure_plugin_uac_negado_nao_instala(tmp_path, bank, monkeypatch):
    """Usuario clica NAO no UAC -> nao instala e o log diz o que fazer."""
    monkeypatch.setattr(T, "find_bundled_dll", lambda: None)
    game = _game(tmp_path, "exe_version_info=1.53.0.4s\n")
    monkeypatch.setattr(T.shutil, "copyfile",
                        lambda s, d: (_ for _ in ()).throw(
                            PermissionError(13, "Acesso negado")))
    monkeypatch.setattr(T, "_elevated_copy",
                        lambda *a, **k: False)         # clicou NAO
    msgs = []
    r = T.ensure_plugin(log=msgs.append, game_dir=game)
    assert r is None
    assert any("NEGADA" in m for m in msgs)


# --------------------------------------------------------------------------- #
# v0.4.12 fix: --game-dir EXPLICITO sempre vence o CACHE salvo no cwd
# (reproduz o bug do CI: 7 ETS2s validados na mesma maquina e todos os
# casos depois do primeiro analisavam o jogo do primeiro caso)
# --------------------------------------------------------------------------- #
def test_game_dir_explicito_vence_cache_salvo(tmp_path, bank, monkeypatch):
    import importlib.util as ilu
    monkeypatch.setattr(T, "find_bundled_dll", lambda: None)
    # cwd compartilhado = onde ets2-ai-state.json e salvo (igual ao CI)
    shared = tmp_path / "shared-cwd"
    shared.mkdir()
    monkeypatch.chdir(shared)

    casos = [("1.61", "exe_version_info=1.61.1.1s\n", "universal"),
             ("1.41", "exe_version_info=1.41.2.1s\n", "universal"),
             ("1.35", "PatchVersion=1.35.2.2;\n", "v.1.9.0")]
    ultimo = None
    for v, inf, want in casos:
        g = _game(tmp_path, inf)
        ultimo = g
        # passo 2 do autoteste (bridge): resolve com extra EXPLICITO
        got = T.resolve_game_dir(extra=g)
        assert str(got) == str(g), \
            f"ETS2 {v}: cache redirecionou para {got} em vez de {g}"
        # passo 3: instala a DLL ideal DESTE jogo (nao a do anterior)
        r = T.ensure_plugin(log=lambda m: None, game_dir=g)
        assert r is not None and r["tag"] == want, \
            f"ETS2 {v}: escolheu {r and r['tag']}, esperado {want}"
        assert str(g) in r["dll"], f"ETS2 {v}: instalou fora do --game-dir"
    # o cache existe (ultimo explicito) e e usado por quem NAO passa caminho
    assert (shared / "ets2-ai-state.json").exists()
    st = T.load_game_state(shared / "ets2-ai-state.json")
    assert st["game_dir"] == str(ultimo)             # ultimo explicito
    r = T.ensure_plugin(log=lambda m: None)           # game_dir=None
    assert r is not None and r["tag"] == "v.1.9.0"   # analisa o 1.35


def test_game_dir_invalido_cai_na_descoberta(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # caminho explicito que NAO parece jogo -> descoberta normal (cache)
    g = _game(tmp_path, "exe_version_info=1.41.2.1s\n")
    r = T.resolve_game_dir(extra=tmp_path / "nao-existe")
    assert str(r) == str(g) or r is None   # achou o jogo ou nada — nunca
    # o caminho invalido NAO entra no cache
    st = T.load_game_state()
    assert st.get("game_dir") != str(tmp_path / "nao-existe")


# --------------------------------------------------------------------------- #
# v0.4.15: com 2+ instalacoes, o JOGO ABERTO manda sobre o cache salvo
# (a DLL tem que ir para o jogo que o usuario esta jogando)
# --------------------------------------------------------------------------- #
def test_jogo_rodando_vence_cache_de_outra_instalacao(tmp_path, monkeypatch):
    jogo_antigo = _game(tmp_path, "exe_version_info=1.41.2.1s\n")
    jogo_da_vez = _game(tmp_path, "exe_version_info=1.61.1.1s\n")
    monkeypatch.chdir(tmp_path)
    # cache aponta para a instalacao antiga
    T.save_game_state({"game_dir": str(jogo_antigo), "found_by": "steam",
                       "found_at": 1.0, "last_seen": 1.0, "runs": 5})
    # ... mas o processo rodando e o 1.61 (outra instalacao)
    monkeypatch.setattr(T, "_running_game_root", lambda: jogo_da_vez)
    monkeypatch.setattr(T, "_os", type("M", (), {"name": "nt"}))
    msgs = []
    got = T.resolve_game_dir(log=msgs.append)
    assert str(got) == str(jogo_da_vez)
    assert any("ABERTO" in m for m in msgs)
    st = T.load_game_state()
    assert st["game_dir"] == str(jogo_da_vez)      # cache corrigido

    # sem jogo rodando: o cache (agora o certo) e usado normalmente
    monkeypatch.setattr(T, "_running_game_root", lambda: None)
    got2 = T.resolve_game_dir(log=lambda m: None)
    assert str(got2) == str(jogo_da_vez)


def test_jogo_rodando_igual_ao_cache_nao_reescreve(tmp_path, monkeypatch):
    jogo = _game(tmp_path, "exe_version_info=1.53.0.4s\n")
    monkeypatch.chdir(tmp_path)
    T.save_game_state({"game_dir": str(jogo), "found_by": "steam",
                       "found_at": 1.0, "last_seen": 1.0, "runs": 7})
    monkeypatch.setattr(T, "_running_game_root", lambda: jogo)
    monkeypatch.setattr(T, "_os", type("M", (), {"name": "nt"}))
    got = T.resolve_game_dir(log=lambda m: None)
    assert str(got) == str(jogo)
    assert T.load_game_state()["runs"] == 8        # so incrementou


# --------------------------------------------------------------------------- #
# v0.4.18: DLL UNIVERSAL propria (ets2ai/universal_plugin.c) — 1.36+ ate o
# futuro. O banco oficial (RenCloud/nlhans) continua para < 1.36 e reserva.
# --------------------------------------------------------------------------- #
def test_universal_e_primeira_escolha_a_partir_de_1_36():
    avail = {(r, t, a) for r, t, _ in T.DLL_BANK for a in ("x64", "x86")}
    assert T.pick_dll((1, 36), "x64", avail) == ("ets2ai", "universal")
    assert T.pick_dll((1, 61), "x64", avail) == ("ets2ai", "universal")
    assert T.pick_dll((99, 0), "x64", avail) == ("ets2ai", "universal")  # futuro
    # fronteira: 1.35 ainda e matrix oficial
    assert T.pick_dll((1, 35), "x64", avail) == ("rencloud", "v.1.9.0")


def test_universal_dll_offsets_batem_com_o_leitor():
    """Anti-drift: os #define do C tem que ser EXATAMENTE os offsets da
    TelemetryMap do Python (se qualquer um dos dois mudar, este teste
    quebra e obriga a regenerar o outro)."""
    import re
    csrc = (Path(__file__).resolve().parents[1] / "ets2ai"
            / "universal_plugin.c").read_text(encoding="utf-8")
    assert 'Local\\SCSTelemetry' in csrc.replace('L"Local\\\\SCSTelemetry"',
                                                 'Local\\SCSTelemetry') \
        or 'SCSTelemetry' in csrc
    pares = [("sdk_active", "OFF_SDK_ACTIVE"), ("paused", "OFF_PAUSED"),
             ("time", "OFF_TIME"), ("plugin_revision", "OFF_PLUGIN_REV"),
             ("version_major", "OFF_VER_MAJOR"),
             ("version_minor", "OFF_VER_MINOR"), ("game_id", "OFF_GAME_ID"),
             ("gear", "OFF_GEAR"), ("fuel_capacity", "OFF_FUEL_CAP"),
             ("speed", "OFF_SPEED"), ("engine_rpm", "OFF_ENGINE_RPM"),
             ("user_steer", "OFF_USER_STEER"),
             ("user_throttle", "OFF_THROTTLE"), ("user_brake", "OFF_BRAKE"),
             ("fuel", "OFF_FUEL"), ("odometer", "OFF_ODOMETER"),
             ("route_distance", "OFF_ROUTE_DIST"),
             ("route_time", "OFF_ROUTE_TIME"),
             ("speed_limit", "OFF_SPEED_LIM"), ("_pad_f", "OFF_MAGIC"),
             ("special_job", "OFF_SPECIAL_JOB"),
             ("park_brake", "OFF_PARK_BRAKE"),
             ("engine_enabled", "OFF_ENGINE_ON"),
             ("world_x", "OFF_WORLD_X"), ("world_y", "OFF_WORLD_Y"),
             ("world_z", "OFF_WORLD_Z"), ("on_job", "OFF_ON_JOB")]
    for campo, define in pares:
        off = getattr(T.TelemetryMap, campo).offset
        assert re.search(rf"#define {define}\s+{off}\b", csrc), \
            f"{define} no C deveria ser {off} (TelemetryMap.{campo})"
    assert f"{T.UNIVERSAL_MAGIC}u" in csrc or \
        f"0x{T.UNIVERSAL_MAGIC:08X}u" in csrc


def test_parse_marca_fonte_universal_pelo_magic():
    m = T.TelemetryMap()
    m.sdk_active = True
    m.plugin_revision = 15
    m.game_id = 1
    m.speed, m.fuel, m.user_steer = 17.5, 380.5, 0.25
    m._pad_f = T.UNIVERSAL_MAGIC.to_bytes(4, "little") + b"\x00" * 24
    snap = T.parse(bytes(m))
    assert snap["fonte"] == "ets2ai-universal" and snap["sdk_active"]
    m2 = T.TelemetryMap()
    m2.sdk_active = True
    m2.plugin_revision = 15
    m2.game_id = 1
    snap2 = T.parse(bytes(m2))
    assert snap2["fonte"] == "oficial"     # sem magic = plugin oficial


# --------------------------------------------------------------------------- #
# v0.4.21: PROVA DE DIRECAO — jogo-substituto (game_stub.py) com a ABI real
# --------------------------------------------------------------------------- #
def test_game_stub_abi_e_offsets():
    """O jogo-substituto do CI tem que falar a MESMA ABI do SDK (struct de
    init com os 5 ponteiros = 64 bytes em x64) e os MESMOS offsets da
    TelemetryMap (anti-drift triplo: C <-> leitor <-> stub)."""
    import ctypes as ct
    import importlib.util as ilu
    bp = Path(__file__).resolve().parents[1] / "ets2ai" / "game_stub.py"
    spec = ilu.spec_from_file_location("game_stub_t", bp)
    gs = ilu.module_from_spec(spec)
    spec.loader.exec_module(gs)
    assert ct.sizeof(gs.InitParams) == 64
    for campo, off in (("speed", gs.OFF_SPEED), ("fuel", gs.OFF_FUEL),
                       ("user_steer", gs.OFF_STEER),
                       ("route_distance", gs.OFF_ROUTE),
                       ("speed_limit", gs.OFF_LIMIT),
                       ("world_x", gs.OFF_WORLD_X),
                       ("world_z", gs.OFF_WORLD_Z)):
        assert getattr(T.TelemetryMap, campo).offset == off, campo
    assert gs.UNIVERSAL_MAGIC == T.UNIVERSAL_MAGIC


def test_game_stub_init_params_packing():
    """A construcao do struct de init tem que casar com os campos COM
    padding (v0.4.21: log caia no _pad e estourava TypeError antes de
    chamar a DLL — congelado aqui para nunca mais)."""
    import ctypes as ct
    import importlib.util as ilu
    bp = Path(__file__).resolve().parents[1] / "ets2ai" / "game_stub.py"
    spec = ilu.spec_from_file_location("game_stub_p", bp)
    gs = ilu.module_from_spec(spec)
    spec.loader.exec_module(gs)
    p = gs.InitParams(
        game_name=b"Euro Truck Simulator 2", game_id=b"eurotrucks2",
        game_version=(1 << 16) | 45, _pad=0,
        log=gs.LOG_FN(lambda *a: None),
        register_for_event=gs.REG_EVENT(lambda *a: 0),
        unregister_from_event=gs.UNREG_EVENT(lambda e: 0),
        register_for_channel=gs.REG_CHANNEL(lambda *a: 0),
        unregister_from_channel=gs.UNREG_CHANNEL(lambda *a: 0))
    assert p.game_version == ((1 << 16) | 45)
    assert p.game_id == b"eurotrucks2"
    assert ct.sizeof(gs.InitParams) == 64
