# ETS2-AI — piloto automático para Euro Truck Simulator 2 (celular ↔ PC)

> **v0.1.0 — demo funcional.** A IA treinada dirige caminhão num simulador com
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
| MSE validação (loss) | **0.00150** | ≤ 0.150 ✅ (100× melhor) |
| Rotas concluídas (circuito fechado) | **100%** (7/7) | — |
| Tempo dentro da faixa | **100%** | > 95% |
| Velocidade média | **65 km/h** | — |
| Amostras de treino | 115.308 pares estado→ação | — |

Reproduza: `python -m ets2ai.train` (determinístico — o CI retreina do zero e
confere que os pesos batem com os commitados, tolerância 1e-5).

## O que é de verdade e o que ainda é demo (honestidade primeiro)

| Item | Estado |
|---|---|
| Rede neural que dirige (estrada com curvas, faixa, limites) | ✅ real, medido, testado |
| Regras de abastecer/dormir/entregas/dinheiro | ✅ real (regras sobre telemetria — não precisa de ML) |
| APK Android com a IA + HUD + diagnóstico NPU | ✅ sai do CI assinado |
| Bridge Windows `.exe` + injeção de teclas reais | ✅ sai do CI (SendInput/scan codes, kill switch ESC) |
| Celular como "cérebro" do PC (TCP) | ✅ implementado (RTT exibido) |
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
(CPU)** — para uma rede 12→24→24→3, isso custa **microssegundos** por
decisão; NPU seria overkill. Mesmo assim, o CI **já exporta os `.tflite`**
(float32 e int8) validados contra o numpy, e o app traz a tela
**"NPU" (Diagnóstico)** que mostra no seu aparelho exatamente o que existe
de aceleradores/runtimes. Se a Samsung liberar o acesso (ou você trocar de
chip), o modelo está pronto para plugar num delegate.

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
3. Toque **ROTA** para nova estrada, **IA** liga/desliga (sem IA: toque à
   esquerda/direita = volante, meio = freio), **VEL** = x1/x2/x4,
   **NPU** = diagnóstico do aparelho, **BRIDGE** = conectar ao PC.

### Bridge (PC)
```
ETS2-AI-bridge.exe                  # janela demo; IA local ou do celular
ETS2-AI-bridge.exe --inject --window "Euro Truck"   # injeta teclas reais
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

## Kaggle: token via secret, nunca em arquivo

O pipeline não depende do Kaggle hoje (dados sintéticos), mas se você for
usar datasets do Kaggle no futuro:

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

## Roadmap para o ETS2 real

1. **Telemetria**: plugin do SCS SDK (DLL `scs-telemetry`, documentação
   pública em mod.sii/telemetry) publica velocidade, rumo, combustível,
   fadiga, rota do GPS. O formato de entrada do bridge (`S,...`) já está
   pronto para receber esses valores — basta trocar a fonte do estado.
2. **Visão (opcional)**: frames do jogo (captura de tela/DXGI) alimentando
   as features de curvatura — a rede atual usa a "leitura" da estrada; para
   dirigir só por imagem seria um segundo modelo (CNN), treinado do zero.
3. **Dados reais**: gravar suas partidas (o plugin de telemetria + captura)
   gera exatamente os pares estado→ação que `ets2ai/train.py` consome.
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
