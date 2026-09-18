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

## Resultado — rejeitado

Execução `35402357865`, APK c3bad5b7c3505ac85cf02cde579db4d0f23db2405b81518dcaee685a0aa6348f,
fonte e8ab84f1f3c43806126e27f4bcf909e6138932f9. Ambos os estados terminaram com
`TWO_TIMES_TARGET_NOT_MET`; falha do gate de desempenho, não erro da medição.
Valores verificados: 537.919.488 bytes; memória extra alocada: 538.738.176 bytes.

- ON, no mesmo runner: histórico 3,9617; entregue 3,9349; expansão 4,1077 T/s
  (medianas). Ganho pareado mediano histórico +3,9734%, entregue +4,9439%.
- OFF, no mesmo runner: histórico 9,6018; entregue 9,8080; expansão 7,3766 T/s.
  Razões pareadas medianas histórico −23,1755%, entregue −23,6964%.

Não comparar taxas absolutas entre esses runners/estados nem com execuções
anteriores. Saídas e valores preservados não tornam uma regressão aceitável.
**Padrão continua OFF. Não foi incluído no APK entregue.**
A próxima hipótese está em `docs/repacked-weights-experiment.md`.
