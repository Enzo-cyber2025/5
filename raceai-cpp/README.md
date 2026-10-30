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

**É um arquivo só: baixe `RaceAI2D.exe`, clique duas vezes e jogue.** Não tem
que descompactar zip nem instalar nada: as pistas, os carros, os modelos e o
Python opcional viajam **dentro do próprio executável** e são copiados para a
pasta de dados na primeira vez que ele abre.

O mesmo `.exe` tem os dois modos:

| como abrir | o que acontece |
| --- | --- |
| duplo clique (sem argumentos) | abre a janela do jogo |
| `RaceAI2D.exe -g 50 -p 60 --seconds 45` | treina no terminal, sem abrir janela (igual ao `raceai_train`) |

### Onde ficam os arquivos

Na primeira vez o jogo cria a pasta de dados e descompacta o conteúdo nela:

```
%LOCALAPPDATA%\RaceAI2D\      (ex.: C:\Users\você\AppData\Local\RaceAI2D)
  assets/tracks/      pistas em JSON  →  você pode editar e criar as suas
  assets/cars/        carros em JSON
  mods/tracks/        suas pistas (opcional)
  mods/cars/          seus carros (opcional)
  python/             interpretador Python (só para a IA em Python)
  modelos/            onde os modelos treinados são salvos
```

Na aba Corrida, o botão **“Abrir pasta de mods”** leva direto até lá.

Se você preferir a versão “portátil” (tudo do lado do `.exe`, numa pasta que
você controla), é só colocar uma pasta `assets/` com `tracks/` e `cars/` ao
lado do executável: o jogo detecta e passa a usar ela, sem extrair nada.

O `raceai.log` nasce **ao lado do .exe** (não na pasta de dados) para você
achar fácil — se algo não abrir, é ele que diz onde parou.

### Teclas

| Tecla | Função |
|-------|--------|
| **`F2`** | **chave: alterna Corrida ↔ Treinamento** (mesmo app, sem voltar ao menu) |
| **`F3`** | liga/desliga a visão 3D (câmera dentro do carro) |
| Setas / WASD | dirigir (corrida) |
| `R` | reinicia a corrida / zera o treino |
| `C` | câmera livre ou seguindo o carro em foco |
| `TAB` | troca o carro em foco |
| `P` | pausa |
| **`B`** | **pede boxe (pitstop)** para o seu carro na corrida |
| `H` | mostra/esconde o HUD |
| `O` | mostra/esconde os sensores |
| `+` / `-` ou roda do mouse | aproxima/afasta |
| `ESC` | volta ao menu |

---

## Os dois modos no mesmo app

O jogo tem **Corrida** e **Treinamento** no mesmo executável. Aperte **`F2`**
(ou clique no botão `F2 ▸ Treino` / `F2 ▸ Corrida`) para trocar de modo na
hora — nada é perdido: a corrida continua de onde parou e o treino continua
evoluindo enquanto você está na corrida.

| | Corrida | Treinamento |
|---|---|---|
| O que faz | você (ou uma rede) guia contra adversários | evolução genética treina uma rede |
| Mostra | classificação, setores, delta, fantasma, minimapa | loss, erro %, geração, gráfico |
| Controles | setas/WASD | sliders de recompensa e de população |

### Visão 3D

Além da visão de cima (2D), o jogo tem uma **visão 3D** com câmera atrás do
carro: aperte **`F3`** ou clique na chave `2D | 3D` (fica ao lado da chave de
modo). O 3D é um renderizador próprio, por software:

- projeção perspectiva com recorte no plano próximo e ordenação das faces da
  mais longe para a mais perto (algoritmo do pintor) — roda em processadores
  fracos, sem placa de vídeo dedicada;
- a pista é montada em tiras: asfalte, zebrada nas duas bordas, muro e grama;
- árvores/cones de cenário são gerados ao longo do traçado;
- o fantasma da sua melhor volta aparece como uma fita no chão;
- cada carro é uma caixa com a cor do próprio modelo (o seu fica verde);
- campo de visão e altura da câmera mudam com a velocidade.

Pistas podem ter **elevação**: basta que `points` tenha três números por ponto
`[x, y, z]` (com dois, o jogo assume terreno plano).

### Carros pré-modelados

No 3D cada carro é uma **carroceria modelada**, não uma caixa: chassi, cabine,
capô, aerofólio, gaiola, baú, bico, asas — montados com as medidas reais do
JSON (comprimento, largura, altura, entre-eixos e raio de roda). As **rodas
esterçam** com o volante e **giram** na velocidade certa, e o carro projeta
sombra no chão.

São 10 estilos, escolhidos sozinhos pelo `id` do carro (ou pelo campo
`body_style` do JSON, se você quiser mandar):

| estilo | entra quando |
| --- | --- |
| `formula` | formula, monoposto, prototipo |
| `kart` | kart |
| `caminhao` | caminhao, truck, van |
| `buggy` | buggy |
| `picape` | pickup, picape |
| `classico` | classico |
| `drift` | drift, tuner |
| `esportivo` | gt, super, esportivo, muscle |
| `hatch` | hatch |
| `sedan` | qualquer outro (padrão) |

Exemplo de mod: `"body_style": "formula"` faz seu carro virar um monoposto no
3D sem mexer em nada mais.

### Erros ao abrir

Se alguma coisa falhar na abertura, o jogo **mostra uma janela com o erro** e
grava tudo em **`raceai.log`**, na mesma pasta do `.exe`. Abra esse arquivo:
ele lista o passo a passo da inicialização (se o Python foi achado, o tamanho
da janela que coube na sua tela etc.) e a última linha antes do problema.

O tamanho da janela é calculado pela área útil da tela — em telas de
1366×768 ou menores a janela abre menor em vez de ficar cortada.

---

## Telemetria de corrida

- **Setores**: a volta é dividida em 3 setores; o HUD mostra o melhor tempo de
  cada um e marca com `>` o setor atual.
- **Delta**: diferença (±) contra a sua própria melhor volta, igual telemetria
  de jogo de corrida de verdade.
- **Fantasma**: o traçado da sua melhor volta fica desenhado na pista (linha
  tracejada ciano) e no minimapa, para você perseguir a própria marca.
- **Minimapa**: a pista inteira no canto inferior direito, com todos os carros.
- **Sistemas do carro**: marcha, giro do motor, temperatura e desgaste dos
  pneus, dano, combustível, aderência usada e patinação.

---

## A física

O modelo é uma bicicleta dinâmica com pneus Pacejka-lite, integrada a passo
fixo (1/120 s) — determinístico, porque comparar gerações exige isso. O que
entra em cada passo:

1. **Motor com curva de torque** — torque varia com o giro (platô perto do pico
   de torque, queda depois) e é cortado no limitador. Se o mod não informar
   `peak_torque`, ele é derivado da força de tração.
2. **Câmbio automático** — até 9 marchas, com histerese: só sobe se a marcha
   nova ainda ficar acima do ponto de redução e só reduz se não estourar o
   corte (sem isso o câmbio fica "caçando" marcha e o carro não acelera).
3. **Pneus** — força lateral por curva de deriva, com **temperatura** (janela
   ótima de aderência), **desgaste** progressivo e **sensibilidade à carga**
   (transferência de carga custa aderência, como na vida real).
4. **Transferência de carga** longitudinal (eixo) e lateral (roda de dentro
   alivia, a de fora carrega) — a soma das duas é o que faz frear forte em cima
   da curva tirar a direção.
5. **Aerodinâmica** — arrasto `0.5·ρ·Cd·A·v²` e downforce `0.5·ρ·Cl·A·v²`
   distribuída entre os eixos (muda a transferência de carga em alta). O pitch
   da carroceria altera o downforce, e o **vácuo** (aspiração) de quem vem
   colado na frente reduz arrasto e downforce.
6. **Freios com ABS opcional**, controle de tração opcional, **dano por
   impacto** (perde potência e direção) e **consumo de combustível** (o carro
   fica mais leve; sem gasolina, não anda).
7. **Superfície** — cada pista pode ter zonas de grama/terra/gelo que mudam
   aderência e resistência ao rolamento.

### O que há de "simulador" nela

Além do modelo acima, cada eixo tem **roda com inércia própria** (a inércia do
motor é refletida pela marcha, por isso a roda não muda de giro instantaneamente).
Isso faz patinação e travamento **surgirem** da física em vez de serem
"colados" depois — e permite o pneu trabalhar com **escorregamento combinado**:

- o pneu gera uma força só, numa curva tipo Pacejka, a partir do escorregamento
  longitudinal (κ) e do ângulo de deriva (α) somados — o **círculo de atrito é
  consequência do modelo**, não um limitador aplicado no fim. Frear em cima da
  curva solta a traseira; acelerar demais na saída abre a frente;
- as rodas são integradas com **sub-passos e passo semi-implícito** (o declive
  do pneu entra no denominador), então a patinação sai suave em vez de "bater";
- **suspensão com atraso**: a carroceria rola e empina com constante de tempo
  (`susp_tau`), então a transferência de carga não é instantânea — é o que dá
  a sensação de carro vivo na entrada e na saída de curva;
- **cambagem** muda com a rolagem e custa aderência na roda de fora;
- **freio esquenta** com o trabalho da freada, esfria com o vento e
  **perde eficiência (fading)** quando o disco passa de ~380 °C;
- **freio de motor**: tirar o pé já desacelera (e ajuda a assentar o carro na
  entrada da curva);
- **diferencial com trava parcial (LSD)**: mais tração na saída e mais
  estabilidade, ao custo de um pouco de subesterço;
- **ABS e controle de tração** leem o escorregamento real da roda — o ABS alivia
  o disco quando a roda passa de ~13 % de escorregamento, o TC corta o motor
  quando ela patina.

Tudo isso é determinístico (mesma entrada ⇒ mesmíssimo resultado) e roda a
1/120 s em processador fraco, porque é só conta — nada de GPU.

---

## Colisão com danos, aerodinâmica que degrada e pitstop

Três sistemas que mudam a corrida (e dão o que aprender para uma IA de
estratégia):

**1. Colisão com danos.** Bater no muro já custava caro; agora a lataria
amassada tem consequência aerodinâmica (abaixo) e a **colisão entre carros**
existe de verdade — na aba Corrida há a caixa **“colisões entre carros”**
(desligada por padrão). O contato é resolvido por impulso com conservação de
momento (massa contra massa), separação dos carros e rotação proporcional ao
impacto; cada batida soma dano nos dois e conta como batida.

**2. Degradação aerodinâmica.** A asa perde eficiência com o tempo e com a
sujeira: `eficiência = 1 − 0,5·dano − 0,4·sujeira` (nunca abaixo de 40 %), e o
arrasto cresce junto (`+ 0,45·sujeira`). Resultado: **menos downforce na curva
e mais arrasto na reta**. Rodar na grama/terra entope a asa rápido; no
asfalto a perda é quase nada. O HUD mostra `aero -12%`.

**3. Pitstop.** Com a chave **tipo de IA** em *Estratégia*, a zona de boxe
aparece no início da pista: uma faixa extra de 4,5 m do lado direito, com
**limite de velocidade** (22 m/s). Entrando nela e ficando o tempo do serviço
(4 s), o carro recebe:

- pneus novos (desgaste zerado e temperatura assentada),
- tanque cheio,
- lataria batida (o dano cai para 1/4) e asa lavada (aerodinâmica 100 %),
- freio resfriado.

A IA *pede* o boxe pela terceira saída da rede; a partir daí o carro encosta
na faixa e obedece o limite sozinho. Contar paradas é o que faz a rede
aprender **estratégia**: vale a pena parar? Quando? O HUD mostra
`boxe 1  no boxe` / `pediu boxe` / `na pista`.

**Você também pode parar.** Na aba Corrida há a caixa **“boxe (B pede
parada)”** e a **tecla B**: aperte B na volta em que quiser parar, encoste na
faixa e fique o tempo do serviço — pneus novos, tanque cheio, lataria batida.
Apertar B de novo cancela o pedido.

Os parâmetros do boxe ficam em sliders na aba Corrida (e valem para o treino
da IA de estratégia também):

| slider | faixa | padrão |
| --- | --- | --- |
| **tempo de boxe** | 1 a 15 s | 4 s |
| **limite do boxe** | 8 a 40 m/s | 22 m/s |
| **largura da faixa** | 3 a 9 m | 4,5 m |

---

## Gerador de IA (sem programar)

Não precisa escrever código para montar a rede: no painel do Treinamento há o
bloco **“gerador de IA”**, com quatro escolhas e um botão.

| controle | o que faz |
| --- | --- |
| **camadas** | campo livre: digite quantas quiser, do tamanho que quiser — `256, 128, 64`, `8`, `1024,512,256,128` (limite de segurança: 8 camadas de até 4096) |
| **atalhos** | escrevem o campo para você: constante `64, 64`, funil `128, 64, 32`, ampulheta `32, 64, 32` |
| **ativação** | `tanh` (padrão), `relu`, `sigmoid` ou `leaky` |
| **formato** | constante (64→64), funil (64→32) ou ampulheta (32→64→32) |
| **passo da mutação** | o “sigma”: quanto cada peso muda por geração |
| **tipo de IA** | chave: **Corrida** (só piloto) ou **Estratégia** (piloto + boxe) |
| **Gerar e treinar** | aplica a rede e recomeça o treino do zero |

Embaixo aparece a rede escolhida por extenso, por exemplo
`24 → 64 → 32 → 2  (4.7k parâmetros)`. A saída é sempre `tanh`, porque esterço
e acelerador vivem em [-1, 1]; a ativação vale para as camadas escondidas.

### A chave “tipo de IA”

| posição | rede | o que muda |
| --- | --- | --- |
| **Corrida** | `24 → ... → 2` | só esterço e acelerador: o piloto de sempre |
| **Estratégia** | `29 → ... → 3` | +5 entradas (pneu, tanque, dano, aerodinâmica, paradas) e +1 saída: **pedir boxe** |

Com a chave em **Estratégia** a rede passa a *sentir* o estado do carro e a
decidir **quando parar**: a terceira saída acima de zero é o pedido de boxe.

Também dá para treinar pelo terminal (mesmas opções):

```
RaceAI2D.exe --track oval_iniciante --car sedan --hidden 128 -g 80 -p 60 --out meu.json
```

Cada linha do treino mostra a **estimativa para terminar todas as épocas**:

```
  10    12.480    0.120     1.2%      1050     2.0     30.1      0.1   0.180
      ETA 1m 12s para as 39 épocas restantes (1.85s por época • 0m 18s rodados)
```

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

Na tela de treinamento há um campo de texto, com quatro botões:

| botão | o que faz |
| --- | --- |
| **Aplicar código** | compila o que está escrito no campo |
| **Exemplo** | traz de volta o piloto de exemplo |
| **Abrir .py** | lê um arquivo `.py` do disco e já aplica |
| **Salvar .py** | grava o código do campo num arquivo `.py` |

Se o código tiver erro, ele é recusado com o traceback na tela e a IA fica
neutra (o carro não sai do lugar) até você corrigir e aplicar de novo.

O contrato é este:

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
| 24–28 | **só com a chave em Estratégia**: desgaste do pneu, combustível, dano, aerodinâmica degradada e paradas/5 |

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

É o **mesmo arquivo**: chame o `RaceAI2D.exe` com argumentos e ele treina no
terminal em vez de abrir a janela (não precisa de um segundo executável).

Para treinar sem janela (bem mais rápido, usa todos os núcleos):

```bat
RaceAI2D.exe --track kartodromo --car kart -g 200 -p 120 --seconds 60 ^
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

## Como o “um arquivo só” é feito

Nada de instalador: o próprio `make` grava o conteúdo **dentro** do executável.

1. `tools/empacotar.cpp` junta `assets/`, `modelos/` e `python/` num pacote
   binário simples (`RACEAIPAK`: nome, tamanho e dados de cada arquivo) e
   anexa esse pacote ao **fim** do `.exe`, seguido de um trailer de 24 bytes
   com o tamanho. O Windows ignora o que vem depois da imagem PE, então o
   executável continua funcionando normalmente.
2. `src/app/conteudo.cpp` lê esse trailer, acha o pacote e extrai para a pasta
   de dados — só o que ainda não existe, para nunca sobrescrever um mod seu.
3. Se não houver pacote (ou já existir `assets/` do lado do `.exe`), nada muda:
   o jogo roda em modo portátil, como antes.

E tem um detalhe que faz diferença no mundo real: o executável é ligado
**estaticamente** (`-static -static-libgcc -static-libstdc++`). Sem isso ele
dependeria de `libgcc_s_seh-1.dll`, `libstdc++-6.dll` e `libwinpthread-1.dll` —
DLLs do compilador que não existem no seu computador, e aí o Windows mostraria
“The code execution cannot proceed because libgcc_s_seh-1.dll was not found”.
Assim o `.exe` só depende de DLLs do próprio Windows.

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

## Modelos prontos (a pasta `modelos/`)

O jogo já vem com **um modelo de demonstração** treinado em `modelos/`
(`demo_oval_iniciante_sedan.json`: sedã no Oval Iniciante, 60 gerações, erro
~1,3%). Ele entra sozinho no grid quando você abre a **Corrida** — com o carro
em que foi treinado — e serve como adversário e como exemplo do formato.
Quando você salvar o seu modelo, ele passa a valer também.

Quer mais? Tem um script com uma lista de combinações prontas (pista, carro,
tamanho da rede e gerações) — a primeira é justamente o modelo de demonstração:

```
./tools/treinar_modelos.sh        # 1 modelo (o de demonstração)
./tools/treinar_modelos.sh 12     # os 12 da lista (~10 min)
RaceAI2D.exe --track speedway --car formula -g 120 -p 60 --seconds 45 \
             --out modelos/meu_modelo.json     # ou na mão, do seu jeito
```

Cada modelo guarda nos metadados em qual pista e com qual carro foi treinado
(é daí que a interface escolhe o carro dele no grid).

Cada modelo tem ~85 KB (5.890 números). Em 25-60 s de treino no seu
Pentium N5030 você chega a perda ~0,05 e erro ~0,5% em pistas fáceis.

---

## O que é um modelo, afinal

**Não tem nada de especial**: é um conjunto de matrizes de uma rede neural
comum (MLP), sem metadados mágicos, sem otimizador, sem grafo de operações.

Arquitetura: `24 entradas → 64 → 64 → 2 saídas`, `tanh` em todas as camadas.

```json
{
  "obs_dim": 24,          // quantos sensores a rede lê
  "hidden": [64, 64],     // neurônios por camada oculta
  "act_dim": 2,           // saídas: esterço, acelerador
  "weights": [ ... ],     // 5890 números, na ordem abaixo
  "meta": { "track": "Kartódromo", "best_loss": 0.091, "best_error_pct": 0.74 }
}
```

**Ordem dos pesos** (é só isso): para cada camada, primeiro a matriz de pesos
`n_entradas × n_saídas` — uma linha por neurônio de saída (`W[saída][entrada]`)
— e depois o bias de cada saída.

```
camada 0:  24×64 = 1536 pesos   +  64 biases   = 1600
camada 1:  64×64 = 4096 pesos   +  64 biases   = 4160
camada 2:  64×2  =  128 pesos   +   2 biases   =  130
                                        total  = 5890
```

A inferência é literalmente `x = tanh(W·x + b)` três vezes — umas 12 mil
multiplicações por decisão, a 30 decisões por segundo. Por isso roda de boas
no Intel UHD 605 / Pentium N5030 sem GPU nenhuma.

O `.pt` do PyTorch guarda exatamente os mesmos números, só que dentro do
formato zip do torch (por isso precisa do torch inteiro — ~1 GB de DLLs —
para ser lido). É esse 1 GB que você lembra, **e não o modelo**: a rede em si
cabe em 23 KB se gravada em binário.

### Dá para usar qualquer topologia?

Sim — `obs_dim` tem que ser **24** (são os sensores) e `act_dim` **2**
(esterço e acelerador); as camadas do meio você escolhe. Não precisa ser
64-64: `24->512->256->2` funciona, `24->32->2` (uma camada só) também, e o
arquivo aceita quantas camadas quiser.

Não há limite de tamanho no arquivo: o único limite é a memória do computador
(se não couber, o jogo avisa em vez de travar).

O limite real é o tempo de inferência. Medido em 1 núcleo:

| rede | pesos | decisões/s | 1 carro a 30 Hz usa |
| --- | --- | --- | --- |
| 24→64→32→2 (padrão) | 3,7 mil | 307.000 | 0,01% |
| 24→256→128→2 | 39 mil | 31.800 | 0,09% |
| 24→512→256→2 | 144 mil | 9.278 | 0,32% |
| 24→1024→512→2 | 551 mil | 2.451 | 1,22% |
| 24→2048→1024→2 | 2,1 milhão | 641 | 4,68% |

Na **corrida** (até 6 carros) dá para usar rede de milhões de parâmetros
tranquilo. No **treino**, lembre que são 60 indivíduos decidindo ao mesmo
tempo: multiplicando por 60, uma rede de 2,1 milhão de pesos já não caberia
no Pentium N5030 em tempo real, enquanto a padrão (5.890) sobra.

Um "quintilhão de parâmetros" (10¹⁸) seriam 4 exabytes de memória — não cabe
em disco nenhum, quanto mais em RAM. O gargalo nunca foi o formato: é a
quantidade de conta que o processador precisa fazer por decisão.

---

## Carregar rede de fora (`.pt`, `.pth`, `.npz`, `.safetensors`)

O jogo lê **diretamente** os formatos de todo mundo — sem PyTorch, sem NumPy,
sem instalar nada. É só escolher o arquivo em **Carregar modelo** (ou
**Adicionar modelo**, na corrida):

| formato | de onde vem |
| --- | --- |
| `.pt` / `.pth` | PyTorch (zip + pickle + storages) — o mais comum |
| `.npz` | NumPy (`np.savez`) |
| `.safetensors` | HuggingFace / safetensors |
| `.json` | o formato do próprio jogo |

Não há limite de tamanho nem de topologia: vale `24→32→2`, `24→4096→4096→2`,
dez camadas, uma camada só, o que for. A rede é **adaptada** nas pontas:

- entrada com mais de 24 colunas → usa as 24 primeiras
- entrada com menos de 24 → completa com zero
- saída com mais de 2 → usa as 2 primeiras
- saída com 1 → a segunda fica em zero
- sem bias na camada → bias zero

Só é recusado o que **não for rede neural** (arquivo aleatório, texto, um
modelo convolucional sem matriz nenhuma). Nesse caso aparece a mensagem
explicando o motivo.

Testes: o mesmo modelo gravado nos 5 formatos produz exatamente os mesmos
290 pesos (`tests/modelos_teste/`).

---

## Aproveitar um modelo da versão Python (.pt)

*( continua válido, mas hoje é opcional — o jogo abre o `.pt` sozinho. )*

O executável em C++ não usa PyTorch (assim ele roda no Pentium N5030 sem CUDA),
então o formato dele é `.json`. Se quiser converter antes, use o script que
acompanha o jogo:

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

**Atalho para começar:** na primeira vez que você abre o `Abrir pasta de mods`,
o jogo cria dois arquivos de exemplo — `meu_carro_exemplo.json` e
`minha_pista_exemplo.json`. Copie, mude os números e clique em
**Recarregar mods**: é só isso para fazer seu primeiro mod.

Campos novos do carro (todos opcionais, todos sanitizados):

| campo | o que faz |
| --- | --- |
| `wheel_inertia`, `engine_inertia` | inércia das rodas e do motor (patinação/travamento) |
| `diff_lock` | 0 = diferencial aberto, 1 = travado (LSD) |
| `brake_heat`, `brake_cool`, `brake_fade` | temperatura do disco e perda por fading |
| `roll_grad`, `pitch_grad`, `susp_tau` | quanto e com que rapidez a carroceria rola/empina |
| `camber_static`, `camber_gain`, `camber_loss` | cambagem e quanto ela custa de aderência |
| `aero_pitch` | quanto o pitch muda o downforce |
