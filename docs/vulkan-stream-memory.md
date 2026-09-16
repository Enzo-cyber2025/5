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

## Resultado medido

Run concluído **PASS_UI_EXPERIMENT_ONLY**, em 2026-09-16 23:56:17 UTC. APK de baseline reconstruído: `e1af272c1d58611588030db5b0237fc35afeacc0238bc1052b1d2094beda8ef7`; candidato novo: `fc19462bf94448b266924ba7489d2d8f3b2781eade22e92ccef52f81be8717f5`.

| Mediana na mesma execução | UI anterior reconstruída | UI nova | Variação |
|---|---:|---:|---:|
| Decode acesa | 3,27780 tokens/s | 3,32316 tokens/s | +1,38% |
| Decode apagada | 4,06075 tokens/s | 4,05538 tokens/s | −0,13% |
| Enviar → primeiro texto acesa | 4,58998 s | 4,51553 s | −1,62% no tempo |

**São diferenças pequenas e podem incluir variação do emulador. Não configuram grande ganho de throughput.** Não usar os 7–9 tokens/s de outro runner como comparação. A taxa acesa ficou em 81,94% da apagada: paridade não alcançada. Não houve limitação deliberada da tela apagada para igualar resultados.

Validação Android aprovou as respostas determinísticas idênticas de 128 tokens, código/Copy em streaming e histórico, inserções agrupadas síncronas com conteúdo exato, rolagem e notificação/encerramento com tela apagada. As cinco capturas listadas no relatório foram revisadas; fixture de inserção não é resposta do modelo. As 12 taxas medidas foram recalculadas a partir de contagem e `decodeNs` nativos.

Regressões locais: **186 aprovadas, 66 puladas** por disponibilidade de ferramentas/fixtures/plataforma. Etapa hospedada focada: **34 aprovadas, 3 puladas**. O teste adicional local de reconstrução DEX, criado após o início do job, é contado apenas no conjunto local.

Relatório consolidado: `.delivery/ui-overhead-round2.json`; evidência bruta: `ci-results/35162496639-1/`. Metas anteriores 21×/26× não foram certificadas. O APK entregue 323fd5 continua intacto: candidatos com assinatura descartável **não são atualizações compatíveis para o usuário**. Nenhuma execução permanece pendente.
