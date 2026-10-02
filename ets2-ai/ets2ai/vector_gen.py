"""Vectorized batch data generator (v0.4.4).

Same expert law as ets2ai/sim.py (pure-pursuit + predictive speed + dock
profile + radar braking), but simulates B trucks on B independent roads in
parallel with numpy — orders of magnitude more samples/s than the scalar
sim. This is what makes "billions of samples" a streaming reality instead
of a 128 GB impossibility: samples are generated on the fly, all unique.

State is path-relative (s, offset, heading_error, speed) — an exact
reformulation of the scalar (x, y, heading)+projection loop while
|offset| (<= 4.6 m) is far below the curve radius (>= 83 m).

Used by `train.py --stream-samples` and by the Kaggle kernel (2x T4).
"""
import numpy as np

# ---- physics (identical to sim.py) ----
DT = 0.1
WHEELBASE = 4.0
MAX_STEER = 0.6
MAX_ACCEL = 1.8
MAX_BRAKE = 3.2
DRAG = 0.030
LAT_ACCEL_ROLLOVER = 3.6
ROLLOVER_MARGIN = 0.82
V_MAX = 36.0
RADAR_SLOW = 0.95
RADAR_BRAKE = 2.6
SPEED_LIMIT = 25.0
PURE_PURSUIT_D = 12.0
LOOKAHEAD = (8.0, 18.0, 40.0, 90.0, 170.0)
FUEL_BURN_IDLE = 0.000012
FUEL_BURN_FULL = 0.000160
FATIGUE_RATE = 1.0 / (11 * 3600)
DOCK_DECEL = 1.6
DOCK_LINE = 6.0          # stop line: length - 6 m
OVERSAMPLE_DOCK_M = 150.0
OVERSAMPLE_REPS = 4      # matches data.py _oversample_dock

# ---- vector roads ----
SEG_LEN = 150.0
N_SEG = 72               # ~10.8 km routes (scalar avg ~9.6 km)
MAX_CURV = 0.012
P_STRAIGHT = 0.35
N_RADARS = 8

CHUNK_ROWS = 262_144     # rows per yielded chunk (~16 MB float32)


def _make_roads(rng, n):
    """Vector roads: curvature (n, N_SEG), radar positions (n, N_RADARS)."""
    curv = rng.uniform(-MAX_CURV, MAX_CURV, (n, N_SEG)).astype(np.float64)
    straight = rng.random((n, N_SEG)) < P_STRAIGHT
    curv[straight] = 0.0
    # radars: first at 700 m, then every U(1500, 2800) — like sim.py
    radars = np.full((n, N_RADARS), np.inf)
    pos = np.full(n, 700.0)
    for r in range(N_RADARS):
        radars[:, r] = pos
        pos = pos + rng.uniform(1500.0, 2800.0, n)
    length = SEG_LEN * N_SEG
    radars[radars > length - 150.0] = np.inf
    return curv, radars, length


def _speed_profile(curv):
    """Allowed speed at each segment START, planning against curves the way
    the scalar expert does: only within its ~260 m lookahead horizon
    (upcoming_curves max_dist). With SEG_LEN=150 that is the next 2 segments."""
    a_lat = LAT_ACCEL_ROLLOVER * ROLLOVER_MARGIN
    with np.errstate(divide="ignore"):
        vc = np.where(np.abs(curv) > 1e-6,
                      np.sqrt(a_lat / np.maximum(np.abs(curv), 1e-9)), V_MAX)
    vc = np.minimum(vc, V_MAX)
    vs = vc.copy()
    # constraint from the NEXT segment's start (150 m away, 12 m brake margin)
    nxt = np.sqrt(np.pad(vc, ((0, 0), (0, 1)), mode="edge")[:, 1:] ** 2
                  + 2.0 * RADAR_BRAKE * max(0.0, SEG_LEN - 12.0))
    vs = np.minimum(vs, nxt)
    return vs


class _Fleet:
    """B trucks stepping in lockstep on B roads."""

    def __init__(self, rng, n):
        self.n = n
        self.curv, self.radars, self.length = _make_roads(rng, n)
        self.vs = _speed_profile(self.curv)
        self.reset(rng)

    def reset(self, rng):
        n = self.n
        # posicoes iniciais ALEATORIAS ao longo da estrada: a frota fica
        # permanentemente misturada (como episodios independentes do escalar)
        self.s = rng.uniform(5.0, self.length - 600.0, n)
        self.offset = rng.uniform(-2.0, 2.0, n)
        idx = np.clip((self.s / SEG_LEN).astype(np.int64), 0, N_SEG - 1)
        v_allow0 = self.vs[np.arange(n), idx]
        self.speed = np.minimum(rng.uniform(8.0, 22.0, n), v_allow0)
        self.hdg_err = rng.uniform(-0.25, 0.25, n)
        self.steer_pos = np.zeros(n)
        self.fuel = np.ones(n)
        self.fatigue = np.zeros(n)

    def _kappa_at(self, s):
        idx = np.clip((s / SEG_LEN).astype(np.int64), 0, N_SEG - 1)
        return self.curv[np.arange(self.n), idx], idx

    def step_expert(self):
        """One DT step: expert actions + GOVERNOR overlay + truck physics.
        (v0.4.4: o dataset escalar grava acoes POS-governador — freios fortes
        das curvas/radares/dock. Sem esse overlay a rede profunda nao quebra
        o platou de 'prever a media'.) Returns (feats, governed_acts)."""
        n = self.n
        ar = np.arange(n)
        k_now, idx = self._kappa_at(self.s)
        # --- pure pursuit steering ---
        alpha = np.arctan2(-self.offset, PURE_PURSUIT_D) - self.hdg_err
        steer = np.clip(2.0 * np.sin(alpha), -1.0, 1.0)
        # --- speed target: curves (backward profile), dock, radar, fatigue ---
        seg_start = idx * SEG_LEN
        v_next = self.vs[ar, np.minimum(idx + 1, N_SEG - 1)]
        d_next = seg_start + SEG_LEN - self.s
        v_allow = np.sqrt(v_next ** 2 + 2.0 * RADAR_BRAKE * np.maximum(0.0, d_next - 12.0))
        a_lat = LAT_ACCEL_ROLLOVER * ROLLOVER_MARGIN
        v_curve_now = np.where(np.abs(k_now) > 1e-6,
                               np.sqrt(a_lat / np.maximum(np.abs(k_now), 1e-9)), V_MAX)
        v_target = np.minimum(np.minimum(V_MAX, v_curve_now), v_allow)
        # dock profile
        d_dock = (self.length - DOCK_LINE) - self.s
        v_target = np.minimum(v_target, np.sqrt(2.0 * DOCK_DECEL * np.maximum(0.0, d_dock)))
        # radar
        d_radar = np.min(np.where(self.radars > self.s[:, None],
                                  self.radars - self.s[:, None], np.inf), axis=1)
        d_radar = np.minimum(d_radar, 500.0)
        v_radar = SPEED_LIMIT * RADAR_SLOW
        brake_dist = np.maximum(0.0, self.speed ** 2 - v_radar ** 2) / (2.0 * RADAR_BRAKE) + 25.0
        v_target = np.where(d_radar < brake_dist, np.minimum(v_target, v_radar), v_target)
        # fatigue easing
        v_target = v_target * (1.0 - 0.08 * self.fatigue)
        v_target = np.where(v_target < 0.4, 0.0, v_target)
        dv = v_target - self.speed
        throttle = np.clip(dv / 1.8, 0.0, 1.0)
        brake = np.clip(-dv / 2.6, 0.0, 1.0)
        # --- features (contract, in order) ---
        feats = np.empty((n, 13))
        feats[:, 0] = self.speed / 25.0
        feats[:, 1] = self.offset / 3.5
        feats[:, 2] = self.hdg_err / 0.6
        for j, d in enumerate(LOOKAHEAD):
            feats[:, 3 + j] = self._kappa_at(self.s + d)[0] / 0.05
        feats[:, 8] = SPEED_LIMIT / 25.0
        feats[:, 9] = self.fuel
        feats[:, 10] = self.fatigue
        feats[:, 11] = np.minimum((self.length - self.s) / 1000.0, 20.0) / 20.0
        feats[:, 12] = d_radar / 500.0
        # --- governor overlay (mirrors sim.governor; MAX_BRAKE budget) ---
        # curve starts within 260 m: current seg, next, next-next
        worst_gov = np.full(n, np.inf)
        for off in (0, 1, 2):
            j = np.clip(idx + off, 0, N_SEG - 1)
            k = self.curv[ar, j]
            d = np.maximum(0.0, j * SEG_LEN - self.s)
            ok = (np.abs(k) > 1e-6) & (d <= 260.0)
            vc = np.sqrt(a_lat / np.maximum(np.abs(k), 1e-9))
            va = np.sqrt(vc ** 2 + 2.0 * MAX_BRAKE * np.maximum(0.0, d - 8.0))
            worst_gov = np.where(ok, np.minimum(worst_gov, va), worst_gov)
        # dock governor
        v_allow_dock = np.sqrt(2.0 * MAX_BRAKE * np.maximum(0.0, d_dock - 2.0))
        full_brake = ((worst_gov < np.inf) & (self.speed > worst_gov + 0.3)) \
            | ((d_dock > 0) & (d_dock < 600.0) & (self.speed > v_allow_dock + 0.3))
        hold = (d_dock > 0) & (d_dock <= 1.5)
        creep = (d_dock > 0) & (d_dock < 600.0) & (self.speed < 2.0)
        anti_stall = (self.speed < 0.6) & (d_dock > 4.0)
        g_steer = steer
        g_throttle = np.where(full_brake | hold, 0.0, throttle)
        g_brake = np.where(full_brake | hold, 1.0, brake)
        g_throttle = np.where(creep | anti_stall, np.maximum(g_throttle, 0.35), g_throttle)
        g_brake = np.where(creep | anti_stall, 0.0, g_brake)
        acts = np.stack([g_steer, g_throttle, g_brake], axis=1)
        # --- truck physics (path-relative, same law as Truck.step) ---
        steer_cmd, throttle, brake = g_steer, g_throttle, g_brake
        self.steer_pos += np.clip(steer_cmd - self.steer_pos, -0.15, 0.15)
        wheel = self.steer_pos * MAX_STEER
        self.hdg_err += (self.speed / WHEELBASE) * np.tan(wheel) * DT \
            - self.speed * np.cos(self.hdg_err) * k_now * DT
        self.offset += self.speed * np.sin(self.hdg_err) * DT
        self.s += self.speed * np.cos(self.hdg_err) * DT
        self.speed = np.maximum(0.0, self.speed +
                                (throttle * MAX_ACCEL - brake * MAX_BRAKE
                                 - DRAG * self.speed) * DT)
        self.fuel = np.maximum(0.0, self.fuel - DT *
                               (FUEL_BURN_IDLE + throttle * (FUEL_BURN_FULL - FUEL_BURN_IDLE)))
        self.fatigue = np.minimum(1.0, self.fatigue + DT * FATIGUE_RATE)
        return feats, acts

    def alive(self):
        return (self.s < self.length - DOCK_LINE) & (np.abs(self.offset) <= 4.6)


def stream(seed, n_trucks=3072, dtype=np.float32):
    """Yields (x, y) chunks of fresh expert demonstrations, forever.
    Deterministic under `seed`. All samples unique (roads regenerate)."""
    rng = np.random.default_rng(seed)
    fleet = _Fleet(rng, n_trucks)
    buf_x, buf_y = [], []
    rows = 0
    while True:
        feats, acts = fleet.step_expert()
        alive = fleet.alive()
        if alive.any():
            fx, ay = feats[alive], acts[alive]
            dock_mask = ((fleet.length - DOCK_LINE) - fleet.s[alive]) < OVERSAMPLE_DOCK_M
            if dock_mask.any():
                fx = np.concatenate([fx] + [fx[dock_mask]] * (OVERSAMPLE_REPS - 1))
                ay = np.concatenate([ay] + [ay[dock_mask]] * (OVERSAMPLE_REPS - 1))
            buf_x.append(fx.astype(dtype))
            buf_y.append(ay.astype(dtype))
            rows += len(fx)
        if (~alive).any():
            # restart the finished trucks at random positions (mixed fleet)
            done = np.where(~alive)[0]
            r2 = np.random.default_rng(rng.integers(0, 2**63))
            fleet.s[done] = r2.uniform(5.0, fleet.length - 600.0, len(done))
            fleet.offset[done] = r2.uniform(-2.0, 2.0, len(done))
            idx = np.clip((fleet.s[done] / SEG_LEN).astype(np.int64), 0, N_SEG - 1)
            fleet.speed[done] = np.minimum(r2.uniform(8.0, 22.0, len(done)),
                                           fleet.vs[done, idx])
            fleet.hdg_err[done] = r2.uniform(-0.25, 0.25, len(done))
            fleet.steer_pos[done] = 0.0
            fleet.fuel[done] = 1.0
            fleet.fatigue[done] = 0.0
            # fresh roads for the restarted trucks
            c2, r2r, _ = _make_roads(np.random.default_rng(rng.integers(0, 2**63)), len(done))
            fleet.curv[done] = c2
            fleet.radars[done] = r2r
            fleet.vs[done] = _speed_profile(c2)
        if rows >= CHUNK_ROWS:
            yield np.concatenate(buf_x), np.concatenate(buf_y)
            buf_x, buf_y, rows = [], [], 0


def val_set(seed=999, n_trucks=384, max_rows=131072, dtype=np.float32):
    """Fixed validation set from a held-out stream (different seed)."""
    gen = stream(seed, n_trucks=n_trucks, dtype=dtype)
    x, y = next(gen)
    return x[:max_rows], y[:max_rows]
