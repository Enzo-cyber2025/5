#!/usr/bin/env python3
"""Gera pistas e carros extras do RaceAI 2D (C++).

Uso:
    python3 tools/gerar_conteudo.py            # grava em assets/
    python3 tools/gerar_conteudo.py --check    # só valida, não grava nada

As pistas são curvas fechadas definidas por pontos de controle; o script
interpola com Catmull-Rom e reamostra a linha de centro a cada `spacing`
metros (o mesmo passo que o motor usa para os sensores). Assim todas as
pistas do jogo têm a mesma qualidade de malha das feitas à mão.

Os carros usam os campos novos de física (marchas, torque, aerodinâmica,
pneus, ABS, tanque) — cada um com uma personalidade de dirigibilidade.
"""
import json
import math
import os
import sys

SPACING = 3.0


# ------------------------------------------------------------------ geometria
def catmull_rom(pts, samples=40):
    """Interpola uma lista de pontos (aberta) com Catmull-Rom."""
    out = []
    n = len(pts)
    for i in range(n):
        p0 = pts[(i - 1) % n]
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        p3 = pts[(i + 2) % n]
        for s in range(samples):
            t = s / samples
            t2, t3 = t * t, t * t * t
            x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t +
                       (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 +
                       (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t +
                       (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 +
                       (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            out.append((x, y))
    return out


def resample(pts, spacing=SPACING):
    """Reamostra a curva fechada com passo constante (`spacing` metros)."""
    pts = list(pts) + [pts[0]]
    # malha fina primeiro
    dense = []
    for i in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        d = math.hypot(x1 - x0, y1 - y0)
        steps = max(2, int(d / 0.25))
        for s in range(steps):
            t = s / steps
            dense.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    dense.append(pts[0])

    out = [dense[0]]
    acc = 0.0
    for i in range(1, len(dense)):
        x0, y0 = dense[i - 1]
        x1, y1 = dense[i]
        acc += math.hypot(x1 - x0, y1 - y0)
        if acc >= spacing:
            out.append((round(x1, 2), round(y1, 2)))
            acc = 0.0
    if len(out) < 20:
        raise ValueError("curva curta demais")
    return out


def comprimento(pts):
    return sum(math.hypot(pts[(i + 1) % len(pts)][0] - pts[i][0],
                          pts[(i + 1) % len(pts)][1] - pts[i][1])
               for i in range(len(pts)))


def pista(nome, descricao, dificuldade, largura, pontos, zonas=()):
    linha = resample(catmull_rom(pontos))
    return {
        "name": nome,
        "description": descricao,
        "difficulty": dificuldade,
        "closed": True,
        "width": largura,
        "spacing": SPACING,
        "points": [[p[0], p[1]] for p in linha],
        "zones": [{"start": z[0], "end": z[1], "grip": z[2]} for z in zonas],
    }


def oval(raio_x, raio_y, suavidade=1.0):
    pts = []
    for k in range(24):
        a = 2 * math.pi * k / 24
        pts.append((raio_x * math.cos(a) * suavidade, raio_y * math.sin(a)))
    return pts


# ------------------------------------------------------------------- pistas
TRACKS = {}

TRACKS["anel_veloz"] = pista(
    "Anel Veloz", "Anel de alta velocidade: duas retas enormes e duas curvas de raio longo.",
    "médio", 16.0,
    [(-240, -70), (-120, -95), (0, -100), (120, -95), (240, -70),
     (300, 0), (250, 70), (120, 95), (0, 100), (-120, 95),
     (-250, 70), (-300, 0)],
)

TRACKS["rua_estreita"] = pista(
    "Circuito de Rua", "Muro colado nas laterais: chicanes e duas curvas de 90°. Sem espaço para errar.",
    "difícil", 9.5,
    [(-150, -60), (-60, -62), (-40, -30), (40, -28), (62, -60),
     (150, -58), (168, -10), (120, 0), (60, 6), (-10, 40),
     (-60, 90), (-150, 92), (-172, 40), (-120, 30), (-60, 28),
     (-20, -10), (-60, -40)],
    zonas=[(0.30, 0.36, 0.72)],          # trecho de paralelepípedo molhado
)

TRACKS["misto_tecnico"] = pista(
    "Misto Técnico", "Sequência de médias, um grampo e uma reta de verdade. Exige tração na saída.",
    "médio", 12.0,
    [(-180, -50), (-100, -80), (-20, -70), (40, -40), (80, -70),
     (150, -40), (170, 20), (110, 40), (60, 20), (10, 50),
     (-30, 90), (-110, 100), (-170, 60), (-200, 0)],
)

TRACKS["oval_triplo"] = pista(
    "Tri-Oval", "Oval com três curvas de alto suporte: pé embaixo o tempo todo, desgaste de pneu alto.",
    "fácil", 18.0,
    [(-260, -60), (-160, -95), (-40, -105), (80, -100), (200, -70),
     (280, -20), (300, 40), (240, 90), (120, 105), (0, 105),
     (-120, 100), (-220, 80), (-290, 30), (-300, -30)],
)

TRACKS["deserto_drift"] = pista(
    "Deserto (terra)", "Pista de terra larga: a traseira sai fácil e a poeira come aderência.",
    "médio", 20.0,
    oval(230, 150) + [],
    zonas=[(0.0, 1.0, 0.78)],            # terra solta no circuito inteiro
)

TRACKS["neve_gelo"] = pista(
    "Neve e Gelo", "Aderência baixíssima: quem freia tarde sai. Ideal para aprender controle fino.",
    "difícil", 15.0,
    [(-200, -40), (-120, -80), (0, -90), (110, -70), (190, -20),
     (210, 40), (140, 80), (40, 90), (-60, 80), (-150, 60), (-200, 20)],
    zonas=[(0.0, 0.25, 0.42), (0.55, 0.75, 0.38)],
)

TRACKS["slalom_chicane"] = pista(
    "Slalom", "Chicanes em sequência curta: esterço rápido e paciência no acelerador.",
    "difícil", 10.0,
    [(-160, -20), (-120, -60), (-70, -20), (-20, -60), (30, -20),
     (80, -60), (130, -20), (170, 20), (130, 60), (80, 20),
     (30, 60), (-20, 20), (-70, 60), (-120, 20), (-180, 20)],
)

TRACKS["grande_premio"] = pista(
    "Grande Prêmio", "Circuito longo com setores distintos: reta, misto lento e curva de alta.",
    "difícil", 14.0,
    [(-320, -40), (-240, -90), (-140, -110), (-40, -100), (40, -70),
     (110, -90), (180, -60), (230, 0), (240, 70), (170, 110),
     (80, 120), (0, 100), (-60, 130), (-150, 140), (-230, 120),
     (-300, 80), (-340, 20)],
    zonas=[(0.62, 0.70, 0.70)],
)


# -------------------------------------------------------------------- carros
CARS = {}

CARS["classico"] = {
    "id": "classico", "name": "Clássico 78",
    "mass": 1080.0, "length": 4.1, "width": 1.68, "wheelbase": 2.45,
    "cg_front": 1.20, "cg_height": 0.58,
    "engine_force": 5200.0, "max_power": 68000.0, "brake_force": 7500.0,
    "max_speed": 48.0, "max_steer": 0.52, "steer_rate": 2.6, "steer_falloff": 0.35,
    "grip_front": 1.10, "grip_rear": 1.05, "tire_stiffness": 6.5, "tire_shape": 1.30,
    "drag": 0.55, "rolling": 30.0, "downforce": 0.0,
    "drive_front": 0.0, "brake_front": 0.58, "yaw_inertia": 1.10,
    "gears": [3.60, 2.10, 1.45, 1.10, 0.90], "final_drive": 3.90,
    "wheel_radius": 0.30, "peak_torque": 150.0, "rpm_peak": 4200.0, "rpm_limit": 5600.0,
    "cd_a": 0.95, "cl_a": 0.0, "abs_level": 0.0, "traction_control": 0.0,
    "tire_opt_temp": 80.0, "tire_wear_rate": 0.00028, "fuel_capacity": 70.0,
    "damage_rate": 0.06, "body_color": "#2f7d5d", "accent_color": "#e8d8b0",
}

CARS["super_gt"] = {
    "id": "super_gt", "name": "Super GT",
    "mass": 1240.0, "length": 4.6, "width": 2.0, "wheelbase": 2.72,
    "cg_front": 1.30, "cg_height": 0.46,
    "engine_force": 12500.0, "max_power": 330000.0, "brake_force": 21000.0,
    "max_speed": 88.0, "max_steer": 0.55, "steer_rate": 5.0, "steer_falloff": 0.60,
    "grip_front": 1.85, "grip_rear": 1.80, "tire_stiffness": 12.0, "tire_shape": 1.55,
    "drag": 0.40, "rolling": 24.0, "downforce": 2600.0,
    "drive_front": 0.0, "brake_front": 0.60, "yaw_inertia": 0.95,
    "gears": [3.10, 2.05, 1.52, 1.20, 0.98, 0.82], "final_drive": 3.30,
    "wheel_radius": 0.34, "peak_torque": 500.0, "rpm_peak": 5800.0, "rpm_limit": 7800.0,
    "cd_a": 0.78, "cl_a": 2.60, "downforce_front": 0.42,
    "abs_level": 0.85, "traction_control": 0.35,
    "tire_opt_temp": 100.0, "tire_wear_rate": 0.00022, "fuel_capacity": 110.0,
    "damage_rate": 0.04, "body_color": "#1f4fd8", "accent_color": "#ffffff",
}

CARS["monoposto"] = {
    "id": "monoposto", "name": "Monoposto",
    "mass": 760.0, "length": 4.8, "width": 1.9, "wheelbase": 3.05,
    "cg_front": 1.40, "cg_height": 0.36,
    "engine_force": 14000.0, "max_power": 400000.0, "brake_force": 26000.0,
    "max_speed": 95.0, "max_steer": 0.48, "steer_rate": 6.0, "steer_falloff": 0.70,
    "grip_front": 2.30, "grip_rear": 2.25, "tire_stiffness": 14.0, "tire_shape": 1.60,
    "drag": 0.45, "rolling": 20.0, "downforce": 4200.0,
    "drive_front": 0.0, "brake_front": 0.56, "yaw_inertia": 0.85,
    "gears": [2.90, 2.00, 1.55, 1.26, 1.05, 0.90, 0.78], "final_drive": 3.10,
    "wheel_radius": 0.33, "peak_torque": 560.0, "rpm_peak": 9500.0, "rpm_limit": 13000.0,
    "cd_a": 0.85, "cl_a": 4.20, "downforce_front": 0.40,
    "abs_level": 0.0, "traction_control": 0.0,
    "tire_opt_temp": 105.0, "tire_temp_rate": 0.028, "tire_wear_rate": 0.00035,
    "fuel_capacity": 140.0, "damage_rate": 0.07,
    "body_color": "#c8102e", "accent_color": "#101010",
}

CARS["rally"] = {
    "id": "rally", "name": "Rally 4x4",
    "mass": 1320.0, "length": 4.2, "width": 1.85, "wheelbase": 2.60,
    "cg_front": 1.25, "cg_height": 0.68,
    "engine_force": 10500.0, "max_power": 220000.0, "brake_force": 17000.0,
    "max_speed": 62.0, "max_steer": 0.68, "steer_rate": 4.6, "steer_falloff": 0.35,
    "grip_front": 1.55, "grip_rear": 1.55, "tire_stiffness": 8.5, "tire_shape": 1.40,
    "drag": 0.62, "rolling": 34.0, "downforce": 0.0,
    "drive_front": 0.45, "brake_front": 0.58, "yaw_inertia": 1.05,
    "gears": [3.30, 2.20, 1.60, 1.22, 1.00, 0.85], "final_drive": 3.70,
    "wheel_radius": 0.36, "peak_torque": 380.0, "rpm_peak": 4500.0, "rpm_limit": 7200.0,
    "cd_a": 0.92, "cl_a": 0.10, "abs_level": 0.4, "traction_control": 0.15,
    "tire_opt_temp": 85.0, "tire_wear_rate": 0.00030, "fuel_capacity": 90.0,
    "damage_rate": 0.035, "body_color": "#0f766e", "accent_color": "#facc15",
}

CARS["caminhao"] = {
    "id": "caminhao", "name": "Caminhão",
    "mass": 5200.0, "length": 7.6, "width": 2.5, "wheelbase": 4.60,
    "cg_front": 2.10, "cg_height": 1.05,
    "engine_force": 16000.0, "max_power": 260000.0, "brake_force": 32000.0,
    "max_speed": 40.0, "max_steer": 0.42, "steer_rate": 1.8, "steer_falloff": 0.45,
    "grip_front": 1.00, "grip_rear": 0.95, "tire_stiffness": 5.0, "tire_shape": 1.25,
    "drag": 1.70, "rolling": 60.0, "downforce": 0.0,
    "drive_front": 0.0, "brake_front": 0.52, "yaw_inertia": 1.35,
    "gears": [4.60, 2.90, 1.95, 1.40, 1.00, 0.78, 0.62], "final_drive": 4.10,
    "wheel_radius": 0.50, "peak_torque": 700.0, "rpm_peak": 1500.0, "rpm_limit": 2400.0,
    "cd_a": 3.20, "cl_a": 0.0, "abs_level": 0.5, "traction_control": 0.10,
    "track_width": 2.10, "load_sens": 0.16,
    "tire_opt_temp": 85.0, "tire_wear_rate": 0.00012, "fuel_capacity": 300.0,
    "fuel_burn": 0.16, "damage_rate": 0.02,
    "body_color": "#7c3aed", "accent_color": "#e5e7eb",
}

CARS["eletrico"] = {
    "id": "eletrico", "name": "Elétrico",
    "mass": 1750.0, "length": 4.5, "width": 1.9, "wheelbase": 2.85,
    "cg_front": 1.35, "cg_height": 0.44,
    "engine_force": 13000.0, "max_power": 300000.0, "brake_force": 15000.0,
    "max_speed": 70.0, "max_steer": 0.54, "steer_rate": 4.2, "steer_falloff": 0.55,
    "grip_front": 1.55, "grip_rear": 1.55, "tire_stiffness": 10.0, "tire_shape": 1.45,
    "drag": 0.34, "rolling": 20.0, "downforce": 0.0,
    "drive_front": 0.35, "brake_front": 0.55, "yaw_inertia": 1.00,
    "gears": [1.00], "final_drive": 8.50,          # câmbio de 1 marcha
    "wheel_radius": 0.34, "peak_torque": 700.0,
    "rpm_peak": 6000.0, "rpm_limit": 15000.0, "torque_shape": 2.6,
    "cd_a": 0.60, "cl_a": 0.0, "abs_level": 0.9, "traction_control": 0.55,
    "fuel_capacity": 0.0,                           # bateria: sem consumo
    "tire_opt_temp": 85.0, "tire_wear_rate": 0.00015, "damage_rate": 0.05,
    "body_color": "#0ea5e9", "accent_color": "#e2e8f0",
}

CARS["tuner_drift"] = {
    "id": "tuner_drift", "name": "Tuner Drift",
    "mass": 1180.0, "length": 4.3, "width": 1.8, "wheelbase": 2.55,
    "cg_front": 1.22, "cg_height": 0.52,
    "engine_force": 11500.0, "max_power": 280000.0, "brake_force": 15000.0,
    "max_speed": 78.0, "max_steer": 0.70, "steer_rate": 6.0, "steer_falloff": 0.35,
    "grip_front": 1.75, "grip_rear": 1.45, "tire_stiffness": 9.5, "tire_shape": 1.35,
    "drag": 0.44, "rolling": 24.0, "downforce": 300.0,
    "drive_front": 0.0, "brake_front": 0.62, "yaw_inertia": 1.00,
    "gears": [3.20, 2.10, 1.55, 1.22, 1.00, 0.85], "final_drive": 3.90,
    "wheel_radius": 0.32, "peak_torque": 340.0, "rpm_peak": 5000.0, "rpm_limit": 7600.0,
    "cd_a": 0.72, "cl_a": 0.30, "abs_level": 0.30, "traction_control": 0.30,
    "tire_opt_temp": 95.0, "tire_wear_rate": 0.00055, "fuel_capacity": 80.0,
    "damage_rate": 0.05, "body_color": "#db2777", "accent_color": "#111827",
}

CARS["buggy"] = {
    "id": "buggy", "name": "Buggy do Deserto",
    "mass": 780.0, "length": 3.4, "width": 1.9, "wheelbase": 2.35,
    "cg_front": 1.15, "cg_height": 0.64,
    "engine_force": 7000.0, "max_power": 130000.0, "brake_force": 10000.0,
    "max_speed": 55.0, "max_steer": 0.75, "steer_rate": 5.5, "steer_falloff": 0.30,
    "grip_front": 1.35, "grip_rear": 1.32, "tire_stiffness": 7.0, "tire_shape": 1.30,
    "drag": 0.85, "rolling": 40.0, "downforce": 0.0,
    "drive_front": 0.0, "brake_front": 0.50, "yaw_inertia": 0.95,
    "gears": [3.00, 1.95, 1.40, 1.05, 0.85], "final_drive": 4.20,
    "wheel_radius": 0.42, "peak_torque": 320.0, "rpm_peak": 5200.0, "rpm_limit": 8000.0,
    "cd_a": 1.10, "cl_a": 0.0, "abs_level": 0.0, "traction_control": 0.0,
    "track_width": 1.90, "load_sens": 0.16,
    "tire_opt_temp": 75.0, "tire_wear_rate": 0.00040, "fuel_capacity": 60.0,
    "damage_rate": 0.05, "body_color": "#f59e0b", "accent_color": "#1f2937",
}



# ------------------------------------------------- pistas novas (2a fornada)

TRACKS["autodromo_nacional"] = pista(
    "Autódromo Nacional",
    "Reta longa, S em descida, Curva do Sol e junção de volta à reta. O clássico.",
    "difícil", 15.0,
    [(-330, -60), (-260, -110), (-150, -120), (-60, -95), (10, -60),
     (60, -70), (110, -40), (150, 10), (120, 60), (60, 70),
     (10, 40), (-40, 70), (-90, 110), (-190, 120), (-280, 90),
     (-350, 40), (-360, -10)],
    zonas=[(0.70, 0.78, 0.80)],
)

TRACKS["kart_travado"] = pista(
    "Kart Travado",
    "Kartódromo apertado: nove curvas de baixa, senão você não passa. Freio é tudo.",
    "médio", 8.0,
    [(-90, -50), (-40, -52), (-30, -20), (10, -18), (22, -50),
     (70, -48), (80, -10), (50, 5), (10, 0), (-10, 30),
     (-40, 60), (-70, 25), (-95, 30), (-110, -10)],
)

TRACKS["noturno_rua"] = pista(
    "Rua Noturna",
    "Circuito de rua à noite: muros, duas chicanes e um trecho de asfalto sujo.",
    "difícil", 11.0,
    [(-170, -70), (-90, -75), (-30, -40), (40, -38), (75, -72),
     (160, -70), (180, -20), (130, 10), (60, 20), (10, 55),
     (-40, 95), (-120, 95), (-175, 55), (-140, 20), (-70, 15),
     (-30, -10), (-80, -40)],
    zonas=[(0.42, 0.50, 0.68)],
)

TRACKS["dirt_oval"] = pista(
    "Oval de Terra",
    "Oval de terra: a traseira sai sozinha e o acelerador é o volante de trás.",
    "fácil", 19.0,
    oval(210, 130),
    zonas=[(0.0, 1.0, 0.74)],
)

TRACKS["misto_molhado"] = pista(
    "Misto Molhado",
    "Segundo setor encharcado: quem chegar passando do limite vai parar na grama.",
    "difícil", 13.0,
    [(-210, -50), (-130, -85), (-40, -80), (30, -45), (90, -75),
     (170, -45), (200, 15), (150, 55), (70, 40), (10, 70),
     (-50, 105), (-140, 105), (-205, 60), (-235, 5)],
    zonas=[(0.34, 0.62, 0.58)],
)

TRACKS["praia_circuito"] = pista(
    "Circuito da Praia",
    "Duas retas enormes à beira-mar e um miolo travado. Aerodinâmica decide a volta.",
    "médio", 21.0,
    [(-300, -60), (-150, -80), (0, -85), (150, -80), (300, -60),
     (350, 0), (300, 60), (150, 80), (60, 40), (-20, 70),
     (-120, 85), (-250, 70), (-340, 30)],
)

TRACKS["short_oval"] = pista(
    "Oval Curto",
    "Ovalzinho de 600 m: volta em menos de 30 s, ótimo para treinar a rede do zero.",
    "fácil", 16.0,
    oval(120, 80),
)

TRACKS["triangulo_veloz"] = pista(
    "Triângulo Veloz",
    "Três retas e três curvas de raio longo: nada de frear, tudo de coragem.",
    "médio", 17.0,
    # vértices + pontos a 15 % de cada aresta: o Catmull-Rom arredonda a quina
    [(-260, -150), (-182, -150), (182, -150), (260, -150),
     (221, -82), (39, 232), (0, 300), (-39, 232), (-221, -82)],
)


# -------------------------------------------------- carros novos (2a fornada)

CARS["formula_jr"] = {
    "id": "formula_jr", "name": "Fórmula Júnior",
    "mass": 640.0, "length": 4.3, "width": 1.7, "wheelbase": 2.70,
    "cg_front": 1.25, "cg_height": 0.34,
    "engine_force": 7000.0, "max_power": 130000.0, "brake_force": 12000.0,
    "max_speed": 68.0, "max_steer": 0.50, "steer_rate": 5.5, "steer_falloff": 0.65,
    "grip_front": 1.80, "grip_rear": 1.75, "tire_stiffness": 11.0, "tire_shape": 1.50,
    "drag": 0.42, "rolling": 18.0, "downforce": 900.0,
    "drive_front": 0.0, "brake_front": 0.56, "yaw_inertia": 0.80,
    "gears": [3.00, 2.10, 1.62, 1.30, 1.08, 0.92], "final_drive": 3.40,
    "wheel_radius": 0.30, "peak_torque": 240.0, "rpm_peak": 7000.0, "rpm_limit": 9500.0,
    "cd_a": 0.70, "cl_a": 1.10, "downforce_front": 0.44,
    "abs_level": 0.0, "traction_control": 0.0, "diff_lock": 0.45,
    "roll_grad": 0.035, "pitch_grad": 0.020, "susp_tau": 0.10,
    "tire_opt_temp": 95.0, "tire_temp_rate": 0.030, "tire_wear_rate": 0.00035,
    "fuel_capacity": 60.0, "damage_rate": 0.07,
    "body_color": "#facc15", "accent_color": "#111827",
}

CARS["stock_car"] = {
    "id": "stock_car", "name": "Stock Car V8",
    "mass": 1350.0, "length": 4.9, "width": 1.95, "wheelbase": 2.90,
    "cg_front": 1.40, "cg_height": 0.52,
    "engine_force": 12000.0, "max_power": 370000.0, "brake_force": 19000.0,
    "max_speed": 82.0, "max_steer": 0.52, "steer_rate": 4.0, "steer_falloff": 0.55,
    "grip_front": 1.60, "grip_rear": 1.50, "tire_stiffness": 9.0, "tire_shape": 1.40,
    "drag": 0.48, "rolling": 28.0, "downforce": 1400.0,
    "drive_front": 0.0, "brake_front": 0.58, "yaw_inertia": 1.05,
    "gears": [2.80, 1.95, 1.45, 1.15, 0.95, 0.80], "final_drive": 3.55,
    "wheel_radius": 0.35, "peak_torque": 620.0, "rpm_peak": 5200.0, "rpm_limit": 7200.0,
    "cd_a": 0.90, "cl_a": 1.60, "downforce_front": 0.46,
    "abs_level": 0.0, "traction_control": 0.0, "diff_lock": 0.70,
    "roll_grad": 0.060, "pitch_grad": 0.030, "susp_tau": 0.14,
    "camber_static": -0.035, "camber_gain": 0.60, "camber_loss": 0.60,
    "brake_fade": 0.45, "brake_heat": 0.26,
    "tire_opt_temp": 100.0, "tire_wear_rate": 0.00032, "fuel_capacity": 120.0,
    "damage_rate": 0.05, "body_color": "#0b5ed7", "accent_color": "#ffffff",
}

CARS["prototipo"] = {
    "id": "prototipo", "name": "Protótipo Híbrido",
    "mass": 1030.0, "length": 5.0, "width": 2.0, "wheelbase": 3.15,
    "cg_front": 1.45, "cg_height": 0.38,
    "engine_force": 15000.0, "max_power": 500000.0, "brake_force": 28000.0,
    "max_speed": 96.0, "max_steer": 0.50, "steer_rate": 5.5, "steer_falloff": 0.68,
    "grip_front": 2.10, "grip_rear": 2.05, "tire_stiffness": 13.0, "tire_shape": 1.58,
    "drag": 0.40, "rolling": 19.0, "downforce": 3800.0,
    "drive_front": 0.40, "brake_front": 0.52, "yaw_inertia": 0.90,
    "gears": [2.70, 1.90, 1.48, 1.20, 1.00, 0.86, 0.76], "final_drive": 3.20,
    "wheel_radius": 0.34, "peak_torque": 700.0, "rpm_peak": 7800.0, "rpm_limit": 10500.0,
    "cd_a": 0.76, "cl_a": 3.90, "downforce_front": 0.41, "aero_pitch": 0.45,
    "abs_level": 0.70, "traction_control": 0.45, "diff_lock": 0.55,
    "roll_grad": 0.030, "pitch_grad": 0.018, "susp_tau": 0.09,
    "wheel_inertia": 4.0, "engine_inertia": 0.30,
    "tire_opt_temp": 105.0, "tire_temp_rate": 0.026, "tire_wear_rate": 0.00020,
    "fuel_capacity": 100.0, "fuel_burn": 0.075, "damage_rate": 0.05,
    "body_color": "#16a34a", "accent_color": "#052e16",
}

CARS["hot_hatch"] = {
    "id": "hot_hatch", "name": "Hatch Esportivo",
    "mass": 1280.0, "length": 4.05, "width": 1.78, "wheelbase": 2.58,
    "cg_front": 1.05, "cg_height": 0.50,
    "engine_force": 9000.0, "max_power": 200000.0, "brake_force": 15000.0,
    "max_speed": 72.0, "max_steer": 0.58, "steer_rate": 4.6, "steer_falloff": 0.50,
    "grip_front": 1.62, "grip_rear": 1.50, "tire_stiffness": 9.5, "tire_shape": 1.42,
    "drag": 0.44, "rolling": 25.0, "downforce": 250.0,
    "drive_front": 1.0, "brake_front": 0.66, "yaw_inertia": 1.05,
    "gears": [3.40, 2.15, 1.55, 1.18, 0.96, 0.82], "final_drive": 3.70,
    "wheel_radius": 0.32, "peak_torque": 380.0, "rpm_peak": 4800.0, "rpm_limit": 7000.0,
    "cd_a": 0.68, "cl_a": 0.25, "abs_level": 0.85, "traction_control": 0.40,
    "diff_lock": 0.15, "roll_front": 0.62,
    "roll_grad": 0.065, "susp_tau": 0.16,
    "tire_opt_temp": 88.0, "tire_wear_rate": 0.00020, "fuel_capacity": 55.0,
    "damage_rate": 0.05, "body_color": "#dc2626", "accent_color": "#111827",
}

CARS["muscle"] = {
    "id": "muscle", "name": "Muscle V8",
    "mass": 1680.0, "length": 4.8, "width": 1.92, "wheelbase": 2.85,
    "cg_front": 1.45, "cg_height": 0.56,
    "engine_force": 12000.0, "max_power": 340000.0, "brake_force": 14000.0,
    "max_speed": 78.0, "max_steer": 0.48, "steer_rate": 3.2, "steer_falloff": 0.50,
    "grip_front": 1.35, "grip_rear": 1.22, "tire_stiffness": 7.5, "tire_shape": 1.32,
    "drag": 0.52, "rolling": 30.0, "downforce": 0.0,
    "drive_front": 0.0, "brake_front": 0.58, "yaw_inertia": 1.15,
    "gears": [2.90, 2.00, 1.40, 1.00, 0.80], "final_drive": 3.70,
    "wheel_radius": 0.35, "peak_torque": 680.0, "rpm_peak": 4200.0, "rpm_limit": 6000.0,
    "cd_a": 0.95, "cl_a": 0.10, "abs_level": 0.0, "traction_control": 0.0,
    "diff_lock": 0.85, "load_sens": 0.18,
    "roll_grad": 0.075, "pitch_grad": 0.040, "susp_tau": 0.18,
    "camber_static": -0.015, "camber_gain": 0.70, "camber_loss": 0.70,
    "brake_fade": 0.50, "brake_heat": 0.24,
    "tire_opt_temp": 90.0, "tire_wear_rate": 0.00045, "fuel_capacity": 95.0,
    "fuel_burn": 0.10, "damage_rate": 0.05,
    "body_color": "#7f1d1d", "accent_color": "#fef3c7",
}

CARS["pickup"] = {
    "id": "pickup", "name": "Picape Off-road",
    "mass": 2100.0, "length": 5.4, "width": 2.0, "wheelbase": 3.30,
    "cg_front": 1.55, "cg_height": 0.82,
    "engine_force": 11000.0, "max_power": 190000.0, "brake_force": 16000.0,
    "max_speed": 58.0, "max_steer": 0.62, "steer_rate": 3.0, "steer_falloff": 0.40,
    "grip_front": 1.30, "grip_rear": 1.28, "tire_stiffness": 6.5, "tire_shape": 1.30,
    "drag": 0.95, "rolling": 45.0, "downforce": 0.0,
    "drive_front": 0.40, "brake_front": 0.56, "yaw_inertia": 1.25,
    "gears": [3.60, 2.40, 1.70, 1.25, 1.00, 0.80], "final_drive": 4.10,
    "wheel_radius": 0.40, "peak_torque": 520.0, "rpm_peak": 3600.0, "rpm_limit": 5200.0,
    "cd_a": 1.40, "cl_a": 0.0, "abs_level": 0.6, "traction_control": 0.20,
    "diff_lock": 0.60, "load_sens": 0.16, "track_width": 1.75,
    "roll_grad": 0.095, "pitch_grad": 0.050, "susp_tau": 0.22,
    "wheel_inertia": 5.0, "tire_opt_temp": 80.0, "tire_wear_rate": 0.00025,
    "fuel_capacity": 110.0, "fuel_burn": 0.09, "damage_rate": 0.03,
    "body_color": "#65a30d", "accent_color": "#1f2937",
}


def main():
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dir_p = os.path.join(raiz, "assets", "tracks")
    dir_c = os.path.join(raiz, "assets", "cars")
    gravar = "--check" not in sys.argv

    for nome, dados in TRACKS.items():
        compr = comprimento([tuple(p) for p in dados["points"]])
        print(f"pista  {nome:<16} {len(dados['points']):>4} pontos  {compr:7.1f} m")
        if gravar:
            with open(os.path.join(dir_p, nome + ".json"), "w", encoding="utf-8") as f:
                json.dump(dados, f, ensure_ascii=False, indent=1)
    for nome, dados in CARS.items():
        print(f"carro  {nome:<16} {dados['name']}")
        if gravar:
            with open(os.path.join(dir_c, nome + ".json"), "w", encoding="utf-8") as f:
                json.dump(dados, f, ensure_ascii=False, indent=1)
    if not gravar:
        print("\n(--check: nada foi gravado)")


if __name__ == "__main__":
    main()
