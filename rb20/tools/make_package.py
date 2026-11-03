"""
make_package.py -- assemble the installable .zip.

Zip layout:
  LEIA-ME.txt                 (PT-BR install + limitations)
  VALIDACAO.md                (telemetry comparison summary)
  REFERENCIAS.md              (reference images / 3D models / sources)
  content/cars/arb_rb20/...   (drop straight into the AC root)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import zipfile


LEIAME = """ARB RB20 2024 - MOD PARA ASSETTO CORSA (VANILLA / SEM CSP)
============================================================

INSTALACAO
----------
1. Extraia este ZIP e copie a pasta "content/cars/arb_rb20" para:
   ...\\Steam\\steamapps\\common\\assettocorsa\\content\\cars\\arb_rb20
   (ou simplesmente extraia o ZIP dentro da pasta raiz do Assetto Corsa,
    mantendo a estrutura "content/cars/...").
2. Abra o Assetto Corsa (launcher original ou Content Manager) e selecione
   "ARB RB20 2024". Nao e necessario Custom Shaders Patch, Sol, extensoes
   de fisica, data.acd criptografado nem arquivos .lua.

O QUE ESTA INCLUSO
------------------
- Modelo 3D original (KN5 v5 vanilla), 4 rodas, asas, halo, difusor,
  sidepods, suspensao, cockpit; texturas DDS DXT1 embutidas.
- data/ aberto (nao criptografado): car.ini, engine.ini, power.lut,
  drivetrain.ini, suspensions.ini, tyres.ini (3 compostos), aero.ini,
  brakes.ini, setup.ini, electronics.ini, ai.ini e todas as LUTs.
- 3 compostos P Zero, termica, desgaste, pressao e camber ajustaveis.
- Física calibrada com telemetria REAL da volta da pole de Verstappen
  no GP do Bahrein 2024 (FastF1): relacoes de cambio, curva de torque,
  arrasto, downforce, aderencia e frenagem. Veja calibration.json e VALIDACAO.md.

SEM CSP - POR CONSTRUCAO
------------------------
- car.ini VERSION=1 (nunca "extended-2"), tyres.ini VERSION=7 (nao v10/CSP),
  aero.ini VERSION=3, suspensions.ini VERSION=2.
- Somente shaders vanilla (ksPerPixel). Sem ext_config.ini, sem wing_controller,
  sem data.acd, sem scripts Lua, sem physics/extended.
- Sem DRS ativo e sem gerenciamento de energia ERS (recursos que exigem CSP
  ou scripting): a contribuicao eletrica esta embutida na curva de torque real.

LIMITACOES HONESTAS
-------------------
- Nao ha banco de som FMOD (.bank) proprio: o carro pode ficar sem som de
  motor ou usar o fallback do jogo. Nao e um defeito de fisica.
- Modelo e livery sao uma interpretacao original, SEM logos, marcas ou
  pintura oficial de equipe. Projeto de fa, nao oficial, sem licenca F1.
- DRS, ERS ajustavel em cockpit, chuva e fisica estendida nao existem.
- Este mod NAO foi executado dentro do Assetto Corsa neste ambiente
  (sem jogo/Windows). A validacao feita foi: leitura/round-trip do KN5,
  checagem de todas as referencias de arquivos, varredura anti-CSP e
  simulacao numerica offline comparada com a telemetria (VALIDACAO.md).

RECONSTRUIR (GitHub Actions com Blender)
---------------------------------------
O workflow .github/workflows/rb20-mod.yml instala o Blender (bpy), modela o
carro, calibra a fisica com a telemetria, gera os KN5, valida e produz este ZIP.
"""
VALIDACAO_HEAD = """VALIDACAO DA FISICA (offline, comparada com telemetria real)
============================================================

Origem dos dados: telemetria FastF1 de VER, classificacao do GP do Bahrein
2024 (volta da pole, 1:29.179), arquivo telemetry/VER_2024_Bahrain_Q.csv.
Mais detalhes em telemetry/SOURCES.md.

"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--car-dir", required=True)
    ap.add_argument("--validation", required=True)
    ap.add_argument("--references", default="")
    ap.add_argument("--zip", required=True)
    args = ap.parse_args()

    car_dir = os.path.abspath(args.car_dir)
    with open(args.validation, "r", encoding="utf-8") as f:
        vr = json.load(f)
    sim = vr["simulation"]
    cmp_ = vr["telemetry_comparison"]
    validacao = VALIDACAO_HEAD
    validacao += "Valores obtidos pela simulacao dos arquivos .ini/.lut entregues:\n\n"
    validacao += "- Velocidade maxima .......... %.1f km/h (telemetria: 322 km/h no Bahrein)\n" % sim["top_speed_kmh"]
    validacao += "- 0-100 / 0-200 / 0-300 ....... %s / %s / %s s\n" % (
        sim["accel_times_s"].get(100), sim["accel_times_s"].get(200), sim["accel_times_s"].get(300))
    validacao += "- Frenagem 300 -> 0 km/h ..... %.1f m, pico %.2f g (telemetria: %.2f g)\n" % (
        sim["braking_from_300_kmh"]["distance_m"],
        sim["braking_from_300_kmh"]["peak_decel_g"],
        vr["telemetry"]["peak_braking_g_telemetry"])
    validacao += "- Aderencia lateral @260 ..... %.2f g\n" % (
        dict(sim["lateral_g_vs_kmh"])[260])
    validacao += "- Erro medio aceleracao ...... %.2f m/s2\n" % cmp_["accel_mae_mps2"]
    validacao += "- Erro medio frenagem ........ %.2f m/s2\n" % cmp_["brake_mae_mps2"]
    validacao += "\nParametros ajustados por minimos quadrados (calibration.json):\n"
    p = vr["parameters"]
    validacao += "- mu (slick) %.3f | CdA %.3f m2 | CLA %.3f m2 | massa %.1f kg\n" % (
        p["mu"], p["CdA"], p["CLA"], p["m"])
    validacao += "- Cambio: 8 marchas, UP %.0f rpm, diferencial e relacoes reais da telemetria\n" % p["shift"]
    validacao += "\nTodos os checks: %s\n" % ("PASSOU" if vr["all_checks_passed"] else "FALHOU")
    validacao += "\nIMPORTANTE: isto e uma simulacao numerica offline dos dados do mod,\n"
    validacao += "NAO uma execucao do jogo Assetto Corsa (veja LEIA-ME.txt).\n"

    # Hot-reload note + sfx placeholder inside the car folder
    sfx = os.path.join(car_dir, "sfx")
    os.makedirs(sfx, exist_ok=True)
    with open(os.path.join(sfx, "LEIA-ME-SOM.txt"), "w", encoding="utf-8") as f:
        f.write("Nenhum banco FMOD proprietario e redistribuido neste projeto.\n"
                "O AC pode usar seu fallback de audio ou ficar sem som de motor.\n"
                "Isso nao afeta a fisica nem a compatibilidade vanilla.\n")

    refs = ""
    if args.references and os.path.exists(args.references):
        with open(args.references, "r", encoding="utf-8") as f:
            refs = f.read()

    os.makedirs(os.path.dirname(os.path.abspath(args.zip)), exist_ok=True)
    docs = {"LEIA-ME.txt": LEIAME, "VALIDACAO.md": validacao,
            "REFERENCIAS.md": refs or "Ver rb20/references/REFERENCES.md no repositorio.\n"}
    with zipfile.ZipFile(args.zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, text in docs.items():
            z.writestr(name, text)
        for root, dirs, files in os.walk(car_dir):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in sorted(files):
                full = os.path.join(root, name)
                rel = os.path.relpath(full, os.path.dirname(car_dir)).replace("\\", "/")
                z.write(full, "content/cars/" + rel)
    with open(args.zip, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    size = os.path.getsize(args.zip)
    with open(os.path.splitext(args.zip)[0] + ".sha256", "w", encoding="utf-8") as f:
        f.write("%s  %s\n" % (sha, os.path.basename(args.zip)))
    print("wrote %s (%d bytes)" % (args.zip, size))
    print("sha256", sha)


if __name__ == "__main__":
    main()
