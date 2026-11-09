#!/usr/bin/env python3
"""Calculadora CVSS v3.1 (somente Base Score) usada para pontuar os achados.

Uso: python3 cvss.py "AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:L/A:N" ["outro vetor"...]
"""
import math
import sys

AV = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}
AC = {"L": 0.77, "H": 0.44}
PR_U = {"N": 0.85, "L": 0.62, "H": 0.27}
PR_C = {"N": 0.85, "L": 0.68, "H": 0.5}
UI = {"N": 0.85, "R": 0.62}
CIA = {"H": 0.56, "L": 0.22, "N": 0.0}


def roundup(x):
    i = int(round(x * 100000))
    return i / 100000.0 if i % 10000 == 0 else (math.floor(i / 10000) + 1) / 10.0


def base(vector):
    m = dict(p.split(":") for p in vector.split("/"))
    sc = m["S"] == "C"
    pr = (PR_C if sc else PR_U)[m["PR"]]
    iss = 1 - (1 - CIA[m["C"]]) * (1 - CIA[m["I"]]) * (1 - CIA[m["A"]])
    if sc:
        impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15
    else:
        impact = 6.42 * iss
    expl = 8.22 * AV[m["AV"]] * AC[m["AC"]] * pr * UI[m["UI"]]
    if impact <= 0:
        return 0.0
    score = roundup(min((impact + expl) * 1.08, 10)) if sc else roundup(min(impact + expl, 10))
    return score


def severidade(s):
    return ("Nenhuma" if s == 0 else "Baixa" if s < 4 else "Média" if s < 7 else
            "Alta" if s < 9 else "Crítica")


if __name__ == "__main__":
    for v in sys.argv[1:]:
        s = base(v)
        print(f"{v}  ->  {s:.1f} ({severidade(s)})")
