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
