# ARB RB20 2024 — mod de Assetto Corsa (vanilla, sem CSP)

Mod de F1 2024 inspirado no **RB20**, com modelo 3D original feito em
**Blender dentro de um runner do GitHub Actions**, física calibrada com
**telemetria real**, **potência oficial publicada de 805 kW**, **ERS**, **DRS** e
**pneus de chuva** — tudo nativo do AC vanilla, **nenhuma dependência de CSP**.

> Projeto de fã, não oficial. Sem logos, marcas ou pintura de equipe. Nenhum
> arquivo de terceiros é redistribuído dentro do mod.

---

## 📦 Download

**Link direto (Release, gerado pelo runner do GitHub Actions):**

https://github.com/Enzo-cyber2025/5/releases/download/rb20-v1.0/RB20_AssettoCorsa.zip

Espelho no branch: `rb20/download/RB20_AssettoCorsa.zip` (2.258.269 bytes,
SHA-256 `4cac80fc0969ab02d88a4580603c24240c3cd0081f4be9fad60d8bf5806a429c`).
O asset da Release é sempre o ZIP reconstruído pelo Actions (modelado no
Blender). O ZIP contém `content/cars/arb_rb20/` pronta para extrair na raiz do
AC, mais `LEIA-ME.txt`, `VALIDACAO.md` e `REFERENCIAS.md`.

## 🎮 Instalação

Copie `content/cars/arb_rb20` para
`.../steamapps/common/assettocorsa/content/cars/arb_rb20` e abra o jogo
(launcher original **ou** Content Manager). Selecione **ARB RB20 2024**.
Não instale CSP, Sol, Lua, `data.acd` ou física estendida: nada disso é usado.

**Controles:** mapeie **DRS** e **KERS/ERS** em Opções → Controles. No cockpit,
o seletor *ERS delivery* alterna `Charge → Balanced → Hotlap`; o botão KERS dá
deploy máximo imediato (overtake).

---

## ⚡ Potência oficial: 805 kW

| Grandeza | Valor | Origem |
|---|---:|---|
| Pico combinado publicado RB20 / Honda RBPTH002 | **805 kW (1.080 hp)** | Liquipedia RB20; Wikipedia *Honda V6 hybrid F1 power unit* cita 810 kW (est.) |
| MGU-K (elétrico) | **120 kW** | Limite FIA 2024 / especificação oficial Mercedes W15 |
| ICE (combustão) | **685 kW** | 805 − 120, derivado |
| Deploy ERS | **4 MJ/volta = 33,33 s a 120 kW** | Regulamento FIA 2024 |
| Recuperação MGU-K | **2 MJ/volta** | Regulamento FIA 2024 |

`power.lut` contém **somente o ICE** (685 kW, 654 Nm de pico).
`kers_torque.lut` contém o MGU-K (120 kW constantes de 3.000 ao limitador de
15.000 rpm). A soma das curvas entregues é **805,6 kW** — medida pelo validador,
não apenas escrita na UI.

**Por que a telemetria não "via" 805 kW o tempo todo?** Uma volta de
classificação de 89,179 s só permite 4 MJ de deploy elétrico, ou seja fração
média de 0,374 do MGU-K → ~730 kW no virabrequim em média. Antes o ajuste livre
por mínimos quadrados chegava a 483 kW *nas rodas*; agora a potência é **fixada
no número oficial** e é o **arrasto/downforce** que são ajustados aos dados reais
(`CdA = 1,727 m²`, `CLA = 2,849 m²`). A tensão entre número de marketing e
limite de energia por volta está modelada e documentada, não escondida.
Fontes e conflitos: [`references/POWER_AND_VANILLA_FEATURES.md`](references/POWER_AND_VANILLA_FEATURES.md).

---

## 🔋 ERS nativo (sem CSP)

`data/ers.ini` (`VERSION=1`), `ctrl_ers_0.ini` **Charge**, `ctrl_ers_1.ini`
**Balanced**, `ctrl_ers_2.ini` **Hotlap**, `kers_torque.lut`,
`kers_torque_coast.lut` e LUTs de controle (`GAS`, `GEAR`, `SLIPRATIO_MAX`).

- `DISCHARGE_TIME=33333` ms = 4 MJ ÷ 120 kW: a carga dura 33,33 s de deploy
  contínuo, como o regulamento.
- `HAS_BUTTON_OVERRIDE=1` → botão KERS/overtake ignora o perfil e entrega 120 kW.
- `BRAKE_REAR_CORRECTION=45` compensa o torque de recuperação no eixo traseiro.
- `[HEAT] TORQUE_PERC=0`: o MGU-H só recupera energia, não inventa torque extra
  acima do limite regulamentar de 120 kW.

## 🪽 DRS nativo (sem CSP)

`data/drs.ini` (`VERSION=2`) atua sobre a asa `WING_4`, o **flap traseiro**
separado em `aero.ini`. `MODE=ANGLE` leva o flap de 12° (fechado) a 0° (aberto),
onde as LUTs reduzem seu CL a 10% e seu CD a 30%. `IGNORE_ZONES=1` faz o DRS
funcionar em **qualquer pista vanilla**, sem editar arquivos de circuito.
Efeito medido: `CdA 1,727 → 1,509`, `CLA 2,849 → 2,413`, velocidade final
**319,6 → 334,3 km/h** com deploy pleno.

**DRS agora é funcional também no visual.** `data/wing_animations.ini` (formato
vanilla Kunos, não CSP) liga `WING=4` a `animations/rb20_drs.ksanim`, um
`.ksanim` v2 gerado pelo próprio build com 13 keyframes (quaternion x,y,z,w +
posição + escala). O AC mapeia o ângulo da asa 12°→0° nos frames e o flap **gira
de verdade** em torno da dobradiça. `data/digital_instruments.ini` usa as seções
nativas `DRS_AVAILABLE_0` / `DRS_ENABLED_0` para acender os dois LEDs no volante,
como no carro real. Os nós dummy e mesh do KN5 receberam nomes distintos — com
nomes duplicados o `lights.ini` resolve o dummy e nenhuma luz aparece.

## 🔴 Luz traseira — comportamento de F1 real

`data/lights.ini` (`VERSION=3`, chaves vanilla) controla quatro emissores de
malha independentes:

| Seção | Malha | Comportamento |
|---|---|---|
| `[BRAKE_0]` | `RAIN_LIGHT_MESH` | luz central traseira, mais forte ao frear |
| `[LIGHT_0]` | `RAIN_LIGHT_WET_MESH` | luz de chuva, acionada pelo interruptor de luzes |
| `[LIGHT_1]` `[LIGHT_2]` | `RAIN_LIGHT_L_MESH` / `_R_MESH` | `KERS=1 SPECIAL=1`: **piscam no harvest do MGU-K/ERS** |

`KERS_BLINKING=1`, `FLASHING_BLINK_TIME=0.15` e `FLASHING_REPEAT=8` são chaves
do ACD vanilla. O regulamento desportivo **FIA 2024, art. 26.11** exige a luz
traseira acesa **sempre** que se usam pneus Intermediate ou Full Wet. O AC
vanilla não tem vínculo composto→luz (isso exigiria CSP/Lua), portanto a regra
real é implementada como **ação documentada do piloto: ligar as luzes ao calçar
pneus de chuva**. O piscar na recuperação de energia é automático e nativo.
Sem shaders `_emissive`, sem `ext_config.ini`, sem `RainFX`.

## 🌧️ Pneus de chuva

`tyres.ini` ganhou os compostos **3** e **4**: *2024 Cinturato Intermediate*
(`SHORT_NAME=I3`, μ = 0,72 × slick, raio 362 mm) e *2024 Cinturato Full Wet*
(`W4`, μ = 0,56 × slick, raio 368 mm), com curvas próprias de desgaste,
temperatura (pico ~60 °C em vez de ~100 °C), maior resistência ao rolamento e
ângulo de limite menor. Selecionáveis no setup, como qualquer composto vanilla.

> **Limite honesto:** o AC vanilla **não tem chuva dinâmica** — isso exigiria
> CSP/RainFX, que recusamos. Os pneus existem e têm a física de pista molhada,
> mas a condição da pista não muda sozinha no jogo base.

---

## 🧊 Blender no GitHub Actions

Workflow: [`.github/workflows/rb20-mod.yml`](../.github/workflows/rb20-mod.yml)

```
checkout → setup-python 3.11 → apt (libs X/GL) → pip install bpy==4.5.4
        → blender_model.py   (MODELA O CARRO EM BLENDER, headless)
        → calibrate.py       (telemetria → INIs/LUTs + features.py)
        → make_kn5.py        (mesh.json → KN5 v5 vanilla + texturas DDS)
        → render_preview.py  (preview.jpg / badge.png)
        → physics_sim.py     (validação: potência, ERS, DRS, chuva, telemetria)
        → make_package.py    (ZIP)
        → validate.py        (gate: estrutura + anti-CSP + física + recursos)
        → publicação da Release + ZIP no branch
```

`tools/features.py` é chamado ao final de `calibrate.py` e escreve todos os
arquivos nativos de ERS/DRS/compostos de chuva, além de atualizar `ui_car.json`
e `calibration.json`. O KN5 é gerado a partir da saída do Blender (33.684
triângulos com Bevel/WeightedNormal, 137 objetos, 10 texturas DXT1) e o
build deriva os três LODs reduzidos a partir da mesma malha.

---

## 📈 Física e validação offline

Fonte: [`telemetry/VER_2024_Bahrain_Q.csv`](telemetry/VER_2024_Bahrain_Q.csv)
— 702 amostras, 89,179 s, 5.367 m, FastF1, classificação do Bahrein 2024, VER.

| Grandeza | Valor | Como saiu |
|---|---:|---|
| Relações de câmbio (8 marchas) | 4,655 … 12,5 (total) | mediana `RPM/rotação da roda`, ajuste log-linear; troca a 10.815 rpm |
| μ do pneu slick | 1,624 | envelope de frenagem `decel = μg + c₁v²` |
| Frenagem de pico | 4,65 g | percentil 10 por faixa de velocidade |
| `CdA` / `CLA` | **1,727 / 2,849 m²** | mínimos quadrados com **potência oficial fixa** + relação de frenagem |
| Potência | **805 kW** (685 ICE + 120 MGU-K) | número publicado + limite FIA, não ajustado |
| Torque ICE de pico | 654 Nm | `T = P/ω` → `power.lut` |
| Freio | 2.710 Nm/roda | limite de aderência + 25% de folga |

Validação numérica lendo os `.ini`/`.lut` **entregues** (`physics_sim.py`):

| Métrica | Mod | Referência |
|---|---:|---|
| Velocidade final (volta) | **309,3 km/h** | 322 km/h no Bahrein |
| Só ICE / deploy pleno / deploy pleno + DRS | **302,8 / 319,6 / 334,3 km/h** | — |
| 0–100 / 0–200 / 0–300 | **2,69 / 5,16 / 12,60 s** | ~2,6 / ~5 / ~13 s |
| Frenagem 300→0 (slick) | **116,1 m**, pico **4,76 g** | 4,65 g na telemetria |
| Frenagem 300→0 (full wet) | **189,3 m** | — |
| Aderência lateral @260 (slick / wet) | **3,51 / 1,98 g** | ~4 g em alta velocidade |
| Erro médio aceleração / frenagem | **1,81 / 3,88 m/s²** | — |

O gate `validate.py` exige 10 checks, incluindo pico combinado 805 kW lido das
curvas, DRS reduzindo arrasto/downforce, ERS melhorando 0–300 e compostos de
chuva com menos aderência.

## 🚫 Zero dependência de CSP

| Item | Estado |
|---|---|
| Headers | `car.ini=1`, `tyres.ini=7`, `aero.ini=3`, `drs.ini=2`, `ers.ini=1`, `suspensions/drivetrain=2`, `ai.ini=4` |
| Shaders / texturas | apenas `ksPerPixel`; DDS DXT1 |
| `data/` | aberto, sem `data.acd` |
| `ext_config.ini`, `extension/`, `wing_controller.ini`, `.lua`, `physics/extended`, `_emissive` | **ausentes** (`wing_animations.ini` é vanilla e está presente) |
| DRS / ERS / pneus de chuva / luz / flap | **nativos vanilla** (`drs.ini`, `ers.ini`, `tyres.ini`, `lights.ini`, `wing_animations.ini` + `.ksanim`, `digital_instruments.ini`) |
| Chuva dinâmica / RainFX / física estendida | **ausentes** (exigiriam CSP) |

---

## ⚠️ Limitações honestas

1. **Não rodou no Assetto Corsa real.** Ambiente Linux, sem o jogo. O que foi
   executado: Blender headless no Actions, leitura/round-trip do KN5, parsing de
   todos os INIs/LUTs, varredura anti-CSP, rasterização do preview e simulação
   numérica contra telemetria. A última palavra sobre o showroom é do seu AC.
2. **Sem banco FMOD próprio** (`.bank` proprietário não redistribuído).
3. **A luz de chuva não é automática.** A FIA manda acendê-la com pneus de
   chuva; no AC vanilla não há como ler o composto sem CSP, então o piloto liga
   as luzes. O piscar no harvest do ERS é automático.
4. **Sem chuva dinâmica.** Os compostos de chuva existem; a pista não fica
   molhada sozinha no AC vanilla.
5. **É uma volta, um circuito, um piloto.** Não é mapa de motor de fábrica nem
   dados confidenciais de equipe. A FIA/Red Bull não publicam uma potência
   combinada única "oficial": 805 kW é o valor publicado para a RB20; outras
   fontes citam 550–560 kW de ICE e ~750 kW combinados. Conflito documentado.
6. **Modelo é interpretação original**, sem logotipos ou pintura oficial.

## 🗂️ Estrutura (layout Kunos padrão)

O ZIP contém **apenas** `content/`, como um carro oficial. A documentação vai
dentro da pasta do carro, e não solta na raiz do AC:

```
content/cars/arb_rb20/
├── arb_rb20.kn5                    modelo principal (Blender → KN5 v5)
├── arb_rb20_LOD_B.kn5              ┐
├── arb_rb20_LOD_C.kn5              ├ cadeia de LOD de data/lods.ini
├── arb_rb20_LOD_D.kn5              ┘
├── collider.kn5
├── logo.png                        (também em ui/)
├── driver_base_pos.knh             rig mínimo gerado (formato vanilla)
├── body_shadow.png
├── tyre_0_shadow.png … tyre_3_shadow.png
├── animations/
│   ├── steer.ksanim                volante (driver3d.ini)
│   ├── shift.ksanim, car_shift.ksanim
│   └── rb20_drs.ksanim             flap do DRS (wing_animations.ini)
├── data/
│   ├── car.ini, engine.ini, drivetrain.ini, suspensions.ini, brakes.ini
│   ├── tyres.ini, aero.ini, setup.ini, electronics.ini, ai.ini
│   ├── ers.ini, ctrl_ers_0..2.ini, kers_*.lut
│   ├── drs.ini, wing_animations.ini, aero_drs_*.lut
│   ├── lights.ini, digital_instruments.ini
│   ├── driver3d.ini, cameras.ini, dash_cam.ini, escmode.ini
│   ├── fuel_cons.ini, blurred_objects.ini, proview_nodes.ini
│   ├── suspension_graphics.ini, sounds.ini, damage.ini, colliders.ini
│   ├── mirrors.ini, ambient_shadows.ini, lods.ini
│   ├── flames.ini, flame_presets.ini, analog_instruments.ini
│   ├── ratios.rto, final.rto       opções de câmbio (telemetria)
│   ├── *.lut                       curvas de potência/aero/pneu/ERS,
│   │                               wing_controller_*, analog_speed_curve
│   └── calibration.json            metadado do build (não é lido pelo AC)
├── sfx/
│   ├── GUIDs.txt                   banco comum do AC
│   ├── backfire_1..11.wav, backfireEXT_1..9.wav  (sintéticos, originais)
│   └── LEIA-ME-SOM.txt
├── skins/default/
│   ├── preview.jpg, livery.png, ui_skin.json, skin.ini
│   └── *.dds                       texturas repintáveis
├── texture/                        display.png, display_off.png,
│                                   flames/*.dds + 7.png / 8.png
├── ui/                             ui_car.json, badge.png, logo.png,
│                                   preview_small.png, old_badge.png,
│                                   upgrade.png, dlc_preview.png
├── LEIA-ME.txt, VALIDACAO.md, REFERENCIAS.md
```

Referência de layout: o template open-wheel da Kunos `formula_k`
(`javirs200/acCar`, GPL-3.0) e `ks_mazda_mx5_nd2`. **Nenhum arquivo binário de
terceiros é copiado**: o `.knh` (árvore nome + matriz 4×4), os `.dds` das chamas
(A8R8G8B8), os `.wav` (PCM sintético), os `.ksanim` (v2), `.rto`, `.lut`,
`.ini` e PNGs são **gerados pelo build** a partir dos nossos próprios dados.

O único item que continua ausente é o **banco FMOD `.bank` proprietário**:
o formato é fechado e exige o FMOD Studio, então não pode ser gerado nem
redistribuído. O carro usa `sfx/GUIDs.txt` com o banco comum do AC e o fallback
de áudio do jogo — sem CSP. Fora isso, todos os arquivos vanilla não
proprietários dos carros padrão estão presentes.

Árvore do repositório (código-fonte, **não** o carro instalado):

```
rb20/
├── README.md
├── references/         REFERENCES.md + POWER_AND_VANILLA_FEATURES.md
├── telemetry/          VER_2024_Bahrain_Q.csv + SOURCES.md
├── tools/              mesh_core, blender_model, kn5format, textures,
│                       make_kn5, render_preview, calibrate, features,
│                       layout, physics_sim, make_package, validate
├── download/RB20_AssettoCorsa.zip   ← ENTREGÁVEL
└── out/                gerado (ignorado)
```
