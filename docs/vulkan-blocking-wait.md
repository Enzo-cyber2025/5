# Espera Vulkan: eliminar polling sem remover sincronização

## Hipótese e escopo

Na dependência fixa `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`,
`ggml_vk_wait_for_fence` aguarda o sinal “almost ready”, mas depois faz polling
ilimitado da fence final, com instruções de pausa entre consultas. Os últimos
20% dos nós podem incluir operações caras; porcentagem de nós não é porcentagem
de tempo. Esse loop ocupa CPU sem executar o modelo. Pode competir com a UI e,
especialmente no emulador, com o driver Vulkan por software.

O experimento mantém a espera/reset de `almost_ready_fence` e substitui somente
o polling da **mesma fence final** por `waitForFences`. Não retira dependências,
não muda comandos, shaders, pesos, precisão, lote 128/32, orçamento ou sampling.
Não usa sleeps nem atrasa artificialmente uma versão para igualar ON/OFF.
A liberação da fence continua obrigatória antes de ler resultados/reusar buffers.

Build normal: inalterado nesse ponto. Apenas o build com
`GGUF_EXPERIMENT_BLOCKING_WAIT=1` aplica o patch. Nesse APK experimental, a espera
bloqueante é o padrão; `GGUF_VULKAN_BLOCKING_WAIT=0` ativa o controle original.
Assim o candidato medido não precisa ser modificado depois para ativar a mudança.

## Verificação e aceitação definidas antes dos resultados

- Testes C++ extraem a função real do Vulkan: controlam polling, ordem de waits,
  resets, sinal almost-ready e erro da fence final. Não são benchmarks de GPU.
- Um APK para ambos os modos; o ambiente real do processo e o log da política
  são conferidos. Artefato isolado, nunca substitui o APK entregue.
- Texto: três pares AB/BA/AB com aquecimento excluído, ON/OFF, mesmos históricos
  completos/128 tokens/configurações. Cada par ON >=10% de ganho, mediana >=15%,
  OFF sem piora >3%, primeiro texto ON sem piora >aproximadamente 5,3%.
- Imagens: dois pares AB/BA com foto completa, aquecimento e **cache de embeddings
  desligado nos dois modos**. Tanto encoder quanto Send→primeiro texto devem ser
  >=10% mais rápidos em ambos. Não atribuir cache ou imagem menor ao novo caminho.
- Mesma contagem de grafos/nós matemáticos estritos. Sem outros experimentos,
  profiler, mudança de resolução ou cortes de conteúdo.
- Tempo de CPU da thread geradora também deve cair nos pares ON. É um relógio
  real `CLOCK_THREAD_CPUTIME_ID`, não tempo total de CPU do app, energia ou bateria.
- Texto e imagens rodam em jobs separados, com evidências separadas. Nunca
  comparar velocidades absolutas entre essas máquinas ou multiplicar ganhos.
- APK só é candidato, não entrega aprovada. Testes em Vulkan por software não
  certificam aceleração em GPU física. Uma hipótese que falhar permanece fora
  do build normal; não diminuir os limites depois de ver resultados.


## Resultado: rejeitado, inclusive pelo critério posterior de ganho pequeno

Run 35378808404, fonte e0709c2. Compilação, funcionalidade, respostas completas,
rotas estritas, contagens de grafos/nós e código/Copy passaram. Ambos os gates
numéricos falharam intencionalmente: texto ON mediano −1,24%, espera de imagens
ligeiramente pior nos dois pares. CPU da thread geradora tampouco caiu de forma
consistente. Portanto, a hipótese de benefício não se confirmou; **não faz
parte do APK entregue**. O build normal continua sem aplicar esse patch.

Os relatórios completos foram recuperados do HTML público, em commits
imutáveis, depois da expiração da conexão. O leitor foi validado contra bytes
previamente recuperados por Git autenticado; hashes/prefixos e proveniência
constam em `.delivery/vulkan-wait-rejected.json`. Os gates foram recomputados
localmente. Essa recuperação não é um fetch Git autenticado nem download do
binário experimental.

Após a autorização de entrega com ganhos menores, a conexão funcionou novamente:
os relatórios foram obtidos por Git autenticado em d3aa668 e conferidos byte a
byte contra a recuperação pública. Ambos os resultados de rejeição coincidem.
