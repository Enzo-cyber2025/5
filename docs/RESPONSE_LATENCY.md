# Otimização de latência — resultado aprovado nos testes

## APK e instalação

- APK: `eabd016935ac51cdd89063a97fbc1b562f7f9261981f54b5191d37734e7922eb` — 28.370.376 bytes, Android 9+, ARM64/x86_64; modelos não incluídos.
- Código compilado: `ce0118db8646f1523d11725a8c5c29b6e88230f2`.
- Motor fixado: llama.cpp `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`.
- [Aprovação verificável](../.delivery/latency-acceptance.json). Verificador: `python ci/verify_latency_acceptance.py`.

**Assinatura diferente:** a restauração do ambiente não recuperou a chave privada anterior. Conforme a autorização prévia do usuário, foi criada outra chave local, com backup privado. Certificado atual: `4f75afe8637f28ccb167db407e3b2bc9b260e1cfe6059b7377ea20b0b4dc2ac3`.

O Android **não permite atualizar diretamente** o APK anterior de certificado `3dd851d4…`. A tentativa real foi recusada com `INSTALL_FAILED_UPDATE_INCOMPATIBLE`, preservando os arquivos existentes após a recusa. A reinstalação seguinte foi feita **somente no emulador descartável**. Não constitui migração de dados. **Não desinstale o aplicativo do celular sem proteger seus dados.** Chave e senha não foram enviadas ao Git ou CI.

## Resultado medido, sem reduzir o modelo

Comparação com o último APK entregue, `b8145469da04884849b17cd99aff69fbea07f0bb24723ed1611373c7fce1743f`. Mesmo emulador Android 35 x86_64, CPU, duas threads, contexto 2048, mesmos pesos SmolLM2-135M-Instruct-Q4_K_M e amostragem gulosa. Quatro pares por versão: um aquecimento excluído e três pares medidos. **Respostas comparadas integralmente e iguais**, inclusive após mudança do prompt de sistema.

| Mediana | Antes | Depois |
|---|---:|---:|
| Preparação do primeiro prompt, sem cache | 9,81 s | 9,88 s |
| Preparação da continuação com histórico | 14,64 s | 1,47 s |
| Tempo nativo total da continuação, preparação + geração | 31,56 s | 18,21 s |
| Geração da continuação, sem preparação | 7,57 tokens/s | 7,65 tokens/s |

- **89,99% menos tempo preparando a continuação**, aproximadamente 10× mais rápido nessa etapa.
- **42,31% menos tempo nativo total** na continuação medida.
- Não há ganho relevante comprovado no primeiro prompt nem na geração token a token. O ganho principal vem de evitar reprocessar o histórico.
- Primeira entrega de texto na versão nova: mediana de 9,881 s no prompt frio e 1,470 s na continuação. Essa métrica começa na entrada da geração nativa, **não no toque e não no carregamento do modelo**.

### Imagem repetida

Na mesma execução e processo, a preparação com imagem passou de **21,75 s sem cache para 4,78 s com cache**. É **uma observação com perguntas diferentes**, não uma garantia estatística. Os logs mostram três recortes reutilizados, zero recodificações no acerto; ao acrescentar a imagem de um ônibus, zero acertos e cinco recodificações. A resposta à nova imagem foi `Bus.`. A identidade dos pixels e o posicionamento continuam sendo conferidos.

Resultados de emulador não certificam esses tempos no celular físico, em qualquer modelo ou GPU. Respostas de dois a quatro tokens não são benchmarks de velocidade, mesmo que o rodapé mostre uma taxa alta.

## Mudanças implementadas

- **Cache KV textual:** reutiliza somente o prefixo de tokens exatamente igual no mesmo motor/contexto. Confere as posições realmente disponíveis e exige remoção bem-sucedida do sufixo antigo. Reavalia pelo menos o último token da entrada para obter logits atuais.
- Recorrentes, híbridos, encoder-decoder e difusão não usam esse reaproveitamento. Prefixos expulsos pela janela de atenção também não. Se não for seguro reutilizar, o processamento é completo.
- **Lotes mantidos em 128/32**, iguais aos do baseline. O experimento 512/128 foi rejeitado por mudar a saída determinística.
- **Cache visual opcional de até 16 MiB de vetores em RAM:** chave baseada em SHA-256 dos bytes efetivamente decodificados, lista ordenada de imagens, ordinal do recorte e geometria serializada. Não usa nomes de arquivo. Não é limite de anexos: imagens maiores continuam sendo processadas sem cache.
- Em mensagens com imagens, o KV textual é reconstruído. O helper oficial preserva M-RoPE, posições e atenção não causal; somente a codificação visual pura é evitada em um acerto exato.
- Falhas/cancelamento invalidam caches. Trocar o motor ou encerrar o processo também. Não há cache de estado nativo persistido em disco.
- **Interface incremental:** `TextView.append`, sem copiar/substituir toda a resposta a cada bloco e sem truncar o texto ao vivo. Mantidas as quebras de linha, o primeiro envio imediato e o agrupamento UTF-8.
- Conversão de tokens usa buffer pequeno na pilha e aloca dinamicamente apenas quando necessário.
- Preservados os tokens/s reais abaixo das respostas e sua persistência. Acrescentados `firstTokenNs`, `promptTokens` e `reusedPromptTokens` ao JSON.
- Pesos, quantização, amostragem e limites escolhidos pelo usuário não foram reduzidos para obter os números acima.

## Testes reais e capturas

**APK da assinatura distribuída:** execução [35017084063](https://github.com/Enzo-cyber2025/5/actions/runs/35017084063), job `104543107009`, commit de teste `4266f9b948292dc1feb111962a4d18e2894e4fd9`: **SUCCESS**.

Passaram a igualdade das respostas, reutilização real de prefixo, mudança de sistema, reabertura, persistência e posição do rodapé, cancelamento com recuperação, imagem real com a tela efetivamente apagada, liberação do bloqueio de CPU antes de reiniciar, acerto do cache visual e recodificação de imagens diferentes. O APK assinado foi conferido byte a byte contra o conteúdo ZIP compilado, incluindo hashes das bibliotecas nativas.

Cinco capturas reais foram abertas e inspecionadas: [continuação](../ci-results/35017084063-1/physical-latency-follow-footer.png), [mudança de sistema](../ci-results/35017084063-1/physical-latency-changed-system-footer.png), [reabertura](../ci-results/35017084063-1/physical-latency-reopened-footer.png), [visão](../ci-results/35017084063-1/physical-latency-vision-footer.png) e [imagem em cache](../ci-results/35017084063-1/physical-latency-cached-image-footer.png). Não são imagens geradas ou telas simuladas.

**Suíte ampla da compilação:** [35013826315](https://github.com/Enzo-cyber2025/5/actions/runs/35013826315), job `104532130205`: **SUCCESS**, incluindo compilação das duas ISAs, regressões, DEX/JVM, oito verificações físicas do GGUF, anexos e leitura/inferência real. Essa suíte ampla usa uma assinatura descartável e Vulkan por software, não GPU física. Testes locais direcionados: **21 passaram, 1 depende de javac local indisponível**. O código Java e o IME auxiliar foram compilados no CI.

**Limites de qualidade:** as respostas iguais do modelo pequeno continuam podendo ser repetitivas ou desobedecer instruções. Na suíte ampla, a resposta por conversa reteve ORCHID em vez de CEDAR; no comparativo, a resposta sobre o código também foi inadequada em ambas as versões. Aprovação de latência/funcionamento não é certificação universal de precisão, áudio, suspensão extrema de fabricantes ou imunidade a force-stop.

## Experimentos e falhas anteriores preservados

- APK `43c802…`, código `59faf72…`, execução `35005228698`: **rejeitado**. Os lotes 512/128 mudaram a resposta apesar de entrada completa de 1744 caracteres, configurações e sistema iguais. Seus números provisórios não são usados como aprovação.
- `35003361411`: uma rajada longa de teclas sintéticas perdeu caracteres antes de chegar ao app. A entrada passou a ser verificada integralmente.
- `35014529821`: o IME auxiliar ainda não havia sido registrado durante o desbloqueio inicial do emulador. Agora o teste observa o ID publicado pelo sistema.
- `35015163610`: oito gerações reais do baseline concluídas, mas Back fechou o editor porque o IME não tem painel. Agora a edição usa InputConnection verificado e toca Salvar explicitamente.
- `35016320164`: corrida de inicialização da gaveta SAF; a captura real mostrava Downloads. A seleção agora espera a gaveta e o título visíveis, com ID do framework ou provedor.
- O IME é um APK **separado, descartável e exclusivo do emulador**, sem acesso a rede/armazenamento. Escreve no EditText real; não injeta respostas, modelos ou métricas e não integra o APK entregue.
- As duas interrupções de autenticação foram resolvidas por reconexão. O estado final foi consultado pela API; saída do monitor isoladamente não foi tratada como aprovação.
- Antes de recuperar o checkout, seus 1.158 arquivos antigos foram arquivados e comparados: todos os blobs já estavam preservados no histórico Git.
