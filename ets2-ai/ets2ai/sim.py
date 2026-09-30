"""ETS2-AI world model: road, truck physics, expert driver, career rules.

Deterministic, dependency-light, ported 1:1 to Java (SimWorld.java) and to the
Windows bridge demo so that the phone, the PC and the trainer all agree on
physics and the expert never disagrees with itself.
"""
import math
import numpy as np

DT = 0.1                 # simulation step (s)
WHEELBASE = 4.0          # m (kinematic bicycle)
MAX_STEER = 0.6          # rad at the wheels, scaled by |steer| command
MAX_ACCEL = 1.3          # m/s^2 at full throttle
MAX_BRAKE = 3.2          # m/s^2 at full brake
DRAG = 0.045             # rolling/aero deceleration factor per (m/s)
LAT_ACCEL_COMFORT = 2.4  # m/s^2 the expert accepts in curves
LANE_HALF = 2.0          # |offset| beyond this = off-lane
ROAD_HALF = 4.6          # |offset| beyond this = off-road (crash barrier)

FUEL_START = 1.0
FUEL_BURN_IDLE = 0.000012      # per second
FUEL_BURN_FULL = 0.000160      # per second at full throttle
FATIGUE_START = 0.0
FATIGUE_RATE = 1.0 / (11 * 3600)   # ~11 h of driving to full fatigue
REFUEL_BELOW = 0.14
SLEEP_ABOVE = 0.82
FUEL_PRICE = 1.45              # EUR / L  (tank modelled as fraction)
TANK_LITERS = 600
SLEEP_HOURS = 9
SPEED_LIMIT_MPS = 25.0         # 90 km/h truck limit

LOOKAHEAD = (8.0, 18.0, 30.0, 45.0, 60.0)
PURE_PURSUIT_DIST = 12.0


# ---------------------------------------------------------------------------
# Road: piecewise-constant-curvature ribbon, seeded deterministically.
# ---------------------------------------------------------------------------
class Road:
    def __init__(self, seg_lengths, seg_curvs):
        self.seg_lengths = [float(v) for v in seg_lengths]
        self.seg_curvs = [float(v) for v in seg_curvs]
        self.cum = [0.0]
        for L in self.seg_lengths:
            self.cum.append(self.cum[-1] + L)
        self.length = self.cum[-1]
        # integrate centreline
        pts = [(0.0, 0.0)]
        hdg = 0.0
        step = 2.0
        s = 0.0
        self.samples = [pts[0]]
        self.sample_s = [0.0]
        while s < self.length:
            s = min(s + step, self.length)
            hdg += self.curvature_at(s) * step
            x, y = self.samples[-1]
            self.samples.append((x + step * math.cos(hdg),
                                 y + step * math.sin(hdg)))
            self.sample_s.append(s)

    @staticmethod
    def random(seed, n_seg=40, min_len=60.0, max_len=260.0, max_curv=0.012):
        rng = np.random.default_rng(seed)
        lens = rng.uniform(min_len, max_len, n_seg)
        curvs = []
        for _ in range(n_seg):
            r = rng.uniform()
            if r < 0.35:                    # straight
                curvs.append(0.0)
            else:
                curvs.append(float(rng.uniform(-max_curv, max_curv)))
        return Road(lens, curvs)

    def curvature_at(self, s):
        s = max(0.0, min(s, self.length - 1e-6))
        for i, L in enumerate(self.seg_lengths):
            if s <= self.cum[i + 1] + 1e-9:
                return self.seg_curvs[i]
        return 0.0

    def project(self, x, y, hint=None):
        """Closest centreline sample -> (s, offset, tangent_heading).

        `hint`: last sample index; searches a local window first (the truck
        moves a few metres per step). Falls back to a full scan. Same
        behaviour in the Java port.
        """
        samples = self.samples
        n = len(samples)
        if hint is not None:
            lo, hi = max(0, hint - 40), min(n, hint + 40)
            best_i, best_d2 = None, float("inf")
            for i in range(lo, hi):
                px, py = samples[i]
                d2 = (px - x) ** 2 + (py - y) ** 2
                if d2 < best_d2:
                    best_i, best_d2 = i, d2
            if best_i is not None and best_d2 < (30.0 ** 2):
                return self._project_at(best_i, x, y)
        best_i, best_d2 = 0, float("inf")
        for i, (px, py) in enumerate(samples):
            d2 = (px - x) ** 2 + (py - y) ** 2
            if d2 < best_d2:
                best_i, best_d2 = i, d2
        return self._project_at(best_i, x, y)

    def _project_at(self, best_i, x, y):
        s = self.sample_s[best_i]
        i0 = max(0, best_i - 2)
        i1 = min(len(self.samples) - 1, best_i + 2)
        tx = self.samples[i1][0] - self.samples[i0][0]
        ty = self.samples[i1][1] - self.samples[i0][1]
        tn = math.hypot(tx, ty) or 1.0
        tx, ty = tx / tn, ty / tn
        dx, dy = x - self.samples[best_i][0], y - self.samples[best_i][1]
        offset = dx * -ty + dy * tx
        return s, offset, math.atan2(ty, tx)


# ---------------------------------------------------------------------------
# Truck state + physics step (identical in Java/Python).
# ---------------------------------------------------------------------------
class Truck:
    def __init__(self, road, s=0.0, offset=0.0, speed=15.0, heading=None):
        self.s = s
        self._hint = 0
        x, y, th = road_point(road, s)
        # start on the lane line given by offset (positive = right of centre)
        self.x = x - offset * math.sin(th)
        self.y = y + offset * math.cos(th)
        self.s, self.offset, self.tangent = self.project(road)
        self.heading = self.tangent if heading is None else heading
        self.speed = speed
        self.steer_pos = 0.0  # smoothed actual steering, for features
        self.fuel = FUEL_START
        self.fatigue = FATIGUE_START
        self.money = 0.0
        self.driven_km = 0.0

    def project(self, road):
        """Fast re-projection using a moving window (kept in Java too)."""
        samples = road.samples
        n = len(samples)
        best_i, best_d2 = self._hint, float("inf")
        for i in range(max(0, self._hint - 40), min(n, self._hint + 40)):
            px, py = samples[i]
            d2 = (px - self.x) ** 2 + (py - self.y) ** 2
            if d2 < best_d2:
                best_i, best_d2 = i, d2
        if best_d2 > 30.0 ** 2:
            return road.project(self.x, self.y)   # full scan fallback
        self._hint = best_i
        return road._project_at(best_i, self.x, self.y)

    def step(self, road, steer, throttle, brake, dt=DT):
        steer = max(-1.0, min(1.0, steer))
        throttle = max(0.0, min(1.0, throttle))
        brake = max(0.0, min(1.0, brake))
        # steering actuator: rack moves toward command
        self.steer_pos += max(-0.15, min(0.15, steer - self.steer_pos))
        wheel = self.steer_pos * MAX_STEER
        self.heading += (self.speed / WHEELBASE) * math.tan(wheel) * dt
        self.x += self.speed * math.cos(self.heading) * dt
        self.y += self.speed * math.sin(self.heading) * dt
        acc = throttle * MAX_ACCEL - brake * MAX_BRAKE - DRAG * self.speed
        self.speed = max(0.0, self.speed + acc * dt)
        self.driven_km += self.speed * dt / 1000.0
        self.fuel = max(0.0, self.fuel - dt *
                        (FUEL_BURN_IDLE + throttle * (FUEL_BURN_FULL - FUEL_BURN_IDLE)))
        self.fatigue = min(1.0, self.fatigue + dt * FATIGUE_RATE)
        self.s, self.offset, self.tangent = self.project(road)


def road_point(road, s):
    """(x, y, heading) of centreline near arclength s (nearest sample)."""
    i = min(range(len(road.sample_s)), key=lambda k: abs(road.sample_s[k] - s))
    th = heading_at(road, i)
    x, y = road.samples[i]
    return x, y, th


def heading_at(road, i):
    i0, i1 = max(0, i - 1), min(len(road.samples) - 1, i + 1)
    return math.atan2(road.samples[i1][1] - road.samples[i0][1],
                      road.samples[i1][0] - road.samples[i0][0])


# ---------------------------------------------------------------------------
# Features / actions (the contract in numbers).
# ---------------------------------------------------------------------------
def features(road, truck, job_left_km):
    s, offset, tangent = truck.project(road)
    hdg_err = wrap_angle(truck.heading - tangent)
    curvs = [road.curvature_at(s + d) / 0.05 for d in LOOKAHEAD]
    return [
        truck.speed / 25.0,
        offset / 3.5,
        hdg_err / 0.6,
        curvs[0], curvs[1], curvs[2], curvs[3], curvs[4],
        SPEED_LIMIT_MPS / 25.0,
        truck.fuel,
        truck.fatigue,
        min(job_left_km, 100.0) / 100.0,
    ]


def wrap_angle(a):
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


# ---------------------------------------------------------------------------
# Expert driver: pure-pursuit steering + predictive speed control.
# ---------------------------------------------------------------------------
def expert(road, truck, job_left_km, noise=0.0, rng=None):
    s, offset, tangent = truck.project(road)
    tx, ty = math.cos(tangent), math.sin(tangent)
    d = PURE_PURSUIT_DIST
    gs = s + d
    gx = road_point(road, gs)[0] if gs <= road.length else None
    # target point on centreline ahead
    i = min(range(len(road.sample_s)), key=lambda k: abs(road.sample_s[k] - gs))
    px, py = road.samples[i]
    hdg_err = wrap_angle(truck.heading - tangent)
    lat_err = offset
    # pure pursuit: steer toward eliminating combined error
    alpha = math.atan2(-lat_err, d) - hdg_err
    steer = 2.0 * math.sin(alpha) / max(d, 1e-3) * 12.0
    steer = max(-1.0, min(1.0, steer))
    # speed target from upcoming curvature (worst within lookaheads)
    v_target = SPEED_LIMIT_MPS
    for dist in LOOKAHEAD:
        c = abs(road.curvature_at(s + dist))
        if c > 1e-6:
            v_target = min(v_target, math.sqrt(LAT_ACCEL_COMFORT / c))
    v_target = min(v_target, 25.0)
    # fatigue makes the expert ease off slightly (safe behaviour to imitate)
    v_target *= (1.0 - 0.08 * truck.fatigue)
    dv = v_target - truck.speed
    throttle = max(0.0, min(1.0, dv / 1.8))
    brake = max(0.0, min(1.0, -dv / 2.6))
    if noise and rng is not None:
        steer = max(-1.0, min(1.0, steer + rng.normal(0, noise)))
        throttle = max(0.0, min(1.0, throttle + rng.normal(0, noise * 0.5)))
        brake = max(0.0, min(1.0, brake + rng.normal(0, noise * 0.5)))
    return steer, throttle, brake


# ---------------------------------------------------------------------------
# Closed-loop episode runner (used for data generation AND evaluation).
# ---------------------------------------------------------------------------
def run_episode(road, policy, seed=0, max_steps=7000, noise=0.0,
                record=False, start_jitter=True):
    """policy(road, truck, job_left_km) -> (steer, throttle, brake)."""
    rng = np.random.default_rng(seed)
    if start_jitter:
        truck = Truck(road, s=5.0,
                      offset=float(rng.uniform(-2.0, 2.0)),
                      speed=float(rng.uniform(8.0, 22.0)))
        truck.heading += float(rng.uniform(-0.25, 0.25))
    else:
        truck = Truck(road, s=5.0, offset=0.0, speed=15.0)
    job_km = road.length / 1000.0
    feats, acts = [], []
    in_lane = off_road = 0
    stopped = False
    steps = 0
    while steps < max_steps:
        s, offset, _ = truck.project(road)
        if s >= road.length - 10.0:
            break
        job_left = max(0.0, (road.length - s) / 1000.0)
        steer, throttle, brake = policy(road, truck, job_left, rng)
        if record:
            feats.append(features(road, truck, job_left))
            acts.append([steer, throttle, brake])
        truck.step(road, steer, throttle, brake)
        steps += 1
        if abs(offset) < LANE_HALF:
            in_lane += 1
        if abs(offset) > ROAD_HALF or truck.speed < 0.3 and steps > 60:
            off_road += 1
            break
        # career rules (identical in the app): refuel / sleep
        if truck.fuel < REFUEL_BELOW:
            truck.fuel = 1.0
            truck.money -= FUEL_PRICE * TANK_LITERS * (1.0 - REFUEL_BELOW)
            stopped = True
        if truck.fatigue > SLEEP_ABOVE:
            truck.fatigue = 0.0
            truck.money -= 220.0  # hotel
            stopped = True
    km = truck.driven_km
    metrics = {
        "steps": steps,
        "in_lane_pct": in_lane / max(1, steps),
        "finished": steps < max_steps and km * 1000.0 >= road.length - 60.0,
        "km": km,
        "money": truck.money,
        "stopped_for_rules": stopped,
        "avg_speed": km / max(0.1, steps * DT) * 1000,
    }
    if record:
        return np.array(feats, dtype=np.float32), np.array(acts, dtype=np.float32), metrics
    return metrics
