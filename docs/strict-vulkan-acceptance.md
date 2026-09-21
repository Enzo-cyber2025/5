# Vulkan estrito — aprovado funcionalmente, meta de +150% não atingida

**Estado: testes funcionais do APK assinado passaram; desempenho solicitado não aprovado.** O ganho de +150% (2,5 vezes o throughput) não foi atingido. Não há certificação de GPU física ou de uso zero de CPU pelo aplicativo inteiro.

APK candidato SHA-256: `323fd5a33667c6cab278699e97c89fe253e1bb7acead45b869729bf022eb9f5c`.
Fonte/native: `d3a16d7677be07ca61898fa31907b9ed95b4e198`.
Unsigned: `01c86072a860c293ec5d68317eb4dd5e40d6fc37dcff6ed10b5617c4e12c7036`.
Baseline realmente entregue: `8a994b58efc0a65a0851534402eacb5f0c305ff534a100075a88e5c5dbf95399`, preservado no commit `53dd3487bab82b313289faeb37d42135e6bc838a`.

## O que mudou

- No modo Vulkan, qualquer pedido de camadas diferente de zero passa a solicitar **todas** as camadas. Pesos de entrada, inclusive embeddings, também recebem buffer do dispositivo Vulkan. Overrides pertencem ao Engine, não a uma variável temporária do carregador.
- Operações tensoriais pequenas suportadas pelo Vulkan são priorizadas nesse dispositivo, em vez de seguir a preferência heurística por CPU.
- Antes de executar qualquer parte de um grafo, verificar todos os seus blocos: se uma operação de cálculo foi destinada a outro backend, falhar **antes** da execução. Há também proteção nas chamadas diretas de execução de grafo, fora do scheduler.
- A proteção é por thread e delimitada pelo ciclo de carregamento/geração JNI; abrange o modelo de linguagem, encoder mtmd e manutenção KV que usam esses schedulers. Não altera silenciosamente outra conversa explicitamente configurada como CPU.
- A cadeia inteira de amostragem precisa ter suporte no backend, e o token final precisa vir dele. Suporte apenas parcial não basta. Não alterar temperatura, filtros, penalidades ou seed para esconder uma incompatibilidade.
- Para decoders elegíveis, reservar apenas **uma linha de logits de saída**, que é o que a API deste app solicita. Isso não reduz contexto, prompt, limite de geração ou batching 128/32. Encoders/difusão mantêm os requisitos originais.
- As otimizações anteriores de exportar só o token, evitar getters redundantes e sobrepor decode posterior à entrega JNI continuam.

## O que “estrito” não significa

**Não significa que 100% do aplicativo roda na GPU ou que o uso de CPU será zero.** Android, UI, arquivos, tokenização, preparação de imagens, controle do gerador aleatório e estado do sampler continuam usando CPU nesta implementação. Buffers de entrada/saída, cópias e operações de metadados sem cálculo também não são kernels do modelo.

O que a política restringe é a **execução das operações tensoriais pelo backend** e a seleção final do token em modo Vulkan. Um modelo/operação/parâmetro sem suporte não deve cair silenciosamente para cálculo CPU: pode ser recusado. O modo CPU continua sendo uma escolha explícita, nunca fallback automático. A validação estrutural de importação já usava carregadores CPU e não foi rebatizada como inferência GPU.

Nos testes, o Vulkan é implementado por software no emulador: seus shaders acabam sendo executados pela CPU do servidor. Esse teste valida o caminho Vulkan e a proteção contra troca para o backend ggml CPU, **não a ausência física de trabalho na CPU nem a velocidade da GPU de um telefone**.

## Evidência já concluída

- Build [35148206020](https://github.com/Enzo-cyber2025/5/actions/runs/35148206020), job 104969880647: compilação nativa/UI, 171 regressões (2 skips), integração ggml host, DEX e relay do unsigned passaram. **O workflow amplo terminou em falha**, pela resposta incorreta ` CERO EMIOFSELLA.` ao ônibus. A comparação assinada separada confirmou a mesma resposta incorreta na versão anterior; não converter a falha ampla em sucesso.
- Local: 145 testes passaram, 28 pulados na seleção de regressões antes da alteração final de reserva/lifetime; seleção final focada: 13 passaram, 3 pulados. Host llama completo com o patch compilado. Teste real do backend ggml CPU confirmou rejeição de ADD, inclusive pelo scheduler, sem modificar o tensor de saída; fora do escopo estrito, o mesmo backend calculou corretamente.
- Os quatro binários JNI (ARM64 baseline/dotprod/i8mm e x86_64) contêm os marcadores de proteção compilados. Isso não prova execução ARM em hardware.
- Comparativo visual assinado exato [35149450717](https://github.com/Enzo-cyber2025/5/actions/runs/35149450717), tentativa 1, job 104973741503, commit `92e1e7436cb3329630a1914113487fb4039e92ae`: **PASS_EQUALITY_ONLY**. Atualização com mesma assinatura e preservação de modelos/conversas passaram. O log da inferência nova registrou 35 grafos e 19.290 nós de cálculo submetidos sob a política estrita, sem bloqueio; seleção final de tokens no backend.

### Memória/roteamento observados nesse modelo visual

No mesmo GGUF externo SmolVLM, antes → depois:
- Pesos no buffer `CPU_Mapped`: **28,76 MiB → nenhum buffer de pesos CPU listado**.
- Pesos no buffer `Vulkan0`: **136,47 → 165,24 MiB**.
- Buffer de cálculo `Vulkan0` na reserva inicial: **6,16 → 0,95 MiB**.
- Blocos do grafo de linguagem na reserva inicial: **2 → 1**.
- Pesos do projetor: 103.756.800 bytes, 198 tensores, Vulkan0 nas duas versões.

São dados reais de colocação/reserva, não uma redução universal de RAM total nem uma medição de tokens/s. Transferir pesos para o buffer GPU aumenta esse buffer; não confundir com pesos removidos ou quantização menor.

### Limitação visual preservada

A resposta ao ônibus foi **` CERO EMIOFSELLA.` nas duas versões**, semanticamente incorreta em ambas. Igualdade não é acerto semântico. O encoder e a geração realmente executaram; não houve resposta artificial. A falha conhecida não deve ser convertida em aprovação universal de visão.

## Validação de velocidade concluída — meta reprovada

A execução 35149450810 passou na identidade/assinatura do APK, mas falhou na etapa de emulador, sem produzir `summary.json`. Download de logs pelo cliente retornou EOF; o retry inclui relay diagnóstico pelo runner e captura limitada de stdout/stderr, mantendo o código de saída real.

Retry: [35150143379](https://github.com/Enzo-cyber2025/5/actions/runs/35150143379), job 104976090371, commit `7a5299617182866ad5812501d0f9c249748cf54d`. Mesmo APK, sem recompilar ou reassinar. Execução completou **success** em 21:43:45 UTC. Uma resposta de aquecimento excluída e três respostas medidas por estado/versão; continuação, amostragem não greedy, inferência de cachorro explicitamente em Vulkan, código/Copiar, atualização preservando dados e avisos com tela apagada passaram. Screenshot/revisão e hashes em `.delivery/vulkan-acceptance.json`; `ci/verify_vulkan_acceptance.py` passou. O relay do log antigo também não conseguiu baixar o log: a causa exata do bootstrap anterior permanece não determinada.

## Assinatura

Certificado `7295130ab387cd5123c1faab79c96f3ca8d8eb694ae7b15c611086d48b5898a0`, igual ao último APK 8a994 entregue. A chave privada foi preservada e não publicada. A atualização assinada sobre o APK anterior passou nos testes. Isso aprova a funcionalidade do candidato, não a meta de velocidade.


### Medianas, APK 8a994 → 323fd5, mesmo software Vulkan

| Medida | Tela acesa | Tela apagada |
|---|---:|---:|
| Decode tokens/s | **2,0578 → 2,0515 (−0,31%)** | **4,0105 → 4,0614 (+1,27%)** |
| Total nativo | 66,963 → 67,110 s | 36,548 → 36,108 s |
| Primeiro texto nativo | 4,839 → 4,835 s | 4,657 → 4,503 s |
| Enviar → primeiro texto na UI | 4,879 → 4,904 s | Não aplicável à renderização com tela apagada |

Todos os casos determinísticos comparados emitiram os mesmos 128 tokens e texto exato. SmolLM2-135M Q4_K_M, contexto 2048, Auto threads, GPU 99, mesmo GGUF/quantização/parâmetros. As diferenças são pequenas e não estabelecem significância estatística. Total não inclui importação/carregamento inicial; primeiro texto não é conclusão em 5 segundos.

Continuações (uma observação, não mediana): total acesa 74,450 → 74,600 s; apagada 40,494 → 40,152 s. Não greedy conserva filtros e penalidades, mas seeds derivadas de nanoTime não são iguais: teste de conclusão, não prova de igualdade estocástica.

A meta de +150% exigiria pelo menos **5,1446 tokens/s acesa e 10,0263 tokens/s apagada** nesse par de testes. O gate separado `ci/verify_vulkan_target.py` deve falhar enquanto ambos não atingirem 2,5×. A aprovação funcional não contorna esse gate.

### Próxima investigação, sem nova promessa de ganho

Execução exploratória `35156484592` usa o mesmo APK assinado, sem alterar seu payload: políticas upstream de submissão 100/32/512 nós, conferindo o ambiente efetivo do processo e a saída determinística. Uma observação por configuração/estado serve apenas como triagem. Uma execução separada habilita timestamps Vulkan; o profiler adiciona esperas e seus tempos NÃO contam como throughput normal nem como ganho de 150%. Não houve seleção cega dessas opções como novo padrão no APK.


### Resultado da investigação adicional

[35156484592](https://github.com/Enzo-cyber2025/5/actions/runs/35156484592), job 104997041756, concluiu **PASS_EXPLORATORY_ONLY**. Wrapper Android aplicado e variáveis efetivas conferidas no processo real; mesmo APK e respostas idênticas de 128 tokens em todas as configurações. Nada foi recompilado, reassinado ou adotado como novo padrão.

| Política de submissão | Decode acesa | Decode apagada |
|---|---:|---:|
| Padrão 100 nós | 1,9941 tokens/s | 4,0522 tokens/s |
| 32 nós | 2,0272 tokens/s | 4,0811 tokens/s |
| 512 nós | 2,0516 tokens/s | **3,5276 tokens/s (regressão observada)** |

São observações únicas, sem controle de aquecimento. O primeiro caso aceso teve primeiro texto em 24,291 s, contra cerca de 4,6 s nos posteriores; não atribuir essa diferença de ordem/aquecimento à política de submissão nem anunciar 88,478 → 66,963 s como ganho causal. Nenhuma dessas taxas mostrou 2,5×. O parâmetro padrão 100 permaneceu no APK.

O profiler separado produziu timestamps Vulkan reais: grupos que contêm MUL_MAT somaram aproximadamente **82,75% dos 37,369 s registrados**. Grupos podem incluir operações fundidas vizinhas; não é custo isolado de cada multiplicação nem taxa do app sem instrumentação. A execução instrumentada teve esperas extras, portanto seus 3,669 tokens/s não entram na comparação de velocidade.

Relatório resumido: `.delivery/vulkan-profile-screening.json`; dados brutos e logs: `ci-results/35156484592-1/`. Resultado final desta rodada: roteamento tensorial estrito e funcionalidade aprovados; **meta de desempenho de +150% reprovada**.
