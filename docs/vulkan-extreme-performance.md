# Nova rodada: tela acesa e apagada, sem alterar qualidade

## Metas e referência

Pedido: +2000% em tokens/s e +2500% na rapidez do primeiro token, com tela acesa tão rápida quanto apagada **sem desacelerar a apagada**. Interpretação comunicada: throughput **21×** e espera **dividida por 26** (redução de 96,15%, não uma redução impossível de 2500%).

Referência desta nova rodada: último APK entregue, SHA-256 `323fd5a33667c6cab278699e97c89fe253e1bb7acead45b869729bf022eb9f5c`. Não usar CPU, outro GGUF, menos tokens, outra precisão ou um primeiro caso frio como denominador favorável.

A igualdade de tempos em todas as execuções não é garantível: há variação de escalonamento, carga, temperatura, driver e hardware. O gate conservador exige mediana acesa **pelo menos** igual à apagada, além das metas de ganho em ambos os estados; não foi acrescentada uma tolerância silenciosa para anunciar sucesso.

## Revisão realizada e alterações

Revisão dirigida dos caminhos de streaming/rolagem, notificações, pré-processamento, sincronização, seleção de tokens e caches. **Não é uma alegação de revisão exaustiva de cada linha de todas as dependências nem de ausência absoluta de bugs.**

- DEX entregue: `onToken` chama `scrollToBottom` a cada trecho; este aloca um Runnable, que chama `ScrollView.fullScroll`. A rolagem suave padrão pode animar a movimentação. `ScrollTail` agrupa pedidos até o próximo pré-desenho e desloca diretamente depois do layout, sem animação ou busca de foco. Não retarda o primeiro texto, a renderização do código ou os callbacks de geração. Referências fracas tanto para a view quanto para seu observador evitam reter Activities pelo mapa estático.
- DEX entregue: `GenerationService$2` chama a notificação até uma vez por segundo. `GenerationStats.preview` só mostra os **primeiros 80 caracteres**, que não mudam após o prefixo ficar completo. `PreviewCadence` elimina reconstruções idênticas, reinicia em cada pedido e não participa da notificação de conclusão. O serviço continua visível e protegido durante a inferência.
- Preservados: ordem e conteúdo dos callbacks, armazenamento completo, parser de código, Copy, medidas nativas, buffers/KV, tokenizer, parâmetros, quantidade de tokens, sincronizações de segurança e rejeição de fallback tensorial CPU.
- Não foram forçados MMVQ/quantização extra de ativações, troca de modelo, alteração de batch, redução de contexto ou caches de respostas prontas. Não foi removida funcionalidade de importação apenas para reduzir tamanho do APK.

A diferença antiga de tela ocorreu em **Vulkan por software**, onde renderização e inferência usam recursos do host. As duas despesas acima são hipóteses verificáveis, não prova de que expliquem sozinhas a diferença.

## Experimento isolado

Run [35159076182](https://github.com/Enzo-cyber2025/5/actions/runs/35159076182), job `105005355177`, fonte `63913d1f5e60b1d912eae085c49bc237a30711d5`.

`build_ui_experiment.py` monta o candidato a partir do APK de referência, altera somente `classes.dex` e compara todos os outros arquivos do payload, inclusive bibliotecas nativas, manifesto e recursos. A chave descartável de teste é apagada após a assinatura; o candidato **não é atualização assinada com a chave 7295** nem substitui `.delivery/GGUF-Chat-mobile.apk`. Desinstalação no teste ocorre somente após verificar o emulador descartável; não é recomendação para apagar dados do usuário.

Metodologia: mesmo SmolLM2-135M Q4_K_M, contexto 2048, GPU99, threads auto, 128 tokens; um aquecimento excluído e três medições por estado/versão, alternando a ordem dos estados. A ordem fixa das versões ainda permite viés térmico/cache. Verificam-se igualdade de resposta, contadores nativos, roteamento estrito, conclusão real com tela apagada, notificações, limpeza do serviço, footer, código/Copy e geometria de rolagem no Android. Contagens de quadros incluem navegação do harness e não são apresentadas como custo puro do renderer.

Status inicial: compilação e etapa de regressões hospedadas aprovadas; teste Android em andamento. Resultado pendente não significa ganho aprovado.

## Gate separado

`ci/evaluate_extreme_vulkan.py <summary.json>` recompõe taxas de tokens/tempo nativo de cada observação; testa separadamente 21×, espera /26 e paridade entre telas. Falta de medição reprova o respectivo requisito. `firstTokenNs` começa na geração nativa, **não** no toque Enviar: não pode substituir Enviar → primeiro token com tela apagada. Uma aprovação funcional ou do teste de rolagem jamais autoriza declarar as metas de desempenho atingidas.

Os testes aritméticos de `tests/test_extreme_vulkan_target.py` são explicitamente sintéticos e não constituem medições do aplicativo.
