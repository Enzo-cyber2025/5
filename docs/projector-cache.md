# Cache exato do projetor — investigação em andamento

## Alteração

O cache anterior era indexado pela ordem dos recortes e descartado integralmente
quando a lista ordenada de hashes de imagens mudava. Acrescentar B a uma conversa
com A obrigava a executar novamente o projetor para A.

Agora o Engine mantém uma LRU por entrada preparada. A chave SHA-256 cobre a
serialização de metadados, **todos os bytes dos pixels F32 preparados** e os quatro
campos `anyres` omitidos pela serialização upstream. Os pixels são percorridos em
seu buffer existente, sem concatenar/copiar o payload para calcular a chave.
Isso também distingue recortes de mesma geometria e mesmo ID de origem.

O cache pertence a um único Engine/modelo/projetor; não cruza processos, modelos,
dispositivos ou configurações. Seus valores são cópias completas dos embeddings
F32 produzidos pelo projetor. Continuam passando pelo helper original de posição,
M-RoPE, atenção não causal e avaliação no modelo. Não há reutilização de resposta
textual, corte de anexos, mudança de resolução, precisão ou batching 128/32.

Limites **do cache opcional**, não dos anexos: 16 MiB de embeddings retidos e 128
entradas. A alocação de uma entrada nova pode transitoriamente coexistir com as
antigas antes da expulsão; 16 MiB não é uma promessa sobre pico de RSS. Entradas
maiores continuam sendo inferidas sem cache. Falha de alocação descarta o cache;
não redireciona tensores para CPU. Erros de geração também limpam o cache.

## Instrumentação e limites

`GGUF_PROJECTOR_STAGES` separa leitura/decodificação nativa, tokenização e
pré-processamento, cálculo da chave e tempo de parede das chamadas ao encoder.
`encode_call_ns` inclui esperas/dependências de dispositivo: **não é tempo isolado
de kernel GPU**. Os logs originais `image decoded (batch...) in ... ms` registram
o helper de avaliação dos embeddings; o retorno pode envolver submissão assíncrona,
portanto não representa sozinho toda a execução GPU. `prefillNs` e `firstTokenNs`
continuam sendo os contadores reais de geração, separados da velocidade de decode.

`GGUF_VERIFY_IMAGE_EMBED_CACHE=1` é um diagnóstico: em cada hit recalcula o
projetor e compara **todos os bytes** do embedding. Essa execução é deliberadamente
mais lenta e será excluída da comparação de desempenho. O controle de diagnóstico
`GGUF_DISABLE_IMAGE_EMBED_CACHE` permite desabilitar somente o cache, não trocar
modelo, parâmetros ou backend. Nenhum desses controles é ativado por padrão.

A primeira imagem ainda executa o projetor inteiro e agora também calcula sua
chave. O benefício esperado é evitar **trabalho repetido**, especialmente ao
acrescentar/desativar/reativar fotos. Não há alegação de shader mais rápido,
aceleração garantida de imagem inédita, 21×/26× global ou paridade ON/OFF.

## Validação

- Local: **188 passaram, 69 pulados** após restaurar o APK original verificado.
  As primeiras duas falhas eram ausência desse fixture, não regressão de código.
- Testes C++ compilam as definições reais de tipos/serialização do mtmd fixado
  `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`, com dados sintéticos. Comprovam que
  alteração de pixel, `anyres`, padding, posição e ID mudam a chave, placeholders
  são rejeitados, LRU mantém A ao inserir B e limites/expulsão funcionam.
  Há também injeção de falha de alocação e verificação de patch idempotente.
  **Não são medições de inferência nem prova de todas as arquiteturas.**
- Android: pipeline experimental, resultados ainda pendentes. Mesmos arquivos
  públicos de cachorro/ônibus e mesmo GGUF físico independente. Preserva o
  pré-processamento já existente, inclusive seu limite de 1024 px; não reduz esse limite.
  Antes = payload entregue 323, reassinado exclusivamente para comparação
  descartável. Depois também inclui as melhorias anteriores de UI; não atribuir
  toda mudança de latência aos kernels do projetor.
- Protocolo ajustado para uma sequência de quatro etapas por versão/estado de tela:
  A; adicionar B; desativar A; reativar A. Execução separada verifica bytes de A e B.
  A limitação de amostras é explícita: o projetor em Vulkan por software levou
  cerca de quatro minutos para uma foto no ensaio anterior. Não é uma redução
  de conteúdo, configuração ou número máximo de tokens.

O APK entregue 323 e sua assinatura permanecem inalterados. A assinatura do
experimento não é uma chave de atualização para esse APK. Não há aprovação de
release ou certificação de GPU física enquanto os testes não terminarem.

### Execuções desta investigação

- `35243048649` / job `105276101366`: compilação nativa e testes host
  concluídos; execução cancelada e substituída para ajustar a duração do protocolo.
  Os fragmentos em `ci-results/35243048649-1` **não são um resultado de desempenho**.
- `35244519496` / job `105281662691`, fonte `f89d92e`: comparação ajustada
  em andamento. Código nativo é o de `f42c518`; o ajuste muda apenas o harness
  e a documentação, não fotos, modelo, shaders ou parâmetros de inferência.
- Os dois testes host adicionais foram executados localmente depois desse
  disparo; não atribuir sua execução ao job hospedado ainda em andamento.
