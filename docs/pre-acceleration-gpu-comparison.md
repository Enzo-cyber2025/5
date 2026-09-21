# APK anterior à primeira aceleração: comparação de T/s Vulkan

## Resultado concluído — 18/09/2026

Execução real [35400546163](https://github.com/Enzo-cyber2025/5/actions/runs/35400546163), ambos os estados concluídos. **Não demonstrou ganho estável de T/s contra esse baseline.**

| Estado | APK anterior, mediana T/s | APK atual, mediana T/s | Variação entre essas medianas |
|---|---:|---:|---:|
| Tela ligada | 3,983264 | 3,965417 | −0,45% |
| Tela apagada | 4,068059 | 4,040002 | −0,69% |

Pares individuais, na ordem AB/BA/AB:

| Estado / par | Anterior T/s | Atual T/s | Atual/anterior − 1 |
|---|---:|---:|---:|
| Ligada / 1 | 3,767568 | 3,912604 | +3,8496% |
| Ligada / 2 | 4,026488 | 3,965417 | −1,5167% |
| Ligada / 3 | 3,983264 | 3,989104 | +0,1466% |
| Apagada / 1 | 3,828825 | 3,978798 | +3,9169% |
| Apagada / 2 | 4,107104 | 4,040002 | −1,6338% |
| Apagada / 3 | 4,068059 | 4,068958 | +0,0221% |

A **mediana das razões pareadas**, outra estatística (não a razão das medianas), é +0,1466% ON e +0,0221% OFF. Há regressão no segundo par dos dois estados. Não selecionar apenas o primeiro par positivo nem apresentar essas oscilações pequenas como aceleração comprovada. Três pares não demonstram significância estatística.

Os dois braços mantiveram modelo, parâmetros, 128 tokens, prompts, IDs de entrada e respostas completas idênticos. A validação durante a execução exigiu offload Vulkan em ambos e política estrita de operações/amostragem no atual. São **intervalos de entrega nativa após o primeiro token em Vulkan por software**, não desempenho da GPU do telefone, tempo puro de kernel ou rodapé/UI do aplicativo.

Assinaturas de diagnóstico: somente cópias temporárias, com todos os arquivos não relacionados à assinatura idênticos aos originais. APK entregue e chave de produção não alterados.

Evidências completas de callbacks/saídas e resultados: `ci-results/35400546163-1-pre-accel-gpu-{awake,asleep}/`. Reavaliação local dos dois `summary.json` passou; todos os dados brutos de callbacks e os dois contadores nativos de 128 tokens por observação foram reconferidos. **Limitação de retenção:** o log de sistema limitado a 1,5 MB da primeira observação antiga de cada estado perdeu o carregamento e o marcador inicial do warmup. O harness validou esses dados no log completo durante a execução; a cópia publicada conserva os contadores de fim de ambos os estágios e o estágio medido. As outras dez observações permitem repetir também a coleta integral a partir do log publicado. O harness foi corrigido para preservar separadamente o log completo do processo nativo em execuções futuras; não se refez o teste para escolher outro resultado.

Verificação do código deste protocolo: 51 testes selecionados passaram; Java, DEX, assinaturas e igualdade dos arquivos dos APKs foram verificados no CI. A suíte host completa, após instalar as dependências declaradas, teve 281 aprovados, 117 ignorados e 2 falhas por ausência da fixture `.cache/gguf/GGUF-Chat.apk`; **não é aprovação da suíte completa**.

## Referência corrigida

A referência é `2af2b3894fe18d4a8eb5c3320cc0d9539b78d44d:.delivery/GGUF-Chat-mobile.apk`, SHA-256 `0c45fd2e6c318da3ebb961bbd461c56d7401161c31a1869157f509550e4b05d1`. O primeiro registro de candidato de aceleração (`9a5e656:ci/speed-candidate.json`) nomeia explicitamente esse APK como baseline, antes do candidato `b8145469`. Isso identifica a primeira rodada **registrada no Git**, não uma recuperação independente de toda a cronologia das mensagens.

Comparar com o entregue `entrega/GGUF-Chat-acelerado.apk`, SHA-256 `bd7c45d3c9b80ee583e0d4102595c5ed55242c37aa0394f0befe093c07fd88d2`.

Não é o primeiro APK funcional `409985de`. O teste daquele APK falhou antes de medir, no seletor antigo de importação. Também não é o baseline posterior `323fd5`: os resultados anteriores de +9,49% não respondem a esta comparação. Não multiplicar ganhos de experimentos diferentes.

## Métrica comum, sem prefill

O APK antigo não tem o contador moderno de tempo de decode. Não reinterpretar suas antigas medições CPU/tempo total de resposta como T/s GPU.

O observador Android separado chama **a classe Native e as bibliotecas reais do APK instalado**, por reflexão. Não inclui uma implementação Native alternativa. Registra `System.nanoTime()` à entrada de cada callback `onToken`, antes de armazenar a string. A taxa é **127 intervalos de entrega de token / tempo entre o primeiro e o último dos 128 callbacks**. Exclui carregamento, processamento inicial do prompt, primeiro token, última finalização e UI. Inclui orquestração nativa, amostragem e a entrega JNI; **não é tempo puro dos kernels GPU**, tempo Enviar→fim ou o rodapé moderno do app.

Callbacks não são tokens em geral! A aprovação exige simultaneamente:

- Contador nativo independente `GGUF_NATIVE_COMPLETE tokens=128 reason=length`.
- Exatamente 128 callbacks não vazios, relógios estritamente crescentes e resposta completa.
- Igualdade de todas as strings por callback, respostas, prompts renderizados e IDs de entrada entre as versões e repetições.
- Mesmo GGUF SmolLM2-135M Q4_K_M (hash `2e8040ceae7815abe0dcb3540b9995eaa1fa0d2ca9e797d0a635ae4433c68c2d`), contexto 2048, threads 2, GPU 99, batch 128/ubatch 32, greedy, repeat 1,1/64, orçamento **128 inalterado**.
- Se o buffer de 50 ms agrupar callbacks, houver EOS antecipado, falha, resposta diferente ou ausência de offload, **não publicar uma taxa comparativa válida**. Não substituir tokens por palavras, caracteres ou callbacks agrupados.

Cada observação usa processo/Engine novos, warmup descartado, seguido da mesma continuação com o histórico completo. Três pares AB/BA/AB por estado de tela. Mesma concessão de wakelock parcial de teste nas duas versões; tela ligada/desligada confirmada pelo PowerManager antes/depois da inferência. Isso testa o motor nativo, **não o serviço de geração em segundo plano ou a interface do APK**.

## GPU e assinaturas de diagnóstico

O ambiente é o mesmo emulador descartável com **Vulkan por software**. Requer inicialização Vulkan e offload positivo no processo que executa a geração. A versão atual também precisa passar os contadores estritos de operações/amostragem GPU de cada geração. O APK antigo permanece com sua própria política histórica: offload positivo **não prova que todas as suas operações eram GPU**. Não alterar sua biblioteca para torná-lo artificialmente estrito, nem ocultar essa diferença.

O Android exige compatibilidade de assinatura para instrumentação. Criam-se **cópias de diagnóstico de ambos os APKs**, assinadas com a mesma chave temporária do observador. Todos os arquivos ZIP não relacionados à assinatura (DEX, bibliotecas nativas, manifesto, recursos etc.) têm hashes idênticos aos originais; o manifesto dessa verificação e os hashes dos APKs originais/de teste são publicados. Não recompilar o modelo nem as bibliotecas. A chave temporária é removida, nunca publicada. Os APKs de diagnóstico ficam em `.cache`, nunca substituem o APK entregue, e não são uma atualização instalável para o usuário.

## Execução e interpretação

- Workflow: `.github/workflows/pre-acceleration-gpu.yml`.
- Observador: `tests/android-gpu-rate/`.
- Harness: `scripts/test_gpu_rate_android.py`.
- Avaliador independente: `ci/evaluate_gpu_rate.py`.
- Evidências: `ci-results/<run>-1-pre-accel-gpu-{awake,asleep}/`.

O avaliador separa **comparação válida** de **todos os pares mais rápidos**. Uma regressão também é resultado e não será rotulada como ganho. Três pares em uma fixture não certificam desempenho no telefone, todos os modelos, imagens, pureza de kernels GPU ou ausência universal de regressões. `release_approved` permanece falso: é comparação, não nova entrega.

**Decisão:** comparação executada; ganho estável de taxa de geração não demonstrado. A aprovação do job indica medição válida, não ganho ou nova aprovação de entrega.
