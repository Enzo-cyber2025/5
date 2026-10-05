# Fazer a IA PRATICAR no ETS2 (telemetria real)

Este é o caminho do **treino/aprendizado no jogo de verdade**: a IA lê a
telemetria do ETS2, **aprende a estrada dirigindo com você**, depois dirige
sozinha — e cada correção sua vira dado de treino (DAgger). Sem captura de
tela, sem mexer no jogo: só o plugin oficial de telemetria da SCS + teclas.

```
   ETS2 ──(DLL RenCloud)──> memoria Local\SCSTelemetry ──> ets2ai.practice
                                                        │
     mapa da pista aprendida (practice/mapa.json) <──────┤ gravar/refinar
                                                        │
   teclado <──(SendInput, volante PWM)───────────────────┴── rede 290×13
```

## 0) Requisitos (uma vez só) — PLUG & PLAY

1. **ETS2 original 64-bit** (Steam) no Windows.
2. **Nada de DLL na mão**: o `ETS2-AI-bridge.exe` (v0.4.5+) já embute a DLL
   de telemetria (plugin RenCloud, licença MIT) e **instala sozinho** na
   pasta do jogo na primeira vez que você roda um modo de prática — ele
   acha o ETS2 pelo registro do Steam. Se quiser, force o caminho com
   `--game-dir`. (A DLL também é open source: RenCloud/scs-sdk-plugin.)
3. **Celular no cabo USB** (opcional, para a IA rodar no aparelho): o .exe
   também embute o `adb` e cria o túnel `adb reverse` sozinho — no app toque
   **BRIDGE → AUTO** e conecta (sem digitar IP, sem Wi-Fi). Requer
   "Depuração USB" ativada uma única vez no aparelho.
   - **Tela bloqueada? Sem problema** (v0.4.6+): enquanto o bridge ou o
     teclado BT está ativo, o app sobe um serviço em 1º plano (wake lock
     parcial + Wi-Fi em alto desempenho) — a IA roda na **mesma velocidade**
     com a tela ligada ou bloqueada, e a notificação mostra **cmd/s e RTT ao
     vivo** (com botão Encerrar). Trave a tela e confira: o contador de
     comandos continua subindo no mesmo ritmo. Na 1ª vez o Android pergunta
     se você quer isentar o app da otimização de bateria — recomendo aceitar
     (fabricantes como a Samsung são agressivos com apps em 2º plano).
4. Rodar: `ETS2-AI-bridge.exe --ets2 record` (ou
   `python -m ets2ai.practice record` com o repo).

> Como funciona por dentro: `ets2ai/telemetry.py` lê os 32 KB de
> `Local\SCSTelemetry` (layout oficial do plugin, offsets travados por
> testes). O SDK **não** dá offset na faixa nem curvatura à frente — por isso
> o `ets2ai/roadmap.py` **aprende a estrada** com as passadas que você dirige
> (linha central + curvaturas a 8/18/40/90/170 m, os mesmos 5 olhares da rede).
> A conversão de eixos do jogo é **calibrada automaticamente** na primeira
> dirigida com curvas (detecção de espelhamento).

## 1) `record` — você dirige, a IA aprende a estrada (1ª sessão, ~5 min)

```
python -m ets2ai.practice record            # ou: ETS2-AI-bridge.exe --ets2 record
```

- Dirija um trecho **com curvas** no começo (calibra os eixos do mundo).
- Na **1ª passada** o mapa é construído; da **2ª passada** em diante tudo
  vira dado de treino (gravado em `practice/record-<data>.csv`).
- Quanto mais passadas, mais refinada a linha central (média das passadas).
- Ctrl+C encerra e salva `practice/mapa.json` (o "cérebro da estrada").

## 2) `shadow` — a IA observa e dá o veredito (segurança primeiro)

```
python -m ets2ai.practice shadow
```

Você dirige; a IA só calcula o que faria. No HUD aparece a **concordância**
entre a IA e você:

- `sinais OK (concordancia 8x%)` → pode ir para o modo drive;
- `ESPELHADO` → rode `record` de novo em trechos com curvas (a calibração
  vai corrigir) antes de deixar a IA dirigir.

## 2b) Telemetria: duas vias (`--telemetry`)

| via | como | quando |
|---|---|---|
| `mem` (`--no-dll`) | LEITURA de memoria do processo — **não instala NADA** na pasta do jogo | offsets da sua versão no pacote `ets2-mem-offsets.json` (ao lado do .exe, editável sem recompilar) |
| `dll` | plugin SDK oficial (RenCloud, MIT) **embutido no .exe** com auto-install invisível | sempre funciona; é o padrão quando `mem` não valida |
| `auto` (padrão) | tenta `mem` primeiro; se não validar, usa a `dll` embutida | recomendado |

O leitor `mem` precisa de `speed + world_x + world_z` no pacote para dirigir;
campos que faltam ganham padrões seguros, e a detecção de humano usa as
teclas FÍSICAS do teclado (não a telemetria).

## 2c) Tomada imediata (`drive`)

A IA assume **no primeiro tick** — caminhão parado? Ela liga o motor (E),
solta o freio de mão (.) sozinha e arranca. Com o mapa ainda vazio ela
assume moderada (~40 km/h) até se situar (~40 pontos de estrada), depois
acelera até o limite. ESC continua sendo o kill switch e encostar no
teclado vira correção DAgger.

## 2d) Teclas ORIGINAIS do jogo + USB

- **Versões alternativas (repacks tipo optijuegos)**: a pasta do jogo é
  achada **sem depender do Steam**, em cascata: `--game-dir` > processo
  rodando > Steam > **varredura LITERAL do disco todo** (TODAS as pastas de
  TODOS os discos locais — fixos e pen drive — sem excluir nada, nem
  pastas de sistema/ocultas; teto de 10 min só contra travamento) >
  **último caso: rastros do jogo** (atalhos .lnk e registro de
  desinstalação) > **config padrão**. O parser do
  `controls.sii` também entende **aliases** de perfis antigos
  (`input k_left \`keyboard.a?0\``). A busca completa roda **UMA vez** e o
  caminho fica salvo em `ets2-ai-state.json` (ao lado do .exe): nas
  execuções seguintes ele é usado direto (sem varrer disco de novo) e o
  estado é atualizado a cada execução (telemetria usada, modo, nº de
  execuções). Se o jogo mudar de lugar, refaz a busca uma única vez.
- **Joystick/volante/gamepad**: todos os controles são vigiados (DirectInput
  + XInput, sem instalar nada). Como a IA só injeta teclas, qualquer
  movimento de eixo/botão de um controle = humano intervindo — a IA solta o
  volante na hora e grava a correção (funciona até na telemetria sem DLL).
- **Mapeamento original**: o bridge lê o `controls.sii` do SEU perfil
  (`Documents\Euro Truck Simulator 2\profiles\<id>\`) e usa as teclas que
  o jogo realmente espera — dsteerleft/dsteerright/dforward/dbackward,
  parkingbrake, engine, lblinker/rblinker. Sem o arquivo (ou bind faltando),
  cai no padrão **WASD** (W/S/A/D, E motor, espaço freio de mão, [ ] setas).
  No log aparece `[teclas] mapeadas do jogo: <caminho>`.
- **Setas**: a IA acende a seta ~60 m antes de curvas fortes (raio < ~300 m)
  e apaga ao endireitar (respeitando o auto-cancel do próprio jogo).
- **Freio de mão**: puxado ao parar no destino; solto sozinho no arranque.
- **Abastecer / dormir**: com telemetria completa (DLL ou pack de offsets
  com fuel/rest_stop): tanque < 15% ou sono — a IA avisa, e parada no posto/
  descanso confirma o diálogo com Enter.
- **Conexão**: dois modos, ambos só cabo (zero internet):
  - **Cabo simples (padrão, zero configuração)**: espete o cabo USB com o
    celular em "Transferir arquivos" — **sem Depuração USB e SEM porta TCP
    criada**. **A IA roda no APK**: o PC escreve `estado.txt` na memória do
    celular (MTP — o mesmo canal do Explorador de Arquivos), o APK roda a
    rede (GPU) e devolve `comando.txt`. Entre respostas, o PC suaviza com a
    mesma IA em numpy (pesos idênticos). O botão BUSCAR (sempre visível,
    independe da conexão) localiza o jogo (busca completa 1×, depois usa o
    caminho salvo) e mostra as teclas. *Taxa menor que o túnel adb (MTP
    grava ~3×/s); com Depuração USB o túnel roda a 20 Hz.*
  - **Túnel adb (opcional)**: com Depuração USB ligada, o cérebro (GPU) pode
    rodar no celular — túnel `adb reverse` em localhost (nada na rede).
    `--rede` abre para Wi-Fi só como exceção.

## 3) `drive` — a IA dirige de verdade

> **IA no CELULAR (revisado v0.4.6+):** no modo real, se o APK estiver
> conectado (BRIDGE → AUTO), a IA roda **no celular** (GPU/TFLite) — o PC
> só lê a telemetria e injeta as teclas. Sem celular, a IA local do PC
> assume automaticamente. O cabo USB (túnel adb) também funciona aqui.

## 3) `drive` — a IA dirige de verdade

```
python -m ets2ai.practice drive --inject --window "Euro Truck"
```

- **ESC = kill switch** (solta todas as teclas na hora).
- Teclas usadas: setas (volante em PWM proporcional, aceleração, freio) —
  binds padrão do ETS2.
- Seguranças embutidas: sem telemetria/menu → solta as teclas; estrada sem
  mapa → limita a ~30 km/h; curva à frente → freia antes (governador ESC);
  fim da rota → para na linha da entrega; nunca para no meio da estrada
  (anti-stall).
- **Você é o professor**: encoste no teclado a qualquer momento — a IA
  detecta, solta o volante e grava sua correção como dado prioritário
  (DAgger). Quando você solta, ela volta a dirigir.

## 4) `finetune` — a sessão vira aprendizado (o "praticar" de verdade)

```
python -m ets2ai.finetune --recordings practice/record-*.csv practice/drive-*.csv
```

- Se o relatório aprovar (MSE ≤ 0,150 e circuito fechado ≥ 75%), promova:
  ```
  cp artifacts-finetuned/model-weights.json artifacts/model-weights.json
  ```
- Os pesos promovidos valem para **TUDO**: o `.exe` do bridge, o APK
  (recarregando os pesos no app) e o modo drive da próxima sessão.

## 5) Repita

Cada ciclo record → drive → finetune deixa a IA melhor **na sua estrada, no
seu caminhão, no seu estilo**. O mapa cresce sozinho conforme você dirige
rotas novas (a IA estende o mapa onde ele não existe).

## Praticar SEM o meu PC rodando o jogo — o que é possível (honesto)

O **jogo** precisa existir em algum lugar: ETS2 é pago, Windows, sem
servidor dedicado/headless e sem build para nuvem pública. As opções reais:

| Opção | Custo | Como fica |
|---|---|---|
| **Seu PC** (recomendado) | já tem | Tudo plug & play: .exe instala a DLL, `adb reverse` conecta o celular no cabo, o modo prática aprende dirigindo |
| **PC na nuvem com GPU** (Shadow, Azure NV, Paperspace...) | ~R$ 50-150/mês | Você instala Steam+ETS2 lá e roda o MESMO `.exe` (a DLL auto-instala). A prática acontece na VM; você só assiste/controla por streaming |
| **"ETS2 grátis na nuvem"** | — | **Não existe**: jogo pago, DRM do Steam, sem versão headless. Qualquer promessa disso é pirataria |

O que **já** roda 100% na nuvem de graça é o **treino em massa**: a cadeia
de sessões 2×T4 do Kaggle (workflow `ets2-ai-chain.yml`) acumula amostras
até passar de **500 bilhões** (~1,25 bilhão de km) sem tocar no seu PC —
ver `CHAIN.md` (contador) e `STATUS.md` (sessão ao vivo). A
prática no jogo (record/shadow/drive) é o complemento que adapta a rede à
sua estrada real em minutos, por DAgger.

## Perguntas frequentes

- **Funciona em qualquer mapa/mod?** Sim — nada é extraído dos arquivos do
  jogo; a estrada é aprendida dirigindo.
- **Dá para treinar só no Kaggle?** Não. O ETS2 é um jogo Windows pago, sem
  interface programática de input/telemetria na nuvem. O Kaggle treina a rede
  base (1B de amostras do simulador); a prática no jogo adapta a base à
  realidade (é mais rápida exatamente por isso: minutos de correções valem
  mais que milhares de km dirigidos).
- **Perde algo em relação ao simulador?** Os radares: o SDK não expõe a
  posição das câmeras — a rede recebe "sem radar à frente" e respeita o
  limite da via (feature real `speed_limit` da telemetria).
- **Desempenho no N5030/4 GB?** Loop de 20 Hz, numpy puro, um forward de
  1M parâmetros por tick (~1 ms) — provado pelo `--bench` do bridge.
- **A IA dirige mal no início da estrada nova** — normal: sem mapa não há
  offset/curvatura; ela anda devagar (30 km/h) até você gravar uma passada.

> Nota de build (retrigger): job Treino do build 37364256906 foi cancelado na fila sem iniciar nenhum passo (testes verdes no mesmo commit); este build repete o mesmo conteudo.

> Nota: builds 19:34/19:55/20:10 foram cancelados pelo incidente GitHub Actions (runners; 0 passos executados). Retry.

> Retry 2 do incidente Actions (jobs ganhando runners gradualmente: Treino/EXE/TFLite OK na tentativa anterior).
