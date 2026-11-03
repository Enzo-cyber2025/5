# ARB RB20 2024 — mod de Assetto Corsa (vanilla, sem CSP)

Mod de carro de F1 2024 inspirado no **RB20**, com modelo 3D original feito em
**Blender dentro de um runner do GitHub Actions**, física calibrada com
**telemetria real** da volta da pole de Verstappen no GP do Bahrein 2024 e
**nenhuma dependência de Custom Shaders Patch**.

> Projeto de fã, não oficial. Sem logos, marcas ou pintura de equipe. Nenhum
> arquivo de terceiros é redistribuído dentro do mod.

---

## 📦 Download

**Link direto (Release, gerado pelo runner do GitHub Actions):**

https://github.com/Enzo-cyber2025/5/releases/download/rb20-v1.0/RB20_AssettoCorsa.zip

Espelho no branch: `rb20/download/RB20_AssettoCorsa.zip` (609.500 bytes,
SHA-256 `7d4a2453e2958758111f377a37dfcb5e1a378c6aad7aee61801014e2866e636f`).

O ZIP contém `content/cars/arb_rb20/` pronta para extrair na raiz do Assetto
Corsa, mais `LEIA-ME.txt`, `VALIDACAO.md` e `REFERENCIAS.md`. O KN5 entregue
tem 32.604 triângulos (o Bevel/WeightedNormal do Blender aumentou a malha de
9.336 triângulos da geometria base), 127 objetos, 9 texturas DDS DXT1 e apenas
o shader vanilla `ksPerPixel`.

## 🎮 Instalação

Copie `content/cars/arb_rb20` para
`.../steamapps/common/assettocorsa/content/cars/arb_rb20` e abra o jogo
(launcher original **ou** Content Manager, tanto faz). Selecione **ARB RB20 2024**.

Não instale CSP, Sol, Lua, `data.acd` ou "extended physics": nada disso é
necessário e nada disso é usado.

---

## 🧊 Blender no GitHub Actions

Workflow: [`.github/workflows/rb20-mod.yml`](../.github/workflows/rb20-mod.yml)

```
checkout → setup-python 3.11 → apt (libs X/GL) → pip install bpy==4.5.4
        → blender_model.py   (MODELA O CARRO EM BLENDER, headless)
        → calibrate.py       (física a partir da telemetria real)
        → make_kn5.py        (FBX/mesh.json → KN5 v5 vanilla + texturas DDS)
        → render_preview.py  (preview.jpg / badge.png)
        → physics_sim.py     (validação numérica offline)
        → make_package.py    (ZIP)
        → validate.py        (gate: estrutura + anti-CSP + física)
        → upload-artifact (ZIP, .blend, .fbx, mesh.json, relatórios)
```

`tools/blender_model.py` roda com a API `bpy` do Blender: cria 127 objetos a
partir de `tools/mesh_core.py`, aplica modificadores reais **Bevel** e
**WeightedNormal**, triangula com `bmesh`, extrai posições/normais/UVs e exporta
`mesh.json` (e salva `.blend` + `.fbx` editáveis como artefato). O KN5 entregue
é gerado **a partir dessa saída do Blender**.

Executar localmente (sem Actions) também funciona: se `mesh.json` não existir,
`make_kn5.py` usa a geometria paramétrica diretamente.

```bash
python -m pip install bpy==4.5.4 pillow numpy matplotlib
python rb20/tools/blender_model.py --out rb20/out
python rb20/tools/calibrate.py --telemetry rb20/telemetry/VER_2024_Bahrain_Q.csv \
       --car-dir rb20/out/content/cars/arb_rb20
python rb20/tools/make_kn5.py --mesh rb20/out/mesh.json \
       --car-dir rb20/out/content/cars/arb_rb20 \
       --skins-dir rb20/out/content/cars/arb_rb20/skins/default
python rb20/tools/render_preview.py --mesh rb20/out/mesh.json \
       --car-dir rb20/out/content/cars/arb_rb20
python rb20/tools/physics_sim.py --car-dir rb20/out/content/cars/arb_rb20 \
       --telemetry rb20/telemetry/VER_2024_Bahrain_Q.csv --out rb20/out/validation
python rb20/tools/make_package.py --car-dir rb20/out/content/cars/arb_rb20 \
       --validation rb20/out/validation/validation_report.json \
       --references rb20/references/REFERENCES.md \
       --zip rb20/download/RB20_AssettoCorsa.zip
python rb20/tools/validate.py --car-dir rb20/out/content/cars/arb_rb20 \
       --validation rb20/out/validation/validation_report.json \
       --zip rb20/download/RB20_AssettoCorsa.zip --out rb20/out/validate_report.json
```

---

## 📈 Física calibrada com telemetria real

Fonte: [`telemetry/VER_2024_Bahrain_Q.csv`](telemetry/VER_2024_Bahrain_Q.csv)
— 702 amostras, 89,179 s, 5.367 m, FastF1, classificação do Bahrein 2024, VER.
Detalhes e atribuição em [`telemetry/SOURCES.md`](telemetry/SOURCES.md).

Ajustes por mínimos quadrados (código em `tools/calibrate.py`, resultados em
`content/cars/arb_rb20/calibration.json`):

| Grandeza | Valor | Como saiu da telemetria |
|---|---:|---|
| Relações de câmbio (8 marchas) | 4,655 … 12,5 (total) | mediana de `RPM / rotação da roda` por marcha + ajuste log-linear; rpm de troca 10.815 |
| μ do pneu slick | 1,624 | envelope de frenagem `decel = μg + c₁v²` |
| Frenagem de pico | 4,65 g | percentil 10 por faixa de velocidade |
| `CdA` | 0,980 m² | ajuste conjunto com a equação de potência |
| `CLA` (downforce) | 3,309 m² | combinada com a relação de frenagem |
| Potência efetiva sustentada | 483 kW | `m·a·v = P(rpm) − ½ρ(CdA+Crr·CLA)v³ − Crr·m·g·v` |
| Torque de pico | 462 Nm | `T = P/ω` → `power.lut` |
| Freio | 2.920 Nm/roda | limite de aderência a ~63 m/s + 25% de folga |

**Validação numérica offline** (lendo os `.ini`/`.lut` **entregues**, não os
atalhos da calibração) — `tools/physics_sim.py`, `out/validation/validation.png`:

| Métrica | Mod | Referência real |
|---|---:|---|
| Velocidade final | **322,6 km/h** | 322 km/h no Bahrein |
| 0–100 km/h | **2,63 s** | ~2,6 s (F1 2024) |
| 0–200 / 0–300 km/h | **5,25 s / 13,54 s** | ~5 s / ~13 s |
| Frenagem 300→0 | **116,2 m**, pico **4,66 g** | 4,65 g na telemetria |
| Aderência lateral @260 km/h | **3,82 g** | ~4 g em alta velocidade |
| Erro médio de aceleração | **1,18 m/s²** | — |
| Erro médio de frenagem | **4,06 m/s²** | — |

Arquivos de física: `car.ini` (798 kg, `INERTIA=2.00,0.95,5.60`), `engine.ini`
(15.000 rpm), `power.lut`/`coast.lut`, `drivetrain.ini` (8 marchas, diferencial),
`suspensions.ini` (DWB + heave springs, WHEELBASE 3,6 m), `tyres.ini` v7 com
**3 compostos** (térmica, desgaste, pressão, camber, load sensitivity),
`aero.ini` (4 asas, LUTs de AoA e de altura/efeito-solo), `brakes.ini`,
`setup.ini` (asas, pressões, alturas, molas, camber, brake bias),
`electronics.ini` (sem ABS/TC, como o regulamento), `ai.ini`.

> **Por que 483 kW e não os ~750 kW divulgados?** 1.021 hp é o pico de ICE+MGU-K
> em condição ideal. Numa volta de classificação o fluxo de combustível e o
> estado de carga do ERS limitam a potência *sustentada*, e os dados de timing
> da FastF1 são filtrados. Ajustar à telemetria reproduz 322 km/h, 2,63 s e
> 4,65 g de frenagem; usar o número de marketing sem aumentar o arrasto
> produziria um carro irreal. Tudo está documentado, não escondido.

## 🚫 Zero dependência de CSP

| Item | Estado |
|---|---|
| `car.ini` | `VERSION=1` (nunca `extended-2`) |
| `tyres.ini` | `VERSION=7` (vanilla Kunos SDK, não v10/CSP) |
| `aero.ini` / `suspensions.ini` / `drivetrain.ini` | `VERSION=3 / 2 / 2` |
| Shaders | apenas `ksPerPixel` (shader fallback do próprio ksEditor) |
| Texturas | DDS **DXT1** descomprimíveis pelo AC vanilla |
| `data/` | aberto, sem `data.acd` criptografado |
| `ext_config.ini`, `extension/`, `wing_controller.ini`, `.lua`, `physics/extended` | **ausentes** |
| DRS / ERS ajustável / chuva / física estendida | **não implementados** (exigiriam CSP) |

`tools/validate.py` varre todo o carro e o ZIP e **falha o build** se qualquer
token CSP aparecer, se um LUT/textura referenciado não existir, se o KN5 não
fizer round-trip ou se a validação de física não passar.

## 🖼️ Referências

Imagens de referência (launch/side/top/blueprint), modelos 3D de referência
(RB6 ortográfico, silhueta RB20 em STL, Formula K do SDK para *formato* de
arquivos) e dimensões publicadas: [`references/REFERENCES.md`](references/REFERENCES.md).

---

## ⚠️ Limitações honestas

1. **Não rodou no Assetto Corsa real.** Este ambiente é Linux, sem o jogo, sem
   Windows e sem licença do AC. O que foi executado de verdade: Blender
   headless no Actions, geração/leitura binária do KN5, parsing de todos os
   INIs/LUTs, varredura anti-CSP, rasterização do preview e uma simulação
   numérica longitudinal/lateral comparada com a telemetria. A última palavra
   sobre "aparece no showroom" só o seu AC pode dar — o `LEIA-ME.txt` explica
   como testar em 2 minutos.
2. **Sem banco de som FMOD próprio** (`.bank` proprietário não é redistribuído).
   O carro pode ficar sem som de motor ou cair no fallback do jogo; isso não
   afeta física nem compatibilidade.
3. **DRS, ERS gerenciável, chuva e animações de asa** não existem: são recursos
   de CSP/script. A contribuição elétrica está embutida na curva de torque real.
4. **É uma volta, um circuito, um piloto.** Não é um mapa de motor de fábrica
   nem dados de engenharia de equipe (isso é confidencial). Posição X/Y da
   FastF1 é grossa demais para aceleração lateral, então o grip lateral veio do
   envelope de frenagem + downforce.
5. **Modelo é uma interpretação original** (9.336 triângulos), não uma conversão
   de um mod existente. Sem logotipos ou pintura oficial.

---

## 🗂️ Estrutura

```
rb20/
├── README.md                     este arquivo
├── references/REFERENCES.md      imagens + modelos 3D de referência
├── telemetry/
│   ├── VER_2024_Bahrain_Q.csv    telemetria real
│   └── SOURCES.md                origem, licença e limitações
├── tools/
│   ├── mesh_core.py              geometria paramétrica original
│   ├── blender_model.py          Blender/bpy (roda no Actions)
│   ├── kn5format.py              writer/reader KN5 v5 próprio
│   ├── textures.py               DDS DXT1 + materiais ksPerPixel
│   ├── make_kn5.py               mesh.json → KN5 + collider
│   ├── calibrate.py              telemetria → todos os .ini/.lut
│   ├── physics_sim.py            validação offline contra telemetria
│   ├── render_preview.py         preview.jpg + badge.png (CPU)
│   ├── make_package.py           ZIP instalável
│   └── validate.py               gate anti-CSP / estrutura / física
├── download/RB20_AssettoCorsa.zip   ← ENTREGÁVEL
└── out/                         gerado (ignorado pelo git)
```
