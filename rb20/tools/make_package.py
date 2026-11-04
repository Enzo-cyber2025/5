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
   .../Steam/steamapps/common/assettocorsa/content/cars/arb_rb20
   (ou extraia o ZIP dentro da raiz do AC, mantendo "content/cars/...").
2. Abra o AC (launcher original ou Content Manager) e selecione "ARB RB20 2024".
   Nao e necessario Custom Shaders Patch, Sol, fisica estendida, data.acd nem Lua.
3. Mapeie os botoes DRS e KERS/ERS em Opcoes -> Controles.

POTENCIA OFICIAL
----------------
805 kW (1.080 hp) e o pico combinado publicado para a RB20 / Honda RBPTH002:
685 kW do ICE (power.lut) + 120 kW do MGU-K (kers_torque.lut, limite FIA 2024).
A FIA permite apenas 4 MJ de deploy por volta (33,33 s a 120 kW) e 2 MJ de
recuperacao, entao numa volta de classificacao a media eletrica e menor que o
pico. O arrasto e a downforce foram reajustados por minimos quadrados a partir
da telemetria real COM a potencia oficial fixa. Veja VALIDACAO.md e
calibration.json (fontes: README.md / REFERENCIAS.md no repositorio).

ERS (NATIVO, SEM CSP)
---------------------
Arquivos: data/ers.ini, data/ctrl_ers_0..2.ini, data/kers_torque.lut,
data/kers_torque_coast.lut e as LUTs de controle.
- 3 modos no cockpit: Charge, Balanced, Hotlap (seletor "ERS delivery").
- Botao KERS/overtake = deploy maximo imediato de 120 kW.
- Carga limitada a 33,33 s de deploy continuo (4 MJ por volta).
- MGU-K recupera energia na frenagem (2 MJ/volta) com correcao no eixo traseiro.

DRS FUNCIONAL (NATIVO, SEM CSP)
-------------------------------
Arquivos: data/drs.ini (VERSION=2), data/wing_animations.ini (vanilla),
animations/rb20_drs.ksanim (13 keyframes, formato binario vanilla v2),
data/digital_instruments.ini (secoes DRS_AVAILABLE_0 / DRS_ENABLED_0).
- Pressione o botao "DRS" mapeado nos controles: o flap WING_4 vai de 12 graus
  (fechado) a 0 (aberto), a aerodinamica muda E A MALHA GIRA de verdade em
  torno da dobradica. O AC associa o angulo da asa aos keyframes do .ksanim.
- Dois LEDs no volante acendem: "DRS disponivel" e "DRS ativo", como no carro
  real (digital_instruments.ini e nativo do ACD, nao e CSP).
- IGNORE_ZONES=1: funciona em QUALQUER pista vanilla, sem editar o circuito.
- Aberto: CdA cai ~13% e a downforce ~15%; ganho de velocidade em VALIDACAO.md.

LUZ TRASEIRA (COMPORTAMENTO DE F1 REAL)
---------------------------------------
Arquivo: data/lights.ini (VERSION=3, chaves vanilla). Quatro emissores de malha
independentes: luz central principal, luz central de chuva e dois repetidores
nas placas laterais da asa traseira.
- [BRAKE_0] -> luz central principal: fica mais forte ao frear.
- [LIGHT_0] -> luz de chuva: LIGUE AS LUZES DO CARRO ao usar Intermediate ou
  Full Wet. O regulamento desportivo FIA 2024 art. 26.11 obriga a luz traseira
  a estar acesa SEMPRE com pneus intermediarios/de chuva. O AC vanilla nao
  consegue detetar o composto automaticamente (isso exigiria CSP/Lua), entao
  a acao do piloto e documentada em vez de fingirmos automacao.
- [LIGHT_1] / [LIGHT_2] -> repetidores nas endplates com KERS=1 e
  KERS_BLINKING=1: PICAM durante a recuperacao de energia do MGU-K/ERS,
  exatamente como os carros de F1 reais. SPECIAL=1 impede que o interruptor
  de luzes apague esse comportamento.
- Sem shaders _emissive, sem ext_config.ini, sem dados AC_RAIN/RainFX.

PNEUS DE CHUVA
--------------
5 compostos selecionaveis no setup: Soft, Medium, Hard, Cinturato Intermediate
e Cinturato Full Wet. Os de chuva tem raio maior, aderencia menor, maior
resistencia ao rolamento e temperatura ideal mais baixa.
IMPORTANTE: o AC vanilla NAO tem chuva dinamica (isso exigiria CSP/RainFX,
que nao usamos). Os pneus existem e tem a fisica de pista molhada, mas a
condicao da pista nao muda sozinha no jogo base.

ESTRUTURA DO CARRO (PADRAO KUNOS)
---------------------------------
content/cars/arb_rb20/
  arb_rb20.kn5 + arb_rb20_LOD_B/C/D.kn5 + collider.kn5
  logo.png, body_shadow.png, tyre_0..3_shadow.png
  animations/  steer.ksanim, rb20_drs.ksanim
  data/        todos os INIs/LUTs (inclui driver3d.ini, cameras.ini,
               dash_cam.ini, escmode.ini, fuel_cons.ini, blurred_objects.ini,
               proview_nodes.ini, suspension_graphics.ini, lights.ini,
               digital_instruments.ini, wing_animations.ini)
  sfx/         GUIDs.txt (banco comum), backfire*.wav sinteticos
               e LEIA-ME-SOM.txt
  skins/       default/preview.jpg, livery.png, ui_skin.json, *.dds
  texture/     display.png, display_off.png
  ui/          ui_car.json, badge.png, logo.png, preview_small.png,
               old_badge.png, upgrade.png, dlc_preview.png

O ZIP contem SOMENTE content/; este LEIA-ME, VALIDACAO.md e REFERENCIAS.md
ficam dentro da pasta do carro, sem espalhar arquivos na raiz do AC.
Layout espelhado no template F1 da Kunos (formula_k). CORRECAO DE CRASH:
os 4 LODs sao copias integrais do KN5 (nenhum no de roda/luz ausente),
os .ksanim usam geometria local ao pivo e translacao constante, e foram
REMOVIDOS os arquivos que o AC carrega sozinho e nao podemos validar sem
o jogo (driver_base_pos.knh, flames.ini/DDs de chama, analog_instruments.ini,
shift.ksanim, secoes ITEM_n do painel). Permanecem os arquivos inertes
(rto, LUTs, WAVs sinteticos, skin.ini, PNGs). Unica ausencia proprietaria:
o banco FMOD .bank. Nada disso depende de CSP.

O QUE ESTA INCLUSO
------------------
- Modelo 3D original (KN5 v5 vanilla), asas, halo, difusor, sidepods,
  suspensao e cockpit; texturas DDS DXT1 embutidas.
- data/ aberto (nao criptografado) com todos os INIs/LUTs: car, engine,
  power, coast, drivetrain, suspensions, tyres (5 compostos), aero (5 asas),
  brakes, setup, electronics, ai, ers, drs, lights,
  digital_instruments, wing_animations e curvas de controle.
- animations/rb20_drs.ksanim: animacao visual nativa do flap do DRS.
- Fisica calibrada com telemetria REAL da pole de Verstappen no GP do Bahrein
  2024 (FastF1): cambio, torque, arrasto, downforce, aderencia e frenagem.

SEM CSP - POR CONSTRUCAO
------------------------
- Headers inteiros vanilla: car.ini 1, tyres.ini 7, aero.ini 3, drs.ini 2,
  ers.ini 1, suspensions/drivetrain 2, ai.ini 4.
- Somente shaders vanilla ksPerPixel. Sem ext_config.ini, sem extension/,
  sem data.acd, sem Lua, sem fisica estendida, sem shaders _emissive.

LIMITACOES HONESTAS
-------------------
- Nao ha banco FMOD proprio: o AC pode usar o fallback de audio do jogo.
- A luz de chuva NAO e automatica: tem de ligar as luzes com pneus de chuva
  (limitacao do AC vanilla, documentada acima).
- Chuva dinamica e MGU-H detalhado exigiriam CSP; nao foram usados.
- Modelo e livery originais, SEM logos ou marcas de equipe. Projeto de fa.
- Este mod NAO foi executado dentro do Assetto Corsa neste ambiente (sem
  jogo/Windows). Validacao: KN5 round-trip, parsing de INIs/LUTs, varredura
  anti-CSP e simulacao numerica offline contra a telemetria (VALIDACAO.md).

RECONSTRUIR (GitHub Actions com Blender)
---------------------------------------
O workflow .github/workflows/rb20-mod.yml instala o Blender (bpy), modela o
carro, calibra a fisica, gera ERS/DRS/pneus de chuva, luzes de F1 e a
animacao .ksanim do flap, gera os KN5, valida e produz este ZIP.
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
        sim["accel_times_s"].get("100"), sim["accel_times_s"].get("200"), sim["accel_times_s"].get("300"))
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
    op = vr.get("official_power", {})
    validacao += "\nPOTENCIA OFICIAL, ERS, DRS E PNEUS DE CHUVA\n"
    validacao += "- Pico combinado publicado ....... %.0f kW (%.0f hp)\n" % (
        op.get("published_rb20_combined_kw", 0), op.get("published_rb20_hp", 0))
    validacao += "- ICE %.0f kW + MGU-K %.0f kW = %.1f kW lidos das curvas entregues\n" % (
        op.get("ice_kw", 0), op.get("mguk_kw", 0),
        op.get("combined_peak_kw_from_shipped_luts", 0))
    validacao += "- ERS: %.0f MJ/volta = %.2f s a 120 kW; fracao media na volta %.3f\n" % (
        op.get("ers_deploy_mj_per_lap", 0), op.get("full_deploy_seconds_per_lap", 0),
        op.get("lap_average_deploy_fraction", 0))
    ersr = vr.get("ers", {})
    validacao += "- 0-300 km/h: so ICE %s s / volta %s s / deploy pleno %s s\n" % (
        ersr.get("ice_only", {}).get("marks_s", {}).get("300", "-"),
        ersr.get("lap_average", {}).get("marks_s", {}).get("300", "-"),
        ersr.get("full_deploy", {}).get("marks_s", {}).get("300", "-"))
    drsr = vr.get("drs", {})
    validacao += "- DRS: CdA %.3f -> %.3f, CLA %.3f -> %.3f, ganho %.1f km/h\n" % (
        drsr.get("closed_CdA", 0), drsr.get("open_CdA", 0),
        drsr.get("closed_CLA", 0), drsr.get("open_CLA", 0),
        drsr.get("top_speed_gain_kmh", 0))
    wtr = vr.get("wet_tyres", {})
    validacao += "- Pneus: mu slick %.3f / intermediate %.3f / full wet %.3f\n" % (
        wtr.get("slick_mu", 0), wtr.get("intermediate_mu", 0), wtr.get("full_wet_mu", 0))
    validacao += "- Frenagem 300->0: %.1f m (slick) / %.1f m (wet); lateral @260 wet %.2f g\n" % (
        wtr.get("braking_300_to_0_slick_m", 0), wtr.get("braking_300_to_0_wet_m", 0),
        wtr.get("lateral_g_260_wet", 0))
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
    car_id = os.path.basename(os.path.normpath(car_dir))
    with zipfile.ZipFile(args.zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        # A standard AC car ZIP has only the content/ tree at its root. The
        # documentation travels inside the car folder, like a Kunos car's own
        # readmes, instead of scattering files into the AC installation root.
        for name, text in docs.items():
            z.writestr("content/cars/%s/%s" % (car_id, name), text)
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
