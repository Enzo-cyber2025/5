"""Modo float64 (--dtype float64): precisão nativa sem quebrar o float32.

O caminho float32 é o de deploy (APK/EXE/TFLite/.pt) e precisa continuar
bit-idêntico — o CI retraina e compara contra os pesos commitados. O modo
float64 existe para o experimento de precisão (ver README, seção float64).
"""
import numpy as np
import pytest

from ets2ai.contract import model_meta
from ets2ai.model import forward, init_layers, mse, train


@pytest.fixture(scope="module")
def synthetic():
    rng = np.random.default_rng(0)
    x = rng.standard_normal((1024, 13)) * 2
    y = rng.standard_normal((1024, 3)) * 0.1
    return x, y


def test_float32_determinista_e_bit_identico(synthetic):
    x, y = synthetic
    l1, _ = train(x, y, epochs=2, verbose=False)
    l2, _ = train(x, y, epochs=2, verbose=False)
    assert all(np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])
               for a, b in zip(l1, l2))
    assert all(w.dtype == np.float32 for w, b in l1)


def test_float64_pesos_em_double(synthetic):
    x, y = synthetic
    layers, hist = train(x, y, epochs=2, verbose=False, dtype=np.float64)
    assert all(w.dtype == np.float64 for w, b in layers)
    # loss finita e na precisão nativa (não vira NaN/inf em double)
    assert np.isfinite(mse(forward(x, layers), y))


def test_mse_float64_enxerga_1e40():
    """Em float32, (1e-20)^2 = 1e-40 arredonda para 0; float64 conserva."""
    d = mse(np.array([1e-20], dtype=np.float64), np.zeros(1, dtype=np.float64))
    assert d == pytest.approx(1e-40, rel=0.01)


def test_forward_herdando_dtype_dos_pesos():
    rng = np.random.default_rng(1)
    for dt in (np.float32, np.float64):
        layers = init_layers(rng, dtype=dt)
        out = forward(np.zeros((4, 13)), layers)
        assert out.dtype == dt


def test_meta_dtype_so_quando_float64():
    m32 = model_meta(epochs=1, samples=10, loss=0.01)
    m64 = model_meta(epochs=1, samples=10, loss=0.01, dtype="float64")
    assert "dtype" not in m32          # JSON canonical float32 fica igual
    assert m64["dtype"] == "float64"
