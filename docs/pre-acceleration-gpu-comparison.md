# APK anterior à primeira aceleração: comparação de T/s Vulkan

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

**Estado ao criar este protocolo:** ainda sem medição Android válida `0c45fd2e → bd7c45d3`. Testes unitários verificam o protocolo, não substituem sua execução real.
