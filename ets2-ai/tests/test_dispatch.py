"""Dispatcher tests: best-route choice + offer economics (company layer)."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ets2ai import dispatch                         # noqa: E402
from ets2ai.sim import Road                         # noqa: E402


def _rng(seed=42):
    return np.random.default_rng(seed)


def test_offer_economics():
    rng = _rng()
    best, offers = dispatch.pick_best(rng, Road, n=3)
    assert len(offers) == 3
    # score = max among offers (it really picked the best)
    assert best.score == max(o.score for o in offers)
    # economics consistent: pay >= net (costs never add money)
    for o in offers:
        assert o.pay_eur >= o.net_eur
        assert o.fuel_stops >= 0 and o.sleep_stops >= 0
        assert 5.0 < o.km < 12.0            # road generator range
    # deterministic for the same seed
    rng2 = _rng(42)
    best2, _ = dispatch.pick_best(rng2, Road, n=3)
    assert best2.road_seed == best.road_seed


def test_score_prefers_straight_over_curvy_at_same_pay():
    a = dispatch.score_offer(100.0, 10.0, 0, 0, 0.000)
    b = dispatch.score_offer(100.0, 10.0, 0, 0, 0.010)
    assert a > b


def test_score_counts_costs():
    free = dispatch.score_offer(100.0, 10.0, 0, 0, 0.0)
    costly = dispatch.score_offer(100.0, 10.0, 1, 1, 0.0)
    assert free > costly
    # um abastecimento (745 EUR) pesa mais que um hotel (220 EUR)
    hotel = dispatch.score_offer(100.0, 10.0, 0, 1, 0.0)
    assert costly < hotel < free
