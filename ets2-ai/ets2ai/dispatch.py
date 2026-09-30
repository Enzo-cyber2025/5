"""Job dispatcher / company management (mirrored in Dispatcher.java).

Chooses the best job among generated offers, the way a profitable haulage
company would: net EUR per km after fuel and mandatory rests, penalised by
route curviness (curvy roads are slower -> worse EUR/hour).

Deterministic given the RNG; same formulas/constants as the Android port.
"""
import math

FUEL_STOP_EUR = 745.0        # full 600 L tank at 1.45 EUR/L
FUEL_RANGE_KM = 1500.0       # km per full tank (~29 L/100 km real-world truck)
REST_EVERY_KM = 900.0        # 11 h driving at ~65 km/h average
HOTEL_EUR = 220.0
EUR_PER_KM_MIN = 9.0
EUR_PER_KM_MAX = 14.0
CURVE_PENALTY = 8.0          # weight of mean |curvature| in the score


class Offer:
    def __init__(self, road_seed, km, pay_eur, fuel_stops, sleep_stops,
                 mean_abs_curv, score):
        self.road_seed = road_seed
        self.km = km
        self.pay_eur = pay_eur
        self.fuel_stops = fuel_stops
        self.sleep_stops = sleep_stops
        self.mean_abs_curv = mean_abs_curv
        self.score = score

    @property
    def net_eur(self):
        return (self.pay_eur - self.fuel_stops * FUEL_STOP_EUR
                - self.sleep_stops * HOTEL_EUR)

    @property
    def label(self):
        return (f"{self.km:.1f} km, {self.pay_eur:.0f} EUR "
                f"({self.net_eur / max(self.km, 0.1):.1f} EUR/km liq.)")


def score_offer(pay_eur, km, fuel_stops, sleep_stops, mean_abs_curv):
    net = pay_eur - fuel_stops * FUEL_STOP_EUR - sleep_stops * HOTEL_EUR
    return net / (max(km, 0.1) * (1.0 + CURVE_PENALTY * mean_abs_curv))


def generate_offers(rng, road_cls, n=3):
    """road_cls: the Road class (sim.Road or a stub with .random(seed))."""
    offers = []
    for _ in range(n):
        seed = int(rng.integers(1, 2 ** 31 - 1))
        road = road_cls.random(seed)
        km = road.length / 1000.0
        pay = (EUR_PER_KM_MIN + rng.random() * (EUR_PER_KM_MAX - EUR_PER_KM_MIN)) * km
        fuel_stops = math.ceil(km / FUEL_RANGE_KM)
        sleep_stops = math.ceil(km / REST_EVERY_KM)
        curv = sum(abs(c) for c in road.seg_curvs) / len(road.seg_curvs)
        offers.append(Offer(seed, km, pay, fuel_stops, sleep_stops, curv,
                            score_offer(pay, km, fuel_stops, sleep_stops, curv)))
    return offers


def pick_best(rng, road_cls, n=3):
    offers = generate_offers(rng, road_cls, n)
    best = max(offers, key=lambda o: o.score)
    return best, offers
