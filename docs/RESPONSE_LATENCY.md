# Menor espera: cache de histórico e de visão

## Mudanças no motor e na interface

- **KV do texto:** reaproveita somente o prefixo de tokens exatamente igual, no mesmo motor/contexto. Confere as posições realmente presentes na memória e remove o sufixo antigo. Reavalia pelo menos o último token do prompt para obter logits atuais.
- Modelos recorrentes, híbridos, encoder-decoder e de difusão não usam esse reaproveitamento. Prefixos já expulsos pela janela de atenção também não. Se a remoção parcial não for suportada, faz o processamento completo.
- **Prompt:** mantém o lote lógico de 128 e microlote de 32 do APK anterior. O experimento 512/128 foi rejeitado por alterar a saída determinística no teste real.
- **Visão:** cache opcional dos embeddings do projetor, separado do KV textual. A identidade vem do SHA-256 dos bytes efetivamente decodificados, gerado pelo helper oficial fixado. A lista ordenada de imagens, ordinal do recorte e geometria serializada precisam coincidir. Não usa nome de arquivo como identidade.
- O cache visual guarda até 16 MiB de vetores em RAM, não arquivos. Isso **não limita anexos ou leitura**: imagens que não caibam no cache continuam sendo processadas normalmente. Falha na cópia opcional por falta de memória descarta o cache.
- Em imagens, o KV do modelo de linguagem continua sendo reconstruído. O helper oficial preserva posicionamento, M-RoPE e atenção não causal. Só a codificação visual pura é evitada quando o resultado exato já existe.
- Erro/cancelamento invalida os caches; fechar o processo ou trocar o motor também. Nada é persistido em disco como cache de estado nativo.
- **Texto na tela:** `TextView.append` incremental em vez de copiar/substituir/reduzir toda a resposta a cada bloco. Quebras de linha e todo o texto continuam disponíveis, inclusive durante a geração.
- Conversão de tokens usa buffer pequeno na pilha, com alocação dinâmica somente quando o token não cabe. Preserva envio inicial imediato, agrupamento UTF-8 e gravação integral da resposta.
- Pesos, quantização, temperatura, amostragem e limites escolhidos pelo usuário não são reduzidos para conseguir velocidade.

## Medição

Os tokens/s continuam abaixo de cada resposta. O JSON da mensagem registra também `firstTokenNs`, `promptTokens` e `reusedPromptTokens`.

`firstTokenNs` mede desde a entrada na geração nativa até a primeira entrega de texto completo ao callback. **Não é tempo desde o toque até o desenho na tela**, nem inclui um carregamento de modelo anterior à entrada nativa. Prefill, geração e espera da interface não devem ser misturados como se fossem a mesma medição.

## Validação em andamento

Candidato **REJEITADO**: `43c802e7244d3a9ea09dd91821353a2be4ce7943148e34900463bfb449d3de82`, código `59faf72ce32092163950288662fc06f2f00135c7`.

- Compilação ARM64/x86_64, regressões de código e DEX/JVM concluídas.
- Comparação Android assinada com o APK anterior `b8145469…` falhou na igualdade da resposta: quatro pares de perguntas por versão (um par de aquecimento excluído), três medições de prompt frio e de continuação. Mesmo emulador, modelo, contexto 2048, duas threads e amostragem gulosa.
- Verificações de mudança de sistema, reabertura, cancelamento, imagem real com tela apagada, reutilização da mesma imagem e recodificação quando outra imagem é anexada.
- A primeira tentativa com APK intermediário falhou no observador: o envio de uma longa rajada de teclas sintéticas perdeu parte do prompt antes de chegar ao app. A correção usa um IME descartável de teste com InputConnection e verifica independentemente o conteúdo integral do EditText antes de enviar. O IME não faz parte do app distribuído. O relatório anterior permanece como falha.

**Nenhum número de aceleração aprovado neste documento até concluir as medições.** Resultados em emulador não certificam velocidade em celular físico, qualquer arquitetura/modelo ou precisão semântica geral. Vulkan em software não é GPU física.

Assinatura do candidato rejeitado: `3dd851d414caaa20d06ea22391e75b752aab0d26c749168b3353dd389b1332da`, igual aos dois últimos APKs de teste. Continua incompatível com os APKs antigos assinados com `9b658c…`; não desinstale uma versão antiga sem proteger seus dados.

## Rejected numerical batching experiment; corrected rebuild

The signed 43c802 candidate failed deterministic cold-output equality in real
Android run 35005228698, despite identical 1744-character input, sampling settings
and system SHA. Thus the observed follow-up prefill decrease is provisional and
NOT an accepted speed/quality comparison. Cancellation/image cache gates were
not reached. The 512/128 batching experiment is removed; baseline 128/32 is
restored while guarded caches and incremental rendering remain.

After reconnection the workspace was restored to an older checkout. Remote
786c46a (including all published evidence) was recovered on the same branch,
with the previous worktree archived locally before restoration. The unpushed
correction is reapplied here. Signing key and private backup are not present
in this restored environment: no same-certificate update can be promised.
No corrected APK has been accepted yet.

## Assinatura após restauração do ambiente

A chave anterior não foi restaurada. Usando a autorização prévia do usuário para
outra assinatura se necessário, foi preparada a chave local `4f75afe8637f28ccb167db407e3b2bc9b260e1cfe6059b7377ea20b0b4dc2ac3`.
O novo APK será **incompatível com atualização direta** dos anteriores. Não
desinstale o app do celular sem proteger os dados. O teste mantém o APK baseline
original intacto, verifica a recusa de atualização pelo Android e a preservação
dos arquivos após a recusa, e só então reinstala no emulador descartável.
Não equivale a migração ou atualização preservando dados no aparelho real.
