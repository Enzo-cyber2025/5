# Meta atual: +200% = 3×, agrupamento de linhas Vulkan

A solicitação atual substitui a meta de +100%: **pelo menos 3× a taxa de T/s**
do APK anterior à primeira aceleração, `0c45fd2e…`. Não é 200% da velocidade
original (2×); é aumento de 200% (3×). Os relatórios e avaliadores históricos
com meta 2× permanecem intactos, para não reescrever os resultados anteriores.

## Hipótese, não resultado

O upstream fixado `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4` especializa o
matvec pelo número de linhas independentes (`NUM_ROWS`). No llvmpipe testado,
Q5_0 usa duas linhas por grupo e Q8_0 usa uma. O experimento multiplica
`rm_stdq` por **4**, configurando respectivamente oito e quatro linhas,
com o mesmo divisor de dispatch e a mesma constante de especialização.

- Não converte pesos, não reescreve GGUF, não reduz precisão ou contexto.
- Preserva fontes dos shaders, redução por linha, largura dos grupos, atenção,
  sampling, número de tokens, batch/ubatch e número de threads.
- Pode reduzir o custo de agendar grupos e reutilizar leituras de ativações.
  Também pode piorar pressão de registradores. Nenhum ganho é presumido.
- Fatores aceitos em tempo de execução: 1 (controle), 2, 4 e 8. A medição de
  confirmação usa somente 4 e 8, declarados antes da execução.
- Build `GGUF_EXPERIMENT_ROW_TILE=1` e ambiente `GGUF_VK_ROW_TILE=4` obrigatórios.
  Ambos ficam fora do caminho normal. Sem variável: controle, fator 1.
- O modo ativo rejeita outros valores, hardware que não seja llvmpipe FP32,
  integer-dot habilitado, subgroup diferente de 8 ou flags que forcem MMVQ.
  Não é uma otimização já qualificada para GPU física.
- Não consulta `device->mmvq_mode` durante criação de pipelines: esse campo só
  recebe sua política depois de `ggml_vk_load_shaders`. Valida as flags de
  ambiente diretamente, sem ler um campo ainda não inicializado.
- Não combina expansão F32, repack Q5→Q8, prefixo multimodal ou espera alterada.

O log registra a configuração e o primeiro dispatch de uma coluna para Q5_0,
Q8_0, Q4_K e Q6_K, incluindo linhas efetivas, ativação F32 e ausência de
requantização. Compilações dinâmicas repetem a linha de configuração; o
avaliador exige que todas sejam **idênticas** (uma única configuração), não
uma linha única. A primeira execução falhou exatamente por isso: o build estava
correto, mas o parser tratava compilações repetidas como ambiguidade.
Isso não é um perfil de tempo dos kernels. A conclusão nativa e a auditoria de
Vulkan estrito são verificações separadas da execução. A telemetria pontual
ocorre no warmup; as verificações `call_once` permanecem no código medido.

## Por que essa hipótese, com dados

Timings instrumentados de um experimento anterior
(`ci-results/35156484592-1/physical-vulkan-kernel-timings.txt`) mostram, do
tempo total, aproximadamente 30% em `MUL_MAT_VEC q5_0 m=1536 n=1 k=576`, 15% em
`MUL_MAT_VEC q8_0 m=49152 n=1 k=576` (cabeça de vocabulário), 7% em
`MUL_MAT_VEC q6_K`, 7% em `MUL_MAT_ADD MUL_MAT_VEC q5_0`, 6% em outros combos
Q5_0/Q8_0 e 4% em `MUL_MAT_VEC q4_K`. Todos rodam a **~1-2 GFLOPS/s**, cerca de
1% do que o hardware entrega — ou seja, o custo está no número de grupos de
trabalho despachados e não na aritmética. O divisor de dispatch
(`wg_denoms[0]`) é o que define quantas linhas cada grupo cobre, então aumentar
esse multiplicador reduz o número de despachos sem mudar nenhuma conta.

Isso é uma hipótese quantitativa, não um resultado: o perfil tem overhead de
instrumentação e foi medido em outro runner. O efeito real precisa aparecer nos
pares cronometrados.

## Protocolo e aprovação

1. Compilar x86_64 e ARM64, assinar **somente cópia diagnóstica descartável**.
2. Mesmo APK experimental OFF e ON em processos separados: observar respostas
   completas, prompts e IDs de entrada iguais. Não usar esses tempos na razão
   de velocidade. Não alegar equivalência bit a bit de todos os intermediários.
3. Executar três trios alternados: histórico/entregue/candidato;
   candidato/entregue/histórico; histórico/entregue/candidato.
4. Fixture SmolLM2-135M Q4_K_M, contexto 2048, threads 2, GPU 99, batch 128,
   ubatch 32, greedy, orçamento 128. Warmup excluído. Exatamente 128 callbacks
   e 128 tokens segundo contador nativo; usar 127 intervalos após o primeiro
   callback. Não incluir prefill nem confundir taxa com UI/footer/kernel puro.
5. Cada razão candidato/histórico **≥3** e cada razão candidato/entregue **≥1**,
   com saídas completas iguais. Exigir os dois estados de tela. Um par ruim
   reprova mesmo se a mediana atingir 3×.
6. Não comparar taxas absolutas entre runners, somar ganhos de experiências
   diferentes, diminuir orçamento ou retardar controles.

Workflow: `.github/workflows/row-tile.yml` (matriz estado × fator: 4 jobs);
avaliador: `ci/evaluate_row_tile.py`, que grava
`evidence/physical-row-tile-target-<estado>-f<fator>.json`. A meta é atingida se
**existir um fator pré-declarado** com todas as razões históricas ≥3 e todas as
razões contra o entregue ≥1, nos dois estados.
O sucesso de um estado não aprova release. Imagens, outras cargas, startup,
memória, CPU/arquiteturas não suportadas, GPU física e continuidade da assinatura
continuam necessários. O APK entregue `bd7c45d3…` não é alterado.

## Observação por token sem teto artificial de callbacks

O código normal agrupa entregas separadas por menos de 50 ms. Acima de cerca de
20 T/s isso pode produzir menos de 128 callbacks para 128 tokens; contar esses
callbacks como se fossem tokens seria incorreto. O build experimental, tanto
OFF quanto ON, entrega cada trecho real após sampling/decode, sem esse
agrupamento temporal. Não cria callbacks vazios, timestamps, espera artificial,
tokens extras ou respostas preparadas. Mantém a retenção necessária de UTF-8
incompleto; por isso a fixture ainda precisa comprovar 128 callbacks completos,
128 tokens no contador nativo independente e saídas completas iguais.

A mesma primeira/última entrega continua definindo os 127 intervalos; o trabalho
adicional de JNI fica dentro do tempo. Não se atribui um ganho ao simples
número de callbacks, nem se compara com controles que tenham agrupamento
incompatível. Os APKs históricos/entregues não são modificados e também precisam
passar a contagem 128/128. A alteração é explicitamente registrada no manifesto
`per_token_callbacks=true` e nos dois contadores nativos de cada observação.
O fluxo normal e o APK entregue conservam a política anterior. Esta é mais uma
razão para não chamar o experimento de release qualificado.

## Validação antes da execução Android

121 testes locais passaram; quatro foram omitidos por dependências locais
ausentes (compilador GLSL, JDK ou DEX do candidato). Há teste C++ executando o bloco real de configuração com
macro ON/OFF, checagem do patch contra o upstream fixado, testes de identidade,
telemetria e rejeição do avaliador 3×. Esses testes **não provam velocidade nem
execução de shaders no Android**. A execução nativa e as taxas ainda precisam
ser obtidas pela CI.


## Execuções anteriores: falhas de diagnóstico, não de medição

Segunda execução (35444185532): o estado ON falhou no guard do experimento. A
checagem comparava `device->name`, que é o identificador lógico **"Vulkan0"**, com
"llvmpipe"; o nome real do dispositivo físico está em
`device->properties.deviceName`. Corrigido, com log anterior à validação
(`GGUF_VK_ROW_TILE_PRE`) para que qualquer falha exponha os valores medidos, e
com verificação de que `linhas_por_grupo × subgroup` cabe em
`maxComputeWorkGroupInvocations`. Nenhuma taxa foi publicada nessa execução.

Build nativo passou; os dois jobs de medição falharam no parser antes de
qualquer razão ser calculada. O log nativo mostra `GGUF_VK_ROW_TILE factor=1`
30 vezes por estágio (uma por compilação dinâmica de pipeline) — o build estava
correto e o fator OFF é 1. Nenhuma razão de velocidade foi publicada, nenhum
APK foi entregue, nada foi declarado como ganho. A lista de despachos também
confirmou Q5_0 e Q8_0 de uma coluna com ativação F32 e sem requantização.

## Publicação pendente

A reconexão permitiu recuperar e reavaliar as evidências anteriores. Porém, na
tentativa de push do novo experimento, a autenticação voltou a falhar; a API
confirmou HTTP 401. **Nenhuma execução Android deste novo experimento foi
iniciada.** Alterações estão commitadas localmente na mesma branch. É necessária
nova reconexão do GitHub no Arena para publicar e disparar a CI. Não houve
mudança de assinatura do APK entregue nem declaração de ganho comprovado.


## Resultado medido — 35445074482 (rejeitado para a meta de 3×)

Execução válida: build nativo passou, os quatro jobs (2 estados × 2 fatores)
completaram as observações, com 128 callbacks e 128 tokens por contador nativo,
saídas completas idênticas entre OFF/ON e entre todos os pares, offload Vulkan
positivo e prova fora do tempo. Nenhum par foi descartado.

| Estado | Fator | T/s histórico | T/s entregue | T/s candidato | Ganho vs histórico | vs entregue |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Ligada | 4 | 6,980898 | 6,830280 | 7,147468 | **+2,386%** | **+4,644%** |
| Ligada | 8 | 3,989070 | 3,962265 | 2,906984 | **−26,894%** | **−26,452%** |
| Apagada | 4 | 9,068770 | 8,907170 | 8,971528 | **−0,018%** | **+1,820%** |
| Apagada | 8 | 6,703739 | 6,679453 | 6,439861 | **−3,936%** | **−3,620%** |

- Fator 8: **regressão em todos os seis pares**, com as três razões entre 0,73 e
  0,88. Não usar.
- Fator 4: ganho pequeno e **não estável** — na tela apagada um dos três pares
  ficou 1,8% mais lento que o histórico, e o ganho contra o entregue (+1,8%/+4,6%)
  está na ordem da variação já observada entre pares. Não atende 3×.
- Meta de **+200% (3×) não atingida**. `target_3x_passed=false` nos quatro jobs.
- As taxas absolutas **não** são comparáveis entre estados nem entre jobs: os
  controles rodaram a 3,99 T/s e a 6,98 T/s em runners diferentes com o mesmo
  código. Só as razões pareadas valem.

### Por que não deu 3×

O perfil nativo mostra kernels a ~1-2 GFLOPS/s, mas as três famílias de
experimento já medidas mostram que nenhum recurso isolado explica o custo:

| Experimento | O que mudou | Efeito medido |
| --- | --- | --- |
| Expansão F32 (35402357865) | remove decodificação, 6× mais bytes | +4,0% acordado, −23,2% apagado |
| Repack Q5→Q8 (35404555171) | menos operações de bits | −10,3% acordado, −6,4% apagado |
| Agrupamento de linhas f4 | 4× menos grupos | +2,4% / −0,02% |
| Agrupamento de linhas f8 | 8× menos grupos | −26,9% / −3,9% |

Menos ALU de decodificação não acelera; menos tráfego de memória acelera de
forma modesta; menos grupos de trabalho **piora** quando reduz paralelismo. Isso
indica que o tempo está distribuído em custo por elemento/por thread do llvmpipe,
não em um recurso que o agrupamento de linhas ataque. Reduzir instruções por
elemento exigiria dot product inteiro ou fp16 — o dispositivo reporta
`int dot: 0` e `fp16: 0` — ou seja, exige outro caminho numérico (proibido) ou
outra GPU.

### Incidentes de infraestrutura (registrados)

- 35450340252: o workflow de triagem era **inválido** (`timeout-minutes`
  duplicado no job), e o GitHub rejeitou o arquivo sem gastar tempo de build.
  Corrigido; agora existe teste que faz parse de todos os arquivos de workflow e
  falha em chave duplicada de job.
- Reconexões do GitHub caíram repetidamente durante a sessão (HTTP 401 na API e
  no `git push`). Os commits ficam locais até a reconexão; nada é perdido e o
  APK entregue não é tocado.

### Incidente de cache de build (encontrado e corrigido)

A triagem 35456005328 falhou nos sete jobs com `Ambiguous or missing native row
grouping`. O log nativo do braço OFF mostrava o **formato antigo** da linha de
configuração (sem `large=`), ou seja, o APK medido não correspondia ao código
do commit: o job restaurou objetos nativos compilados de uma execução anterior
e o CMake não recompilou o arquivo alterado, porque os objetos restaurados
tinham mtime mais novo que as fontes.

Correções: (1) chave de cache passa a incluir o hash de
`apk-fix/native/**`, `apk-fix/*.py` e `ci/mobile-models.sh`; (2) o build falha
explicitamente se a biblioteca empacotada não contiver os marcadores
diagnósticos atuais (`GGUF_ROW_TILE_CALLBACKS`, `large=%u fp16`,
`lanes=%u activation`, `GGUF_VK_ROW_TILE_PRE`). Assim, um binário desatualizado
não pode mais ser medido silenciosamente. Nenhuma taxa foi publicada nessa
execução.

### Prova de qual pipeline realmente rodou

O log nativo agora registra, na linha de configuração, `large=` (se o lever de
workgroup largo estava ativo) e, no primeiro dispatch de cada tipo, **rows e
lanes** do pipeline efetivamente selecionado. O avaliador exige que rows e lanes
batam com o que a configuração pede — não basta a variável de ambiente. Assim,
uma execução "ON" que na verdade usou o pipeline padrão é reprovada em vez de
ser tratada como ganho.

A aceitação agora cobre matriz estado × fator {4, 8} × largo {0, 1}: oito jobs,
todos exigindo as razões ≥3 (histórico) e ≥1 (entregue).

### Próximo passo preparado (não executado)

`vulkan-screening.yml` mede, no mesmo APK e no mesmo emulador, sete
configurações alternadas: fatores 2, 4, 8 e 16, workgroup largo
(`GGUF_VK_DMMV_LARGE`, 32 lanes por linha em vez de 8), fator 2 + largo e
fator 4 + largo. É triagem de descoberta, não
aceitação: `ci/evaluate_screening.py` só valida identidade, contagens e saídas,
e nunca aprova release. A hipótese que sobra é **aumentar o paralelismo** (mais
lanes por linha), coerente com a queda observada ao reduzir grupos de trabalho.
Nada disso foi medido ainda.


### Terceiro incidente: cache restaurou objetos "mais novos" que as fontes

A execução 35458536766 compilou do zero (a chave de cache mudou), então o
formato emitido ainda era o antigo e a checagem de marcadores falhou no
empacotamento — corretamente. Duas causas somadas:

1. Uma edição anterior no gerador de patch não encontrou o texto alvo e falhou
   sem avisar; o código emitido continuou no formato antigo.
2. O `actions/cache` restaura objetos com mtime do momento da extração, que
   fica **mais novo** que as fontes recém-clonadas. O Ninja então considera os
   objetos atualizados e reaproveita um `libaijni.so` antigo.

Correções: verificação de contagem em cada substituição do gerador; teste que
aplica o patch ao upstream fixado e exige os cinco marcadores e os campos lidos
pelo avaliador; passo de build que faz `touch` nas fontes nativas depois do
restore do cache; e a checagem de marcadores no APK empacotado, que agora
falha o build em vez de medir o binário errado. Nenhuma taxa saiu dessas
execuções.

## Resultado do screening 35465977658 e correção de leitura

O workflow `vulkan-screening.yml` mediu o **mesmo APK candidato** com e sem cada
lever, em pares alternados, tela acesa. O avaliador `ci/evaluate_screening.py`
calcula `razão = tps(ON)/tps(OFF)`; portanto **razão > 1 é ganho**.

| config | pares válidos | razão par 0 | razão par 1 | veredito |
|---|---|---|---|---|
| row4 | 2 | 0,975817 | 0,916849 | mais lento |
| row8 | 2 | 1,366197 | 0,989355 | misto (um par ganha, o outro perde) |
| large | 2 | 0,545987 | 0,540473 | **mais lento** |
| row4large | 2 | 0,834013 | 0,626397 | mais lento |
| row2 / row16 / row2large | 1 | — | — | **inválidos**: o observador rejeitou o fator |

Uma leitura anterior desta sessão trocou o sentido da razão e registrou
"1,85×" para o lever `large`. **Isso estava errado**: `large` foi 1,83-1,85×
**mais lento** (`0,545987` e `0,540473`), `row4` também perdeu
(`0,975817`/`0,916849`) e `row4large` perdeu ainda mais
(`0,834013`/`0,626397`). O único par acima de 1,0 é `row8`/par 0
(`1,366197`), com o par 1 em `0,989355`: misto, não é ganho estável. Nenhum
lever de agrupamento de linhas ou de workgroup largo produziu ganho estável ≥ 1
nesta plataforma. Nada disso é evidência de release: o screening não compara com
o APK histórico e não certifica GPU física.

Os três jobs reprovados não falharam por medição física: o script de observação
recusa fatores fora de `PREDECLARED_FACTORS=(4,8)`, então `row2`, `row16` e
`row2large` abortaram em `candidate_metadata`. Nenhuma taxa saiu dessas
execuções.

## O que o perfil de kernels diz (e o que ele descarta)

`ci-results/35156484592-1/physical-vulkan-kernel-timings.txt` (instrumentado, com
overhead do logger) mostra o perfil de uma execução completa de 128 tokens em
llvmpipe. Somando apenas as operações de decodificação:

| operação | tempo total | % do decode | GFLOPS/s |
|---|---|---|---|
| `MUL_MAT_VEC q5_0 m=1536` (gate+up fundidos) | 11,23 s | 32% | 1,19 |
| `MUL_MAT_VEC q8_0 m=49152` (cabeça) | 5,54 s | 16% | 1,30 |
| projeções qkv (`m=576/192`) | 4,34 s | 12% | 0,94-0,98 |
| `ffn_down` q6_K/q4_K com add | 4,37 s | 13% | 1,15-2,01 |
| `attn_output` + add | 2,51 s | 7% | 0,96 |
| flash attention (n=1) | 2,53 s | 7% | 0,88 |
| RMS_NORM_MUL (576,1,1,1) | 1,52 s | 4% | — |
| ROPE + SET_ROWS | 0,95 s | 3% | — |

Duas conclusões quantitativas:

1. Matvecs `n=1` (DMMV) são ~80% do tempo de decodificação e rodam a
   **~1,0-1,3 GFLOPS/s**, com ~**120 ns por invocação** (8 threads por linha em
   `BLOCK_SIZE=8`). Operações triviais (SUB, STEP, SCALE, SET_ROWS) custam
   ~130-200 µs cada, ou seja o custo fixo de um dispatch é da ordem de 10⁻⁴ s.
2. No **mesmo** processo, o caminho batido (MMQ, `n=30/32`, usado no prefill)
   atinge **4,8-5,4 GFLOPS/s**: 4-5× mais eficiente por operação. O gargalo não é
   a máquina, é a estrutura do kernel `n=1`.

Isso descarta "reduzir o número de workgroups" como alavanca: multiplicar as
linhas por grupo mantém o número de invocações e só aumentou o trabalho serial
por thread, exatamente como medido acima. O caminho com potencial real de 3×
está no item 2: aproximar o kernel `n=1` da eficiência do kernel batido.

## Laboratório host-side (llvmpipe) para iterar rápido

`.github/workflows/llvmpipe-lab.yml` + `ci/llvmpipe_lab.sh` constroem o
`llama-bench` a partir do **mesmo** upstream fixado e medem, no host do runner,
o **mesmo** dispositivo (lavapipe/llvmpipe) que o emulador usa via `-gpu host`.
Isso dá uma volta de iteração de minutos em vez de dezenas de minutos por
emulador, e serve para descartar hipóteses antes de gastar uma execução de
screening. Não é evidência de release, de GPU física nem de celular: é
laboratório, exatamente como o próprio dataset de perfis acima.

O laboratório mede: linha de base `-ngl 99` e referência `-ngl 0`, varredura de
`LP_NUM_THREADS` (para saber se o lavapipe usa 1 ou N núcleos neste shader),
knobs de submissão/fusão/MMVQ e o perfil por operação. Patch opcional
(`LAB_PATCHES`) permite comparar um kernel alterado contra o controle limpo no
mesmo run.
