"""DAgger/finetune pipeline tests.

Simulates exactly what the bridge --record mode produces (ets2ai-rec,v1 CSV:
normalized features + commands + override flag + source tag) and verifies the
finetune gates and that committed weights are never touched.
"""
import hashlib
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ets2ai import finetune                                  # noqa: E402
from ets2ai.sim import Road, expert, run_episode             # noqa: E402


def _write_recording(path, seed, noise=0.03, n_override=25):
    """Expert run -> recording file in the bridge --record format."""
    road = Road.random(seed)
    feats, acts, _ = run_episode(
        road,
        lambda r, t, j, rng: expert(r, t, j, noise=noise, rng=rng),
        seed=seed, record=True, max_steps=2500)
    lines = [finetune.REC_HEADER]
    for i, (f, a) in enumerate(zip(feats, acts)):
        override = 1 if i < n_override else 0
        src = "H" if override else "L"
        vals = [f"{v:.6f}" for v in f] + [f"{v:.6f}" for v in a] + [str(override), src]
        lines.append(",".join(vals))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(feats)


def test_load_recordings_override_weight(tmp_path):
    p = tmp_path / "rec.csv"
    n = _write_recording(p, seed=60601, n_override=25)
    x, y = finetune.load_recordings([p], override_weight=1)
    assert x.shape == (n, 13) and y.shape == (n, 3)
    x3, _ = finetune.load_recordings([p], override_weight=3)
    # 25 override rows duplicated 3x -> +50 extra rows
    assert x3.shape[0] == n + 50
    # features normalizadas dentro do range do contrato
    assert float(x[:, 0].min()) >= 0.0 and float(x[:, 0].max()) <= 1.5


def test_finetune_gates_and_no_side_effects(tmp_path):
    art = ROOT / "artifacts" / "model-weights.json"
    before = hashlib.sha256(art.read_bytes()).hexdigest()

    rec1 = tmp_path / "sessao1.csv"
    rec2 = tmp_path / "sessao2.csv"
    n1 = _write_recording(rec1, seed=60601)
    n2 = _write_recording(rec2, seed=60602)
    assert n1 > 500 and n2 > 500

    # lr gentil: bases fortes (12,5+ bi de amostras) degradam com lr 5e-4
    # em 30 epocas — o gate de circuito fechado corretamente recusa; a
    # receita realista para o teste da mecanica e 1e-4.
    gates = finetune.run([rec1, rec2], epochs=30, lr=1e-4, out=tmp_path / "ft",
                         base_weights=art)

    assert gates["mse_gate"] is True
    assert gates["mse_val_recording"] <= 0.150
    assert gates["closed_loop_gate"] is True
    assert gates["all_pass"] is True
    assert gates["finish_rate"] >= 0.75 and gates["in_lane_pct"] > 0.95

    # artefatos de saida existem; pesos commitados intocados
    assert (tmp_path / "ft" / "model-weights-finetuned.json").exists()
    assert (tmp_path / "ft" / "metrics-finetune.json").exists()
    after = hashlib.sha256(art.read_bytes()).hexdigest()
    assert before == after


def test_rejects_garbage_recording(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("outra,coisa\n1,2,3\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        finetune.load_recordings([bad])
