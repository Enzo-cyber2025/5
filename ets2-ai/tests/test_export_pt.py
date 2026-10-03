"""Export .pt (PyTorch TorchScript): paridade com numpy e auto-contido.

Pula automaticamente quando o torch nao esta instalado (o CI nao o instala;
o .pt e um artefato opcional de conveniencia, gerado localmente/na release).
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("torch")

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = ROOT / "artifacts" / "model-weights.json"


@pytest.fixture(scope="module")
def pt_path(tmp_path_factory):
    out = tmp_path_factory.mktemp("pt") / "ets2ai-test.pt"
    subprocess.run(
        [sys.executable, "-m", "ets2ai.export_pt",
         "--weights", str(WEIGHTS), "--out", str(out)],
        cwd=ROOT, check=True, capture_output=True,
    )
    return out


def test_pt_e_auto_contido_e_possui_meta(pt_path):
    import torch
    m = torch.jit.load(str(pt_path))
    assert m.n_params == 1017613
    assert m.loss < 0.06          # cabecalho do proprio arquivo (verificado no export)
    assert len(m.features) == 13 and "radar_dist" in m.features
    assert list(m.actions) == ["steer", "throttle", "brake"]


def test_pt_paridade_com_numpy(pt_path):
    import torch
    from ets2ai.model import forward

    m = torch.jit.load(str(pt_path)); m.eval()
    data = json.loads(WEIGHTS.read_text())
    layers = [(np.asarray(l["w"], np.float32), np.asarray(l["b"], np.float32))
              for l in data["layers"]]

    rng = np.random.default_rng(3)
    x = np.clip((rng.standard_normal((512, 13)) * 1.5).astype(np.float32),
                -2.0, 2.0)          # faixa do contrato (ver export_pt.py)
    ref = forward(x, layers)
    with torch.no_grad():
        got = m(torch.from_numpy(x)).numpy()
    assert np.abs(ref - got).max() < 5e-5
