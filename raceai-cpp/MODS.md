# Mods — pistas e carros

Qualquer arquivo `.json` largado em `mods/tracks/` ou `mods/cars/` aparece nos
menus do jogo (sem precisar recompilar nada). Os valores são validados e
limitados a faixas seguras: um mod escrito errado não derruba a física.

---

## Pista (`mods/tracks/*.json`)

```json
{
  "name": "Meu Autódromo",
  "description": "duas retas e uma chicane",
  "difficulty": "médio",
  "closed": true,
  "width": 14.0,
  "spacing": 3.0,
  "points": [[0, 0], [80, 0], [140, 40], [140, 120], [60, 150], [-40, 120], [-60, 40]],
  "zones": [
    { "start": 0.55, "end": 0.70, "grip": 0.6, "name": "terra" }
  ]
}
```

| Campo | Obrigatório | Significado |
|-------|-------------|-------------|
| `name` | não | nome exibido (padrão: nome do arquivo) |
| `closed` | não | `true` = circuito fechado (padrão) |
| `points` | **sim** | pontos de controle `[x, y]` em metros (mínimo 4) |
| `width` | não | largura em metros; pode ser um número **ou** uma lista (largura variável) |
| `spacing` | não | espaçamento da linha de centro em metros (padrão 3.0) |
| `start` | não | fração do traçado onde fica a largada (padrão 0) |
| `zones` | não | faixas com aderência diferente |

**Zonas:** `start`/`end` são frações do comprimento total (0 a 1) e `grip` é o
multiplicador de aderência (1.0 = asfalto, 0.6 = terra, 0.35 = gelo).

Dicas:

* os pontos passam por um spline Catmull-Rom e são reamostrados, então
  poucos pontos bem distribuídos já dão uma curva suave;
* evite deixar trechos paralelos a menos de ~20 m um do outro (o jogo avisa);
* largura mínima prática: 8 m (carros têm ~2 m e a IA precisa de espaço).

---

## Carro (`mods/cars/*.json`)

```json
{
  "name": "Meu Kart",
  "mass": 620,
  "length": 2.6,
  "width": 1.4,
  "wheelbase": 1.55,
  "cg_front": 0.75,
  "cg_height": 0.32,
  "engine_force": 3200,
  "max_power": 30000,
  "brake_force": 5200,
  "max_speed": 38,
  "max_steer": 0.62,
  "steer_rate": 5.0,
  "steer_falloff": 0.5,
  "grip_front": 1.75,
  "grip_rear": 1.70,
  "tire_stiffness": 10.0,
  "tire_shape": 1.45,
  "drag": 0.42,
  "rolling": 24.0,
  "downforce": 0.0,
  "drive_front": 0.0,
  "brake_front": 0.62,
  "yaw_inertia": 1.0,
  "body_color": "#e0483a",
  "accent_color": "#f5f5f5"
}
```

| Campo | Significado | Faixa aceita |
|-------|-------------|--------------|
| `mass` | massa (kg) | 300 – 6000 |
| `length`, `width` | dimensões (m) | — |
| `wheelbase` | distância entre eixos (m) | 1 – 8 |
| `cg_front` | distância do CG ao eixo dianteiro (m) | 0,6 – (wheelbase − 0,6) |
| `cg_height` | altura do CG (m) | 0,15 – 1,5 |
| `engine_force` | força de tração em baixa (N) | 500 – 60000 |
| `max_power` | potência máxima (W) — limita a força em alta | 3000 – 2000000 |
| `brake_force` | força de frenagem (N) | 500 – 80000 |
| `max_speed` | velocidade máxima (m/s) | 8 – 140 |
| `reverse_ratio` | fração da força usada na ré | 0 – 1 |
| `max_steer` | esterço máximo (rad) | 0,15 – 1,2 |
| `steer_rate` | velocidade do volante (rad/s) | 0,5 – 12 |
| `steer_falloff` | redução do esterço em alta | 0 – 0,9 |
| `grip_front`, `grip_rear` | coeficiente de atrito dos pneus | 0,4 – 3,0 |
| `tire_stiffness` | fator B do pneu (Pacejka) | 2 – 25 |
| `tire_shape` | fator C do pneu | 1,0 – 2,2 |
| `drag` | arrasto (F = drag·v²) | 0,05 – 3,0 |
| `rolling` | resistência ao rolamento (F = rolling·v) | 0 – 300 |
| `downforce` | F = downforce·v² (negativo = sustentação) | −2 – 20 |
| `drive_front` | 0 = tração traseira, 1 = dianteira, 0,5 = integral | 0 – 1 |
| `brake_front` | distribuição de frenagem | 0,2 – 0,85 |
| `yaw_inertia` | multiplicador da inércia em guinada | 0,5 – 2,5 |

O `id` do carro é o nome do arquivo sem extensão.

---

## Modelos treinados

`modelos/*.json` guarda a topologia da rede e os pesos. Dá para carregar no
jogo (**Carregar modelo**) ou continuar o treino:

```bat
raceai_train.exe --load modelos\meu_modelo.json -g 50 -p 60 --out modelos\melhor.json
```

O arquivo é JSON legível: `obs_dim`, `hidden`, `act_dim`, `weights` (vetor de
pesos) e `meta` com a pista, o carro, a geração e as métricas do melhor
indivíduo.
