# Projetor: teste de pares em Vulkan e aceleração medida

## Motivo

Mover a reorganização RGB para Vulkan foi validado byte a byte, mas não provou
aceleração. O encoder domina os segundos/minutos observados no emulador. Esta
investigação tenta amortizar chamadas e permitir mais trabalho por execução,
processando no máximo dois recortes compatíveis por vez — sem remover recortes,
alterar quantização/resolução/normalização ou o batching 128/32 do modelo de texto.

O Idefics3 fixado ainda não anunciava suporte a batch: o seu pixel-unshuffle
perdia a dimensão de imagens. O caminho experimental mantém essa dimensão nos
reshapes/permutes, conserva o caminho original para uma imagem e só anuncia
suporte com `GGUF_PROJECTOR_BATCH2`. A atenção do ViT já separa a dimensão B.
Outros projetores mantêm as capacidades declaradas pelo upstream.

O helper JNI usa a API mtmd_batch, retém os embeddings até consumir o próximo
recorte e avalia texto/imagens no LLM na ordem original. Não agrupa entradas já
em cache nem duplica a próxima entrada se sua chave for igual à atual. Declínio
por incompatibilidade/tamanho antes de calcular mantém execução individual
**na GPU**, não fallback CPU. Falha de cálculo do lote aborta, sem tentar refazer
silenciosamente. Há limite de dois recortes simultâneos, não cota de anexos. A API de batch faz
cópias temporárias dos pixels e aumenta o pico de memória/ativações. Esse custo
entra nas medições; não se presume que agrupar seja sempre mais rápido.

## Protocolo

- Mesmo APK, pesos, foto, parâmetros e GPU por software nos dois modos.
- Reorganização RGB em Vulkan **ligada nos dois**, para isolar o efeito do batch.
- Cache de embeddings desativado para exigir a codificação integral da foto.
- Duas comparações em ordem AB/BA. Cada observação tem sua própria geração
  completa de aquecimento, excluída das medições, no mesmo Engine da amostra.
- Medição sem readback extra, hashes de embeddings ou verificações de bytes.
- Verificação separada compara os embeddings de cada recorte do lote com uma
  execução individual real em Vulkan. Divergência impede aprovação, mesmo que
  a resposta textual aparente seja igual. O primeiro índice/bits divergentes
  é registrado somente nesse diagnóstico.
- Métrica principal: Enviar → primeiro texto visível. Também separam-se tempo
  de chamada ao encoder e contagem de chamadas. O tempo de chamada não é um
  timestamp isolado do kernel GPU; pode incluir esperas de outras submissões.

Testes host do grafo real ggml comparam pixel-unshuffle antigo e novo para B=1,
B=2 e B=3, com dimensões pares/ímpares, padding e fatores 2/4. São testes de
layout em CPU, não benchmarks de inferência ou prova de GPU física. Testes de
lifetime/erros do helper usam doubles da API e são identificados como tais.

O caminho permanece opt-in. Não há alegação prévia de ganho. Dois pares não
certificam significância estatística, todos os aparelhos, tela apagada ou uma
primeira inicialização fria. Decode, redimensionamento, recortes e normalização
continuam no host: isso não conclui o objetivo de todo o pré-processamento GPU.
Nenhum APK de entrega foi substituído e os resultados das rodadas anteriores
não serão somados/multiplicados para fabricar os ganhos pedidos.

## Execução

Fonte **7fcfb6bc264a9fc87bebee90a66ebc366b4b55a2**, execução **35266241599**,
job **105354027833**, em andamento. Suíte local: **200 passados, 70 pulados**;
um teste adicional do avaliador foi adicionado depois do disparo do CI.
O avaliador `ci/evaluate_projector_pairs.py` rejeita resultado incompleto,
instrumentação nas amostras, mudança de histórico bruto e ganho inconsistente.
Nenhum ganho ou aprovação de release será declarado antes do resultado completo.
