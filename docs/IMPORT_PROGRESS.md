# GGUF Chat — progresso por arquivo e etapa

**APK aprovado em Android com a mesma assinatura da última entrega.**

[Baixar somente o APK](https://github.com/Enzo-cyber2025/5/releases/download/gguf-progress-dba56b2/GGUF-Chat-mobile.apk)

28.349.896 bytes · Android 9+ · ARM64/x86_64 · sem pesos de modelos.

SHA-256 do APK: `afaf22c63022b44320604407246abe47a921c4e4d1fe55694ce7428abb047e86`.

Fonte compilada: `dba56b23dc490b360dc927f1fc82994e8c336e8d`.

## O que a interface mede

- **Importação 1 e 2, com o nome do arquivo:** bytes realmente escritos na cópia privada. A cópia só recebe 100% após o fim da leitura e sincronização do arquivo. A importação individual usa o mesmo painel.
- **Identificação de cada arquivo:** campos de metadados lidos, descritores de tensores lidos e verificações de limites dos tensores concluídas. O denominador é `n_metadados + 2 × n_tensores`, não uma previsão de duração.
- **Unificação (pesos):** bytes de tensores realmente escritos no GGUF de saída. Cabeçalhos/alinhamento não são usados para inventar um percentual de tempo.
- **Conferência dos tensores:** bytes comparados com as duas fontes, além das verificações de nomes, formas e tipos.
- **Validação no motor:** explicitamente indeterminada enquanto o carregador nativo trabalha, pois ele não fornece callback de progresso para esta interface. Só é concluída depois do retorno válido do carregador. Não é necessária para identificar um arquivo exclusivamente textual.
- **Salvar na biblioteca:** conclusão apenas depois do caminho de persistência bem-sucedido.

Uma etapa ainda ativa fica, no máximo, em **99%**. Os **100%** daquela etapa significam término explícito, não término de toda a transação. Um erro não emite conclusão bem-sucedida da importação nem sucesso de salvamento.

Quando o provedor Android não informa um tamanho utilizável, a interface mostra **“tamanho não informado” e os MiB copiados**, em vez de estimar uma porcentagem. A barra acompanha a etapa atual, cujo nome fica no início do painel. Os números ficam nas linhas nomeadas; o rodapé numérico padrão é desativado para não sugerir “0/100” em uma etapa indeterminada. Atualizações visuais são agrupadas em intervalos de até aproximadamente 180 ms para não sobrecarregar a interface; os contadores vêm das operações, não desse intervalo.

## Mesma assinatura

Esta atualização mantém a chave da última versão pública `gguf-atomic-5cf14ef`:

`9b658c30f602e0f2ff65c176423cb95bea8fbdeb660c306ab908862f90d9bc3c`

A chave privada existente é usada somente no ambiente local; não é criada outra chave nem enviada ao GitHub. O certificado foi verificado e `adb install -r` foi executado sobre o APK público anterior, preservando um arquivo privado de teste. Isso é uma atualização sobre a última versão **9b658c…**, não uma promessa de compatibilidade com versões históricas de certificado **9a368c…**.

## Garantias anteriores preservadas

Exatamente dois arquivos selecionados continuam sendo uma única transação: cópias privadas, identificação intrínseca, compatibilidade linguagem/projetor, um GGUF físico, comparação de todos os tensores, carregamento nativo de linguagem e visão a partir desse mesmo arquivo, remoção dos componentes temporários e publicação de um arquivo/registro. Pares inválidos são recusados sem dois sucessos parciais, alteração das fontes ou remoção da biblioteca/conversas existentes.

A importação individual de um GGUF visual já completo continua sendo identificada e validada; um arquivo textual não recebe olho/câmera por causa do nome. Mais de dois arquivos continuam no fluxo sequencial, sem fusão indiscriminada. Pares legados não são silenciosamente destruídos.

## Qualidade geral e limites

Porcentagem de trabalho concluído não é avaliação da qualidade do modelo. Os limites e respostas reais do [relatório anterior](ATOMIC_IMPORT.md) continuam relevantes: alterações de prompt podem não ser obedecidas, há casos de eco/resposta inadequada e um teste antigo que encontrou “hello” na instrução ecoada foi marcado manualmente como falha semântica.

Testes em emulador com Vulkan por software não comprovam desempenho em GPU física, consumo em um telefone específico nem compatibilidade universal entre arquiteturas. O par Gemma público de referência pode não ser igual aos arquivos do usuário. Preservar pesos de áudio também não comprova uma interface de entrada/transcrição de áudio.

## Aprovação desta versão

[Execução assinada 34973247833](https://github.com/Enzo-cyber2025/5/actions/runs/34973247833): **SUCCESS nos dois jobs**, sobre os bytes exatos deste APK.

- **Gemma: job 104394458336.** Atualização com a mesma assinatura, percentuais medidos, um GGUF físico, auditoria independente de todos os **2.012 tensores**, carregamento nativo, persistência/reinício e respostas **Dog / Dog / 4**. Saída: 3.431.306.464 bytes, SHA-256 `cb17b173deb6b62c1b8a2e914ea9bbdde75ae8a9a41baef23aaff2d074056066`.
- **Regressões: job 104394458575.** Progresso no par menor, em GGUF visual externo e em modelo textual; atalho de biblioteca vazia; quatro recusas atômicas sem falso sucesso; arquivo individual truncado fecha o progresso, não salva e preserva a biblioteca/conversas. Visão, texto, prompts, anexos, arquivos, duas capturas reais pela câmera emulada e erros explícitos passaram funcionalmente.
- **Código/JVM:** 131 testes de código na compilação; 6.804 classes do APK convertido para JVM, zero erros de tradução, 39 testes JVM e 16 testes do leitor extraído. Auditoria adicional das classes reais do APK confirmou percentuais indeterminados, limite de 99%, totais, preservação e rejeição de bytes corrompidos. Os testes JVM não são apresentados como inferência Android.
- **Revisão visual:** imagens reais de `adb screencap`, abertas e conferidas; nenhuma tela foi recriada ou gerada. O primeiro candidato não foi entregue porque o painel ocultava as mensagens; esta versão corrigida passou na revisão.

### Capturas reais conferidas

| Etapa | Exemplo visível |
|---|---|
| [Arquivo 1](../ci-results/34973247833-1-gemma4/physical-progress-gemma4-pair-copy0-2.png) | 40%, com nome e MiB |
| [Arquivo 2](../ci-results/34973247833-1-gemma4/physical-progress-gemma4-pair-copy1-1.png) | 39%; arquivo 1 já concluído |
| [Identificação](../ci-results/34973247833-1-gemma4/physical-progress-gemma4-pair-identify0-0.png) | 3% |
| [Unificação](../ci-results/34973247833-1-gemma4/physical-progress-gemma4-pair-merge-2.png) | 45% |
| [Conferência](../ci-results/34973247833-1-gemma4/physical-progress-gemma4-pair-verify-2.png) | 46% |
| [Motor nativo](../ci-results/34973247833-1-gemma4/physical-progress-gemma4-pair-native-0.png) | Sem percentual disponível, sem rodapé enganoso |
| [Importação individual textual](../ci-results/34973247833-1-regression/physical-progress-single-text-identify0-0.png) | Cópia 100%, identificação 4% |
| [Importação individual visual](../ci-results/34973247833-1-regression/physical-progress-single-vision-native-0.png) | Validação nativa após cópia/identificação |

Os nomes dos frames refletem o último evento observado, não um percentual artificialmente sobreposto. As porcentagens acima foram lidas nos próprios pixels.

### Qualidade geral nesta execução

Os relatórios brutos mantêm seus resultados automáticos. A revisão manual **reprova** o teste de saudação após o anexo excessivo: o `hello` encontrado estava na instrução ecoada. A troca de código por conversa ainda retornou ORCHID em vez de CEDAR, e a saudação após rejeitar imagem num modelo textual falhou. Isso não invalida os testes de cópia, leitura, erros, progresso e persistência, mas impede anunciar qualidade semântica geral.

[Resumo Gemma](../ci-results/34973247833-1-gemma4/summary.json) · [Resumo de regressões](../ci-results/34973247833-1-regression/summary.json) · [Contadores reais](../ci-results/34973247833-1-gemma4/physical-progress-gemma4-pair-proof.json) · [Aprovação e revisão](../.delivery/progress-acceptance.json).

A publicação é bloqueada se os jobs aprovados, hashes, assinatura, payload, capturas ou verificações obrigatórias não coincidirem. O processo ainda baixa o APK público e compara seus bytes com o arquivo aprovado.
