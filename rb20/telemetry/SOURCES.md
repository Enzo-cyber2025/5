# Telemetria real usada na calibração

## Arquivo

`VER_2024_Bahrain_Q.csv` — 702 amostras, 89,179 s, 5.367 m.

Colunas: `Date, SessionTime, DriverAhead, DistanceToDriverAhead, Time, RPM,
Speed, nGear, Throttle, Brake, DRS, Source, RelativeDistance, Status, X, Y, Z,
Distance`.

## Origem

Dados públicos de timing/telemetria da **classificação do GP do Bahrein de 2024**
(volta da pole de Max Verstappen, Red Bull RB20, 1:29.179), obtidos via
**FastF1** e publicados no repositório:

- https://github.com/sharanyaswaminathan/F1_Performance_Explorer
  (arquivo `data/VER_telemetry.csv`, também `fastest_lap_telemetry.csv`)
- FastF1: https://github.com/theOehrly/Fast-F1 — biblioteca não-oficial que lê
  os dados públicos de cronometragem da F1.

O repositório de origem não declara licença explícita; o arquivo aqui é um
conjunto de **medições factuais** (velocidade, rpm, marcha, pedal, distância),
mantido com atribuição para fins de estudo e calibração de um mod de fã sem
fins comerciais. Se você for redistribuir comercialmente, substitua por seus
próprios dados FastF1 (`fastf1.get_session(2024, 'Bahrain', 'Q')`).

## Como foi usado (`tools/calibrate.py`)

1. Reamostragem uniforme a 0,02 s + suavização, derivada para obter `a(t)`.
2. **Câmbio**: mediana de `RPM / (v/(2πR)·60)` por marcha (marchas 3–8 presentes
   na volta), ajuste log-linear para extrapolar 1–2; rpm de troca = mediana dos
   eventos de upshift.
3. **Frenagem**: envelope de desaceleração (percentil 10 por faixa de velo-
   cidade) ajustado como `decel = μ·g + c₁·v²` → μ do pneu e `B = μ·CLA + CdA`.
4. **Potência / aero**: mínimos quadrados com 2 parâmetros sobre amostras de
   acelerador cheio:
   `m·a·v + Crr·m·g·v = P_max·shape(rpm) − ½ρ·(CdA + Crr·CLA)·v³`.
   Combinando com (3): `CdA`, `CLA` e a curva de torque `power.lut`.
5. **Freios**: torque por roda derivado do limite de aderência em ~63 m/s.
6. **Pneus**: `DX0/DY0 = μ`, 3 compostos com degradação/termica próprias.

Valores e equações completas: `content/cars/arb_rb20/calibration.json` no ZIP.

## Limitações

- FastF1 entrega canais de cronometragem, **não** telemetria de engenharia da
  equipe (sem cargas de asa, temperaturas de pneu, pressão de turbo, SOC).
- Posição X/Y é muito grosseira para calcular aceleração lateral; por isso a
  aderência lateral foi derivada do envelope de frenagem + downforce, não de
  curvatura de trajetória.
- DRS e deploy do MGU-K não são canais utilizáveis aqui; a contribuição
  elétrica está embutida na curva de torque efetiva da volta.
- É **uma** volta, **um** circuito, **um** piloto. Não é um mapa completo de
  motor nem um modelo de pneus de fornecedor.
