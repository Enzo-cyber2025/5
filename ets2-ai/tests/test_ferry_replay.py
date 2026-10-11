# -*- coding: utf-8 -*-
"""REPLAY da telemetria REAL do jogo do usuario (v0.4.27).

O exe grava `jogo-replay.json` ao lado de ets2-ai-log.txt enquanto o
usuario joga (ex.: embarca na balsa no PORTO de verdade). Esse arquivo NAO
contem nada do jogo — so a linha do tempo da telemetria (paused, ferry,
train, route, speed). Coloque-o em ets2-ai/replays/jogo-replay.json e este
teste reexecuta a IA contra o comportamento REAL do jogo:

- em TODA janela de pausa com travessia pendente (balsa/trem) a IA tem
  que confirmar o dialogo (Enter);
- depois que a travessia conclui (flag consumida + jogo rodando), nenhum
  Enter pode ser enviado (sem spam na doca);
- nenhum dialogo pode receber mais de 6 confirmacoes (cap de seguranca).
"""
import json
from pathlib import Path

import pytest

REPLAY = Path(__file__).resolve().parents[1] / "replays" / "jogo-replay.json"


def _base_sn(ev):
    from ets2ai.telemetry import parse, TelemetryMap
    import ctypes as ct
    buf = bytearray(ct.sizeof(TelemetryMap))
    m = TelemetryMap.from_buffer(buf)
    m.sdk_active = True
    m.plugin_revision = 12
    sn = parse(bytes(buf))
    sn.update({"fuel": 100.0, "fuel_capacity": 600.0,
               "speed_limit": 22.22, "engine_enabled": True,
               "user_steer": 0.0, "user_throttle": 0.0, "user_brake": 0.0,
               "world_x": 0.0, "world_z": 0.0, "ticks": 0})
    sn.update(ev)
    return sn


def test_replay_da_balsa_real():
    if not REPLAY.exists():
        pytest.skip("sem replays/jogo-replay.json — rode o exe no PC real "
                    "(embarque na balsa) e envie o arquivo")
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ets2ai.practice import PracticeLoop
    from ets2ai.contract import load_weights

    layers, _ = load_weights(str(
        Path(__file__).resolve().parents[1] / "artifacts" / "model-weights.json"))
    eventos = json.loads(REPLAY.read_text(encoding="utf-8"))["eventos"]
    assert eventos, "replay vazio"

    taps = []          # [(scan, t)]

    class Inj:
        keymap = {"up": 0x11, "left": 0x1e, "right": 0x20, "brake": 0x39}
        down = set()
        enabled = True

        def tap(self, scan, name=""):
            taps.append((scan, _t[0]))

        def release_all(self):
            pass

        def update(self, *a):
            pass

        def foreign_keys_down(self):
            return set()

    class RoadMap:
        x = []
        z = []
        frame = type("F", (), {"locked": True})()

        def locate(self, x, z, c):
            return None

        def record(self, *a):
            pass

        def save(self, *a):
            pass

    loop = PracticeLoop("drive", RoadMap(), lambda: {}, layers=layers,
                        injector=Inj(), log=lambda *a, **k: None)
    loop._last_macro_t = -1e9
    _t = [0.0]
    for ev in eventos:
        _t[0] = ev["t"]
        sn = _base_sn(ev)
        loop.step(sn, ev["t"])
    enter_taps = [t for s, t in taps if s == 0x1C]

    # 1) janelas de DIALOGO (pausa + travessia pendente + perto do porto)
    janelas = []
    ini = None
    for ev in eventos:
        dialogo = (ev.get("paused") and (ev.get("ferry") or ev.get("train"))
                   and ev.get("route") is not None and ev["route"] < 60.0)
        if dialogo and ini is None:
            ini = ev["t"]
        elif not dialogo and ini is not None:
            janelas.append((ini, ev["t"]))
            ini = None
    if ini is not None:
        janelas.append((ini, eventos[-1]["t"]))
    assert janelas, "replay sem dialogo de travessia — grave o embarque"
    for ini, fim in janelas:
        ok = any(ini - 1.0 <= t <= fim + 5.0 for t in enter_taps)
        assert ok, f"IA nao confirmou o dialogo real em t={ini:.1f}"

    # 2) cap: nenhuma janela com mais de 6 confirmacoes (seguranca)
    for ini, fim in janelas:
        n = sum(1 for t in enter_taps if ini - 1.0 <= t <= fim + 1.0)
        assert n <= 6, f"spam no dialogo real em t={ini:.1f}: {n} Enters"

    # 3) depois que a travessia concluiu, nada de Enter
    consumo = None
    prev = None
    for ev in eventos:
        if prev is not None and prev.get("ferry") and not ev.get("ferry") \
                and not ev.get("paused"):
            consumo = ev["t"]
            break
        prev = ev
    if consumo is not None:
        depois = [t for t in enter_taps if t > consumo + 10.0]
        assert not depois, f"Enter DEPOIS da travessia concluida: {depois}"


def test_gravador_de_replay_funciona():
    """O gravador em si: PracticeLoop com timeline_path escreve o json com
    as transicoes (pausa, balsa) — e o passo de 2 s nao explode o arquivo."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ets2ai.practice import PracticeLoop
    from ets2ai.contract import load_weights
    layers, _ = load_weights(str(
        Path(__file__).resolve().parents[1] / "artifacts" / "model-weights.json"))

    class RoadMap:
        x = []
        z = []
        frame = type("F", (), {"locked": True})()

        def locate(self, x, z, c):
            return None

        def record(self, *a):
            pass

        def save(self, *a):
            pass

    tmp = Path(__file__).resolve().parent / "_replay_teste.json"
    loop = PracticeLoop("drive", RoadMap(), lambda: {}, layers=layers,
                        injector=None, log=lambda *a, **k: None,
                        timeline_path=str(tmp))
    loop._last_macro_t = -1e9
    a = _base_sn({"speed": 0.0, "route_distance": 8.0, "on_job": True,
                  "ferry": True, "paused": False, "ticks": 0})
    b = _base_sn({"speed": 0.0, "route_distance": 8.0, "on_job": True,
                  "ferry": True, "paused": True, "ticks": 1})
    loop.step(dict(a), 1.0)
    loop.step(dict(b), 2.0)          # transicao -> registra
    loop.step(dict(b), 3.0)          # mesmo estado, <2 s -> nao registra
    loop._save_timeline()
    data = json.loads(tmp.read_text(encoding="utf-8"))
    tmp.unlink()
    evs = data["eventos"]
    assert any(e["paused"] and e["ferry"] for e in evs)
    assert len(evs) <= 3
