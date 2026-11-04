# Potência oficial e formatos vanilla (DRS / ERS / chuva)

Documento de rastreabilidade para a mudança pedida: *"tem que ser os kW
oficiais"*, DRS, ERS e pneus de chuva **sem CSP**.

## 1. Potência do RB20 / Honda RBPTH002 (2024)

| Fonte | Valor | Observação |
|---|---|---|
| Liquipedia, *Red Bull Racing RB20* | **1.080 hp (805 kW)** | valor publicado para o carro de 2024; usado no mod |
| Wikipedia, *Honda V6 hybrid Formula One power unit* | **810 kW (1.080 hp)**, rotulado *est.* | confirma a ordem de grandeza para o RBPTH002 |
| Red Bull Racing, lançamento oficial do RB20 | Honda **RBPTH002**, ERS da Red Bull Powertrains, 8 marchas, 15.000 rpm | não publica kW |
| Mercedes-AMG F1, *W15 2024 Technical Specifications* | MGU-K **120 kW**, 4 MJ deploy/volta, 2 MJ recuperação/volta, 50.000 rpm, MGU-H ilimitado | especificação oficial de equipe, derivada do regulamento FIA |
| FIA, *2024 Formula 1 Technical Regulations*, art. 5 | define PU, ICE, ERS, MGU-K, MGU-H, ES | não fixa potência combinada |
| Comparações públicas (2024 vs 2026) | ICE **550–560 kW**, elétrico 120 kW | fonte secundária; conflita com o total publicado |
| Conceptcarz, *2024 Red Bull RB20 Specifications* | 740 bhp (544,64 kW) no ICE + 161 bhp elétrico | outra fonte divergente |

**Decisão:** o mod usa **805 kW (1.080 hp)** como pico combinado publicado do
RB20 — é o número "oficial" que existe publicamente. A FIA **não publica uma
potência combinada única**; 805 kW é um valor de carro, não uma homologação.
Como o regulamento limita o MGU-K a **120 kW**, o ICE resulta em **685 kW**
(`805 − 120`). Essa decomposição está implementada de verdade:
`power.lut` = ICE, `kers_torque.lut` = MGU-K, soma medida = **805,6 kW**.

O conflito com as fontes que citam 550–560 kW de ICE / ~750 kW combinados está
registrado aqui e em `calibration.json` (`official_power.note`). Não foi
"escolhido o maior número" sem física: a potência é fixa e o **arrasto** é que
foi reajustado por mínimos quadrados contra a telemetria (CdA 1,727 m²,
CLA 2,849 m²), e o deploy elétrico é limitado a 4 MJ/volta pela regra FIA
(33,33 s a 120 kW → fração média 0,374 na volta de 89,179 s do Bahrein).

Links:

- https://liquipedia.net/formula1/Red_Bull_Racing_RB20
- https://en.wikipedia.org/wiki/Honda_V6_hybrid_Formula_One_power_unit
- https://www.redbull.com/int-en/oracle-red-bull-racing-2024-launch-live-broadcast
- https://www.mercedesamgf1.com/f1-w15-2024-technical-specifications
- https://www.fia.com/sites/default/files/fia_2024_formula_1_technical_regulations_-_issue_2_-_2023-08-31.pdf
- https://www.conceptcarz.com/s33298/red-bull-rb20.aspx

## 2. DRS / ERS existem no AC vanilla (não são CSP)

Formatos confirmados em carros e ferramentas públicas de AC, usados **apenas
como referência de esquema** — nenhum arquivo de terceiros é copiado para o mod:

| Arquivo | Formato confirmado em |
|---|---|
| `drs.ini` (`[HEADER] VERSION=2`, `[WING_n] MODE=ANGLE/EFFECT`, `[DRS_ZONES] IGNORE_ZONES`, `[DEACTIVATION] LIMIT_G`) | `hitairou/AssettoCorsa_tu_ecoran_c50e` (`data/drs.ini` + `data/aero.ini`) |
| `ers.ini` (`VERSION=1`, `[KINETIC]` `CHARGE_K`, `TORQUE_CURVE`, `COAST_CURVE`, `DISCHARGE_TIME`, `HAS_BUTTON_OVERRIDE`, `MAX_KJ_PER_LAP`, `DEFAULT_CONTROLLER`, `BRAKE_REAR_CORRECTION`, `[HEAT]`, `[COCKPIT_CONTROLS]`) | `bryceacosta3272/Assetto-Corsa-Vehicle-Modifier` (`src/Default Files/ers.ini`) e `Okynawah/assettoCorsaFiestaMK8Synik` |
| `ctrl_ers_N.ini` (`[CONTROLLER_n]` com `INPUT=GAS/GEAR/SLIPRATIO_MAX`, `COMBINATOR=ADD/MULT`, `LUT`, `FILTER`, `UP/DOWN_LIMIT`) | mesmos repositórios |
| `kers_torque.lut` = **Nm por rpm do motor** | `acclub/main` (`acc_mazda_rx7_time_attack/kers.ini` + `kers_torque.lut`) |
| Tutorial "How to add DRS and ERS (hybrid system) in any car" | https://www.reddit.com/r/assettocorsa/comments/ymo6c6/ |
| SF15-T da Kunos: botão KERS, modos MGU-H, DRS como modificadores nativos | https://www.gtplanet.net/forum/threads/assetto-corsa-news-and-general-discussion.236693/page-261 |

Esses arquivos usam `VERSION=1/2` inteiros — o mesmo padrão dos carros Kunos.
CSP *extended physics* (`VERSION=extended-2`, `ext_config.ini`, `.lua`,
`data.acd`, `RainFX`) continua **proibido** pelo `tools/validate.py`.

## 3. Pneus de chuva no AC vanilla

Compostos extras em `tyres.ini` (`[FRONT_n]` / `[REAR_n]` +
`[THERMAL_FRONT_n]` / `[THERMAL_REAR_n]`, `VERSION=7`) são o mecanismo nativo
de múltiplos compostos do AC e aparecem no setup. O que **não** é nativo é a
**chuva dinâmica** (condição de pista variável): isso depende do CSP/RainFX.
Por isso os compostos Intermediate/Full Wet têm aderência, raio, rolamento e
curva térmica próprios, mas o clima da pista não muda sozinho no jogo base.
Isso está declarado no `LEIA-ME.txt` e neste README.

## 4. Licenças

Os repositórios acima foram consultados apenas para entender o **formato** dos
arquivos. Suas licenças são variadas (alguns `NO-LICENSE`); nenhum `.ini`,
`.lut`, `.kn5`, `.ksanim`, malha ou textura deles foi incorporado ao ZIP.
Toda a física e a geometria deste mod são originais.


---

## Luz traseira e animação visual do DRS (v1.2)

Fontes consultadas (todas sobre o AC **vanilla**, não CSP):

- FIA 2024 Formula One **Sporting Regulations**, art. **26.11**: as luzes do
  art. 14.3 devem estar iluminadas **sempre** que se usam pneus intermediate ou
  wet. `https://www.fia.com/sites/default/files/fia_2024_formula_1_sporting_regulations_-_issue_4_-_2024-02-13.pdf`
  (e issue 1, 2023-09-26). Art. 14.3 das *Technical Regulations* define a luz
  traseira vermelha central.
- F1-Fansite "flashing backlight" e Yahoo Autos: a luz traseira também pisca
  durante o harvest do MGU-K/ERS e em baixa visibilidade; os repetidores ficam
  nas placas laterais da asa traseira.
- `https://labs.assettocorsa.jp/documents/reference/acd/lights`: `lights.ini`
  aceita `[HEADER] VERSION`, `FLASHING_BLINK_TIME`, `FLASHING_REPEAT`,
  `KERS_BLINKING`, `NO_LIGHT_SWITCH`; `[BRAKE_n] NAME/COLOR/OFF_COLOR`;
  `[LIGHT_n] NAME/COLOR/OFF_COLOR/FLASH/PITLINE/KERS/SPECIAL`.
  `https://www.scribd.com/document/501206878/AC-Pipeline-PUB-Rev2-0` (guia
  AC Pipeline da Kunos) mostra `[LIGHT_0] NAME=g_Rain_Lights COLOR=180,0,0
  PITLINE=1 KERS=1 SPECIAL=1`. Exemplos reais: `ohyeah2389/Assetto-T-180`
  e `wintersjp/Zero-Culture-Cosmic-Drift-Pack` (`VERSION=2/3`, `COLOR`,
  `OFF_COLOR`, `PITLINE=1`, `SPECIAL=1`, `INTENSITY`).
- `https://labs.assettocorsa.jp/documents/reference/acd/digital_instruments`:
  seções nativas `DRS_AVAILABLE_n`, `DRS_ENABLED_n`, `DRS_SERIE_n`,
  `KERS_CHARGE_SERIE_n`, `KERS_INPUT_SERIE_n`, `KERS_LOAD_SERIE_n`, `LED_n`,
  `RPM_SERIE_n`. Exemplo real: `hitairou/AssettoCorsa_tu_ecoran_c50e
  data/digital_instruments.ini` (`[DRS_ENABLED_0] OBJECT_NAME=... EMISSIVE
  BLINK_TIME`).
- `https://www.overtake.gg/threads/how-to-create-a-wing-animation-in-assetto-corsa.237307/`
  e `https://www.overtake.gg/threads/wing-animation-with-setup-click.262833/`:
  `wing_animations.ini` + `.ksanim` são **vanilla** e ligam `WING=n` ao
  `FILE=...`, com `MIN/MAX` em graus, `SPEED`, `NEXT`, `INVERTED`. Confirmado
  em carros sem física estendida: `rick-lg/Lazy-Gecko-AC cars/prs_box`
  (`car.ini VERSION=2`) e `tfuruha/gokart_ev` (`VERSION=1`). Exemplo real:
  `Gemicaiz/AC_Car_Editor examples/data/wing_animations.ini`
  (`[ANIMATION_0] WING=3 FILE=car_wing.ksanim MIN=0 MAX=13`).
- Formato binário `.ksanim` v2 confirmado por parsing dos arquivos reais em
  `Gemicaiz/AC_Car_Editor examples/audi_A5_teamsesh/animations/`:
  `int32 version=2`, `int32 nodeCount`, e por nó `int32 nameLen`,
  `char name[nameLen]`, `int32 frameCount`, `frameCount × 10 floats`
  = `quat(x,y,z,w) + pos(3) + scale(3)`. Identidade = `(0,0,0,1)`
  (verificado em `car_door_L.ksanim`); `car_wing.ksanim` e `car_wiper.ksanim`
  foram lidos até o último byte. O gerador está em `tools/features.py`.

**Limitação real**: AC vanilla não expõe o composto de pneu ao `lights.ini`.
A regra 26.11 é cumprida pelo piloto (ligar as luzes com pneus de chuva), não
por automação; automatizar exigiria CSP/Lua, que está fora do escopo.


---

## Layout padrão de `content/cars/<id>/` (v1.3)

Para alinhar a estrutura do mod aos carros oficiais, consultamos a árvore
completa do template open-wheel da Kunos `EXAMPLE/formula_k` em
`https://github.com/javirs200/acCar` (GPL-3.0) e de
`daniruiz/AC_MAZDA_MX5-ND2` (`ks_mazda_mx5_nd2`). Ambos mostram que um
carro vanilla tem, além de `data/` + KN5:

- cadeia de LODs (`lods.ini` → `<car>.kn5`, `<car>_LOD_B/C/D.kn5`),
  `collider.kn5`, `logo.png`, `body_shadow.png`, `tyre_0..3_shadow.png`;
- `animations/` (`steer.ksanim`, `shift.ksanim`, suspensões, portas, limpadores);
- `data/driver3d.ini`, `cameras.ini`, `dash_cam.ini`, `escmode.ini`,
  `fuel_cons.ini`, `blurred_objects.ini`, `proview_nodes.ini`,
  `suspension_graphics.ini`, `sounds.ini`, `mirrors.ini`, `damage.ini`;
- `sfx/GUIDs.txt` (+ banco FMOD), `skins/<skin>/preview.jpg`, `ui_skin.json`,
  `livery.png`, `*.dds`, `texture/display.png`, `ui/ui_car.json`,
  `badge.png`, `preview_small.png`.

O `formula_K_LOD_C.kn5` também foi lido com o nosso parser para confirmar a
hierarquia Kunos: um dummy raiz, dummies por objeto (`WING_REAR`,
`WING_REAR_MOBILE`, `REAR_LIGHT`, `STEER_HR`, `WHEEL_LF` com filhos
`TYRE_LF`/`RIM_LF`/`RIM_BLUR_LF`) e nós de malha com o mesmo nome do dummy ou
sufixo `_SUBn`. Nossas malhas de luz/painel mantêm nomes distintos (`_MESH`)
porque `lights.ini`/`digital_instruments.ini` precisam resolver um nó que
realmente tenha material.

**O que não foi replicado** (opcional/binário proprietário): `driver_base_pos.knh`,
banco FMOD próprio, `texture/flames/*.dds`, `flames.ini`, `flame_presets.ini`,
`ratios.rto`/`final.rto` e `wing_controller_*.lut`. Nada disso é necessário
para o AC vanilla carregar o carro.


---

## Completando os arquivos vanilla não proprietários (v1.4)

O `.knh` da Kunos foi decodificado por parsing até o EOF: `int32 nameLen`,
`char name[nameLen]`, `16 floats` (matriz 4×4), `int32 childCount` e filhos
recursivos. O `driver_base_pos.knh` entregue é **gerado** com essa estrutura e
uma árvore mínima original — nenhum dado de rig de terceiros é copiado.

Os DDS de chama do `formula_k` são DXT5 64×64 com mipmaps; para manter tudo
original e legível pelo AC vanilla, geramos `texture/flames/*.dds` em
**A8R8G8B8 não comprimido** (header DirectX padrão de 128 bytes, máscaras
RGBA, um nível de mip), com gradientes de chama procedurais. `flames.ini` e
`flame_presets.ini` usam apenas chaves vanilla.

`ratios.rto` / `final.rto`, `wing_controller_speed.lut` /
`wing_controller_brake.lut` e `analog_speed_curve.lut` são tabelas de texto
vanilla; as primeiras são derivadas das relações de câmbio ajustadas por
telemetria no próprio `drivetrain.ini`. `wing_controller.ini` (CSP) continua
proibido pelo gate — as **LUTs** `wing_controller_*.lut` são Kunos vanilla e
foram liberadas separadamente.

`sfx/backfire_*.wav` são PCM RIFF mono 16-bit sintéticos (ruído com decaimento
exponencial), `animations/shift.ksanim` e `car_shift.ksanim` são `.ksanim` v2
gerados, e os PNGs de UI (`old_badge.png`, `upgrade.png`, `dlc_preview.png`)
são derivados dos nossos próprios `badge.png`/`preview_small.png`.

**Único item não entregue:** o banco FMOD `.bank`. É um formato proprietário
produzido pelo FMOD Studio; não é gerável nem redistribuível. O carro referencia
apenas `bank:/common` em `sfx/GUIDs.txt`. Continua sem CSP, sem Lua, sem
`data.acd`, sem física estendida.
