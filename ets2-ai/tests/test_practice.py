"""Modo pratica: telemetria -> mapa -> features -> IA -> teclas, de ponta a ponta.

O "jogo" aqui e o FakeGame: um sim.Truck com rampas de teclado iguais as do
ETS2 e snapshots no formato do plugin RenCloud. Prova o pipeline inteiro SEM
Windows: curso por deslocamento, mapa aprendido, features do contrato,
governador real, injecao (fake), gravacao DAgger e veredicto do shadow.
"""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ets2ai import sim, telemetry
from ets2ai.practice import (PracticeLoop, features_from, governor_real,
                             REC_MIN_COVERAGE)
from ets2ai.roadmap import RoadMap, Frame
from ets2ai.keys import Recorder


# ---------------------------------------------------------------------------
# Falso ETS2: fisica do sim + rampas de teclado + snapshot RenCloud
# ---------------------------------------------------------------------------
class FakeGame:
    def __init__(self, road, s=5.0, speed=12.0):
        self.road = road
        self.truck = sim.Truck(road, s=s, offset=0.0, speed=speed)
        self.keys = set()
        self.steer = 0.0
        self.throttle = 0.0
        self.brake = 0.0
        self.t = 0.0
        self.manual = False          # True: entradas analogicas diretas

    def step(self, dt):
        if not self.manual:
            tgt = -1.0 if "left" in self.keys else (
                1.0 if "right" in self.keys else 0.0)
            rate = 2.5 if tgt != 0.0 else 3.5
            self.steer += max(-rate * dt, min(rate * dt, tgt - self.steer))
            for attr, key, up, dn in ((self, "accel", "throttle", 0),
                                      (self, "brake", "brake", 0)):
                pass
            tgt_t = 1.0 if "accel" in self.keys else 0.0
            tgt_b = 1.0 if "brake" in self.keys else 0.0
            self.throttle += max(-3.0 * dt, min(2.0 * dt, tgt_t - self.throttle))
            self.brake += max(-3.0 * dt, min(2.0 * dt, tgt_b - self.brake))
        self.truck.step(self.road, self.steer, self.throttle, self.brake, dt)
        self.t += dt

    def snapshot(self):
        t = self.truck
        d_dock = max(0.0, (self.road.length - 6.0) - t.s)
        return {
            "sdk_active": True, "paused": False, "ticks": int(self.t * 1000),
            "game": "ets2", "game_minutes": 420 + int(self.t / 60),
            "speed": t.speed,
            "user_steer": self.steer, "user_throttle": self.throttle,
            "user_brake": self.brake,
            "fuel": t.fuel * 600.0, "fuel_capacity": 600.0,
            "route_distance": d_dock, "speed_limit": 25.0,
            "park_brake": False, "engine_enabled": True,
            "world_x": t.x, "world_y": 0.0, "world_z": t.y,
            "on_job": True, "job_delivered": False,
            "cargo": "caixas", "city_src": "Origem", "city_dst": "Destino",
        }


class FakeInjector:
    """Mesma matematica do KeyInjector (PWM do volante incluido), sem Windows."""

    def __init__(self):
        self.down = set()
        self.kill = False
        self.phase = 0
        self.taps = []          # macros tocadas (engine/park_brake/...)
        self.last_cmd = None

    def update(self, steer, throttle, brake):
        from ets2ai.keys import key_decisions, PWM_PHASES
        self.down = key_decisions(steer, throttle, brake, self.phase)
        self.phase = (self.phase + 1) % PWM_PHASES
        self.last_cmd = (steer, throttle, brake)

    def tap(self, scan, name=""):
        self.taps.append(name or hex(scan))

    def release_all(self):
        self.down = set()


class BoundInjector(FakeInjector):
    """Injetor ligado ao FakeGame (o SendInput do mundo real)."""

    def __init__(self, game):
        super().__init__()
        self.game = game

    def update(self, steer, throttle, brake):
        super().update(steer, throttle, brake)
        self.game.keys = set(self.down)

    def release_all(self):
        super().release_all()
        self.game.keys = set()


class SimClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class SimSleep:
    def __init__(self, clock):
        self.clock = clock

    def __call__(self, s):
        self.clock.t += max(s, 0.0)


GENTLE_ROAD = sim.Road(
    [250.0, 350.0, 300.0, 350.0, 300.0],
    [0.0, 0.004, -0.004, 0.003, 0.0])


def hand_policy(feat):
    """Controlador manual decente (as features sao do contrato)."""
    speed, offset, he = feat[0], feat[1], feat[2]
    curv = max(abs(c) for c in feat[3:8]) * 0.05        # 1/m
    if curv > 1e-4:
        v_t = min(23.0, math.sqrt(0.92 / curv)) / 25.0  # m/s -> normalizado
    else:
        v_t = 0.92
    steer = max(-1.0, min(1.0, -offset * 1.3 - he * 1.6))
    return (steer,
            1.0 if speed < v_t - 0.02 else 0.0,
            1.0 if speed > v_t + 0.04 else 0.0)


def make_loop(mode, game, road_map, injector=None, recorder=None,
              policy=hand_policy, map_path=None, human=False, phone=None):
    clock = SimClock()
    state = {"offsets": [], "speeds": []}

    def source():
        if human:
            # "pessoa" dirigindo: especialista do sim como entradas analogicas
            cmd = sim.expert(game.road, game.truck, 1.0)
            game.steer, game.throttle, game.brake = cmd
        game.step(0.05)
        state["offsets"].append(game.truck.offset)
        state["speeds"].append(game.truck.speed)
        return game.snapshot()

    loop = PracticeLoop(mode, road_map, source, injector=injector,
                        recorder=recorder, map_path=map_path,
                        policy_fn=policy, phone=phone, clock=clock,
                        sleep=SimSleep(clock), log=lambda *a, **k: None)
    return loop, state


# ---------------------------------------------------------------------------
# features_from bate com sim.features no MESMO estado
# ---------------------------------------------------------------------------
def test_features_iguais_ao_sim():
    road = GENTLE_ROAD
    m = RoadMap()
    for i in range(1, len(road.samples)):
        x0, y0 = road.samples[i - 1]
        x1, y1 = road.samples[i]
        m.record(x1, y1, math.atan2(y1 - y0, x1 - x0), 18.0)
    t = sim.Truck(road, s=480.0, offset=1.2, speed=17.0, heading=None)
    game = FakeGame(road, s=480.0, speed=17.0)
    # transportar o truck do teste pro jogo fake
    game.truck = t
    sn = game.snapshot()
    feat, meta = features_from(sn, m, t.heading, job_minutes=0.0)
    exp = sim.features(road, t, (road.length - 6.0 - t.s) / 1000.0)
    for i in range(12):        # 0..11: radar (12) e sempre 1.0 na pratica
        assert abs(feat[i] - exp[i]) < 0.03, (i, feat[i], exp[i])
    assert feat[12] == 1.0
    assert meta["located"] and meta["coverage"] >= REC_MIN_COVERAGE
    assert abs(meta["offset"] - 1.2) < 0.4


def test_features_sem_mapa():
    game = FakeGame(GENTLE_ROAD)
    sn = game.snapshot()
    feat, meta = features_from(sn, RoadMap(), course=None, job_minutes=0.0)
    assert not meta["located"]
    assert feat[1] == 0.0 and feat[3:8] == [0.0] * 5
    assert feat[9] == 1.0 and feat[10] == 0.0


# ---------------------------------------------------------------------------
# governador real
# ---------------------------------------------------------------------------
def test_governor_freia_para_curva():
    meta = {"located": True, "coverage": 5, "curvs": [0.0, 0.008, 0.0, 0, 0],
            "offset": 0.0, "heading_error": 0.0}
    # 22 m/s (~79 km/h) chegando numa curva a 18 m: nao da — freio total
    cmd = governor_real(22.0, meta, 5000.0, (0.0, 1.0, 0.0), 25.0)
    assert cmd == (0.0, 0.0, 1.0)
    # com velocidade compativel, passa
    cmd = governor_real(12.0, meta, 5000.0, (0.2, 1.0, 0.0), 25.0)
    assert cmd == (0.2, 1.0, 0.0)


def test_governor_dock_e_stall():
    meta = {"located": True, "coverage": 5, "curvs": [0.0] * 5,
            "offset": 0.0, "heading_error": 0.0}
    # 24 m/s a 80 m do destino: nao da pra chegar assim — freio total
    cmd = governor_real(24.0, meta, 80.0, (0.0, 1.0, 0.0), 25.0)
    assert cmd[2] >= 0.85
    # parado longe do destino: anti-stall (acelera)
    cmd = governor_real(0.3, meta, 5000.0, (0.0, 0.0, 0.0), 25.0)
    assert cmd[1] >= 0.35
    # parado NA linha do destino: segura
    cmd = governor_real(0.3, meta, 1.0, (0.0, 0.1, 0.0), 25.0)
    assert cmd[2] == 1.0


def test_governor_estrada_desconhecida():
    meta = {"located": False, "coverage": 0, "curvs": [None] * 5,
            "offset": 0.0, "heading_error": 0.0}
    cmd = governor_real(14.0, meta, 5000.0, (0.0, 1.0, 0.0), 25.0)
    assert cmd[2] == 1.0


# ---------------------------------------------------------------------------
# record: aprende o mapa e grava linhas reais (a partir da 2a passada)
# ---------------------------------------------------------------------------
def test_record_aprende_e_grava(tmp_path):
    road = GENTLE_ROAD
    game = FakeGame(road, s=5.0, speed=0.0)
    game.manual = True
    # --- sessao 1: aprende a estrada (sem gravar) ---
    m = RoadMap()
    loop, st = make_loop("record", game, m, human=True,
                         map_path=tmp_path / "mapa.json")
    loop.run(max_seconds=140.0)
    assert len(m.x) > 100
    assert (tmp_path / "mapa.json").exists()
    # --- sessao 2: recarrega o mapa e grava dados de treino ---
    m2 = RoadMap.load(tmp_path / "mapa.json")
    game2 = FakeGame(road, s=5.0, speed=0.0)
    game2.manual = True
    rec_path = tmp_path / "sessao.csv"
    recorder = Recorder(rec_path)
    loop2, st2 = make_loop("record", game2, m2, recorder=recorder,
                           map_path=tmp_path / "mapa.json", human=True)
    loop2.run(max_seconds=140.0)
    assert recorder.n > 150, "2a passada deveria gravar linhas"
    # linhas no formato do finetune
    lines = rec_path.read_text().strip().splitlines()
    assert lines[0] == "ets2ai-rec,v1"
    parts = lines[1].split(",")
    assert len(parts) == 13 + 3 + 2
    assert parts[16] == "1"            # override (13 feats + 3 cmds)
    assert float(parts[0]) > 0.0       # speed


# ---------------------------------------------------------------------------
# drive: IA dirige de ponta a ponta pelo caminho real (teclas bang-bang)
# ---------------------------------------------------------------------------
def test_drive_end_to_end():
    road = GENTLE_ROAD
    m = RoadMap()
    for i in range(1, len(road.samples)):
        x0, y0 = road.samples[i - 1]
        x1, y1 = road.samples[i]
        m.record(x1, y1, math.atan2(y1 - y0, x1 - x0), 18.0)
    game = FakeGame(road, s=5.0, speed=0.0)
    inj = BoundInjector(game)
    loop, st = make_loop("drive", game, m, injector=inj)
    res = loop.run(max_seconds=180.0)
    # as teclas do injetor viram as teclas do jogo (no real: SendInput)
    offsets = [abs(o) for o in st["offsets"]]
    assert game.truck.s > 600.0, f"nao andou: s={game.truck.s}"
    assert max(offsets) < 4.0, f"saiu da pista: {max(offsets)}"
    assert float(np.mean(offsets)) < 1.6
    assert max(st["speeds"]) >= 10.0          # andou de verdade
    assert float(np.mean(st["speeds"])) >= 6.0


def test_drive_humano_intervem_e_vira_dagger(tmp_path):
    road = GENTLE_ROAD
    m = RoadMap()
    for i in range(1, len(road.samples)):
        x0, y0 = road.samples[i - 1]
        x1, y1 = road.samples[i]
        m.record(x1, y1, math.atan2(y1 - y0, x1 - x0), 18.0)
    game = FakeGame(road, s=5.0, speed=0.0)
    inj = BoundInjector(game)
    recorder = Recorder(tmp_path / "daggar.csv")
    loop, st = make_loop("drive", game, m, injector=inj, recorder=recorder)

    step_fn = loop.step
    clock = loop.clock
    sn_fn = loop.source
    # 12 s de IA, depois 8 s de "humano" pisando no freio + volante,
    # depois IA de novo
    t_event = [12.0]

    def source():
        sn = sn_fn()
        now = clock()
        if t_event[0] <= now < t_event[0] + 8.0:
            game.brake = 0.9
            game.steer = 0.5
            sn["user_brake"] = 0.9
            sn["user_steer"] = 0.5
        return sn

    loop.source = source
    res = loop.run(max_seconds=30.0)
    assert recorder.n > 0
    lines = (tmp_path / "daggar.csv").read_text().strip().splitlines()
    srcs = {ln.split(",")[-1] for ln in lines[1:]}
    assert "H" in srcs, f"correcao humana deveria ser gravada: {srcs}"


# ---------------------------------------------------------------------------
# shadow: veredicto de espelhamento
# ---------------------------------------------------------------------------
def test_shadow_veredito():
    road = GENTLE_ROAD
    m = RoadMap()
    for i in range(1, len(road.samples)):
        x0, y0 = road.samples[i - 1]
        x1, y1 = road.samples[i]
        m.record(x1, y1, math.atan2(y1 - y0, x1 - x0), 18.0)
    game = FakeGame(road, s=400.0, speed=12.0)   # ja dentro da curva
    game.manual = True
    recorder = Recorder(tmp_path_shadow())
    loop, st = make_loop("shadow", game, m, recorder=recorder)
    # humano "especialista" dirige seguindo a estrada
    def human_source():
        game.step(0.05)
        cmd = sim.expert(road, game.truck, 1.0)
        game.steer, game.throttle, game.brake = cmd
        return game.snapshot()
    loop.source = human_source
    res = loop.run(max_seconds=25.0)
    assert "OK" in res["shadow"], res["shadow"]
    assert recorder.n > 50


def tmp_path_shadow():
    import tempfile
    return Path(tempfile.mkdtemp()) / "shadow.csv"


def test_shadow_veredito_espelhado():
    road = GENTLE_ROAD
    m = RoadMap()
    for i in range(1, len(road.samples)):
        x0, y0 = road.samples[i - 1]
        x1, y1 = road.samples[i]
        m.record(x1, y1, math.atan2(y1 - y0, x1 - x0), 18.0)
    game = FakeGame(road, s=400.0, speed=12.0)   # ja dentro da curva
    game.manual = True
    # IA com frame ESPELHADO: ve offset/heading/curvatura com sinal trocado
    # (exatamente o que aconteceria com a reflexao errada do mundo do jogo)
    def mirror(feat):
        f = list(feat)
        f[1] = -f[1]          # offset
        f[2] = -f[2]          # heading_error
        for i in range(3, 8):
            f[i] = -f[i]      # curvaturas
        return hand_policy(f)
    loop, st = make_loop("shadow", game, m, policy=mirror)
    def human_source():
        game.step(0.05)
        cmd = sim.expert(road, game.truck, 1.0)
        game.steer, game.throttle, game.brake = cmd
        return game.snapshot()
    loop.source = human_source
    res = loop.run(max_seconds=25.0)
    assert "ESPELHADO" in res["shadow"], res["shadow"]


def test_drive_com_celular_como_cerebro():
    """O APK roda a IA: a pratica manda o estado (protocolo S) e o comando
    vem do celular — sem celular, cai na politica local sem falhar."""
    import math as _math
    from ets2ai.roadmap import RoadMap
    road = GENTLE_ROAD
    m = RoadMap()
    x0, y0 = road.samples[0][:2]
    x1, y1 = road.samples[30][:2]
    m.record(x1, y1, _math.atan2(y1 - y0, x1 - x0), 18.0)
    game = FakeGame(road, s=5.0, speed=12.0)

    class FakePhone:
        connected = True
        sent = []

        def send_fields(self, **kw):
            self.sent.append(kw)

        def wait_cmd(self, timeout):
            return (0.05, 0.9, 0.0)

    ph = FakePhone()
    loop, st = make_loop("drive", game, m, phone=ph, policy=lambda f: (9, 9, 9))
    out = loop.step(game.snapshot(), 0.1)
    assert len(ph.sent) >= 1, "estado nao foi enviado ao celular"
    kw = ph.sent[-1]
    # campos do protocolo S presentes e em unidades crus (m/s, m, rad)
    assert 0.0 <= kw["speed"] <= 50.0 and -10 < kw["offset"] < 10
    assert len(kw["curvs"]) == 5 and 0 < kw["limit"] <= 25.0
    # comando usado veio do CELULAR (0.05/0.9), nao da politica local (9,9,9)
    assert out["cmd"] is not None and abs(out["cmd"][0] - 0.05) < 1e-6
    # pedais passam pelo governor_real (ajuste de velocidade) — so faixa valida
    assert 0.0 <= out["cmd"][1] <= 1.0 and 0.0 <= out["cmd"][2] <= 1.0
    # sem celular conectado: politica local assume (sem excecao)
    ph.connected = False
    loop2, _ = make_loop("drive", game, m, policy=lambda f: (0.1, 0.5, 0.0))
    loop2.phone = ph
    loop2.step(game.snapshot(), 0.2)   # nao deve lancar


# --------------------------------------------------------------------------- #
# TOMADA IMEDIATA + telemetria sem DLL (leitura de memoria)
# --------------------------------------------------------------------------- #
def test_tomada_imediata_arranque_frio():
    """Caminhao PARADO com freio de mao e motor desligado: a IA assume no
    1o tick (fonte 'IA'), liga o motor e solta o freio de mao SOZINHA."""
    road = GENTLE_ROAD
    m = RoadMap()
    game = FakeGame(road, s=5.0, speed=0.0)
    st_ = {"pb": True, "eng": False}
    _orig_snap = game.snapshot
    game.snapshot = lambda: dict(_orig_snap(), park_brake=st_["pb"],
                                 engine_enabled=st_["eng"])
    inj = FakeInjector()
    loop, st = make_loop("drive", game, m, injector=inj,
                         policy=lambda f: (0.0, 0.9, 0.0))
    # 1o tick: parado, motor off — ja e IA no comando (nao espera humano)
    out = loop.step(loop.source(), 0.05)
    assert out["source"] == "IA"
    # ~1 s parado: macros de arranque disparam (motor + freio de mao)
    t = 0.05
    for i in range(24):
        t += 0.05
        loop.step(loop.source(), t)
    assert any("motor" in t for t in inj.taps), inj.taps
    assert any("estacionamento" in t for t in inj.taps), inj.taps
    # contra o freio de mao a IA NAO acelera (solta as teclas)
    assert inj.down == set()
    # freio de mao solto + motor ligado -> IA acelera sozinha
    st_.update(pb=False, eng=True)
    t += 0.05
    out = loop.step(loop.source(), t)
    assert inj.last_cmd is not None and inj.last_cmd[1] > 0.0, out


def test_mapa_vazio_teto_prudente():
    """Mapa vazio: a IA assume IMEDIATAMENTE mas moderada (freia acima de
    11 m/s mesmo com limite 25) — nunca acelera tudo no escuro."""
    road = GENTLE_ROAD
    m = RoadMap()                     # vazio: sem frame, sem pontos
    game = FakeGame(road, s=5.0, speed=16.0)   # 16 m/s > 11+2
    inj = FakeInjector()
    loop, st = make_loop("drive", game, m, injector=inj,
                         policy=lambda f: (0.0, 1.0, 0.0))
    out = loop.step(game.snapshot(), 0.05)
    assert out["cmd"] is not None and out["cmd"][2] >= 0.8   # freou


def test_humano_por_tecla_fisica_sem_dll():
    """Telemetria sem input do jogo (leitor de memoria): humano detectado
    pelas teclas FISICAS que nao fomos nos — IA solta e volta depois."""
    road = GENTLE_ROAD
    m = RoadMap()
    game = FakeGame(road, s=5.0, speed=10.0)
    inj = FakeInjector()

    _orig_snap = game.snapshot
    game.snapshot = lambda: dict(_orig_snap(), user_steer=None,
                                 user_throttle=None, user_brake=None)
    fk = {"hold": False}
    loop, st = make_loop("drive", game, m, injector=inj,
                         policy=lambda f: (0.0, 0.6, 0.0))
    loop.foreign_keys = lambda: ({"accel"} if fk["hold"] else set())
    # humano pisa no acelerador: 3+ ticks -> IA solta
    fk["hold"] = True
    t = 0.0
    for i in range(5):
        t += 0.05
        out = loop.step(loop.source(), t)
    assert out["source"].startswith("HUMANO")
    assert inj.down == set()
    # humano soltou: apos OVERRIDE_RESUME_S a IA volta
    fk["hold"] = False
    for i in range(14):
        t += 0.2
        out = loop.step(loop.source(), t)
    assert out["source"] == "IA", out["source"]


def test_stop_event_para_a_pratica():
    """O botao PARAR da GUI (stop_event) encerra o loop e solta as teclas."""
    import threading
    import time
    m = RoadMap()
    game = FakeGame(GENTLE_ROAD, s=5.0, speed=10.0)
    inj = FakeInjector()
    ev = threading.Event()
    calls = {"n": 0}

    def src():
        calls["n"] += 1
        if calls["n"] > 6:
            ev.set()                      # "usuario clicou PARAR"
        return game.snapshot()

    loop = PracticeLoop("drive", m, src, injector=inj,
                        policy_fn=lambda f: (0.0, 0.6, 0.0),
                        clock=time.monotonic, sleep=lambda s: None,
                        log=lambda *a, **k: None, stop_event=ev)
    loop.run(max_seconds=30)
    assert calls["n"] <= 10, calls["n"]        # parou logo, nao rodou 30 s
    assert inj.down == set()                   # teclas soltas
