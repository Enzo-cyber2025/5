"""Fluxo do COMEÇAR (drive): espera o jogo abrir + so age em TELA CHEIA.

Cobre as duas correcoes de v0.4.8:
  - practice._acquire_source: COMEÇAR clicavel ANTES do jogo (o loop espera
    a telemetria em vez de morrer com 'iniciando e parou');
  - keys.KeyInjector._gate_ok/update/tap: nenhuma tecla e injetada com o
    jogo fora da TELA CHEIA (consentimento) — e tudo solto ao sair;
  - model.train(max_sec=...): teto de tempo (fallback CPU do kernel Kaggle
    precisa terminar dentro do orcamento da sessao).
"""
import sys
import threading
import types
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ets2ai import practice                                   # noqa: E402
from ets2ai.keys import KeyInjector, rect_is_fullscreen       # noqa: E402


# --------------------------------------------------------------------------- #
# tela cheia (consentimento para a IA agir)
# --------------------------------------------------------------------------- #
def test_rect_is_fullscreen():
    mon = (0, 0, 1920, 1080)
    assert rect_is_fullscreen((0, 0, 1920, 1080), mon)          # exata
    assert rect_is_fullscreen((-8, -8, 1928, 1088), mon)        # borda invisivel
    assert not rect_is_fullscreen((0, 0, 1920, 1040), mon)      # maximizada c/ barra
    assert not rect_is_fullscreen((100, 100, 800, 600), mon)    # janela
    assert not rect_is_fullscreen((0, 0, 1024, 768), mon)       # resolucao menor


def _fake_injector(gate):
    """KeyInjector com a parte win32 mockada (testavel em qualquer SO)."""
    inj = KeyInjector("Euro Truck", True)
    inj.enabled = True                      # simula win32 p/ o caminho do gate
    inj.user32 = types.SimpleNamespace(GetAsyncKeyState=lambda k: 0)
    presses = []
    inj._keybd = lambda scan, up: presses.append((scan, up))
    inj._gate_ok = lambda announce=True: gate[0]
    return inj, presses


def test_gate_tela_cheia_bloqueia_e_solta():
    gate = [False]
    inj, presses = _fake_injector(gate)
    inj.update(0.0, 0.8, 0.0)               # acelerador... jogo fora da tela cheia
    assert inj.down == set() and presses == []   # NADA injetado

    gate[0] = True                          # jogo entrou em tela cheia
    inj.update(0.0, 0.8, 0.0)
    assert "accel" in inj.down and len(presses) == 1

    gate[0] = False                         # saiu da tela cheia -> solta tudo
    inj.update(0.0, 0.8, 0.0)
    assert inj.down == set() and len(presses) == 2   # keyup da tecla


def test_macro_ignorada_fora_da_tela_cheia():
    gate = [False]
    inj, presses = _fake_injector(gate)
    msgs = []
    inj.log = msgs.append
    inj.tap(0x12, "E (motor)")
    assert presses == []
    assert any("TELA CHEIA" in m for m in msgs)


# --------------------------------------------------------------------------- #
# espera pelo jogo (fim do 'iniciando e parou')
# --------------------------------------------------------------------------- #
def test_acquire_source_espera_e_conecta(monkeypatch):
    calls = {"n": 0}

    class FakeMem:
        def __init__(self):
            calls["n"] += 1
            if calls["n"] < 3:              # 2 primeiras tentativas: jogo fechado
                raise RuntimeError("processo ets2.exe nao encontrado")
            self.version = "fake"
            self.snapshot = lambda: {"ticks": 1}

    monkeypatch.setattr(practice.memtelemetry, "MemTelemetry", FakeMem)
    monkeypatch.setattr(practice.time, "sleep", lambda s: None)
    logs = []
    src = practice._acquire_source("drive", "auto", logs.append, wait_game=30)
    assert src() == {"ticks": 1} and calls["n"] == 3
    assert any("aguardando" in l for l in logs)


def test_acquire_source_desiste_com_motivo(monkeypatch):
    def boom():
        raise RuntimeError("processo ets2.exe nao encontrado")

    monkeypatch.setattr(practice.memtelemetry, "MemTelemetry", boom)
    monkeypatch.setattr(practice.telemetry, "TelemetryReader", boom)
    with pytest.raises(SystemExit) as ei:
        practice._acquire_source("drive", "auto", lambda m: None, wait_game=0)
    assert "sem telemetria" in str(ei.value)
    assert "ets2.exe" in str(ei.value)      # o MOTIVO aparece na mensagem


def test_acquire_source_parar_durante_a_espera(monkeypatch):
    def boom():
        raise RuntimeError("processo ets2.exe nao encontrado")

    monkeypatch.setattr(practice.memtelemetry, "MemTelemetry", boom)
    ev = threading.Event()
    ev.set()
    with pytest.raises(SystemExit) as ei:
        practice._acquire_source("drive", "mem", lambda m: None,
                                 stop_event=ev, wait_game=30)
    assert "PARAR" in str(ei.value)


# --------------------------------------------------------------------------- #
# teto de tempo do treino (kernel Kaggle CPU termina dentro do orcamento)
# --------------------------------------------------------------------------- #
def test_train_respeita_teto_de_tempo():
    from ets2ai.model import train
    rng = np.random.default_rng(0)
    x = rng.normal(size=(4096, 13)).astype(np.float32)
    y = rng.normal(size=(4096, 3)).astype(np.float32)
    layers, hist = train(x, y, epochs=500, batch=256, verbose=False,
                         max_sec=0.05)
    assert len(hist) < 500                  # cortou: orcamento manda
    assert len(layers) == 14                # arquitetura oficial intacta


# --------------------------------------------------------------------------- #
# telemetria 100% automatica (DLL auto-instalada pelo .exe, nada manual)
# --------------------------------------------------------------------------- #
def _fake_game(tmp_path):
    game = tmp_path / "ETS2"
    (game / "bin" / "win_x64").mkdir(parents=True)
    return game


def test_ensure_plugin_instala_e_eh_idempotente(tmp_path, monkeypatch):
    from ets2ai import telemetry
    game = _fake_game(tmp_path)
    fake_dll = tmp_path / "scs-telemetry.dll"
    fake_dll.write_bytes(b"PLUGIN-FAKE-123")
    monkeypatch.setattr(telemetry, "find_bundled_dll", lambda: fake_dll)

    r1 = telemetry.ensure_plugin(log=lambda m: None, game_dir=game)
    dst = game / "bin" / "win_x64" / "plugins" / "scs-telemetry.dll"
    assert r1["agora_instalou"] is True
    assert dst.read_bytes() == b"PLUGIN-FAKE-123"     # local OFICIAL do plugin
    mtime = dst.stat().st_mtime_ns

    r2 = telemetry.ensure_plugin(log=lambda m: None, game_dir=game)
    assert r2["agora_instalou"] is False              # ja estava no lugar
    assert dst.stat().st_mtime_ns == mtime            # nao reescreveu


def test_ensure_plugin_pasta_que_nao_e_jogo(tmp_path, monkeypatch):
    from ets2ai import telemetry
    fake_dll = tmp_path / "scs-telemetry.dll"
    fake_dll.write_bytes(b"X")
    monkeypatch.setattr(telemetry, "find_bundled_dll", lambda: fake_dll)
    r = telemetry.ensure_plugin(log=lambda m: None,
                                game_dir=tmp_path / "nao_e_jogo")
    assert r is None


def test_cache_negativo_pula_varredura_literal(tmp_path, monkeypatch):
    """Varredura completa que nao achou o jogo NAO repete sozinha — mas as
    vias baratas continuam (literal_scan=False) e o BUSCAR DE NOVO (force)
    refaz tudo."""
    from ets2ai import telemetry
    calls = []

    def fake_gid(extra=None, log=None, literal_scan=True):
        calls.append(literal_scan)
        return []                        # nao acha nada
    monkeypatch.setattr(telemetry, "game_install_dirs", fake_gid)
    st = tmp_path / "state.json"

    assert telemetry.resolve_game_dir(log=lambda m: None, state_file=st) is None
    assert calls == [True]               # 1a vez: varredura literal roda
    saved = telemetry.load_game_state(st)
    assert "scan_failed_at" in saved     # registrou a varredura vazia

    assert telemetry.resolve_game_dir(log=lambda m: None, state_file=st) is None
    assert calls == [True, False]        # 2a vez: so vias baratas

    telemetry.resolve_game_dir(log=lambda m: None, state_file=st, force=True)
    assert calls == [True, False, True]  # force refaz a literal


def test_cache_negativo_desbloqueia_achando_pelo_processo(tmp_path, monkeypatch):
    """Com o jogo ABERTO a deteccao por processo acha mesmo depois de uma
    varredura vazia (e limpa o cache negativo)."""
    from ets2ai import telemetry
    game = _fake_game(tmp_path)
    n = {"i": 0}

    def fake_gid(extra=None, log=None, literal_scan=True):
        n["i"] += 1
        return [str(game)] if n["i"] > 1 else []
    monkeypatch.setattr(telemetry, "game_install_dirs", fake_gid)
    st = tmp_path / "state.json"
    assert telemetry.resolve_game_dir(state_file=st) is None
    got = telemetry.resolve_game_dir(state_file=st)      # 2a: processo achou
    assert Path(got) == game
    saved = telemetry.load_game_state(st)
    assert saved.get("game_dir") == str(game)
    assert "scan_failed_at" not in saved                  # limpou


def test_acquire_reinstala_telemetria_durante_a_espera(monkeypatch):
    """Enquanto espera o jogo, o auto-install da DLL e re-tentado (a cada
    ~60 s) em vez de desistir na primeira."""
    import types

    class _Clock:                       # relogio falso: 30 s por sleep
        def __init__(self):
            self.t = 1000.0

        def monotonic(self):
            return self.t

        def sleep(self, s):
            self.t += 30.0
    clock = _Clock()

    def boom():
        raise RuntimeError("processo ets2.exe nao encontrado")

    installs = {"n": 0}

    def fake_install(game_dir=None, auto=True, log=print, exclude=()):
        installs["n"] += 1
        return None
    monkeypatch.setattr(practice.memtelemetry, "MemTelemetry", boom)
    monkeypatch.setattr(practice.telemetry, "TelemetryReader", boom)
    monkeypatch.setattr(practice, "_try_install_plugin", fake_install)
    monkeypatch.setattr(practice, "time",
                        types.SimpleNamespace(monotonic=clock.monotonic,
                                              sleep=clock.sleep))
    with pytest.raises(SystemExit):
        practice._acquire_source("drive", "auto", lambda m: None,
                                 wait_game=300)
    assert installs["n"] >= 3           # tentou varias vezes (300 s falsos)


# --------------------------------------------------------------------------- #
# v0.4.20: COMEÇAR espera o jogo SEM PRAÇO (wait_game=None) — nunca desiste
# --------------------------------------------------------------------------- #
def test_acquire_source_sem_prazo_nunca_desiste(monkeypatch):
    """wait_game=None: mesmo com o relogio avancando MILENIOS, o loop
    continua esperando (so sai por PARAR). Nada de 'clique COMEÇAR de
    novo'."""
    def boom():
        raise RuntimeError("processo ets2.exe nao encontrado")

    monkeypatch.setattr(practice.memtelemetry, "MemTelemetry", boom)
    monkeypatch.setattr(practice.telemetry, "TelemetryReader", boom)
    monkeypatch.setattr(practice, "_try_install_plugin",
                        lambda *a, **k: None)
    monkeypatch.setattr(practice.time, "sleep", lambda s: None)
    t = {"v": 1_000_000.0}
    monkeypatch.setattr(practice.time, "monotonic",
                        lambda: (t.__setitem__("v", t["v"] + 1000.0)
                                 or t["v"]))
    ev = threading.Event()
    ev.set()                                  # PARAR ja clicado
    with pytest.raises(SystemExit) as ei:
        practice._acquire_source("drive", "auto", lambda m: None,
                                 stop_event=ev, wait_game=None)
    assert "PARAR" in str(ei.value)           # saiu por PARAR, NAO por timeout
    assert "sem telemetria" not in str(ei.value)


def test_botao_esperando_o_jogo():
    import importlib.util as ilu
    bp = Path(__file__).resolve().parents[1] / "bridge" / "ets2_bridge.py"
    spec = ilu.spec_from_file_location("ets2_bridge_btn", bp)
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    st, txt, bg = mod._start_button_state(False, True, local_ok=True,
                                          waiting=True)
    assert st == "normal" and "ESPERANDO O JOGO" in txt and "PARAR" in txt
    st2, txt2, _ = mod._start_button_state(False, True, local_ok=True,
                                           waiting=False)
    assert txt2 == "PARAR"                    # jogo abriu -> dirigindo
    st3, txt3, _ = mod._start_button_state(False, False, local_ok=True)
    assert "COMEÇAR" in txt3


def test_governor_sem_rota_nao_freia_para_sempre():
    """v0.4.21 (prova de direcao): SEM job ativo a rota era 0.0 e o
    governor interpretava como 'cruzou a chegada' -> freio 1.0 PARA
    SEMPRE (a IA assumia o volante e so segurava o freio). Agora sem
    rota = None -> anti-stall dirige devagar; freio so com rota REAL."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ets2ai.practice import governor_real
    meta = {"located": False, "curvs": [None] * 8, "coverage": 0}
    cmd = (0.0, 0.0, 0.0)
    # SEM rota (None), parado: tem que acelerar (anti-stall), NAO frear
    steer, thr, brk = governor_real(0.0, meta, None, cmd, 11.0)
    assert thr >= 0.35 and brk == 0.0, (thr, brk)
    # rota REAL cruzada (0.0 com job): continua freando (comportamento
    # original preservado)
    steer, thr, brk = governor_real(0.0, meta, 0.0, cmd, 11.0)
    assert brk == 1.0, brk
    # rota REAL longe: dirigir normal
    steer, thr, brk = governor_real(0.0, meta, 25000.0, (0.0, 0.8, 0.0), 25.0)
    assert thr >= 0.35 and brk == 0.0, (thr, brk)
