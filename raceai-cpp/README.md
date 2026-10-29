# RaceAI 2D — versão C++

Jogo de corrida 2D para treinar IA, **reescrito inteiro em C++** (Win32 + GDI:
nada de SDL, SDL2, ImGui ou Qt). Um executável pequeno, que abre rápido e roda
em qualquer Windows — inclusive no Pentium N5030 com Intel UHD 605.

Três coisas que esta versão adicionou em relação à de Python:

1. **Sua IA em Python, colada na tela.** Um campo de texto onde você escreve
   `def dirigir(sensores): ... -> (esterço, acelerador)`. O CPython é carregado
   em tempo de execução (ele vem junto, mas o jogo funciona sem ele).
2. **Recompensa e castigos ajustáveis por sliders** — progresso, velocidade,
   precisão, suavidade, fora da pista, batida, contra-mão, parado/desistir e
   bônus de conclusão.
3. **HUD com loss e porcentagem de erro** ao lado da velocidade, mais um
   gráfico de loss por geração.

E uma garantia de projeto: **a recompensa não deixa brecha para a IA "roubar"**
(veja [Por que a recompensa não pode ser explorada](#por-que-a-recompensa-não-pode-ser-explorada)).

---

## Como rodar

Descompacte o ZIP e abra **raceai.exe**. Estrutura da pasta:

```
RaceAI2D-C++/
  raceai.exe          o jogo
  raceai_train.exe    treinador de linha de comando (opcional)
  assets/tracks/      pistas em JSON
  assets/cars/        carros em JSON
  mods/tracks/        suas pistas (opcional)
  mods/cars/          seus carros (opcional)
  python/             interpretador Python (só para a IA em Python)
  modelos/            onde os modelos treinados são salvos
```

### Teclas

| Tecla | Função |
|-------|--------|
| Setas / WASD | dirigir (corrida) |
| `R` | reinicia a corrida / zera o treino |
| `C` | câmera livre ou seguindo o carro em foco |
| `TAB` | troca o carro em foco |
| `P` | pausa |
| `H` | mostra/esconde o HUD |
| `O` | mostra/esconde os sensores |
| `+` / `-` ou roda do mouse | aproxima/afasta |
| `ESC` | volta ao menu |

---

## Treinamento

1. Escolha a **pista** e o **carro** nos menus do topo.
2. Ajuste **indivíduos**, **gerações**, **segundos por episódio**, **voltas
   alvo**, **velocidade da simulação** e **neurônios** da rede.
3. Ajuste os **sliders de recompensa** (o que a IA ganha) e de **penalidade**
   (o que a IA perde). Os valores já vêm calibrados.
4. Clique em **Iniciar**.
5. Acompanhe no HUD: **loss**, **erro %**, velocidade, distância, voltas,
   progresso e precisão — e o gráfico de loss no canto.
6. **Salvar modelo** guarda o melhor indivíduo (`.json`).

A cada geração os melhores passam os pesos adiante (elitismo), o melhor de
todos os tempos nunca se perde, e a mutação é relativa à escala dos pesos de
cada camada — por isso a evolução converge sem "esquecer" o que aprendeu.

---

## Sua IA em Python

Na tela de treinamento há um campo de texto. O contrato é este:

```python
def dirigir(sensores):
    ...
    return esterco, acelerador      # ambos entre -1 e 1
```

* `esterco` positivo vira para a **esquerda**;
* `acelerador` positivo acelera, negativo freia;
* o retorno pode ser tupla ou lista.

Clique em **Aplicar código**: se houver erro, o traceback aparece na tela.
Enquanto o código estiver ativo, ele pilota o carro em foco (tanto no treino
quanto na corrida). Os botões **Exemplo** e **Limpar** ajudam a começar.

### Os 24 sensores

| Índice | Significado |
|--------|-------------|
| 0–8 | nove raios do para-choque, da esquerda para a direita (1.0 = 70 m livre, 0.0 = colado no muro) |
| 9 | velocidade / velocidade máxima do carro |
| 10 | velocidade longitudinal (normalizada) |
| 11 | velocidade lateral |
| 12 | taxa de guinada |
| 13 | esterço atual |
| 14 | deslocamento lateral na pista (+ esquerda, − direita) |
| 15 | erro de direção em relação à pista |
| 16–19 | diferença de direção a 15, 30, 50 e 80 m à frente |
| 20 | aderência do piso (1 = asfalto, menor = terra/gelo) |
| 21 | uso dos pneus (1 = no limite) |
| 22 | último esterço aplicado |
| 23 | último acelerador aplicado |

Exemplo que já vem no campo de texto:

```python
def dirigir(sensores):
    espaco = sensores[8] - sensores[0]          # para que lado há mais espaço
    frente = min(sensores[3], sensores[4], sensores[5])
    esterco = max(-1.0, min(1.0, espaco * 3.0))
    acelerador = 0.35 + 0.65 * frente
    if frente < 0.12:
        acelerador = -0.6                        # freia forte
    return esterco, acelerador
```

> O Python é **opcional**: sem a pasta `python/`, o jogo roda normal e o campo
> avisa que o interpretador não foi encontrado.

---

## Por que a recompensa não pode ser explorada

Toda recompensa simples tem um atalho. Estas foram as brechas fechadas aqui —
e é por isso que a loss é montada do jeito que é:

| Brecha clássica | Como foi fechada |
|-----------------|------------------|
| Ficar parado e "não errar" | progresso é o termo dominante; parado morre por `stall` e ainda recebe a penalidade de **parado/desistir** |
| Desistir cedo para não acumular castigo | o tempo que o agente abriu mão conta como erro (`desistência`) **e** o progresso fica perto de zero: desistir sempre perde de tentar |
| Andar para trás e voltar para somar distância | a distância usada é **monotônica** (`max_s`): ré nunca soma; andar para trás ainda mata o agente (motivo "voltou") |
| Rodar em círculo para ganhar "velocidade" | a velocidade é medida **ao longo da pista** (avanço real), não o módulo do vetor; girar não avança |
| Rastejar em cima da linha de centro para ganhar precisão | precisão e suavidade são médias **por metro percorrido**: parado ou devagar não rende nada |
| Cortar o infield para "fechar a volta" | **checkpoints em ordem**: a volta só conta se o carro passou por todos os postos |
| Bater de propósito para cortar caminho | cada batida entra na loss, com tempo de espera (0,4 s) e limite por episódio |
| Ficar na grama porque o caminho é mais curto | tempo fora da pista é penalizado e a grama tem menos aderência |
| Trocar a volta por sobreviver | as frações de erro são medidas sobre o **tempo dirigido**, então enrolar não dilui o erro |

Todos os termos são **taxas normalizadas entre 0 e 1** (fração do tempo ou do
percurso) multiplicadas pelos pesos dos sliders. A loss é a soma deles
(`fitness = -loss + bônus de conclusão`): qualquer atalho que não seja
*andar rápido, dentro da pista e na direção certa* aumenta a loss.

---

## Treinador de linha de comando

Para treinar sem janela (bem mais rápido, usa todos os núcleos):

```bat
raceai_train.exe --track kartodromo --car kart -g 200 -p 120 --seconds 60 ^
                 --out modelos\meu_modelo.json
```

Opções principais:

```
--track <id|caminho>   --car <id|caminho>
-g, --generations N    quantidade de gerações
-p, --individuals N    indivíduos por geração
--seconds N            duração do episódio
--laps N               voltas alvo (0 = contra o relógio)
--threads N            threads (padrão: automático)
--seed N               semente (resultado reproduzível)
--out <arquivo>        salva o melhor modelo
--load <arquivo>       continua a partir de um modelo
--save-every N         salva a cada N gerações
--eval                 só avalia, sem evoluir
--list                 lista pistas e carros
--reward-progress | --reward-speed | --reward-precision | --reward-smooth
--penalty-offtrack | --penalty-crash | --penalty-wrongway | --penalty-idle
--finish-bonus | --ref-speed
```

Saída (uma linha por geração):

```
 ger    fitness     loss    erro%   dist(m)  voltas   v(m/s)  batidas   sigma
   0     -2.430    2.430    25.3%       193     0.0      9.1      2.6   0.250
  40     -0.320    0.320     1.8%       842     1.0     15.4      3.1   0.213
  79     -0.047    0.047     0.6%      1069     2.0     17.2      5.2   0.168
```

---

## Compilar do zero

Só precisa de um g++ com C++17 (MinGW no Windows).

```bash
cd raceai-cpp
make            # treinador + testes (+ raceai.exe no Windows)
make test       # roda a suíte (221 verificações)
make game       # só o jogo
```

No Windows, o `make` chama o MinGW e produz `build/raceai.exe`.

Estrutura do código:

```
src/core/     núcleo (sem dependências): base, pista, carro/física, simulação,
              política (rede), evolução (GA), assets e o driver Python
src/app/      estado da interface (app_state) e a janela Win32 (main.cpp)
tools/        treinador e teste do Python de linha de comando
tests/        suíte de testes + stub do CPython
assets/       pistas e carros em JSON
```

---

## Aproveitar um modelo da versão Python (.pt)

O executável em C++ não usa PyTorch (assim ele roda no Pentium N5030 sem CUDA),
então o formato dele é `.json`. Para reaproveitar um `.pt` treinado na versão
Python, converta uma vez com o script que acompanha o jogo:

```
python converter-modelo.py modelo.pt            # gera modelo.raceai.json
python converter-modelo.py modelo.pt saida.json # ou escolha o nome
python converter-modelo.py modelo.npz           # também aceita o fallback .npz
```

O script precisa do PyTorch instalado só para ler `.pt` (é o caso de quem
treinou na versão Python). O `.json` gerado já pode ser copiado para a pasta
do jogo e carregado em **Treinamento > Carregar modelo**. A topologia
(`obs_dim`, camadas ocultas, `act_dim`) é lida do próprio arquivo.

Para conferir a instalação sem nenhum modelo, rode
`python converter-modelo.py --self-test`: ele grava um `modelo.raceai.json`
aleatório que o jogo aceita — serve para testar o carregamento.

---

## Mods

Veja **MODS.md**: basta largar JSONs em `mods/tracks/` ou `mods/cars/` — eles
aparecem nos menus. Os valores são sanitizados, então um mod errado não
quebra a física.
