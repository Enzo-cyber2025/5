"""Gerador vetorizado (v0.4.4): fidelidade + transferencia.

O vector_gen gera amostras milhares de vezes mais rapido que o simulador
escalar. Estes testes provam que (1) a distribuicao bate com a do escalar e
(2) uma rede treinada SO em dados vetoriais dirige o mundo escalar — a
prova definitiva de que o fluxo de 1 bilhao de amostras serve o mesmo
comportamento.
"""
import numpy as np
import pytest

from ets2ai import vector_gen


@pytest.fixture(scope="module")
def chunks():
    gen = vector_gen.stream(seed=20260930, n_trucks=1024)
    xs, ys = [], []
    for i, (x, y) in enumerate(gen):
        xs.append(x)
        ys.append(y)
        if i >= 2:
            break
    return np.concatenate(xs), np.concatenate(ys)


def test_forma_e_finitos(chunks):
    x, y = chunks
    assert x.shape[1] == 13 and y.shape[1] == 3
    assert len(x) > 100_000
    assert np.isfinite(x).all() and np.isfinite(y).all()
    assert y[:, 0].min() >= -1.0 and y[:, 0].max() <= 1.0   # steer clipado


def test_distribuicao_bate_com_escalar(chunks):
    import ets2ai.data as data
    data.N_TRAIN_ROADS = 8
    data.N_VAL_ROADS = 3
    xs, ys, _, _ = data.generate()
    x, y = chunks
    for i in (0, 1, 2, 11, 12):          # speed, offset, hdg, job, radar
        assert abs(x[:, i].mean() - xs[:, i].mean()) < 0.15, f"feat {i}"
    for i in (0, 1, 2):                  # steer, throttle, brake
        assert abs(y[:, i].mean() - ys[:, i].mean()) < 0.18, f"act {i}"


def test_transferencia_treina_vetor_dirige_escalar(chunks):
    """Rede pequena treinada em dados VETORIAIS precisa dirigir o simulador
    ESCALAR (circuito fechado) — e' o gate de qualidade do fluxo."""
    from ets2ai.model import train as np_train
    from ets2ai.train import closed_loop_eval

    x, y = chunks
    rng = np.random.default_rng(0)
    sizes = [13, 32, 32, 3]
    layers = [((rng.standard_normal((a, b)) * np.sqrt(1.0 / a)).astype(np.float64),
               np.zeros(b, dtype=np.float64))
              for a, b in zip(sizes[:-1], sizes[1:])]
    layers, _ = np_train(x[:250_000].astype(np.float64),
                         y[:250_000].astype(np.float64),
                         epochs=3, batch=512, verbose=False,
                         start_layers=layers, dtype=np.float64)
    agg, _ = closed_loop_eval(layers, n_roads=3)
    assert agg["in_lane_pct"] > 0.95, "fora da faixa: transferencia falhou"
    assert agg["finish_rate"] >= 2 / 3, "nao dirige o mundo escalar"


def test_val_set_fixa_e_deterministica():
    x1, y1 = vector_gen.val_set(seed=999, n_trucks=256)
    x2, y2 = vector_gen.val_set(seed=999, n_trucks=256)
    assert np.array_equal(x1, x2) and np.array_equal(y1, y2)
    assert len(x1) > 50_000


def test_sem_repeticao_entre_sementes():
    """A cadeia nunca repete dados: a semente da sessao avanca com o total
    acumulado (SEED + cum_prev), entao sessoes distintas geram fluxos
    distintos; e a mesma semente e reproduzivel (auditavel)."""
    def first_batch(seed):
        for x, y in vector_gen.stream(seed=seed, n_trucks=256):
            return x[:64].tobytes() + y[:64].tobytes()

    a = first_batch(7)
    b = first_batch(8)
    c = first_batch(7)
    assert a != b, "sementes diferentes geraram dados identigos (repeticao!)"
    assert a == c, "mesma semente deveria reproduzir exatamente os dados"
