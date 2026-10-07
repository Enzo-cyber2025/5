"""Testes da destilacao (rede nano p/ IA no PC fraco).

A nano imita a rede oficial na MESMA distribuicao de treino (vector_gen) e so
e publicada se passar os gates de fidelidade (distill.gate). Aqui usamos um
professor TOY (arquitetura pequena, aleatoria) para provar:
  - determinismo (mesma semente => mesmos pesos, bit a bit);
  - fidelidade razoavel ate num toy (o aluno segue o professor);
  - gates aceitam relatorio bom e rejeitam ruim;
  - roundtrip save/load dos pesos da nano.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ets2ai import contract, distill as D
from ets2ai.contract import N_IN, N_OUT, load_weights, save_weights
from ets2ai.model import forward


def _toy_teacher():
    """Professor pequeno ([24, 24]) com a MESMA init He do projeto."""
    return D._init_student([24, 24], seed=1234)


def test_distill_quick_deterministic():
    teacher = _toy_teacher()
    s1, r1 = D.distill(teacher, quick=True)
    s2, r2 = D.distill(teacher, quick=True)
    assert len(s1) == len(D.QUICK["hidden"]) + 1
    for (w1, b1), (w2, b2) in zip(s1, s2):
        assert np.array_equal(w1, w2) and np.array_equal(b1, b2), \
            "destilacao deve ser deterministica (semente fixa)"
    assert r1["mse_stream"] == pytest.approx(r2["mse_stream"])
    # fidelidade: aluno TOY tem que seguir o professor TOY razoavelmente
    assert r1["mse_stream"] < 0.05, r1["mse_stream"]


def test_distill_report_and_gate():
    teacher = _toy_teacher()
    _student, rep = D.distill(teacher, quick=True)
    for k in ("mse_stream", "p999_steer_stream", "max_dsteer_stream",
              "sign_ok_stream", "mse_box_real", "sign_ok_box",
              "closed_loop_equiv", "closed_loop_quality",
              "mse_vs_expert_teacher", "mse_vs_expert_nano"):
        assert k in rep, k

    # gate: relatorio bom passa
    good = dict(rep)
    good.update(mse_stream=0.001, p999_steer_stream=0.1,
                mse_box_real=0.01, sign_ok_stream=1.0, sign_ok_box=1.0,
                closed_loop_equiv=True, closed_loop_quality=True)
    ok, reasons = D.gate(good)
    assert ok, reasons

    # cada criterio ruim reprova (e o motivo nomea o criterio)
    bads = [
        dict(mse_stream=1.0), dict(p999_steer_stream=1.0),
        dict(mse_box_real=1.0), dict(sign_ok_stream=0.5),
        dict(sign_ok_box=0.5), dict(closed_loop_equiv=False),
        dict(closed_loop_quality=False),
    ]
    for bad in bads:
        b = dict(good)
        b.update(bad)
        ok, reasons = D.gate(b)
        assert not ok and reasons, bad


def test_nano_roundtrip_save_load(tmp_path):
    teacher = _toy_teacher()
    student, _rep = D.distill(teacher, quick=True)
    meta = {"features": contract.FEATURES, "actions": contract.ACTIONS,
            "hidden": D.QUICK["hidden"], "seed": D.NANO_SEED, "nano": True,
            "final_loss": 0.001}
    p = tmp_path / "model-nano.json"
    save_weights(p, student, meta)
    layers2, meta2 = load_weights(p)
    x = np.random.default_rng(7).uniform(-1, 1, (32, N_IN)).astype(np.float32)
    assert np.allclose(forward(x, student), forward(x, layers2), atol=1e-6)
    assert meta2["nano"] is True and meta2["hidden"] == D.QUICK["hidden"]


def test_nano_hidden_e_menor_que_oficial():
    n_official = sum(w.size + b.size for w, b in D._init_student(
        contract.HIDDEN, seed=1))
    n_nano = sum(w.size + b.size for w, b in D._init_student(
        D.NANO_HIDDEN, seed=1))
    assert n_nano * 20 < n_official, \
        "nano deve ser >20x menor que a oficial (caber no cache do N5030)"
