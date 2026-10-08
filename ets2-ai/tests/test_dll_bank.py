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
        (1, 61): "V.1.12.1", (1, 58): "V.1.12.1", (1, 53): "V.1.12.1",
        (1, 46): "V.1.12.1", (1, 45): "V.1.11.1",
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


# --------------------------------------------------------------------------- #
# rotacao de release (QUALQUER ETS2: jogo recusa a DLL -> proxima do banco)
# --------------------------------------------------------------------------- #
def test_pick_dll_exclui_ja_tentadas():
    avail = {(r, t, "x64") for r, t, _ in T.DLL_BANK}
    # 1.53 ideal = V.1.12.1; se ela falhou, a proxima e V.1.12
    got = T.pick_dll((1, 53), "x64", avail, exclude={("rencloud", "V.1.12.1")})
    assert got == ("rencloud", "V.1.12")
    got2 = T.pick_dll((1, 53), "x64", avail,
                      exclude={("rencloud", "V.1.12.1"), ("rencloud", "V.1.12"),
                               ("rencloud", "V.1.11.1"), ("rencloud", "V.1.11")})
    assert got2 == ("rencloud", "V.1.10.6")
    # banco esgotado p/ a versao -> None
    tudo = {(r, t) for r, t, _ in T.DLL_BANK}
    assert T.pick_dll((1, 53), "x64", avail, exclude=tudo) is None


def test_ensure_plugin_rotaciona_para_proxima_release(tmp_path, bank,
                                                      monkeypatch):
    monkeypatch.setattr(T, "find_bundled_dll", lambda: None)
    game = _game(tmp_path, "exe_version_info=1.53.0.4s\n")
    r1 = T.ensure_plugin(log=lambda m: None, game_dir=game)
    assert r1["tag"] == "V.1.12.1"
    r2 = T.ensure_plugin(log=lambda m: None, game_dir=game,
                         exclude={("rencloud", "V.1.12.1")})
    assert r2["tag"] == "V.1.12" and r2["agora_instalou"] is True
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
    assert r["dll_tag"] == "V.1.11" and r["dll_arch"] == "x64"
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
    assert dst.read_bytes() == b"DLL-rencloud-V.1.12.1"
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

    casos = [("1.61", "exe_version_info=1.61.1.1s\n", "V.1.12.1"),
             ("1.45", "exe_version_info=1.45.1.1s\n", "V.1.11.1"),
             ("1.41", "exe_version_info=1.41.2.1s\n", "V.1.11")]
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
    assert r is not None and r["tag"] == "V.1.11"     # analisa o 1.41


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
