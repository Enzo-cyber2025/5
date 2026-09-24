# GPU primeiro, aquecimento de prefixo e o NPU do A55

Este documento registra o que foi feito nesta rodada, o que foi **medido** e o que
o aparelho de teste **não** permite provar. Todos os números citados existem em
arquivos desta árvore (`ci-results/<rodada>-text-ui/`), nunca em estimativa.

## 1. GPU primeiro

O aplicativo já pedia o modelo inteiro na GPU por padrão (99 camadas); o pipeline
rebaixava esse padrão para CPU antes de reescrevê-lo. Agora o padrão de fábrica
(`-1`, automático) é preservado e a única decisão sobre backend acontece onde ela
pode ser verificada, no nativo:

- pedido de GPU (`camadas != 0`) → **tudo** na GPU, por nome do dispositivo
  (`Vulkan0`), `split_mode = NONE`, com verificação de carregamento completo das
  camadas (`complete_gpu_offload`). Offload parcial silencioso não existe:
  `EngineManager` só tenta a CPU quando o pedido foi explicitamente 0;
- dispositivo Vulkan que é um rasterizador por software (llvmpipe/lavapipe/
  SwiftShader…): recusa declarada e execução na CPU — de verdade: o pedido de
  camadas (`mp.n_gpu_layers`) volta a zero, senão o carregador ainda anuncia
  “offloaded N/N layers to GPU” por causa do pedido original e a execução fica
  ambígua. O aviso fica visível na tela e nunca é sobrescrito pelo aviso de GPU
  (opt-in `debug.gguf.allow_software_vulkan=1` existe só para reproduzir o
  comportamento antigo nas medições);
- GPU pedida mas o modelo não coube nela: a execução vai para a CPU **dizendo o
  motivo** (`CPU (a GPU não comportou o modelo inteiro; offload parcial recusado
  por política: …)`), em vez de cair para a CPU em silêncio;
- GPU usada: o aviso mostra `GPU (Vulkan, camadas N/N)` e o nativo declara
  `GGUF_BACKEND_EXECUTION backend=vulkan layers=N total=M`; nos caminhos de CPU a
  declaração diz `backend=cpu` com o motivo (`software_vulkan_refused`,
  `gpu_load_failed`, `requested_gpu_not_used`, `cpu_choice`). É essa declaração —
  e não a linha do carregador — que o relatório de desempenho usa para classificar
  cada etapa.

O emulador do CI só oferece o rasterizador por software, então **lá** o caminho
medido é a recusa declarada + CPU. Quem tem GPU real (Adreno/Mali) pega o mesmo
pedido de GPU já como padrão; essa parte é verificável pelo log
`GGUF_STRICT_VULKAN`/`GGUF_MODEL_ALL_LAYERS` e pela política de recusa — não por
um número de desempenho medido neste emulador, e nada aqui afirma o contrário.

## 2. −300% de espera: o prefill sai da frente do usuário

A decomposição medida na rodada verde anterior mostra onde a espera mora:

```
GGUF_PROMPT_CACHE input_tokens=65 reused_tokens=0
GGUF_GENERATION_STATS first_token_ns=1.655s  prefill_ns=1.652s   <- 99,8% da espera
GGUF_UI_FIRST_TEXT send_to_first_ui_ns=1.830s
```

O primeiro envio de uma conversa paga o prefill do bloco system inteiro antes de
escrever a primeira palavra. Esse prefixo já é conhecido antes do envio, então o
aplicativo o pré-preenche no KV **antes** de o usuário enviar:

- ao abrir a conversa: o bloco system exato que o envio vai reutilizar
  (`PromptBuilder.buildMessages` + `SystemPrompts.apply` + `renderPrompt`, com o
  texto do usuário vazio);
- a cada pausa de digitação (700 ms): o prompt inteiro com o texto que está no
  campo, em passadas de 16 tokens.

O que **não** muda, por construção e por teste:

- o resultado gerado: o aquecimento usa máscara de logits zerada (nenhuma projeção
  de vocabulário) e nunca consome token de saída;
- o último token: `reusable_prefix` limita o reaproveitamento a `tokens-1`, então
  quem decodifica o último token do prompt é sempre a geração real — a garantia é
  testada compilando o header de produção com g++ (`tests/test_warmup_prefix.py`);
- a prioridade do usuário: entre blocos o nativo checa um sinal de envio
  (`generate_requested`, marcado antes de disputar o mutex) e para; o pior caso de
  um envio que chega no meio é esperar um bloco (16 tokens ≈ 0,5 s);
- o caminho de erro: falha de aquecimento é registrada (`GGUF_WARMUP_FAILED`) e
  ignorada — o envio segue normal.

Medição: `GGUF_WARMUP input_tokens=… prefilled=… reused_tokens=… gpu=… aborted=…`
e, por etapa, `GGUF_WARMUP_UI ok=… chars=…`. No envio, o ganho aparece como
`GGUF_PROMPT_CACHE reused_tokens=` alto e `first_token_ns` perto de zero.

O gancho no APK é opt-in por canal (`GGUF_EXPERIMENT_WARMUP=1`): os outros canais
deste repositório montam o próprio APK com as mesmas camadas e não devem medir
outra coisa sem saber.

### Comparação honesta na mesma rodada

`scripts/test_android.py` (com `GGUF_EXPERIMENT_SUITE=1`) mede três etapas extras,
todas esperando o modelo carregar antes de enviar — elas medem a **espera do
envio**, não a carga:

| Etapa | Aquecimento | Digitação com pausa |
| --- | --- | --- |
| `gpu-preferred-cold` | ligado | não |
| `gpu-preferred-typed` | ligado | sim (1,2 s) |
| `gpu-off-cold` | **desligado** (`debug.gguf.disable_warmup=1`) | não |

`warmup_experiment` no `performance.json` compara `gpu-off-cold` ×
`gpu-preferred-cold` (mesma condição, mesma carga, mesmos tokens). É esse número —
e não a comparação com as etapas que enviam durante a carga — que sustenta
qualquer afirmação de espera. Sem as duas medições o relatório diz
`compared: false` e não estima nada.

### Medição da rodada 36038199713 (mesma condição, mesma máquina)

| Etapa | Aquecimento | Espera até o primeiro texto | 1º token (motor) | prefill | tokens reaproveitados | decodificação |
| --- | --- | --- | --- | --- | --- | --- |
| `gpu-preferred-cold` | ligado | **0,408 s** | 0,233 s | 0,229 s | 64 de 65 | 11,28 T/s |
| `gpu-off-cold` | desligado | **2,549 s** | 2,339 s | 2,335 s | 0 de 65 | 8,90 T/s |
| `gpu-preferred-typed` | ligado (2 passadas) | 0,421 s | 0,201 s | 0,197 s | 64 de 65 | 9,48 T/s |

- **6,25x menos espera** na comparação justa (alvo do pedido: 3x, ou "um terço do
  tempo"). O `reused_tokens` de 64 de 65 tokens é a própria garantia do último
  token aparecendo no log: só ele foi decodificado no envio.
- O custo do prefill (2,33 s) **não desapareceu**: ele saiu da frente do usuário e
  passou para o tempo ocioso da conversa/da digitação. Nada foi cortado.
- Etapas normais da mesma rodada (envio logo após a conversa abrir, com a digitação
  do harness): `cpu` 0,508 s, `vulkan-policy-default` 0,512 s,
  `cpu-threads-auto` 0,407 s — contra 1,8-2,1 s da rodada anterior medida do mesmo
  jeito (`36028665561`). A taxa de decodificação não regrediu em nenhuma etapa
  (`regressions: []`) e ficou em 2,1x-2,7x a linha de base da própria rodada.

## 3. NPU do A55 (Exynos 1480): não é possível neste binário — e o app diz isso

O aparelho "A55" tem NPU (Exynos 1480). O que falta não é a detecção, é o backend:

- este repositório compila o llama.cpp fixado em `b29c606e` (v0.4.1). O inventário
  de backends desse checkout é CPU, BLAS, CANN, CUDA, ET, Hexagon, HIP, Metal,
  MUSA, OpenCL, OpenVINO, RPC, SYCL, Vulkan, WebGPU, ZenDNN, ZDNN — nenhum deles
  é um backend de NPU para Exynos. NNAPI não existe mais neste código;
- o único backend de NPU presente é `ggml-hexagon`, do Hexagon HTP da Qualcomm:
  exige `HEXAGON_SDK_ROOT` e o SDK proprietário da Qualcomm
  (`ggml/src/ggml-hexagon/CMakeLists.txt` falha sem ele). Não se aplica a Exynos;
- no Exynos, a NPU é acessada por SDK de fornecedor (Samsung Neural SDK /
  NeuroPilot), fechado e com registro de parceiro — não é um caminho do llama.cpp;
- a NNAPI, que seria a abstração "genérica" do Android, está descontinuada
  ([1](https://www.reddit.com/r/LocalLLaMA/comments/1imy7gs/android_npu_prompt_processing_16k_tokens_using/),
  [2](https://www.xybrid.ai/blog/on-device-ai-mobile-ios-android)), e o esforço de
  NPU no llama.cpp é por fornecedor (Qualcomm/QNN), com ressalvas de que a NPU
  roda "modelos muito limitados" e às vezes mais devagar que a CPU
  ([3](https://github.com/ggml-org/llama.cpp/discussions/8273));
- o emulador do CI não tem NPU nenhuma, então nem a aceleração nem a recusa
  poderiam ser *medidas* aqui.

O que o aplicativo faz, então, é o honesto: detecta o SoC
(`apk-fix/native/npu_policy.h`, com Exynos 1480/2400, Snapdragon 8 Gen 2/7 Gen 3 e
Tensor G3), registra `GGUF_NPU_PROBE soc=… npu=present|unknown_or_absent
backend=none reason=nenhum backend de NPU embarcado` e, quando há NPU sem backend,
mostra no aviso de backend "NPU … presente, sem backend compatível neste binário".
A aceleração seria um backend novo (código e SDK proprietário), não uma opção de
configuração — e prometer isso sem medição estaria fora das regras desta entrega.

## 4. Busca na web

O caminho de busca continua verificado ponta a ponta no emulador pela fase
`text-renderer`: consulta exibida ("Consulta: capital do Brasil"), provedor
(Wikipédia), contagem ("2 fonte(s)"), fontes numeradas com título/URL e o caminho
de falha ("Falha na busca"), com marcas reais de execução (`GGUF_SEARCH_PANEL
shown=1`). O aquecimento só pré-enche o KV com tokens idênticos aos que o envio
produziria; quando a busca injeta resultados no turno do usuário, o prefixo
comum continua sendo reaproveitado e o resto é decodificado normalmente.

## 5. O que roda em cada gate

| Gate | O que verifica |
| --- | --- |
| `pytest tests/` | 437 testes locais (o CI roda a mesma suíte), incluindo política de NPU e prefixo compilada com g++ |
| `scripts/check_native_syntax.py` | `g++ -fsyntax-only` no nativo, com as declarações que os patches adicionam |
| `scripts/check_java_compile.py` | `javac --release 8` nos ajudantes, onde existe javac (o CI tem) |
| `scripts/check_java_api.py` | nomes de API chamados contra `android.jar` e o smali do APK base |
| `scripts/check_performance.py` | lê o `performance.json` medido: reprova regressão > 5% e exige as metas quando o aparelho permite |
| `.github/workflows/text-ui.yml` | emulador real: texto, anexos destacados, geração nativa e as etapas de medição; depois suíte, sintaxe nativa e javac antes de publicar a evidência |
