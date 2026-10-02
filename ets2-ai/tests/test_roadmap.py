"""RoadMap: o mapa de pista aprendido tem que reproduzir o sim EXATAMENTE.

Estrategia: usar a propria Road do simulador como "estrada real" (amostras de
2 m), gravar no RoadMap como se fosse telemetria, e conferir que as consultas
devolvem offset/heading/curvatura com os MESMOS sinais e valores do sim.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ets2ai import sim
from ets2ai.roadmap import RoadMap, Frame, detect_frame


def build_map_from_road(road, frame=None, refine=True):
    m = RoadMap(frame or Frame())
    for i, (x, y) in enumerate(road.samples):
        # heading "real": tangente entre amostras consecutivas
        if i + 1 < len(road.samples):
            nx, ny = road.samples[i + 1]
        else:
            nx, ny = road.samples[i - 1]
            nx, ny = 2 * x - nx, 2 * y - ny
        heading = math.atan2(ny - y, nx - x)
        m.record(x, y, heading, speed=18.0, refine=refine)
    return m


def test_layout_offset_e_heading():
    road = sim.Road([300.0] * 10, [0.0, 0.008, -0.008] + [0.0] * 7)
    m = build_map_from_road(road)
    # caminhao no centro, no meio de um segmento reto
    t = sim.Truck(road, s=150.0, offset=0.0, speed=15.0)
    loc = m.locate(t.x, t.y, t.heading)
    assert loc is not None
    _, offset, tangent = loc
    assert abs(offset) < 0.35, offset
    assert abs(sim.wrap_angle(tangent - t.tangent)) < 0.1


def test_offset_sinal_direita_positivo():
    road = sim.Road([300.0] * 10, [0.0, 0.008, -0.008] + [0.0] * 7)
    m = build_map_from_road(road)
    # offset +2.0 no sim = direita do centro; o mapa tem que concordar
    t = sim.Truck(road, s=150.0, offset=2.0, speed=15.0)
    _, offset, _ = m.locate(t.x, t.y, t.heading)
    assert 1.5 < offset < 2.5, offset
    t = sim.Truck(road, s=150.0, offset=-2.0, speed=15.0)
    _, offset, _ = m.locate(t.x, t.y, t.heading)
    assert -2.5 < offset < -1.5, offset


def test_curvatura_a_frente_sinal_e_valor():
    # estrada: reta, curva 0.01 a direita, curva 0.01 a esquerda, reta
    road = sim.Road([200.0, 400.0, 400.0, 200.0],
                    [0.0, 0.01, -0.01, 0.0])
    m = build_map_from_road(road)
    t = sim.Truck(road, s=175.0, offset=0.0, speed=15.0)
    idx, _, _ = m.locate(t.x, t.y, t.heading)
    ks = m.curvatures_ahead(idx, t.heading)
    # s=175: +8=183 reto | +18=193 reto | +40=215 curva(+0.01)
    #        +90=265 curva | +170=345 curva
    exp = [road.curvature_at(175.0 + d) for d in sim.LOOKAHEAD]
    for got, want, d in zip(ks, exp, sim.LOOKAHEAD):
        assert got is not None, f"curv a {d} m sem mapa"
        assert abs(got - want) < 0.0025, (d, got, want)
    # sinal: curva a direita do sim (k>0) tem que dar positivo no mapa
    assert ks[2] > 0.005 and ks[4] > 0.005


def test_curvatura_negativa_curva_a_esquerda():
    road = sim.Road([200.0, 400.0], [0.0, -0.012])
    m = build_map_from_road(road)
    t = sim.Truck(road, s=150.0, offset=0.0, speed=15.0)
    idx, _, _ = m.locate(t.x, t.y, t.heading)
    ks = m.curvatures_ahead(idx, t.heading)
    # s=150: +90=240 e +170=320 estao dentro da curva a esquerda (-0.012)
    assert ks[3] is not None and ks[3] < -0.008, ks


def test_segunda_passada_refina_sem_duplicar():
    road = sim.Road([300.0] * 6, [0.0, 0.006, 0.0, -0.006, 0.0, 0.0])
    m = build_map_from_road(road)
    n1 = len(m.x)
    # segunda passada pela mesma estrada, 0.5 m deslocada p/ direita,
    # usando os proprios pontos do mapa (mesmo espaçamento)
    for i in range(n1):
        x, y, th = m.x[i], m.y[i], m.h[i]
        x2 = x - 0.5 * math.sin(th)
        y2 = y + 0.5 * math.cos(th)
        if i + 1 < n1:
            nx, ny = m.x[i + 1] - 0.5 * math.sin(m.h[i + 1]), \
                     m.y[i + 1] + 0.5 * math.cos(m.h[i + 1])
        else:
            nx, ny = 2 * x2 - (m.x[i - 1] - 0.5 * math.sin(m.h[i - 1])), \
                     2 * y2 - (m.y[i - 1] + 0.5 * math.cos(m.h[i - 1]))
        m.record(x2, y2, math.atan2(ny - y2, nx - x2), 17.0, refine=True)
    assert len(m.x) == n1, "segunda passada duplicou pontos em vez de refinar"
    # e a linha central continua consultavel no centro verdadeiro
    t = sim.Truck(road, s=450.0, offset=0.0, speed=15.0)
    _, offset, _ = m.locate(t.x, t.y, t.heading)
    assert abs(offset) < 0.5, offset


def test_detect_frame_sem_espelho():
    road = sim.Road([200.0] * 8, [0.0, 0.009, -0.009, 0.0, 0.008, 0.0, -0.008, 0.0])
    pts, steers = [], []
    for i in range(1, len(road.samples)):
        x0, y0 = road.samples[i - 1]
        x1, y1 = road.samples[i]
        pts.append((x1, y1))
        # "motorista" seguindo a curva: volante no sinal da curvatura local
        steers.append(math.copysign(0.4, road.curvature_at(road.sample_s[i]) or 1e-9)
                      if road.curvature_at(road.sample_s[i]) != 0 else 0.05)
    f, q = detect_frame(pts, steers)
    assert f.locked and not f.z_flip, (f.z_flip, q)
    assert q > 0.3, q


def test_detect_frame_com_espelho():
    """Mundo 'jogo' espelhado (wz = -y): detect tem que achar z_flip=True."""
    road = sim.Road([200.0] * 8, [0.0, 0.009, -0.009, 0.0, 0.008, 0.0, -0.008, 0.0])
    pts, steers = [], []
    for i in range(1, len(road.samples)):
        x0, y0 = road.samples[i - 1]
        x1, y1 = road.samples[i]
        pts.append((x1, -y1))                     # espelhado
        k = road.curvature_at(road.sample_s[i])
        steers.append(math.copysign(0.4, k or 1e-9) if k != 0 else 0.05)
    f, q = detect_frame(pts, steers)
    assert f.locked and f.z_flip, (f.z_flip, q)
    # e com o frame detectado as features saem iguais as do sim
    m = build_map_from_road(road, frame=f)
    # gravar de novo, agora em coordenadas de "jogo" espelhadas
    m2 = RoadMap(f)
    for i, (x, y) in enumerate(road.samples):
        if i + 1 < len(road.samples):
            nx, ny = road.samples[i + 1]
        else:
            nx, ny = road.samples[i - 1]
            nx, ny = 2 * x - nx, 2 * y - ny
        m2.record(x, -y, -math.atan2(ny - y, nx - x), 18.0)
    t = sim.Truck(road, s=250.0, offset=1.5, speed=15.0)
    loc = m2.locate(t.x, -t.y, t.heading if not f.z_flip else -t.heading)
    assert loc is not None
    _, offset, _ = loc
    assert 1.0 < offset < 2.0, offset


def test_persistencia_roundtrip(tmp_path):
    road = sim.Road([300.0] * 5, [0.0, 0.007, 0.0, -0.007, 0.0])
    m = build_map_from_road(road)
    m.save(tmp_path / "mapa.json")
    m2 = RoadMap.load(tmp_path / "mapa.json")
    t = sim.Truck(road, s=400.0, offset=1.0, speed=15.0)
    a = m.locate(t.x, t.y, t.heading)
    b = m2.locate(t.x, t.y, t.heading)
    assert a is not None and b is not None
    assert abs(a[1] - b[1]) < 0.05 and abs(a[2] - b[2]) < 0.01


def test_coverage_cresce_com_o_mapa():
    road = sim.Road([300.0] * 6, [0.0, 0.006, 0.0, -0.006, 0.0, 0.0])
    m = build_map_from_road(road)
    t = sim.Truck(road, s=100.0, offset=0.0, speed=15.0)
    idx, _, _ = m.locate(t.x, t.y, t.heading)
    assert m.coverage(idx, t.heading) == 5
    # perto do fim da estrada o mapa nao alcanca 170 m -> coverage cai
    t = sim.Truck(road, s=road.length - 60.0, offset=0.0, speed=15.0)
    idx, _, _ = m.locate(t.x, t.y, t.heading)
    assert m.coverage(idx, t.heading) < 5
