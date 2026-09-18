# Nova meta: pelo menos 2× T/s contra o APK pré-aceleração

Pedido de 18/09/2026: pelo menos +100%, não aceitar ~10% como meta atingida.
A referência continua **0c45fd2e**, anterior à primeira rodada de aceleração
registrada, não um baseline lento selecionado posteriormente. O APK entregue
**bd7c45d3** é um segundo controle, sem misturar taxas de runners diferentes.

## Hipótese testável

O perfil anterior `ci-results/35156484592-1/physical-vulkan-kernel-timings.txt`
mostra custos elevados nas multiplicações quantizadas (FFN, QKV e vocabulário).
É perfil instrumentado de outro APK: serve para escolher onde investigar, não
para calcular o ganho atual nem para prometer que a soma dos tempos é wall time.

Experimento: expandir uma vez os pesos Q5_0/Q8_0/Q4_K/Q6_K elegíveis para F32
**no próprio Vulkan**, por GET_ROWS com todos os índices, e reutilizá-los.
O GGUF no disco, o modelo, as formas, contexto, KV, amostragem e orçamento não
mudam. Não se requantiza a ativação ou reduz precisão. O custo é **mais memória**
e maior inicialização. Em uma GPU física limitada pela largura de banda isso
pode inclusive ser pior; não habilitar universalmente nem confundir llvmpipe
com desempenho do telefone.

## Guardas

- Flag de compilação `GGUF_EXPERIMENT_EXPANDED_WEIGHTS` OFF por padrão.
- Flag de execução `GGUF_EXPAND_WEIGHTS` somente com valor exato `1`.
- Conversão exclusivamente no dispositivo Vulkan0 selecionado; layouts/tipos
  não qualificados falham explicitamente. Nenhum fallback para CPU.
- Limite experimental de 1 GiB de valores expandidos (mais índices/alinhamento).
  Modelo maior não é cortado: o experimento falha, preservando o padrão original.
- Nenhum tensor do modelo é alterado até todas as conversões terem terminado.
  Alocações extras pertencem ao Engine e são liberadas após contexto/modelo.
- Verificação separada `GGUF_VERIFY_EXPANDED_WEIGHTS=1`: lê os bytes quantizados
  originais e compara **cada bit de cada valor F32 expandido na GPU** com a
  referência independente de desquantização. A referência CPU é somente uma
  checagem diagnóstica; jamais abastece os pesos da inferência.
- Destruir o processo verificado. Medições seguintes usam verificação OFF,
  sem readbacks de validação, e preservam o modelo real inteiramente no Vulkan.
- No primeiro experimento, exigir dispositivo llvmpipe com `fp16: 0`. Políticas
  distintas de matmul FP16 em hardware móvel precisam de qualificação própria.

## Medição e critério

Usar o mesmo observador de intervalos nativos após o primeiro token do teste
35400546163: 128 tokens nativos e 128 callbacks reais, sem estimar contagem.
Warmup excluído, histórico/saídas completos idênticos e roteamento estrito na
versão atual e no candidato. SmolLM2-135M Q4_K_M, contexto 2048, threads 2,
GPU99, batch128/32 e sampling inalterados. Três trios de Engines novos:

1. pré-aceleração → entregue → candidato;
2. candidato → entregue → pré-aceleração;
3. pré-aceleração → entregue → candidato.

Dois jobs independentes: tela ligada e realmente apagada, ambos com a mesma
trava parcial de teste. A meta exige **candidato/histórico ≥2 em cada par** e
nenhuma queda contra o entregue. Um job aprovado isolado não satisfaz os dois
estados. Não escolher apenas um par favorável. Os hashes reais dos três APKs
são vinculados ao relatório; as cópias com assinatura temporária preservam todos
os arquivos não relacionados à assinatura. Não substituir o APK entregue.

Mesmo 2× nesta fixture de texto seria `NOT_RELEASE`: imagens, outros modelos,
memória/inicialização, integração UI e continuidade da assinatura continuam
necessárias. A chave de produção não está disponível; não criar uma atualização
incompatível silenciosamente. Não declarar ganhos antes da execução Android.

Arquivos: `apk-fix/native/expanded_weights.h`, `ci/evaluate_expanded_weights.py`,
`scripts/test_expanded_weights_android.py`, `.github/workflows/expanded-weights.yml`.
