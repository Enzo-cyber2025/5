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
   CI só oferece `llvmpipe`/SwiftShader, um Vulkan que executa na CPU com o custo
   de um driver completo — mensuravelmente mais lento que a CPU direto. Quando o
   dispositivo pedido para offload é um rasterizador por software, o aplicativo
   mantém a CPU, registra `GGUF_VULKAN_SOFTWARE_DEVICE` e mostra
   “Backend: CPU (Vulkan por software ignorado: llvmpipe …)” na linha de estado
   da conversa. O opt-in `debug.gguf.allow_software_vulkan=1` existe apenas para
   reproduzir o comportamento anterior e continua provando que o caminho Vulkan
   não regrediu. Não há fallback silencioso: a escolha fica visível e registrada.
2. **Lotes de prefill proporcionais ao contexto.** `n_batch`/`n_ubatch` passam a
   ser 512/128 com contexto ≥ 1024 (256/64 com ≥ 512, 128/64 abaixo disso). Isso
   encurta o caminho até o primeiro token porque o prompt entra em menos
   submissões ao backend. A decodificação continua com **um token por chamada**,
   portanto a taxa por token não é afetada e nenhum resultado gerado muda.
3. **Instrumentação auditável** (`StatsLog`, `GenerationStats`,
   `ResponseTiming`), lida pelo harness e publicada como evidência.

O contrato de lotes é conferido por `tests/test_latency.py`,
`tests/test_performance_code.py` e demais testes de projetor/Vulkan, e as metas
por `tests/test_performance_targets.py`.

## Interface: referência Off Grid AI, não cópia

A referência é de **estilo**, não de código, marca ou arte. O que foi adotado:

| Elemento da referência | O que este aplicativo passou a fazer |
| --- | --- |
| Linguagem “brutalista, minimalista, inspirada em terminal” | Tipografia **monoespaçada** em todas as telas |
| Acento único esmeralda, usado com parcimônia | `#34D399` apenas em estado ativo, ação primária e sucesso |
| Base neutra quase preta | Fundo `#0A0A0A` e três níveis de superfície (`#121212`, `#1C1C1C`) |
| Hierarquia por tamanho/peso/opacidade, nunca por cor | Quatro faixas de texto snapshotadas por luminância + espaçamento em rótulos pequenos |
| Plano e afiado | Cantos de 8 dp, bordas de fio de cabelo, sem gradientes nem sombras |
| Navegação inferior por destinos | Barra inferior de três destinos, destino ativo em esmeralda |

Implementação: `apk-fix/java/com/ggufchat/app/OffgridUi.java` mais os ganchos de
`apk-fix/offgrid_ui.py` nas quatro telas reais (Main, Conversa, Importar,
Ajustes) e em cada mensagem recém-adicionada. A classe **nunca altera o texto de
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
