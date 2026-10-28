# Manual de mods (RaceAI 2D)

Tudo o que o jogo carrega — pistas e carros — é JSON. Os arquivos em `assets\`
são os mesmos formatos aceitos em `mods\`, então o caminho mais rápido é:

1. **Mods → Nova pista (modelo)** ou **Novo carro (modelo)** (cria o arquivo)
2. editar o JSON na pasta `mods\`
3. **Mods → Recarregar** (ou teclar Recarregar na tela)

Pastas:

```
<RaceAI2D>\mods\tracks\*.json     pistas do usuário
<RaceAI2D>\mods\cars\*.json       carros do usuário
<RaceAI2D>\modelos\*.pt|.npz      modelos treinados
<RaceAI2D>\config.json            configurações salvas
<RaceAI2D>\raceai_erro.log        erros do executável de janela
```

Mods com o mesmo nome de um arquivo embutido aparecem com a marca `[mod]`.
JSON inválido não derruba o jogo: o item aparece com o erro na lista.

## Pista (`mods\tracks\*.json`)

```jsonc
{
  "name": "Minha Pista",
  "description": "opcional, aparece na lista",
  "difficulty": "médio",            // opcional
  "closed": true,                   // false = pista aberta (não há volta)
  "width": 14.0,                    // metros; pode ser lista (largura por ponto)
  "spacing": 4.0,                   // espaçamento da linha de centro (3-4 é um bom valor)
  "start": 0.0,                     // fração (0-1) do traçado onde fica a largada
  "points": [[x, y], ...],          // pontos de controle (mínimo 4)
  "zones": [                        // opcional: trechos com outra aderência
    { "start": 0.55, "end": 0.68, "grip": 0.7, "name": "terra" }
  ]
}
```

Como os pontos viram pista:

1. os pontos de controle são **reamostrados** com espaçamento uniforme
   (evita que pontos muito juntos criem "barriga" no spline);
2. passam por uma spline Catmull-Rom (suaviza as curvas);
3. são reamostrados de novo com `spacing`, gerando a linha de centro;
4. as bordas são deslocadas ±`width/2` pela normal.

Regras práticas:

- **mínimo 4 pontos**, sem pontos repetidos.
- Deixe pelo menos **largura + 8 m** entre dois trechos paralelos (senão a IA
  corta caminho e a progressão fica confusa). O jogo avisa quando detecta isso.
- Raio de curva muito menor que a largura vira "parede": prefira cantos
  arredondados com vários pontos.
- `zones` com `grip` < 1 criam trechos escorregadios (terra, grama, gelo).
  Um `grip` de 0,6 já muda bastante o comportamento do carro.
- Largura mínima garantida: 6 m (para os carros caberem).
- O sentido da pista é a ordem dos pontos; a seta azul na largada mostra o
  sentido. Carros largam ~6 m antes da linha.

Figura 8 funciona (o traçado pode se cruzar): os carros são "fantasmas" entre
si, então não há colisão no cruzamento — apenas cuidado visual.

## Carro (`mods\cars\*.json`)

Todos os campos são opcionais — o que faltar usa o padrão. Valores fora de
faixa são limitados automaticamente (um mod não quebra a física).

| Campo | Padrão | Significado |
|---|---|---|
| `name` | Carro | nome exibido |
| `mass` | 1200 | massa (kg) |
| `length`, `width` | 4.2, 1.9 | dimensões (m) — usadas no desenho e na inércia |
| `wheelbase` | 2.60 | distância entre eixos (m) |
| `cg_front` | 1.25 | distância CG→eixo dianteiro: **menor = mais sobresterço** |
| `cg_height` | 0.55 | altura do CG — transferência de carga |
| `engine_force` | 9000 | força de tração máxima em baixa (N) |
| `max_power` | 120000 | potência (W): limita a força em alta velocidade |
| `brake_force` | 13000 | força de frenagem (N) |
| `max_speed` | 72 | velocidade máxima (m/s ≈ ×3,6 km/h) |
| `max_steer` | 0.60 | esterço máximo (rad) |
| `steer_rate` | 4.0 | velocidade do volante (rad/s) |
| `steer_falloff` | 0.55 | quanto o esterço cai em alta (0 = nada, 0,9 = muito) |
| `grip_front`, `grip_rear` | 1.45 | coeficiente de atrito dos pneus |
| `tire_stiffness` | 9.0 | rigidez do pneu (B): maior = resposta mais pronta, satura antes |
| `tire_shape` | 1.45 | forma da curva do pneu (C) |
| `drag` | 0.42 | arrasto: `F = drag·v²` |
| `rolling` | 26 | resistência ao rolamento: `F = rolling·v` |
| `downforce` | 0.0 | `F = downforce·v²` (gera mais aderência em alta) |
| `drive_front` | 0.5 | 0 = tração traseira, 1 = dianteira, 0,5 = integral |
| `brake_front` | 0.62 | distribuição de frenagem |
| `yaw_inertia` | 1.05 | multiplicador da inércia em guinada |
| `reverse_ratio` | 0.30 | fração da força usada na ré |
| `body_color`, `accent_color` | — | cores (`#rrggbb`) |
| `sprite` | — | (reservado para imagens próprias) |

Receitas rápidas:

- **Kart ágil**: massa baixa (600), `grip` alto (1,7), pouco `drag`, `max_speed` ~38.
- **Drift**: `grip_rear` bem menor que `grip_front` (1,15 vs 1,6), `drive_front` 0.
- **Fórmula**: massa baixa, `downforce` 2–3, `grip` ~1,9, `max_steer` baixo.
- **Caminhão**: massa alta, `cg_height` alto, `steer_rate` baixo, freios fracos.

## Modelos treinados

O `.pt` guarda os pesos **e** os metadados (pista, carro, geração, fitness,
topologia, dispositivo). Se você mudar o número de raios ou as camadas
ocultas, modelos antigos deixam de ser compatíveis — o jogo avisa na hora
de carregar.

Para compartilhar sem PyTorch, use `.npz` (mesmos pesos, formato numpy).

## Dicas de Design de IA

- Comece em pistas curtas (Kartódromo, ~500 m): cada geração termina rápido.
- Aumente a população quando o fitness estagnar; aumente a mutação se a
  diversidade cair (o gráfico na lateral mostra média e melhor).
- Treine num carro e teste em outro: a rede sobrevive razoavelmente, mas o
  comportamento muda (é parte da graça).
