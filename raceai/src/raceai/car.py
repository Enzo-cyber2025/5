"""Carros: especificação (mods em JSON) e modelo de física.

Modelo adotado: **bicicleta dinâmica** com pneus Pacejka simplificado,
transferência de carga longitudinal, downforce opcional e círculo de atrito
(combinando força longitudinal e lateral por eixo). Integração semi-implícita
a passo fixo (1/120 s por padrão) para ser determinística — requisito para
comparar gerações da evolução de forma justa.

Unidades: SI (m, s, kg, N, rad).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict

import numpy as np

G = 9.81

CAR_DEFAULTS = {
    "name": "Carro",
    "mass": 1200.0,          # kg
    "length": 4.2,           # m
    "width": 1.9,            # m
    "wheelbase": 2.60,       # m
    "cg_front": 1.25,        # distância CG -> eixo dianteiro
    "cg_height": 0.55,       # altura do CG
    "engine_force": 9000.0,  # N de força de tração máxima em baixa (nas rodas)
    "max_power": 120000.0,   # W de potência máxima (limita a força em alta)
    "brake_force": 13000.0,  # N de força de frenagem máxima
    "max_speed": 72.0,       # m/s (~260 km/h)
    "reverse_ratio": 0.30,   # fração da força do motor usada na ré
    "max_steer": 0.60,       # rad
    "steer_rate": 4.0,       # rad/s (velocidade do volante)
    "steer_falloff": 0.55,   # redução do esterço em alta velocidade (0..0.9)
    "grip_front": 1.45,      # coeficiente de atrito lateral dianteiro
    "grip_rear": 1.45,       # coeficiente de atrito lateral traseiro
    "tire_stiffness": 9.0,   # fator B do pneu (1/rad)
    "tire_shape": 1.45,      # fator C do pneu
    "drag": 0.42,            # coeficiente aerodinâmico (F = drag * v^2)
    "rolling": 26.0,         # resistência ao rolamento (F = rolling * v)
    "downforce": 0.0,        # F = downforce * v^2 (negativo = sustentação)
    "drive_front": 0.5,      # 0 = tração traseira, 1 = dianteira, 0.5 = integral
    "brake_front": 0.62,     # distribuição de frenagem
    "yaw_inertia": 1.05,     # fator multiplicador de Iz
    "body_color": "#e0483a",
    "accent_color": "#f5f5f5",
    "sprite": "",
}


@dataclass
class CarSpec:
    """Características de um carro (carregável de JSON = mods)."""
    id: str = "car"
    name: str = "Carro"
    mass: float = 1200.0
    length: float = 4.2
    width: float = 1.9
    wheelbase: float = 2.60
    cg_front: float = 1.25
    cg_height: float = 0.55
    engine_force: float = 9000.0
    max_power: float = 120000.0
    brake_force: float = 13000.0
    max_speed: float = 72.0
    reverse_ratio: float = 0.30
    max_steer: float = 0.60
    steer_rate: float = 4.0
    steer_falloff: float = 0.55
    grip_front: float = 1.45
    grip_rear: float = 1.45
    tire_stiffness: float = 9.0
    tire_shape: float = 1.45
    drag: float = 0.42
    rolling: float = 26.0
    downforce: float = 0.0
    drive_front: float = 0.5
    brake_front: float = 0.62
    yaw_inertia: float = 1.05
    body_color: str = "#e0483a"
    accent_color: str = "#f5f5f5"
    sprite: str = ""
    source: str = ""

    # ------------------------------------------------------------------ #
    @property
    def cg_rear(self) -> float:
        return max(0.4, self.wheelbase - self.cg_front)

    @property
    def iz(self) -> float:
        """Momento de inércia em guinada (aproximação de placa retangular)."""
        return self.mass * (self.length ** 2 + self.width ** 2) / 12.0 * self.yaw_inertia

    @property
    def power_to_weight(self) -> float:
        """W/kg — usado para resumos e para a IA não comparar carros injustamente."""
        return self.max_power / max(self.mass, 1.0)

    @classmethod
    def from_dict(cls, data: dict, source: str = "") -> "CarSpec":
        allowed = set(CAR_DEFAULTS) | {"id"}
        clean = {k: v for k, v in data.items() if k in allowed}
        for key, default in CAR_DEFAULTS.items():
            clean.setdefault(key, default)
        # validação/sanitização: mods não podem quebrar a física
        numeric = [k for k, v in CAR_DEFAULTS.items() if isinstance(v, (int, float))]
        for key in numeric:
            try:
                clean[key] = float(clean[key])
            except (TypeError, ValueError):
                clean[key] = CAR_DEFAULTS[key]
        clean["mass"] = float(np.clip(clean["mass"], 300.0, 6000.0))
        clean["engine_force"] = float(np.clip(clean["engine_force"], 500.0, 60000.0))
        clean["max_power"] = float(np.clip(clean["max_power"], 3000.0, 2_000_000.0))
        clean["brake_force"] = float(np.clip(clean["brake_force"], 500.0, 80000.0))
        clean["max_speed"] = float(np.clip(clean["max_speed"], 8.0, 140.0))
        clean["max_steer"] = float(np.clip(clean["max_steer"], 0.15, 1.2))
        clean["steer_rate"] = float(np.clip(clean["steer_rate"], 0.5, 12.0))
        clean["steer_falloff"] = float(np.clip(clean["steer_falloff"], 0.0, 0.9))
        clean["grip_front"] = float(np.clip(clean["grip_front"], 0.4, 3.0))
        clean["grip_rear"] = float(np.clip(clean["grip_rear"], 0.4, 3.0))
        clean["tire_stiffness"] = float(np.clip(clean["tire_stiffness"], 2.0, 25.0))
        clean["tire_shape"] = float(np.clip(clean["tire_shape"], 1.0, 2.2))
        clean["drag"] = float(np.clip(clean["drag"], 0.05, 3.0))
        clean["rolling"] = float(np.clip(clean["rolling"], 0.0, 300.0))
        clean["downforce"] = float(np.clip(clean["downforce"], -2.0, 20.0))
        clean["drive_front"] = float(np.clip(clean["drive_front"], 0.0, 1.0))
        clean["brake_front"] = float(np.clip(clean["brake_front"], 0.2, 0.85))
        clean["yaw_inertia"] = float(np.clip(clean["yaw_inertia"], 0.5, 2.5))
        clean["cg_front"] = float(np.clip(clean["cg_front"], 0.6, clean["wheelbase"] - 0.6))
        clean["cg_height"] = float(np.clip(clean["cg_height"], 0.15, 1.5))
        clean["id"] = str(data.get("id") or os.path.splitext(os.path.basename(source))[0] or "car")
        clean["source"] = source
        return cls(**clean)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("source", None)
        return d

    @classmethod
    def load(cls, path: str) -> "CarSpec":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("id", os.path.splitext(os.path.basename(path))[0])
        return cls.from_dict(data, source=os.path.abspath(path))

    def save(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    def summary(self) -> str:
        pot = self.max_power / 1000.0
        return (f"{self.name}: {self.mass:.0f} kg, {pot:.0f} kW ({self.power_to_weight:.0f} W/kg), "
                f"{self.max_speed * 3.6:.0f} km/h, aderência {self.grip_front:.2f}/{self.grip_rear:.2f}, "
                f"{'dianteira' if self.drive_front > 0.8 else 'traseira' if self.drive_front < 0.2 else 'integral'}")


# parâmetros numéricos que viram arrays no cálculo em lote
CAR_PARAM_KEYS = (
    "mass", "length", "width", "wheelbase", "cg_front", "cg_height",
    "engine_force", "max_power", "brake_force", "max_speed", "reverse_ratio",
    "max_steer", "steer_rate", "steer_falloff", "grip_front", "grip_rear",
    "tire_stiffness", "tire_shape", "drag", "rolling", "downforce",
    "drive_front", "brake_front", "yaw_inertia",
)


class CarBatch:
    """Parâmetros de física de vários carros, um por linha da frota.

    Permite correr com carros diferentes ao mesmo tempo (cada linha da
    simulação usa o seu). Todos os atributos são arrays (n,) de float64.
    """

    __slots__ = ("specs", "n") + CAR_PARAM_KEYS

    def __init__(self, specs: list):
        if not specs:
            raise ValueError("CarBatch precisa de pelo menos um CarSpec")
        self.specs = list(specs)
        self.n = len(self.specs)
        for key in CAR_PARAM_KEYS:
            object.__setattr__(self, key,
                               np.array([float(getattr(sp, key)) for sp in self.specs],
                                        dtype=np.float64))

    # ---------------------------------------------------------------- #
    @classmethod
    def uniform(cls, spec, n: int) -> "CarBatch":
        """Frota inteira com o mesmo carro (modo treino/padrão)."""
        return cls([spec] * max(1, int(n)))

    @property
    def cg_rear(self) -> np.ndarray:
        return np.maximum(0.4, self.wheelbase - self.cg_front)

    @property
    def iz(self) -> np.ndarray:
        return self.mass * (self.length ** 2 + self.width ** 2) / 12.0 * self.yaw_inertia

    @property
    def power_to_weight(self) -> np.ndarray:
        return self.max_power / np.maximum(self.mass, 1.0)

    def __len__(self) -> int:
        return self.n

    def permute(self, perm: np.ndarray):
        """Reordena as linhas (compactação dos vivos na simulação)."""
        self.specs = [self.specs[i] for i in perm]
        for key in CAR_PARAM_KEYS:
            object.__setattr__(self, key, getattr(self, key)[perm])

    def resize(self, n: int):
        """Ajusta a quantidade de linhas repetindo/truncando a lista."""
        n = max(1, int(n))
        if n == self.n:
            return
        specs = (self.specs * (n // max(1, self.n) + 1))[:n] if self.specs else []
        self.specs = specs
        self.__init__(specs) if specs else None


def tire_lateral_force(slip: np.ndarray, fz: np.ndarray, mu: float,
                       stiffness: float, shape: float) -> np.ndarray:
    """Pneus Pacejka-lite: satura suavemente e permite derrapagem controlada."""
    fz = np.maximum(fz, 0.0)
    f_max = mu * fz
    return f_max * np.sin(shape * np.arctan(stiffness * slip))


def physics_step(spec: CarBatch, st, surface_grip: np.ndarray, surface_roll: np.ndarray,
                 dt: float, n: int | None = None) -> None:
    """Avança um passo de física para a frota (arrays numpy, in-place).

    `st` precisa expor os atributos: x, y, heading, vx, vy, r, steer,
    throttle, brake, alive. Escreve também slip_f, slip_r, grip_use, ax, ay
    (usados por sensores e HUD).

    `spec` é um `CarBatch`: um carro por linha (permite grid misto).

    `n` limita o cálculo às primeiras n linhas (otimização: agentes mortos
    são removidos do laço por compactação).
    """
    sl = slice(0, n) if n is not None else slice(None)
    # cada linha pode ser um carro diferente: tudo abaixo é array (A,)
    m = spec.mass[sl]
    a_ax = spec.cg_front[sl]
    b_ax = spec.cg_rear[sl]
    l_wb = a_ax + b_ax
    iz = spec.iz[sl]
    max_speed = np.maximum(spec.max_speed[sl], 1e-6)
    steer_limit = spec.max_steer[sl]
    steer_rate = spec.steer_rate[sl]
    steer_falloff = spec.steer_falloff[sl]
    engine_force = spec.engine_force[sl]
    max_power = spec.max_power[sl]
    reverse_ratio = spec.reverse_ratio[sl]
    brake_force = spec.brake_force[sl]
    drag_c = spec.drag[sl]
    roll_c = spec.rolling[sl]
    down_c = spec.downforce[sl]
    cg_h = spec.cg_height[sl]
    drive_split = spec.drive_front[sl]
    brake_split = spec.brake_front[sl]
    grip_f = spec.grip_front[sl]
    grip_r = spec.grip_rear[sl]
    tire_b = spec.tire_stiffness[sl]
    tire_c = spec.tire_shape[sl]

    alive = st.alive[sl]
    vx = st.vx[sl]
    vy = st.vy[sl]
    yaw_rate = st.r[sl]

    speed = np.sqrt(vx * vx + vy * vy)
    vx_ref = np.maximum(np.abs(vx), 1.2)

    # ---------------- direção (comando -> esterço real) -------------------
    falloff = 1.0 - steer_falloff * np.clip(speed / max_speed, 0.0, 1.0)
    steer_max = steer_limit * falloff
    target = np.clip(st.steer_cmd[sl], -1.0, 1.0) * steer_max
    max_delta = steer_rate * dt
    steer = st.steer[sl] + np.clip(target - st.steer[sl], -max_delta, max_delta)

    # ---------------- ângulos de deriva ----------------------------------
    slip_f = steer - np.arctan2(vy + a_ax * yaw_rate, vx_ref)
    slip_r = -np.arctan2(vy - b_ax * yaw_rate, vx_ref)

    # ---------------- cargas verticais -----------------------------------
    # estimativa de aceleração longitudinal para transferência de carga
    throttle = np.clip(st.throttle[sl], 0.0, 1.0)
    brake = np.clip(st.brake[0:None if n is None else n], 0.0, 1.0)
    # força de tração: limitada pela força em baixa e pela potência em alta
    v_ref = np.maximum(speed, 5.0)
    traction = np.minimum(engine_force, max_power / v_ref)
    power_curve = np.clip(1.0 - (speed / max_speed) ** 1.6, 0.0, 1.0)
    f_drive_demand = throttle * traction * power_curve

    # ré: freio com o carro praticamente parado
    reverse = brake * (speed < 0.6) * (st.reverse_cmd[sl] > 0.5
                                       if hasattr(st, "reverse_cmd") else 1.0)
    f_reverse = reverse * engine_force * reverse_ratio
    f_drive = f_drive_demand - f_reverse

    f_brake_demand = brake * brake_force * (speed >= 0.6)
    drag_f = drag_c * speed * speed
    roll_f = roll_c * surface_roll[sl] * speed
    resist = drag_f + roll_f

    long_demand = f_drive - f_brake_demand - resist
    ax_est = long_demand / m

    downforce_f = down_c * speed * speed
    weight = m * G + downforce_f
    fz_front = weight * (b_ax / l_wb) - m * ax_est * cg_h / l_wb
    fz_rear = weight * (a_ax / l_wb) + m * ax_est * cg_h / l_wb
    fz_front = np.maximum(fz_front, weight * 0.05)
    fz_rear = np.maximum(fz_rear, weight * 0.05)

    # ---------------- forças longitudinais por eixo -----------------------
    f_front_split = drive_split
    f_brake_split = brake_split
    fx_front = (f_drive * f_front_split) - (f_brake_demand * f_brake_split) - resist * 0.5
    fx_rear = (f_drive * (1.0 - f_front_split)) - (f_brake_demand * (1.0 - f_brake_split)) - resist * 0.5

    # ---------------- forças laterais + círculo de atrito -----------------
    grip = np.clip(surface_grip[sl], 0.15, 2.0)
    mu_f = grip_f * grip
    mu_r = grip_r * grip

    fy_front = tire_lateral_force(slip_f, fz_front, mu_f, tire_b, tire_c)
    fy_rear = tire_lateral_force(slip_r, fz_rear, mu_r, tire_b, tire_c)

    cap_front = mu_f * fz_front
    cap_rear = mu_r * fz_rear
    mag_front = np.sqrt(fx_front ** 2 + fy_front ** 2)
    mag_rear = np.sqrt(fx_rear ** 2 + fy_rear ** 2)
    scale_f = np.where(mag_front > cap_front, cap_front / np.maximum(mag_front, 1e-6), 1.0)
    scale_r = np.where(mag_rear > cap_rear, cap_rear / np.maximum(mag_rear, 1e-6), 1.0)
    fx_front *= scale_f
    fy_front *= scale_f
    fx_rear *= scale_r
    fy_rear *= scale_r

    # ---------------- dinâmica no referencial do carro --------------------
    cos_d = np.cos(steer)
    sin_d = np.sin(steer)
    fx_body = fx_front * cos_d - fy_front * sin_d + fx_rear
    fy_body = fy_front * cos_d + fx_front * sin_d + fy_rear
    mz = a_ax * (fy_front * cos_d + fx_front * sin_d) - b_ax * fy_rear

    ax_body = fx_body / m + yaw_rate * vy
    ay_body = fy_body / m - yaw_rate * vx
    dr = mz / iz

    new_vx = vx + ax_body * dt
    new_vy = vy + ay_body * dt
    new_r = yaw_rate + dr * dt

    # ---------------- limites e estabilidade ------------------------------
    # atrito estático: para o carro quando quase parado sem comando
    idle = (throttle < 0.02) & (brake < 0.02) & (speed < 0.8)
    new_vx = np.where(idle, new_vx * 0.85, new_vx)
    new_vy = np.where(idle, new_vy * 0.80, new_vy)
    new_r = np.where(idle, new_r * 0.85, new_r)
    stopped = idle & (speed < 0.25)
    new_vx = np.where(stopped, 0.0, new_vx)
    new_vy = np.where(stopped, 0.0, new_vy)
    new_r = np.where(stopped, 0.0, new_r)

    new_vx = np.clip(new_vx, -max_speed * 0.4, max_speed * 1.05)
    new_vy = np.clip(new_vy, -45.0, 45.0)
    new_r = np.clip(new_r, -6.0, 6.0)

    # integração da pose
    cos_h = np.cos(st.heading[sl])
    sin_h = np.sin(st.heading[sl])
    world_vx = new_vx * cos_h - new_vy * sin_h
    world_vy = new_vx * sin_h + new_vy * cos_h

    update = alive & ~st.frozen[sl]
    st.x[sl] = np.where(update, st.x[sl] + world_vx * dt, st.x[sl])
    st.y[sl] = np.where(update, st.y[sl] + world_vy * dt, st.y[sl])
    st.heading[sl] = np.where(update, st.heading[sl] + new_r * dt, st.heading[sl])
    st.vx[sl] = np.where(update, new_vx, st.vx[sl])
    st.vy[sl] = np.where(update, new_vy, st.vy[sl])
    st.r[sl] = np.where(update, new_r, st.r[sl])
    st.steer[sl] = np.where(update, steer, st.steer[sl])

    # saídas para sensores/HUD
    st.slip_f[sl] = slip_f
    st.slip_r[sl] = slip_r
    st.grip_use[sl] = np.maximum(mag_front / np.maximum(cap_front, 1e-6),
                                 mag_rear / np.maximum(cap_rear, 1e-6))
    st.ax[sl] = ax_body
    st.ay[sl] = ay_body
    st.speed[sl] = np.sqrt(st.vx[sl] ** 2 + st.vy[sl] ** 2)
