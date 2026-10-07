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
