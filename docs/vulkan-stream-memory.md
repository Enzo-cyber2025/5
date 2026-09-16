# Otimização incremental de memória e atualização de texto

## Alterações desta rodada

1. **Remover `ChatActivity.streamingBuf`.** O DEX entregue mantinha uma cópia crescente da resposta que já não era consultada para renderizar nem salvar o texto. Havia uma criação, um append por callback e dois descartes. O patch exige exatamente essas referências; se surgir outro uso, falha em vez de apagar um buffer necessário. O buffer autoritativo do `GenerationService`, os callbacks, persistência, histórico e texto do modelo permanecem intactos.
2. **Agrupar inserções contíguas do parser destinadas ao mesmo TextView.** Antes, texto e quebras de linha podiam disparar vários appends para um único trecho recebido. Agora o sink junta essas emissões, descarrega antes de abrir/fechar um bloco e antes de retornar de `CodeBlocks.append`. O primeiro fragmento usa a String existente; o StringBuilder auxiliar só é criado quando há uma segunda emissão para o mesmo destino. Não há timer, espera por novos tokens, perda de espaços/Unicode ou alteração do parser de fences.

O ganho de memória é a eliminação de **uma cópia completa da resposta na Activity**, não redução de pesos/KV nem uma quantidade de MB medida. O buffer de junção reutilizado cresce conforme o trecho recebido, não com a resposta inteira durante streaming. Não confundir isso com ganho medido em tokens/s.

## Verificação

- Teste local reconstituiu DEX real sem o campo e conferiu: somente `onSend`, `onToken`, `onDone` e `onError` mudaram; nenhum outro método da Activity ou outro campo foi alterado por essa remoção isolada. Esse fixture omite bibliotecas/DEX secundário, não é APK de entrega ou prova de execução Android.
- Teste Android novo usa `TextWatcher` para exigir uma edição por trecho multilinha, em texto comum e código, com conteúdo exato. Confere ainda texto precedente a um fence que abre/fecha dentro do mesmo callback. Fixture de UI explicitamente sintético, não medição da velocidade do modelo.
- Permanecem testes reais de streaming/histórico/Copy, rolagem, geração determinística de 128 tokens em ambos os estados, footer, roteamento tensorial estrito, notificação com tela apagada e encerramento do serviço.

## Comparação corretamente isolada

Run **35162496639**, job **105016205960**, fonte **57c1913**.

O baseline é o **código do candidato UI anterior**, fixado em `63913d1f5e60b1d912eae085c49bc237a30711d5`, reconstruído e assinado com chave descartável. Não são os bytes assinados 215fa7 originais. O candidato novo é reconstruído no mesmo runner; ambos partem do payload 323fd5 e conservam todos os arquivos não-DEX, incluindo todas as bibliotecas nativas, recursos e manifesto. A diferença de assinatura não é tratada como atualização compatível.

Um aquecimento excluído + três observações por estado/versão, mesmo GGUF, contexto 2048, GPU99, threads auto e orçamento 128. A ordem das telas é alternada; a ordem das versões é fixa e ainda pode introduzir viés de cache/temperatura. Não multiplicar os ganhos desta execução pelos de outro runner nem apresentar taxas absolutas entre runners como aceleração.

**Status:** compilação aprovada; comparação Android em andamento. Nenhum ganho de velocidade desta rodada foi certificado. Metas anteriores de 21×/26× e paridade entre telas continuam sem aprovação. APK de entrega 323fd5 permanece intacto; os APKs de teste não são atualizações para o usuário.
