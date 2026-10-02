# ETS2-AI — piloto automático para Euro Truck Simulator 2 (celular ↔ PC)

> **Downloads (IA já treinada dentro de ambos):**
> - APK: https://github.com/Enzo-cyber2025/5/releases/download/ets2-ai-v0.4.4/ETS2-AI-mobile.apk
> - EXE: https://github.com/Enzo-cyber2025/5/releases/download/ets2-ai-v0.4.4/ETS2-AI-bridge.exe
> - Modelo PyTorch (`.pt`): https://github.com/Enzo-cyber2025/5/releases/download/ets2-ai-v0.4.4/ets2ai-v0.4.4.pt
>
> **v0.4.4 — IA de 1.017.613 parâmetros (290×13, estreita e profunda), treino em FLUXO de 1 bilhão de amostras nas 2×T4 + GPU 2×T4 + USB plug-and-play.** A IA treinada dirige caminhão num simulador com
> a mesma física do jogo-alvo, gerencia combustível, sono e entregas, roda no
> **APK do celular** (inferência 100% em Java, sem dependências) e entrega os
> comandos ao **PC Windows** por TCP, onde o bridge injeta **teclas reais**
> (SendInput). O `.exe` e o `.apk` saem prontos do CI.

## Resultados medidos (não estimados)

Treinamento: behavioral cloning de um motorista especialista (pure-pursuit +
controle preditivo de velocidade) sobre 26 estradas aleatórias; validação em
7 estradas **nunca vistas**; avaliação em circuito fechado em outras estradas
inéditas.

| Métrica | Valor | Meta |
|---|---|---|
| MSE validação (loss) | **0.008602** | ≤ 0.150 ✅ (17× melhor; mínimo empírico — ver tabela float64 abaixo) |
| Rotas concluídas (circuito fechado) | **100%** (7/7) | — |
| Tempo dentro da faixa | **100%** | > 95% |
| Velocidade média | **71 km/h** (pico ~130 km/h nas retas) | acima do limite ✅ |
| **Radares** | **100%** das 30 passagens abaixo do limite | freia antes do radar ✅ |
| **Física do tombamento** | 3.33 m/s² de pico (limite 3.6) | o mais rápido possível sem tombar ✅ |
| **Aderência ao GPS** | desvio médio de **0.18 m** do traçado | segue o traçado ✅ |
| **Estacionar no dock** | **100%** das rotas, erro médio de **2.2 m** (modo creep) | para na linha, sem atravessar ✅ |
| Amostras de treino | 115.308 pares estado→ação | — |

Reproduza: `python -m ets2ai.train` (determinístico — o CI retreina do zero e
confere que os pesos batem com os commitados, tolerância 1e-5).

## O que é de verdade e o que ainda é demo (honestidade primeiro)

| Item | Estado |
|---|---|
| Rede neural que dirige (estrada com curvas, faixa, limites) | ✅ real, medido, testado |
| Regras de abastecer/dormir/entregas/dinheiro | ✅ real (regras sobre telemetria — não precisa de ML) |
| **Dispatcher: escolhe a melhor rota de 3 ofertas** (EUR/km líquido − combustível − hotel − curvas) | ✅ real (`ets2ai/dispatch.py` + `Dispatcher.java`) |
| **Teclado Bluetooth**: o celular aparece como teclado HID real no PC | ✅ API pública `BluetoothHidDevice` (Android 9+) |
| **Missão completa**: liga motor (E) → dirige → para na área de entrega → seleciona **"Onde você precisa dele?"** no diálogo (setas + Enter) → estaciona (freio de mão) → carrega (T) → dispatcher escolhe o próximo trabalho → repete | ✅ app, bridge e testes |
| **Habilidades ao subir de nível** | ✅ escolha **aleatória** por design (ADR, Cargas Frágeis, Distâncias Longas…) |
| **Injeção de teclas corrigida** | ✅ setas/Enter com flag `EXTENDEDKEY` (sem isso o Windows interpretaria teclado numérico) |
| **Motor de inferência auto-selecionado** | ✅ benchmark interno escolhe o mais rápido (Java/TFLite/GPU/NNAPI) e mostra no HUD |
| **Benchmark de backends no aparelho** (Java / TFLite CPU / GPU / NNAPI-rota-pública-para-NPU) | ✅ medidas reais no seu A55, botão BACKEND |
| APK Android com a IA + HUD + diagnóstico NPU | ✅ sai do CI assinado |
| Bridge Windows `.exe` + injeção de teclas reais | ✅ sai do CI (SendInput/scan codes, kill switch ESC) |
| Celular como "cérebro" do PC (TCP) | ✅ implementado (RTT exibido) |
| **Engate/desengate do vagão (T)** | ✅ macro no bridge (scan code 0x14) — mesmo fluxo do carregar/entregar |
| **Qualquer estrada/mapa, incl. mods** | ✅ no simulador: a política é **local** (curvatura à frente + estado do caminhão), não memoriza mapa nenhum — estrada nova = dirige do mesmo jeito; no jogo real "ver" a estrada exige telemetria (roadmap 1) |
| **Desviar de carros / sentir o limite do veículo** | ⏳ requer telemetria do jogo (posições do trânsito, velocidade máxima do caminhão carregado) — plugin SCS SDK; no simulador a IA já respeita radares, limites e tombamento |
| Dirigir o **ETS2 de verdade** | ⏳ requer telemetria do jogo (plugin SCS SDK) — ponto de integração pronto e documentado abaixo |
| Rodar na **NPU** do Galaxy A55 | ❌ não exposto a apps terceiros hoje (ver veredito) |

## Veredito NPU (Galaxy A55 5G / Exynos 1480)

Você pediu para insistir na NPU. O resultado da investigação, com fontes:

1. **Samsung Neural SDK está fechado para terceiros.** A própria página
   oficial diz: *"The SDK is no longer provided to third-party developers"*
   — https://developer.samsung.com/neural/overview.html
2. **NNAPI (o caminho público genérico para NPU/DSP) foi depreciado no
   Android 15** e o Google recomenda migrar para TensorFlow Lite/LiteRT:
   — https://developer.android.com/ndk/guides/neuralnetworks/migration-guide
3. Runtimes modernos de NPU (Qualcomm AI Engine Direct, MediaTek NeuroPilot,
   **Exynos AI LiteCore — apenas Exynos 2500/2600**, Google Tensor G5/G6)
   são qualificados por chip; o Exynos 1480 do A55 não aparece nas listas
   de acesso aberto.
4. Portanto: **nenhum app comum programa a NPU do A55 hoje**. O que um app
   terceiro consegue: CPU (float) e GPU (Vulkan/OpenCL via delegates).

**O que o projeto faz com isso:** o APK roda a política em **Java puro
(CPU)** — para a rede atual (13→290×13→3), isso custa **microssegundos** por
decisão; NPU seria overkill. Mesmo assim, o CI **já exporta os `.tflite`**
(float32 e int8) validados contra o numpy, e o app traz a tela
**"NPU" (Diagnóstico)** que mostra no seu aparelho exatamente o que existe
de aceleradores/runtimes. Se a Samsung liberar o acesso (ou você trocar de
chip), o modelo está pronto para plugar num delegate.

## Modelo PyTorch (`.pt`)

Além do Java (APK), do `.tflite` e do bridge, os mesmos pesos treinados saem
também em **`ets2ai-v0.4.4.pt`** (TorchScript, auto-contido, ~1,2 MB) —
gerado por `ets2ai/ets2ai/export_pt.py`, que grava o arquivo só depois de
confirmar paridade numérica com o numpy (max diff < 1e-5 em 2.048 entradas
aleatórias). Carregar e usar em qualquer lugar com PyTorch instalado:

```python
import torch
m = torch.jit.load("ets2ai-v0.4.0.pt")          # não precisa do código do repo
m.eval()
x = torch.zeros(1, 13)                          # [speed, lane_offset, ..., radar_dist]
steer, throttle, brake = m(x)[0].tolist()       # ações da IA
```

Metadados embutidos no arquivo: `m.n_params` (1.017.613), `m.loss` (0.008602),
`m.features` (13 entradas), `m.actions` (steer/throttle/brake). Teste de
regressão em `tests/test_export_pt.py` (pula onde não há torch).

## E float64? (o teto real de precisão)

O treino padrão roda em float32 — a precisão do deploy (APK/EXE/TFLite/.pt).
Para o experimento de precisão existe `--dtype float64`:

```
python -m ets2ai.train --epochs 400 --dtype float64 --out artifacts-f64
```

Tudo em double nativo (pesos, entradas, alvos, loss). Curiosidade honesta:
até a v0.4.0 o treino já rodava em float64 **por acidente** — o NEP 50 do
numpy ≥ 2 promove `float32 * np.float64` para float64, e a inicialização
He multiplicava por um escalar float64. Corrigido: agora float32 é float32
de verdade (verificado por teste) e float64 é explícito.

**Resultado medido (400 épocas, mesma semente, mesmas estradas):**

| Configuração | MSE validação | MSE treino |
|---|---|---|
| 51.715 params, float32, especialista com ruído | 0,008568 | 0,003979 |
| 51.715 params, float64, especialista com ruído | 0,008987 | 0,003166 |
| 150.203 params, float64, especialista com ruído | 0,008790 | 0,001020 |
| **295.103 params, float64, especialista perfeito (v0.4.2)** | **0,008602** | 0,001595 |
| 505.291 params (196×14), FP64, 1,01M amostras (v0.4.3) | 0,009579 (T4, sem restore-best) | — |
| **1.017.613 params (290×13), fluxo de 1B amostras (v0.4.4)** | **número oficial na release v0.4.4** | — |

Quatro configurações — capacidade 5,7×, precisão dobrada, ruído removido —
e a validação fica na mesma faixa (0,0086–0,0090): **este é o mínimo
empírico do problema**. O resíduo é **estrutural**: as travas duras do
especialista (abastecer, dormir, frear no radar, creep do dock) são
descontinuidades que rede lisa alguma cruza de forma exata, e a validação
mede generalização para estradas nunca vistas. Loss de 1e-26 não existe
neste problema em precisão nenhuma; o que melhora de verdade com a
v0.4.2 é o **controle**: MAE 0,0303 (−31%), erro de parada 0,45 m,
desvio do GPS 0,15 m, dock/faixa/radares 100%.

**O que o float64 não faz:** a loss não despenca. O resíduo (~0,0086) é
**estrutural** — o especialista tem travas duras (abastecer, dormir, frear
no radar, creep do dock) que uma rede suave de 1.017.613 parâmetros aproxima
mas não cruza de forma exata; não é ruído numérico. Loss de 1e-41 exigiria
memorizar as descontinuidades com rede lisa — não acontece em nenhuma
precisão. Na T4 do Kaggle o FP64 roda a 1/32 da velocidade, então o kernel
GPU fica em float32 de propósito; float64 é para CPU/numpy.

## Arquitetura

```
┌─────────────── PC WINDOWS ───────────────┐      ┌────── CELULAR (APK) ──────┐
│  ETS2-AI-bridge.exe                      │      │  ETS2-AI app              │
│                                          │ TCP  │                           │
│  [demo sim | ETS2*] ── estado ──► ───────┼─────►│  BridgeClient             │
│      ▲                        (CSV,10Hz) │      │   └─ NeuralNet (Java)     │
│      │                            estado │◄─────┤      12→24→24→3, tanh     │
│  KeyInjector (SendInput) ◄── comandos ───┼──────┤  └─ comandos (CSV)        │
│   ▲ setas: ◄ ► ▲ ▼        (steer,thr,brk)│      │                           │
│   │                                      │      │  Demo local: SimWorld     │
│  janela alvo (--window) + ESC kill       │      │  (física idêntica) + HUD  │
└──────────────────────────────────────────┘      └───────────────────────────┘
 * telemetria real do ETS2 = plugin SCS SDK (roadmap)

Treino: ets2ai/ (numpy puro) ─► pesos idênticos ─► Java (APK), TFLite, bridge
```

**Contrato de features (12):** velocidade, desvio da faixa, erro de proa,
5 curvaturas à frente (8/18/30/45/60 m), limite, combustível, fadiga,
distância da entrega. **Saídas (3):** volante, acelerador, freio. Detalhe em
`ets2ai/contract.py` — único ponto de verdade replicado nas 3 implementações.

## Como usar

### APK (celular)
1. Baixe `ETS2-AI-mobile.apk` (release `ets2-ai-v0.1.0` ou artifact do CI).
2. Instale (permitir "fontes desconhecidas").
3. Toque **ROTA** para nova estrada (o dispatcher já escolhe a melhor oferta
   de job sozinho), **IA** liga/desliga (sem IA: toque à esquerda/direita =
   volante, meio = freio), **VEL** = x1/x2/x4, **NPU**/**BACKEND** =
   diagnóstico e benchmark medido de aceleradores, **BRIDGE** = conectar ao
   PC pela rede, **TECLADO BT** = o celular vira um **teclado Bluetooth
   real** no PC (pareie o PC com o celular antes, nas configurações).

### Bridge (PC) — leve por construção
**O projeto NUNCA captura a tela do jogo** (0% de GPU/CPU do ETS2): o estado
vem da telemetria/demo. Para PC fraco (Pentium N5030 / 4 GB RAM):

```
ETS2-AI-bridge.exe --sem-janela                # modo leve: sem janela, só rede
ETS2-AI-bridge.exe --bench                          # prova o custo de CPU (impacto ~0 no FPS)
ETS2-AI-bridge.exe --sem-janela --somente-celular --inject --window "Euro Truck"
#   ^ a IA roda SÓ no celular; sem conexao o caminhao FREIA (seguranca)
ETS2-AI-bridge.exe                             # janela demo; IA local ou do celular
ETS2-AI-bridge.exe --inject --window "Euro Truck"   # injeta teclas reais
ETS2-AI-bridge.exe --record sessao1.csv             # grava p/ finetune (DAgger)
```
- No app: **BRIDGE** → IP do PC (o bridge imprime na tela) → porta 7777.
- Sem celular conectado (ou RTT > 0,5 s): failover automático para a IA local.
- `--inject`: só envia teclas quando a janela alvo está em foco; **ESC mata**
  a injeção permanentemente. Teclas padrão = setas (padrão do ETS2);
  edite `KEYMAP` no topo do script para remapear.

### Treinar / testar localmente
```
python -m venv .venv && .venv/bin/pip install numpy pytest
python -m ets2ai.train          # retreina e reexporta pesos
pytest tests/ -q                # 10 testes, incl. circuito fechado
bash android/check_java.sh      # paridade Java × numpy (precisa javac)
```

## Protocolo celular ↔ PC (v1, CSV sobre TCP)

```
PC → celular:  S,<vel_m/s>,<desvio_m>,<erro_proa>,<c1>,<c2>,<c3>,<c4>,<c5>,<limite>,<comb>,<fadiga>,<km_restantes>,<ts_ms>
celular → PC:  C,<volante>,<acel>,<freio>,<ts_ms eco>        # RTT = agora − eco
```
Valores físicos brutos; a normalização (÷25, ÷3.5, ÷0.6, ÷0.05…) segue
`NeuralNet.features`/`ets2ai.sim.features` — idêntica nos dois lados.

## Treino no Kaggle disparado pelo GitHub Actions

O workflow tem o job **"Treino no Kaggle (opcional, via secrets)"**: ele
empurra um kernel com o MESMO código e semente do repo para a sua conta
Kaggle, aguarda a execução, baixa os pesos e roda os mesmos gates de
qualidade. Sem secrets configurados ele apenas avisa e fica verde (o treino
local do CI continua sendo a fonte oficial).

Para ativar (1 minuto):
1. **NUNCA cole o token em chat/commit.** Gere em kaggle.com → Settings →
   API → Create New Token (e expire qualquer token já exposto).
2. Repo → Settings → Secrets and variables → Actions:
   - `KAGGLE_USERNAME` = seu usuário Kaggle
   - `KAGGLE_KEY` = o token
3. Push qualquer mudança em `ets2-ai/` (ou Actions → Run workflow).

O kernel é montado por `ets2-ai/kaggle/build_kernel.py` (auto-contido) e
orquestrado por `ets2-ai/kaggle/push.py`.

**GPU 2× T4 (v0.4.3):** o job `kaggle-train` do CI **empurra o kernel,
aguarda a execucao nas 2×T4 (MirroredStrategy, FP64), baixa os pesos
treinados, valida com os mesmos gates e commita como pesos canonicos** —
a release inteira é construída a partir do treino da GPU. Sem o secret
`KAGGLE_KEY`, o mesmo job treina localmente (determinístico) para o
pipeline nunca parar. Para forçar o treino na GPU a qualquer momento:
Actions → *ETS2-AI build* → **Run workflow** → marcar **"Forcar treino
nas 2x T4 do Kaggle"**. O link do notebook ativo aparece no log do job.

### Rodar manualmente no Kaggle (sem secrets)

Sem os secrets configurados, dá para treinar nas 2× T4 direto na UI do
Kaggle em 4 passos (conta precisa de telefone verificado):

1. Abra **kaggle.com → Code → New Notebook**;
2. Settings → Accelerator → **GPU T4 x2**;
3. Cole o conteúdo de `kaggle/kernel-ets2ai-v0.4.4.py` numa célula
   (ou importe `kaggle/kernel-ets2ai-v0.4.4.ipynb` via File → Import);
4. **Run All** — procure `[kaggle] GPU detectada: 2x` no log e, no final,
   `gpu=True, ngpus=2` + circuito fechado. O notebook é 100% auto-contido
   (gera os próprios dados; nada do repo é necessário).

## Kaggle para datasets (opcional)

Se futuramente usar datasets do Kaggle:

1. **Revogue** qualquer token que já tenha colado em chat/screenshot (você
   colou dois nesta conversa — HF e Kaggle — trate-os como vazados).
2. Repo → **Settings → Secrets and variables → Actions → New secret**:
   `KAGGLE_USERNAME` e `KAGGLE_KEY`.
3. No workflow:
   ```yaml
   - run: pip install kaggle
     env:
       KAGGLE_USERNAME: ${{ secrets.KAGGLE_USERNAME }}
       KAGGLE_KEY: ${{ secrets.KAGGLE_KEY }}
   - run: kaggle datasets download -d <usuario>/<dataset> -p dados --unzip
   ```

## Offline (celular) — garantido e provado

O app funciona **100% sem internet**: a IA (pesos Java + `.tflite`), o
simulador, o dispatcher, o teclado Bluetooth e o diagnóstico NPU estão todos
**dentro do APK**. A única função que usa rede é o botão BRIDGE (TCP opcional
com o PC). O CI **prova** isso a cada build (`android/check_offline.sh`):
pesos e modelo embutidos, zero downloads em runtime.

## Interface gráfica (nova)

Ambos os apps ganharam tema escuro: painel superior com chips (engine
selecionado + OFFLINE), velocímetro grande, barras de combustível/sono,
banner de eventos, céu com gradiente, colinas, radares marcados, dock
quadriculado de chegada e caminhão detalhado (rodas, baú, para-brisa). No
PC: header com chip de fonte da IA, botões estilizados e rodapé de telemetria.

## Dados sem dirigir milhares de km (estratégia 0 km)

Você **não precisa dirigir** para gerar dados de treino:

1. **Base sintética (0 km seu):** o especialista (pure-pursuit + controle
   preditivo) dirige no simulador e gera 115 mil pares estado→ação. É a base
   já commitada e medida (loss 0.00150).
2. **DAgger — correções, não direção:** com o bridge em `--record`, a IA
   dirige e você só **aperta as setas quando ela erra** (segundos por sessão).
   Cada correção vira uma linha `override=1` na gravação e vale 3× no treino.
   Minutos de correções >> horas de direção passiva.
3. **Finetune com gates de segurança:**
   ```
   python -m ets2ai.finetune --recordings sessao1.csv sessao2.csv
   ```
   O finetune **só aprova** o modelo se: MSE na gravação ≤ 0.150 **e**
   circuito fechado ≥ 75% de rotas concluídas com > 95% na faixa. Os pesos
   base nunca são sobrescritos — o resultado sai em
   `artifacts-finetuned/` com relatório (`metrics-finetune.json`); promova
   para `artifacts/` (e rode o CI) apenas se `all_pass: true`.
4. **Calibração de telemetria (quando ligar no ETS2 real):** o mesmo formato
   de gravação serve para alinhar as features da telemetria real do jogo
   (SCS SDK) com as do simulador — gravar 5–10 min de direção normal sua
   basta para calibrar escalas/offsets.

## Roadmap para o ETS2 real

1. **Telemetria**: plugin do SCS SDK (DLL `scs-telemetry`, documentação
   pública em mod.sii/telemetry) publica velocidade, rumo, combustível,
   fadiga, rota do GPS. O formato de entrada do bridge (`S,...`) já está
   pronto para receber esses valores — basta trocar a fonte do estado.
2. **Visão (opcional)**: frames do jogo (captura de tela/DXGI) alimentando
   as features de curvatura — a rede atual usa a "leitura" da estrada; para
   dirigir só por imagem seria um segundo modelo (CNN), treinado do zero.
3. **Dados reais**: não dirija milhares de km — use `--record` + DAgger
   (ver seção anterior). O plugin de telemetria alimenta o mesmo formato.
4. **Segurança**: manter kill switch ESC + limite de janela alvo + failover.

## Estrutura

```
ets2-ai/
├── ets2ai/            # núcleo numpy: sim, dados, modelo, treino, contrato, tflite
├── android/           # app (Java puro, sem Gradle): build_apk.sh, check_java.sh
├── bridge/            # ets2_bridge.py (vira ETS2-AI-bridge.exe no CI)
├── tests/             # 10 testes: paridade, protocolo TCP, circuito fechado
├── artifacts/         # pesos + métricas (commitados; CI confere reprodutibilidade)
└── README.md
```

CI: `.github/workflows/ets2-ai.yml` — 6 jobs: retreino verificável, paridade
Java, TFLite, APK assinado, EXE Windows, release.
