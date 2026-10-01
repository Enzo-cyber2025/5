"""Mission interaction gates: delivery dialog + random skill pick."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ets2ai import mission                            # noqa: E402


def test_delivery_dialog_selects_the_right_option():
    idx = mission.delivery_selection()
    assert idx == 1
    assert mission.DELIVERY_DIALOG[idx] == "Onde você precisa dele?"
    # tolerante a variacoes do jogo, sem depender de posicao fixa
    shuffled = ["Cancelar", "Entregar no pátio", "Onde você precisa dele?"]
    assert mission.delivery_selection(shuffled) == 2


def test_menu_key_sequence_navigates_then_confirms():
    assert mission.menu_key_sequence(0) == ["ok"]
    assert mission.menu_key_sequence(1) == ["down", "ok"]
    assert mission.menu_key_sequence(2) == ["down", "down", "ok"]


def test_skill_pick_is_random_but_reproducible():
    a = mission.pick_random_skill(np.random.default_rng(7))
    b = mission.pick_random_skill(np.random.default_rng(7))
    assert a == b                                  # mesma semente, mesma escolha
    picks = {mission.pick_random_skill(np.random.default_rng(k)) for k in range(30)}
    assert all(0 <= p < len(mission.SKILLS) for p in picks)
    assert len(picks) > 1                          # varia com a semente (aleatorio)
    assert all(s in mission.SKILLS for s in mission.SKILLS)
