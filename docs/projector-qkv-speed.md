# QKV do projetor: fusão de chamadas com pesos idênticos (experimental)

A tentativa anterior de batch passou na igualdade, mas melhorou a espera apenas
cerca de 1–2%. Este experimento muda outra coisa: junta as três matrizes Q/K/V
em uma matriz, reutilizando o caminho QKV fundido que já existe no ViT do mtmd.
Não reduz o número teórico de multiplicações; testa amortização de chamadas,
leituras da mesma ativação e melhor aproveitamento do GEMM.

## Limites da implementação

- Opt-in `GGUF_VULKAN_QKV`, desativado por padrão.
- Somente Idefics3 de visão, Q/K/V de layout e tipo iguais, mesmo número de heads,
  sem Q/K norm específico, e biases compatíveis. Outros casos falham claramente
  se o experimento for pedido; não há alteração silenciosa de parâmetros.
- Os bytes quantizados são copiados **no próprio dispositivo** para as views Q/K/V
  do peso concatenado. Usa `ggml_backend_buffer_copy_tensor` e rejeita se a cópia
  direta não estiver disponível; não usa a API genérica que pode passar pelo host.
- Originais são mantidos para referência. Há uma cópia adicional de QKV na memória
  da GPU; o tamanho é registrado em `GGUF_QKV_READY`, inclusive na contabilidade
  de memória. Não é uma economia global de RAM nem de FLOPs.
- Sem requantização, conversão de peso, redução de imagem, alterações do modelo
  de texto ou do batching 128/32. Não misturar com batch2.

## Validação

`GGUF_VERIFY_QKV` verifica, no carregamento, todos os bytes das cópias dos pesos.
Em geração, compara o embedding completo de cada recorte com um novo encode do
caminho individual original, no mesmo dispositivo Vulkan. A seleção temporária
de referência é por contexto, sob o mutex do Engine, e tem restauração RAII.
Uma diferença registra o primeiro índice/bits e rejeita o experimento.

O teste Android começa pela verificação, antes de gastar tempo em benchmarks.
Se passar, realiza dois pares AB/BA com aquecimento completo excluído por Engine.
As amostras cronometradas não fazem readback de diagnóstico/verificação de pesos
ou embeddings. A reorganização RGB em Vulkan fica ligada nos dois modos, cache
de embeddings desligado, foto/GGUF/resolução/quantização/parâmetros iguais.

Testes host usam ggml real para conferir as views/bytes de F32, F16, Q8_0 e biases,
além de uma projeção F32 pequena exatamente representável. São testes CPU do
layout, não inferência acelerada nem certificação física de GPU.

Nenhum ganho será anunciado antes dos dados. O caminho ainda não é release.
Decode, resize/crops e normalização continuam no host; este experimento não
conclui a migração de todo o pré-processamento da imagem para GPU.

## Resultado concluído

Fonte **1eb0920**, CI **35275074925**, job **105383599707**: SUCCESS em
2026-09-17 às **21:46:17 UTC**. Sucesso funcional não significa aprovação de velocidade.

| Comparação aquecida | Q/K/V separados | QKV fundido | Razão de velocidade |
|---|---:|---:|---:|
| A → B | 100,026 s | 99,216 s | 1,00816× |
| B → A | 99,064 s | 98,902 s | 1,00164× |

Razão mediana **1,00490×**: diferenças inferiores a 1%, potencialmente incluindo
ruído. **Não superou 5% nos dois pares; não ativado por padrão.**
As chamadas ao encoder continuaram sendo cinco; cada uma computa os mesmos cinco
recortes no total. Os nós matemáticos caíram de 15.144 para 14.904 devido à fusão,
mas os FLOPs das multiplicações não caíram nessa proporção.

- **12 camadas** fundidas no experimento.
- **22.671.360 bytes** de pesos/biases copiados no dispositivo e verificados no
  diagnóstico, sem requantização. **21,621 MiB adicionais** de memória GPU.
- **5 embeddings completos** de recortes comparados byte a byte com o caminho
  individual original, em execução separada (dez encodes nesse diagnóstico).
- Mesmos pixels (**15 MiB por amostra**), histórico bruto, resposta e contagem de
  tokens nos modos cronometrados. Cache desligado para não mascarar o trabalho.
- Flash attention efetivamente **enabled** em todos os warmups e no diagnóstico;
  o pós-check também rejeitaria uma mudança de política AUTO entre os modos.
- Quatro screenshots reais revisados; o footer mede decode de dois tokens, não
  a espera inteira pelo processamento da foto. Não usar essa taxa curta como
  prova de ganho global de geração de texto.
- Host CI: **23 passaram**. Local: **203 passaram, 70 pulados**. O teste adicional
  do pós-avaliador foi adicionado após o disparo; não atribuído ao job anterior.

Os ~100 s desta execução não devem ser comparados aos ~212 s de outro runner:
a comparação válida está dentro desta tabela. Não há comprovação de aceleração
relevante no aparelho físico, ganho global 21×/26×, paridade ON/OFF, release ou
migração de todo o pré-processamento para GPU. Os originais e o APK entregue 323
permanecem inalterados. Não há job pendente nesta rodada.

Evidências completas: `ci-results/35275074925-1/`. Consolidação em
`.delivery/projector-qkv-experiment.json` e `.delivery/projector-qkv-speed-result.json`.
