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
2. **Zero passo manual (v0.4.10) — banco com TODAS as DLLs**: o
   `ETS2-AI-bridge.exe` embute **todas as releases oficiais** do plugin de
   telemetria (MIT): **RenCloud** V.1.9.0→V.1.12.1 **+ nlhans** (original,
   jogos antigos), x64 e x86. A instalação é **100% automática** e acontece
   na **abertura do .exe**, no botão **BUSCAR**, no **COMEÇAR** e — sob
   demanda — no botão dedicado **INSTALAR TELEMETRIA (varre tudo)**, que
   varre **todo o armazenamento** (sem excluir pasta nenhuma, igual à
   descoberta dos controles), acha a pasta certa, **analisa o jogo**
   (arquitetura `win_x64`/`win_x86` + versão pelo `steam.inf`) e instala a
   **DLL ideal** para aquela versão (jogo 1.45 → V.1.11.1; 1.41–1.44 →
   V.1.11; 1.36–1.40 → V.1.10.6; 1.32–1.35 → V.1.9.0; ≤1.31 → nlhans;
   1.46+ → V.1.12.1). O botão **VERIFICAR DLL** confere o **hash SHA-256**
   da DLL instalada contra a ideal embutida: corrompida, ausente ou versão
   errada → **repara sozinho**. Se a varredura não achar o jogo, ela não
   repete sozinha (só no BUSCAR DE NOVO), mas a detecção por processo
   continua viva: **abra o jogo e toque BUSCAR**. Se o jogo já estava
   aberto na instalação, **reinicie-o 1×** (o plugin carrega na abertura).
   Primeiro o bridge tenta a **leitura de memória** (sem DLL nenhuma no
   jogo); o plugin é o plano B automático para versões sem pack de offsets
   (jogos mais antigos que 1.46 podem não validar no leitor — o log avisa).
   **Qualquer ETS2, garantido por rotação**: se o jogo estiver rodando e a
   DLL escolhida não for aceita (SDK incompatível), o bridge **troca
   sozinho para a próxima release do banco** a cada ~2 min e mostra as
   linhas do `game.log.txt` do próprio jogo explicando o motivo — reinicie
   o jogo quando o log pedir. O botão **AUTOTESTE (diagnóstico)** roda na
   sua máquina o mesmo teste completo da validação do CI (banco, descoberta,
   análise, DLL ideal, verificação, telemetria real, políticas) e grava
   `autoteste-resultado.json` — se algo não funcionar, é só mandar o log.
   E no CI todo build é **validado num Windows real**: o exe roda o
   autoteste contra instalações falsas do jogo em 5 versões (1.22 x86,
   1.35, 1.41, 1.45, 1.53) e só publica release se a DLL certa for
   instalada em cada uma **e** a telemetria real (memória compartilhada do
   "jogo falso") for lida com os valores batendo.
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
    criada**. **A IA roda no CELULAR**: o PC escreve `estado.txt` na pasta
    `ETS2AI` do celular (via MTP), o APK roda a rede e responde
    `comando.txt` (nº de sequência dentro do arquivo + detecção de mudança
    — sem problema de cache; comandos velhos são descartados); o tunel adb
    (opcional, se a Depuração estiver ligada) roda em paralelo e o que
    responder primeiro vale. No APK: conceda "acesso a todos os arquivos"
    1× (botão PERMITIR ARQUIVOS). O botão BUSCAR (sempre visível, independe
    da conexão) localiza o jogo (busca completa 1×, depois usa o salvo) e
    mostra as teclas.
  - **Túnel adb (opcional)**: com Depuração USB ligada, o cérebro (GPU) pode
    rodar no celular — túnel `adb reverse` em localhost (nada na rede).
    `--rede` abre para Wi-Fi só como exceção.
  - **IA no PC (PADRÃO, PC primeiro — escada honesta)**: a política local é
    numpy puro — **0% de GPU** (nem toca) e **zero atraso**. Na abertura o
    exe MEDE a máquina (no caminho real) e sobe a escada:
    1. **rede oficial** (290×13, 1,02 M params): se rodar a ≥250 inf/s
       (≤8% de 1 núcleo a 20 Hz), ela dirige no PC (~85 MB de RAM);
    2. **rede DESTILADA (nano)**: se a oficial não couber (caso do
       Pentium N5030, ~208 inf/s = 9,6% de 1 núcleo), o exe tenta a nano —
       ~28 mil parâmetros (36× menor, cabe no cache L2), **destilada da
       oficial na mesma distribuição de treino** (relatório de fidelidade
       em `distill-report.json` na release; malha fechada equivalente).
       Precisa medir ≥2.000 inf/s = **≤1% de 1 núcleo = 0,25% do N5030**;
    3. **celular via cabo** (arquivos MTP, sem depuração, sem porta TCP):
       só se nem a nano couber.
    Com 1 ou 2 o botão COMEÇAR fica liberado **sem celular** — o APK
    conectado vira painel/backup. Os números aparecem no log `[ia-pc]`.

## 3) `drive` — a IA dirige de verdade

> **Fluxo v0.4.8 (COMEÇAR → tela cheia):** o botão COMEÇAR pode ser clicado
> **antes** de abrir o jogo — a IA fica **esperando o ETS2 por até 15 min**
> (log: "aguardando o ETS2 abrir...") em vez de fechar na hora. Quando a
> telemetria aparece, a IA **só começa a agir com o jogo em TELA CHEIA**
> (janela cobrindo o monitor e em 1º plano): fora dela, todas as teclas
> ficam soltas e o log mostra o motivo — é o consentimento para a IA
> assumir o volante. ESC continua sendo o kill switch. Se a DLL de
> telemetria acabou de ser auto-instalada, **reinicie o jogo** uma vez.
> Quem dirige: rede oficial no PC → rede destilada (nano) no PC → celular
> via cabo (escada medida na sua máquina, ver seção 2).

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

## v0.4.11 — QUALQUER ETS2 (validada no CI, build 37680919405, 9/9 jobs)

- **Rotacao automatica de DLL**: jogo rodando sem telemetria = o jogo
  recusou o SDK → o bridge instala a PROXIMA release do banco a cada
  ~2 min e loga o motivo lido do `game.log.txt` do jogo.
- **Autoteste ponta a ponta** (botao GUI + CLI `--autoteste`): banco,
  descoberta, analise, DLL ideal, hash, TELEMETRIA REAL (jogo falso cria
  a memoria compartilhada `Local\SCSTelemetry` como o plugin faz).
- **Job validacao-windows no CI**: baixa o .exe do build, monta ETS2s
  falsos e roda o autoteste exigindo a DLL certa + telemetria em cada.
  Fix da 1a tentativa (13 s): exe `--noconsole` = GUI → pwsh `& exe`
  nao espera → `Start-Process -Wait -PassThru` + `$p.ExitCode`.
- QEMU descartado: runners do GitHub nao tem KVM (TCG = imagem de
  ~20 GB, boot 30-60 min); `windows-latest` e Windows REAL, melhor.

## v0.4.12 — DLL em pasta protegida + diagnostico que o usuario ENVIA

- **CAUSA RAIZ do "nao funciona" no PC real**: ETS2 do Steam fica em
  `C:\Program Files (x86)\Steam\...` — pasta PROTEGIDA; a copia da DLL
  falhava com PermissionError e so logava uma linha. Agora o bridge
  pede **PERMISSAO DE ADMINISTRADOR ao Windows (UAC)**: 1 clique em SIM
  e um powershell elevado instala a DLL no lugar oficial
  (`_elevated_copy` via ShellExecuteEx "runas"). Recusou = log explica
  o que fazer.
- **AUTOTESTE com janela de resultado + botao COPIAR RESULTADO**
  (cola o JSON no chat) e ABRIR PASTA; salva `autoteste-resultado.json`
  AO LADO DO .exe (nao mais no cwd qualquer).
- **Log de sessao**: tudo ([jogo]/[dll]/[autoteste]) vai para
  `ets2-ai-log.txt` ao lado do .exe (teto 256 KB).
- **Crash dump**: qualquer erro fatal gera `ets2-ai-erro.txt` + janela
  avisando onde esta — nada morre em silencio.
- **CI ate o ETS2 ATUAL**: casos 1.61 (17/set/2026) e 1.58 no
  validacao-windows (7 versoes: 1.22 x86 → 1.61); contagem dinamica.
- Descobertas da pesquisa: RenCloud V.1.12.1 continua sendo a release
  mais recente do plugin e FUNCIONA no 1.57+ (forum SCS); versoes novas
  do jogo mostram AVISO DO SDK na inicializacao — o jogador precisa
  clicar OK/Permitir (comportamento do proprio jogo, nao nosso).
- Suite: 126 passed, 1 skipped.

### v0.4.12 fix (2º commit do ciclo) — validacao-windows x CI

A 1a rodada do v0.4.12 falhou no job validacao-windows: todos os casos
escolhiam a DLL do 1o jogo. Duas causas, ambas bugs REAIS (nao so no CI):

1. **O cache (ets2-ai-state.json) sobrescrevia o --game-dir explicito**:
   quem passa um caminho na mao (ou o CI valida 7 pastas na mesma
   maquina) recebia o jogo do cache anterior. Agora o caminho EXPLICITO
   sempre vence (e atualiza o cache para ele).
2. **Jogo x86 (32 bits) nao era reconhecido como jogo**: bin/win_x86
   agora conta como instalacao valida no dir_looks_like_game.

Reproduzido localmente o loop exato do CI (cwd compartilhado, 7 jogos):
7/7 OK (1.61, 1.58, 1.53 -> V.1.12.1; 1.45 -> V.1.11.1; 1.41 -> V.1.11;
1.35 -> v.1.9.0; 1.22 x86 -> nlhans revision_5_rel_1_4_0). Suite: 128
passed, 1 skipped (+2 testes de regressao do cache/--game-dir e x86).

## v0.4.13 — o app se autodiagnostica (1a execucao) + VC++ + LEIA-ME

- **Primeira execucao = assistente automatico**: sem jogo salvo no
  ets2-ai-state.json, o app roda SOZINHO na abertura: busca do jogo →
  instalacao da telemetria (UAC se pasta protegida) → AUTOTESTE →
  janela de resultado com botao COPIAR RESULTADO. O usuario nao
  precisa saber qual botao apertar; se algo falhar, so copiar/colar.
- **Step "visual c++" no autoteste**: a DLL do plugin precisa do VC++
  Redistributable; se faltar (x64 e/ou x86), o autoteste reprova com o
  link de instalacao (aka.ms/vs/17/release/vc_redist.x64.exe) — antes
  era falha silenciosa no game.log.txt do jogo.
- **LEIA-ME.txt em portugues publicado na release** (5 passos + o que
  enviar quando algo falhar + link do VC++).
- step() do autoteste agora suporta SKIP (ok=None).
- Suite: 128 passed, 1 skipped.

## v0.4.14 — EXE 32-bit + blindagem dos erros de uso mais comuns

- **ETS2-AI-bridge-x86.exe**: build 32-bit (Python x86 + numpy 2.2.6
  win32) publicado junto do x64 — para Windows antigo 32-bit (o unico
  cenario em que o exe x64 nem abre; cobre ETS2 x86 antigo no PC velho).
  O CI valida o x86 tambem (autoteste do exe 32-bit em Windows real).
- **LEIA-ME atualizado**: EXTRAIR do ZIP antes de abrir (rodar de dentro
  do ZIP perde o estado), SmartScreen ("Windows protegeu seu PC" →
  Mais informacoes → Executar assim mesmo) e o exe x86.
- **Link da PROVA nas notas da release**: URL do run que validou ESTA
  build (exe inteiro contra 7 versoes do ETS2 + o 32-bit) — no lugar do
  QEMU, que e tecnicamente impossivel nos runners (sem KVM).
- **Autoteste reporta a maquina**: versao do Windows + 32/64-bit do
  processo (vai no COPIAR RESULTADO — diagnostico sem palpite).
- Suite: 128 passed, 1 skipped.

## v0.4.15 — o jogo ABERTO manda sobre o cache (DLL na instalacao certa)

- Sintoma relatado pelo usuario: "nao instala a telemetria (e nao e a
  correta)". Causa provavel: com 2+ instalacoes do ETS2 no PC (Steam +
  repack), o cache salvava UMA e a DLL era instalada nela para sempre —
  mesmo quando o usuario jogava a OUTRA. Agora o processo rodando
  (eurotrucks2.exe) tem prioridade absoluta: se o jogo aberto esta em
  outra pasta, o cache e corrigido na hora e a DLL vai para o jogo da
  vez. +2 testes de regressao; suite: 130 passed, 1 skipped.
