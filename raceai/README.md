# RaceAI 2D — jogo de corrida para treinar IA (com gerações, mods e GPU)

Um jogo de corrida 2D feito para **neuroevolução**: você pilota no teclado,
carrega um modelo `.pt` para dirigir por você, ou liga o modo **gerações** e
deixa a população evoluir — os melhores passam os pesos adiante, com cruzamento
e mutação. Roda em Windows (`.exe`) com inferência em GPU Intel/AMD via
**DirectML**, e também em CPU se não houver GPU.

```
piloto humano  ->  teclado
piloto IA      ->  rede neural MLP: sensores -> [esterço, acelerador]
treino         ->  algoritmo genético (elitismo + torneio + mutação gaussiana)
```

## Sumário

- [Como usar](#como-usar)
- [Controles](#controles)
- [Modos de jogo](#modos-de-jogo)
- [Treinar (gerações)](#treinar-gerações)
- [Modelos .pt / .npz / .onnx](#modelos-pt--npz--onnx)
- [GPU: DirectML na Intel UHD 605](#gpu-directml-na-intel-uhd-605)
- [Treinador de linha de comando](#treinador-de-linha-de-comando)
- [Mods (pistas e carros)](#mods-pistas-e-carros)
- [A física](#a-física)
- [Desempenho e solução de problemas](#desempenho-e-solução-de-problemas)
- [Estrutura do projeto](#estrutura-do-projeto)

## Como usar

### Executável (Windows)

1. Baixe `RaceAI2D-windows.zip` (artefato/release do CI ou build local).
2. Descompacte **a pasta inteira** (o `.exe` depende das DLLs ao lado dele).
3. Rode `RaceAI2D\RaceAI2D.exe`.
4. Se algo não abrir, rode `RaceAI2D-console.exe` — ele mostra os erros e
   aceita `--selftest`.

### Do código-fonte

```bat
pip install -r requirements.txt
pip install torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu
pip install --no-deps torch-directml==0.2.5.dev240914
python main.py
```

Sem PyTorch também funciona: o jogo cai para o backend numpy (CPU) e salva os
modelos em `.npz` em vez de `.pt`.

Comandos úteis:

```bat
python main.py --selftest                 :: verifica tudo sem abrir janela
python main.py --bench                    :: compara CPU x DirectML na sua máquina
python main.py --mode train               :: abre já treinando
python main.py --model modelos\x.pt       :: abre dirigindo com o modelo
python main.py --headless-train 100       :: treina 100 gerações sem janela
```

## Controles

| Tecla | Ação |
|---|---|
| `↑`/`W` | acelerar |
| `↓`/`S` | frear (e marcha a ré quando quase parado) |
| `←`/`→` ou `A`/`D` | esterçar |
| `G` | **liga/desliga as gerações** (evolução) |
| `F` | velocidade da simulação: 1x, 2x, 4x, 8x, 16x, 32x |
| `C` | troca o carro focado pela câmera |
| `R` | reinicia a geração |
| `P` / `Espaço` | pausa |
| `TAB` | mostra os raios dos sensores |
| `H` | mostra/esconde o HUD |
| `+` / `-` | zoom da câmera |
| `L` | abrir tela de modelos |
| `CTRL+S` | salvar o melhor modelo |
| `1` / `2` / `3` | manual / IA / treino |
| `ESC` | menu |
| `F1` | ajuda |

## Modos de jogo

- **Manual** — um carro, você no volante. Voltas e melhor volta são cronometradas.
- **IA** — um modelo carregado dirige. Se você não carregou nenhum modelo, entra
  o **piloto automático clássico** (perseguição pura), que serve de referência.
- **Treino** — população inteira corre ao mesmo tempo e evolui.

## Treinar (gerações)

Cada geração: todos os indivíduos largam juntos, dirigem até morrerem (parar,
bater demais, ir para o lado errado ou estourar o tempo) e recebem um **fitness**:

```
fitness = distância ao longo da pista
          − 0,08 × segundos vivos
          − 1,2  × segundos fora da pista
          − 4,0  × batidas
          + bônus por concluir voltas no menor tempo
```

A evolução então:

1. **Elitismo** — os melhores (10% por padrão) vão intactos para a próxima
   geração: é assim que os pesos bons "passam para frente".
2. **Torneio** — pais escolhidos por torneio de 3.
3. **Cruzamento** — mistura aritmética (ou uniforme) dos pesos dos pais.
4. **Mutação** — ruído gaussiano por gene (chance e intensidade ajustáveis),
   mais uma pequena chance de genes reiniciados.
5. **Sigma adaptativo** — a intensidade cai devagar a cada geração; se o
   progresso estagnar por 15 gerações, ela aumenta para sair do platô.
6. **Sangue novo** — alguns indivíduos completamente novos por geração.

Tudo isso é ajustável em **Configurações** (população, elitismo, chance e
intensidade de mutação, torneio, cruzamento, duração da geração, sensores...).

A tecla `G` liga e desliga a evolução a qualquer momento: desligada, a geração
atual só corre (útil para observar um comportamento sem perdê-lo).

Dica: para evoluir rápido use pistas curtas (Kartódromo), `F` em 8x/16x e
populações entre 60 e 150.

## Modelos .pt / .npz / .onnx

| Formato | Leitura | Escrita | Observação |
|---|---|---|---|
| `.pt` | precisa de PyTorch | precisa de PyTorch | formato principal (pesos + metadados) |
| `.npz` | sempre (numpy) | sempre | alternativa leve, sem PyTorch |
| `.onnx` | exportação | requer `torch` + `onnx` | para usar em outros runtimes |

Na tela **Modelo (.pt)** você pode:

- carregar um arquivo e **semear a população** (continuar o treino a partir dele);
- carregar e **dirigir** com ele (modo IA);
- salvar o melhor indivíduo da geração atual;
- exportar ONNX;
- abrir a pasta `modelos\`.

Os metadados guardam pista, carro, geração, fitness, topologia e o dispositivo
usado — então o jogo avisa se o modelo não bate com a configuração atual
(por exemplo, se foi treinado com outro número de raios).

O arquivo `.pt` é um `torch.save({"state_dict": ..., "meta": ...})` com camadas
`0.weight/0.bias`, `2.weight/2.bias`, ... — qualquer `state_dict` de um
`nn.Sequential(Linear, Tanh, Linear, Tanh, Linear, Tanh)` compatível é lido.

## GPU: DirectML na Intel UHD 605

O jogo tenta, nesta ordem: **CUDA → DirectML → torch CPU → numpy**.

**Segurança primeiro:** criar o dispositivo DirectML derruba o processo
(0xC0000005) em algumas máquinas sem driver de vídeo utilizável, e isso não é
capaz de ser capturado por `try/except`. Por isso o jogo **não arrisca**: o
teste do DirectML roda num processo separado (`RaceAI2D --dml-probe`) e o
resultado fica em cache no arquivo `.dml_status.json`. Se o teste falhar, o
jogo abre em CPU e segue funcionando normalmente.

- No Windows com `torch-directml` instalado, a inferência roda na GPU Intel
  (UHD 605) via DirectX 12. O HUD mostra o backend ativo e o tempo de
  inferência; `--bench` compara todos os disponíveis.
- **Cada indivíduo tem pesos próprios** (não é um único modelo). Para a GPU
  valer a pena, os pesos de toda a população são empilhados num tensor
  `(população, saída, entrada)` e a rede inteira roda como um único `matmul`
  em batch — um kernel por camada, em vez de 120 redes minúsculas.
- Com populações pequenas (≤ 30) a CPU pode ganhar: o custo de copiar
  observações/ações para a GPU some o ganho do cálculo. Use `--bench` para
  decidir; você também pode trocar de backend em Configurações sem reiniciar.
- Pentium N5030 é um processador bem modesto: prefira populações de 60–120,
  `decision_interval` 4–6 (a rede decide a ~20–30 Hz em vez de 120 Hz) e
  duração de geração de 30–45 s.

## Treinador de linha de comando

Mesma física do jogo, sem janela — bem mais rápido:

```bat
python train_headless.py --list-devices
python train_headless.py --list-assets

python train_headless.py --track kartodromo --car gt --pop 150 --generations 200 ^
       --device dml --max-seconds 40 --out modelos\gt_kart.pt --csv logs\gt_kart.csv

:: continuar de um modelo
python train_headless.py --track kartodromo --car gt --init modelos\gt_kart.pt --generations 100

:: só avaliar um modelo
python train_headless.py --track serra --car gt --load modelos\gt_kart.pt --eval
```

Opções principais: `--pop`, `--generations`, `--max-seconds`, `--device`,
`--elitism`, `--mut-rate`, `--mut-sigma`, `--tournament`, `--crossover`,
`--fresh-blood`, `--rays`, `--hidden 64,64`, `--decision-interval`, `--seed`,
`--save-every`, `--export-onnx`, `--csv`.

## Mods (pistas e carros)

Tudo é JSON — os arquivos de `assets\` são exemplos funcionais. Copie um para
`mods\tracks\` ou `mods\cars\`, edite e use **Mods → Recarregar** (ou os botões
"Nova pista"/"Novo carro", que criam um modelo pronto para editar).

```jsonc
// mods/tracks/minha_pista.json
{
  "name": "Minha Pista",
  "closed": true,
  "width": 14.0,              // largura em metros (ou lista por ponto)
  "spacing": 4.0,             // espaçamento da linha de centro reamostrada
  "start": 0.0,               // fração do traçado onde fica a largada
  "points": [[0,0], [120,0], [190,70], [190,160], [90,200], [-40,150], [-60,60]],
  "zones": [{"start": 0.55, "end": 0.68, "grip": 0.7, "name": "terra"}]
}
```

```jsonc
// mods/cars/meu_carro.json
{
  "id": "meu_carro",
  "name": "Meu Carro",
  "mass": 1200.0,             // kg
  "length": 4.3, "width": 1.9, "wheelbase": 2.65,
  "cg_front": 1.28,           // CG -> eixo dianteiro (define sub/sobresterço)
  "cg_height": 0.52,
  "engine_force": 9500.0,     // N em baixa velocidade
  "max_power": 250000.0,      // W — limita a força em alta
  "brake_force": 13000.0,     // N
  "max_speed": 70.0,          // m/s
  "max_steer": 0.58,          // rad
  "steer_rate": 4.0,          // rad/s (velocidade do volante)
  "steer_falloff": 0.55,      // quanto o esterço cai em alta
  "grip_front": 1.5, "grip_rear": 1.45,
  "tire_stiffness": 9.5, "tire_shape": 1.45,
  "drag": 0.44, "rolling": 28.0, "downforce": 0.4,
  "drive_front": 0.4,         // 0 = tração traseira, 1 = dianteira
  "brake_front": 0.62,
  "yaw_inertia": 1.05,
  "body_color": "#3aa8e0", "accent_color": "#ffffff"
}
```

Valores fora de faixa são automaticamente limitados (um mod não consegue
quebrar a física). A tela de Mods mostra o erro de cada JSON inválido.
Veja `MODS.md` para a lista completa e dicas de desenho de pista.

Pistas embutidas: Oval Iniciante, Kartódromo, Circuito da Serra, Speedway
Retão, Touge Sinuoso, Circuito Urbano, Figura 8, Dirt Oval.
Carros embutidos: Kart 2 Tempos, Sedã 1.6, GT-R Kit, Drift BX, Fórmula Júnior,
Caminhão Turbo.

## A física

Modelo de **bicicleta dinâmica** com pneus não lineares, a 120 Hz (passo fixo,
determinístico — importante para comparar gerações de forma justa):

- Pneu Pacejka simplificado: `Fy = μ·Fz·sin(C·atan(B·α))`, que satura e permite
  derrapagem controlada (drift).
- Transferência de carga longitudinal + downforce opcional → a aderência muda
  ao acelerar e frear.
- **Círculo de atrito** por eixo: se a combinação de força longitudinal e
  lateral passa de `μ·Fz`, as duas são reduzidas (wheelspin, travagem,
  saída de frente/traseira).
- Tração dianteira/traseira/integral muda o comportamento: RWD sai de traseira
  na saída de curva, FWD puxa para dentro, AWD acelera mais cedo.
- Colisão com muro: reposiciona na parede, reflete a componente normal
  (restituição 0,25) e só tira a velocidade tangencial proporcionalmente ao
  ângulo de impacto — raspão quase não perde velocidade, batida frontal, muita.
- Fora da pista: grama com menos aderência e mais resistência ao rolamento.

Sensores da IA (24 valores por padrão): 9 raios até as paredes, velocidade,
velocidades longitudinal/lateral, taxa de guinada, esterço atual, deslocamento
lateral, erro de heading, curvatura a 15/30/50/80 m, aderência da superfície,
saturação dos pneus e a última ação. Saída: `[esterço, acelerador]` em [-1, 1]
(acelerador negativo freia).

## Desempenho e solução de problemas

| Sintoma | O que fazer |
|---|---|
| Tudo lento no N5030 | população 60–120, `F` em 8x, `decision_interval` 5, geração de 30 s, pista curta |
| GPU mais lenta que CPU | normal com poucos agentes; aumente a população ou volte para `--device cpu` |
| "DirectML indisponível" | instale `torch-directml` (Windows) ou use CPU; rode `--bench` |
| DirectML testado e recusado | o teste travou numa execução anterior — o jogo passou a usar CPU. Apague `.dml_status.json` ou use o botão **Retestar GPU** em Configurações |
| Quero desligar a GPU | defina `RACEAI_NO_DML=1` (variável de ambiente) ou use `--device cpu` |
| Modelo incompatível | o número de raios/observações mudou; treine de novo ou ajuste `--rays` |
| Carros "grudados" no muro | a parede tem atrito; é esperado perder tempo, não velocidade instantânea |
| Nada abre (exe de janela) | rode `RaceAI2D-console.exe` e/ou veja `raceai_erro.log` |
| Trava ao iniciar | aguarde: o PyTorch leva alguns segundos para carregar em CPUs fracos |

Os logs e modelos ficam ao lado do executável (`modelos\`, `raceai_erro.log`);
as configurações em `config.json`.

## Estrutura do projeto

```
main.py                 ponto de entrada do jogo (--selftest, --bench, --headless-train)
train_headless.py       treinador de linha de comando
raceai.spec / build.bat build do executável (PyInstaller)
src/raceai/
    mathutil.py         geometria: splines, reamostragem, interseção raio-segmento
    track.py            pistas (JSON), consultas, sensores/raios
    car.py              especificação do carro e modelo de física
    sim.py              frota, colisão, voltas e fitness (headless)
    autopilot.py        piloto clássico (perseguição pura)
    trainer.py          laço de treino + evolução (usado pelo jogo e pelo CLI)
    ai/policy.py        rede e genoma
    ai/ga.py            algoritmo genético
    ai/backend.py       backends: numpy, torch CPU, DirectML, CUDA
    ai/model_io.py      salvar/carregar .pt/.npz/.onnx
    render.py ui.py app.py   desenho, widgets e aplicação (pygame)
    mods.py             descoberta e validação de mods
tests/                  testes do núcleo e fumaça da interface (python tests/run_tests.py)
```

`src/raceai/sim.py` e todo o núcleo **não importam pygame**, então o treinador
roda sem janela e os testes rodam em CI.
