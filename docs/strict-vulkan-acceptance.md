# Vulkan estrito — candidato em validação

**Estado: ainda não aprovado para entrega.** O comparativo de velocidade com tela acesa/apagada precisa terminar. Não há nova meta de velocidade certificada.

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

## Validação de velocidade ainda pendente

A execução 35149450810 passou na identidade/assinatura do APK, mas falhou na etapa de emulador, sem produzir `summary.json`. Download de logs pelo cliente retornou EOF; o retry inclui relay diagnóstico pelo runner e captura limitada de stdout/stderr, mantendo o código de saída real.

Retry: [35150143379](https://github.com/Enzo-cyber2025/5/actions/runs/35150143379), job 104976090371, commit `7a5299617182866ad5812501d0f9c249748cf54d`. Mesmo APK, sem recompilar ou reassinar. Comparação planeja uma resposta de aquecimento e três respostas medidas por estado/versão, continuação, amostragem não greedy, inferência de cachorro explicitamente configurada em Vulkan, código/Copiar, atualização e avisos com tela apagada.

## Assinatura

Certificado `7295130ab387cd5123c1faab79c96f3ca8d8eb694ae7b15c611086d48b5898a0`, igual ao último APK 8a994 entregue. A chave privada foi preservada e não publicada. O APK candidato não foi apresentado como nova entrega aprovada.
