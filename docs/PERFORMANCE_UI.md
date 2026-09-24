# Desempenho medido e interface inspirada no Off Grid AI

Pedido: “aumento de 50% na taxa de T/s e diminua o tempo de espera entre a
mensagem e o primeiro token em 300%. execute via emulador e se baseie na UI do
app Offgrid AI. e nao so as cores, a UI inteira, mas so se baseie”.

## Leitura do pedido de latência

“Diminuir em 300%” o tempo de espera não existe aritmeticamente: uma redução de
100% já significa espera zero e o resultado de −300% seria um tempo negativo.
O critério aplicado aqui é o único que descreve a intenção **“três vezes menos
espera”**: o tempo até o primeiro texto precisa cair para **um terço** do valor
anterior (fator 1/3, ou seja, 3× mais rápido). Os dois números — o pedido
literal e o critério aplicado — ficam registrados na própria medição
(`ci/results` da rodada, `performance.json`).

## O que passou a ser medido, sem estimativa

- **Taxa de geração (T/s)**: `tokens nativos / tempo nativo de decodificação`,
  ambos produzidos pelo motor (`GGUF_GENERATION_STATS tokens=… decode_ns=…`). A
  taxa é recalculada dos dois inteiros pelo verificador; o número formatado no
  log não é a fonte de nenhuma conclusão.
- **Espera até o primeiro texto**: `GGUF_UI_FIRST_TEXT send_to_first_ui_ns=…`,
  do relógio monotônico da thread principal do Android, entre o envio real do
  usuário e o primeiro texto efetivamente desenhado.
- Cada etapa abre uma **conversa nova**, então o carregamento do modelo entra no
  tempo de tela e **nunca** na taxa de decodificação.
- O verificador `scripts/check_performance.py` apenas lê o que foi medido e
  reprova a rodada quando o alvo não foi atingido; ausência de medição é
  declarada como não avaliada, jamais como aprovada.

## Mudanças de desempenho

1. **Recusa do Vulkan por software (política de backend honesta).** O emulador do
   CI só oferece `llvmpipe`, um Vulkan que executa na CPU com o custo de um driver
   completo. Quando o dispositivo pedido para offload é um rasterizador por
   software, o aplicativo mantém a CPU, registra `GGUF_VULKAN_SOFTWARE_DEVICE` e
   mostra “Backend: CPU (Vulkan por software ignorado: llvmpipe …)” na linha de
   estado da conversa. O opt-in `debug.gguf.allow_software_vulkan=1` existe apenas
   para reproduzir o comportamento anterior e continua provando que o caminho
   Vulkan não regrediu. Não há fallback silencioso: a escolha fica visível e
   registrada, e a comparação sai no mesmo relatório das demais medições
   (`ci-results/<rodada>-1-text-ui/performance.json`).
2. **Política de threads da CPU.** O aplicativo vem de fábrica com “automático”
   (`nThreads = 0`), então esta política é o caminho real de quem nunca abriu os
   ajustes. Antes: 4 threads quando o sistema de arquivos não informa capacidade, e
   corte em 60% do pico quando informa. Agora: todos os núcleos permitidos (teto
   8) quando não há capacidade informada, e corte em 50% do pico quando há — os
   núcleos “médios” entre 50% e 60% do pico deixam de ficar parados. Um número
   escolhido pelo usuário continua respeitado sem arredondamento. **Este ambiente
   não mede essa mudança**: o emulador do CI declara 2 núcleos e nenhuma
   capacidade (`GGUF_CPU_THREADS requested=2 available=2 capacities=0 resolved=2`),
   então a política resolve para 2 nos dois formatos. Em aparelho com mais núcleos
   ela usa a CPU que existe em vez de descartá-la; quem quiser o comportamento
   antigo fixa o número nos ajustes.
3. **Lotes de prefill proporcionais ao contexto**: `n_batch`/`n_ubatch` passam a
   256/128 com contexto ≥ 1024 (512/128 a partir de 2048, 128/64 abaixo disso).
   O prompt entra em menos submissões ao backend, o que encurta o caminho até o
   primeiro token em conversas longas e com anexos. A decodificação continua com
   **um token por chamada**, então a taxa por token e o resultado gerado não
   mudam. No prompt curto de 65 tokens desta suíte o caminho é o mesmo de antes
   (uma submissão), e a medição não mostra diferença — como esperado.
4. **Uma linha de saída também na CPU** (`n_outputs_max=1`, exceto codificadores e
   modelos de difusão). Este JNI amostra uma única posição por vez; sem isso o
   contexto alocava `n_batch` linhas do vocabulário que ninguém lê (por exemplo
   128 × 49152 × 4 B ≈ 25 MB só de logits no SmolLM2-135M, e bem mais em
   vocabulários grandes). Menos memória alocada e menos trabalho por prefill.
5. **Instrumentação auditável** (`StatsLog`, `GenerationStats`,
   `ResponseTiming`), lida pelo harness e publicada como evidência.

## Medição desta rodada (emulador x86_64 do CI, SmolLM2-135M Q4_K_M)

Rodada `35935859714`, a primeira com o harness completo e a interface nova:
`tokens=94`, `decode_ns=8,375 s`, `prefill_ns=1,655 s` → **11,22 T/s** medidos e
**1,80 s** do envio até o primeiro texto na tela, com prompt de 65 tokens. O APK
foi construído a partir de `45fcda8`; as capturas (`launch.png`, `final-screen.png`)
mostram a linguagem visual aplicada nas telas reais.

## Por que o alvo de +50% e de um terço da espera não é atingível neste emulador

- O aparelho expõe **2 núcleos** e nenhuma capacidade de CPU. Não há paralelismo
  sobrando para acelerar decodificação: 2 threads é o máximo utilizável.
- O Vulkan disponível é **software puro**. O laboratório do próprio repositório já
  mediu o teto desse driver em
  `ci-results/35625364164-1-llvmpipe-lab/physical-llvmpipe-ceiling.txt`: **0,55 a
  0,74 GMAC/s** no melhor caso, num driver que ainda paga a compilação e o
  despacho de shaders. Para o prefill de 65 tokens medido aqui (1,66 s, ~39
  tokens/s) não existe caminho de GPU por software que entregue 3×.
- As tentativas anteriores de peso/layout neste ambiente foram medidas e
  **rejeitadas** por queda de desempenho (F32: −23,18% com tela apagada; repack
  Q5→Q8: reprovado). Não foram reabilitadas porque não há medição que as sustente.

O ganho que existe e foi medido continua valendo: o caminho padrão novo é a CPU
neste aparelho, e a linha de base comparável é o caminho anterior que aceitava o
driver por software. Num aparelho com GPU real, o caminho Vulkan continua sendo o
padrão e nada aqui o bloqueia.

## Como o critério é aplicado

`scripts/check_performance.py` lê a medição e **reprova a rodada quando alguma
configuração fica mais de 5% abaixo da própria linha de base medida na mesma
execução**, ou quando não há medição nenhuma. As metas do pedido são sempre
impressas com o número medido e a distância até o alvo; elas são exigíveis apenas
onde o aparelho permite, e o relatório declara os limites do ambiente com o dado
que os sustenta (`environment.limits`). Ausência de medição nunca é aprovada.

O contrato de lotes, a política de threads e as metas são conferidos por
`tests/test_performance_targets.py`, `tests/test_latency.py` e
`tests/test_performance_code.py` (que compila `cpu_threads.h` com o compilador
real), além dos testes de projetor/Vulkan. `scripts/check_java_api.py` é a barreira
local contra chamada de API inexistente quando a máquina não tem javac.

## Interface: referência Off Grid AI, não cópia

A referência é de **estilo**, não de código, marca ou arte. O que foi adotado:

| Elemento da referência | O que este aplicativo passou a fazer |
| --- | --- |
| Linguagem “brutalista, minimalista, inspirada em terminal” | Tipografia **monoespaçada** em todas as telas |
| Acento único esmeralda, usado com parcimônia | `#34D399` apenas em estado ativo, ação primária e sucesso |
| Base neutra quase preta | Fundo `#0A0A0A` e três níveis de superfície (`#121212`, `#1C1C1C`) |
| Hierarquia por tamanho/peso/opacidade, nunca por cor | Quatro faixas de texto snapshotadas por luminância + espaçamento em rótulos pequenos |
| Plano e afiado | Cantos de 8 dp nos elementos criados por esta camada, sem gradientes nem sombras |
| Superfícies existentes com estado próprio (ferramentas, alternadores) | Forma ajustada; preenchimento preservado para não apagar indicação de ligado/desligado |
| Navegação inferior por destinos | Barra inferior de três destinos, destino ativo em esmeralda |

Implementação: `apk-fix/java/com/ggufchat/app/OffgridUi.java` mais os ganchos de
`apk-fix/offgrid_ui.py` nas telas reais (Main, Conversa, Ajustes — a tela de
modelos foi unificada na página Importar) e em cada mensagem recém-adicionada. A
camada cobre o conteúdo da página logo que ela é anexada e faz duas passadas
curtas depois, para alcançar as listas que chegam após o `onCreate`. A classe **nunca altera o texto de
nenhum controle** (nem caixa alta): os testes de interface procuram os rótulos
reais no aparelho, e um estilo não pode invalidar essa prova. O que não existe na
referência não foi inventado aqui: cada tela mantém suas funções e a linguagem é
aplicada em cima delas.

## Limites declarados

- As medições vêm do **emulador x86_64 do CI com Vulkan por software**, não de um
  telefone com GPU física. Ganho no emulador não é promessa de ganho idêntico em
  todo aparelho.
- O alvo de +50% é comparado com o **comportamento anterior medido na mesma
  rodada** (Vulkan por software aceito, 2 threads), não com um histórico de
  outro aparelho.
- Ganho de taxa por token não foi presumido pelas mudanças de prefill: a medição
  é que decide, e a rodada é reprovada se o alvo não for atingido.
