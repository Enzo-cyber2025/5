# Geração otimizada e tokens/s por resposta

## O que mudou

- O motor conta os tokens realmente amostrados, sem contar o token de fim. Não há estimativa por palavras, caracteres ou quantidade de atualizações da interface.
- Ao terminar, cada resposta mostra `tokens/s · total de tokens` **abaixo e fora do balão**. A média usa relógio monotônico após o processamento inicial do prompt/imagens; inclui amostragem e entrega do texto. O tempo inicial fica registrado separadamente.
- A medição pertence à mensagem e sobrevive ao fechamento/reabertura. Respostas anteriores aparecem como **sem medição**, sem valores inventados. Respostas parciais medidas são identificadas como interrompidas.
- O primeiro token continua sendo enviado imediatamente quando forma UTF-8 completo. Os demais podem ser agrupados por 50 ms ou 4 KiB, com envio final do texto pendente.
- Notificações deixam de ser recriadas por token: atualização no máximo uma vez por segundo e cópia de no máximo 80 caracteres para a prévia, em vez de copiar toda a resposta repetidamente.
- Foi removido o último decode quando nenhum próximo token será amostrado. Modelo, pesos, quantização e amostragem não foram trocados para obter os resultados.

## Testes reais

**Seis verificações funcionais passaram no APK assinado. Aumento de velocidade não foi comprovado.**

[Execução Android aprovada funcionalmente](https://github.com/Enzo-cyber2025/5/actions/runs/34999699148) · [relatório completo](../ci-results/34999699148-1/summary.json)

| Execução medida | Anterior, tokens/s | Novo, tokens/s |
|---|---:|---:|
| 1 | 3,17 | 3,50 |
| 2 | 4,81 | 9,28 |
| 3 | 10,51 | 4,75 |
| **Mediana** | **4,81** | **4,75** |

Diferença da mediana: **−1,18%**, com grande variabilidade no emulador. Não foi comprovado aumento de tokens/s. As tentativas anteriores registraram diferenças de +16,6% e +6,1%, mas falharam nos observadores descritos abaixo: não foram escolhidas como resultado final nem convertidas em aprovação. A variação entre execuções impede prometer aceleração.

Nos três testes novos, o motor gerou 384 tokens em 321 entregas de texto. A redução de chamadas/atualizações não equivale a um ganho comprovado de velocidade do modelo. O publicador de release de desempenho permanece bloqueado; este APK é disponibilizado como **versão de teste com a funcionalidade validada**, não como release com aceleração aprovada.

Capturas reais revisadas: [rodapé](../ci-results/34999699148-1/physical-speed-footer.png), [após reabrir](../ci-results/34999699148-1/physical-speed-reopened-footer.png), [resposta antiga](../ci-results/34999699148-1/physical-speed-old-response.png), [imagem real](../ci-results/34999699148-1/physical-speed-vision-footer.png).

Na inferência visual, o Android dormiu às 17:23:49.217 e o motor concluiu às 17:24:08.245, salvando “Dog.”. O log e o JSON registram 2 tokens, 52.124.955 ns de geração e 20.376.454.892 ns de prefill. O rodapé de 38,4 tokens/s exclui esse prefill: **uma resposta de dois tokens não é um benchmark de desempenho**. O dump de energia já sem a nossa trava foi verificado enquanto a tela ainda estava apagada, antes de forçar a reabertura.

A regressão ampla do build (34997035140) continua em execução no momento deste registro; compilação, regressões de código e testes DEX/JVM já concluíram com sucesso. Isso é separado da execução funcional assinada acima.

O teste instala os APKs anterior e novo no mesmo Android 35 x86_64 descartável, por `install -r`, com o mesmo modelo real SmolLM2-135M Q4_K_M, CPU, duas threads, contexto 1024, temperatura zero, prompt e limite de 128 tokens. Exclui uma execução de aquecimento e registra três execuções de cada APK. Cada execução usa conversa nova. O aquecimento é do ambiente/cache; não é uma promessa de manter o mesmo processo nativo carregado entre execuções.

A comparação usa o intervalo registrado entre conteúdo preparado e conclusão nativa, **incluindo prefill**, porque o APK anterior não tinha o contador de tempo separado. Portanto essa coluna não é diretamente igual à taxa de geração mostrada no rodapé novo. Os resultados e a variabilidade precisam ser apresentados juntos: não é uma medição em celular físico, nem garantia de ganho em outro modelo/aparelho.

A aceitação também verifica:

- Mesmo texto de saída nas seis execuções medidas.
- Contagem e nanossegundos iguais no log nativo e no JSON da mensagem.
- Valor e posição real do rodapé na interface, antes e depois de reabrir.
- Atualização com mesma assinatura, preservando modelos, conversas e arquivo de controle.
- Ausência de métricas inventadas em mensagens antigas.
- Importação física de GGUF com projetor, imagem real de cachorro avaliada pelo motor, resposta salva com a tela apagada e liberação do bloqueio de CPU antes de reiniciar o processo.

Os relatórios de tentativas que falharam permanecem publicados. Um erro de acesso a atributo XML no observador e uma consulta antecipada ao bloqueio de CPU foram corrigidos no teste, sem alterar o APK nem transformar os relatórios antigos em sucesso.

## APK e assinatura

[Baixar APK de teste (sem ZIP)](https://raw.githubusercontent.com/Enzo-cyber2025/5/9a5e656031aa413fb661c16c975cea42d3e49cc0/.delivery/GGUF-Chat-mobile.apk)

Os bytes desse commit foram baixados pela API de conteúdo do GitHub e comparados integralmente com o APK local testado.

- APK: `GGUF-Chat-mobile.apk`, Android 9+, ARM64 e x86_64, sem modelos incluídos.
- SHA-256: `b8145469da04884849b17cd99aff69fbea07f0bb24723ed1611373c7fce1743f`.
- Código compilado: `abb4fe8ceb6f4785165700a64d448e7e16539004`.
- llama.cpp: `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`.
- Certificado: `3dd851d414caaa20d06ea22391e75b752aab0d26c749168b3353dd389b1332da`.

**Mesma assinatura do APK de teste anterior (`0c45fd…`).** Pode ser instalado sobre esse APK; a preservação de dados é exercitada no emulador. **Não atualiza diretamente os APKs antigos com certificado `9b658c…`.** Desinstalar pode apagar conversas e modelos privados; faça cópia antes se estiver nessa versão antiga.

O teste de tela apagada não promete funcionamento após forçar parada, imunidade a restrições do fabricante ou aprovação de política da loja. Software Vulkan não equivale a GPU física. Reconhecer uma imagem de teste não certifica precisão geral, todos os modelos, áudio ou desempenho de Gemma no telefone.
