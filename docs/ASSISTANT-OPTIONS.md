# Perguntas de esclarecimento e arquivo local de contexto

O botão **Memória** na conversa abre duas opções independentes:

- **Perguntas de esclarecimento**: desligada por padrão. Quando ligada, acrescenta uma instrução ao papel `system` para o modelo perguntar somente quando faltar informação importante ou houver ambiguidade.
- **Salvar contexto automaticamente**: desligado por padrão. Quando ligado, atualiza um retrato textual do histórico da conversa no diretório privado interno do app, ao preparar uma geração. O conteúdo não é enviado pela rede por esse recurso. O botão permite apagar o arquivo.

A cota é configurável entre 1 e 2048 MB (padrão 64 MB), com limite adicional de 8 MB por conversa e reserva de espaço livre. Ao exceder a cota, o app tenta remover primeiro os retratos de conversa mais antigos. Se um retrato individual exceder seu limite, conserva a parte recente e marca que o início foi omitido. Erro de armazenamento não deve interromper a geração: a gravação do arquivo é melhor esforço e deve ser tratada como tal.

O arquivo é um **arquivo local**, não uma janela de contexto infinita: não muda `n_ctx`, não garante que o conteúdo arquivado será reinserido no prompt, e não evita limites de memória/RAM do modelo. As mensagens normais da conversa continuam seguindo o armazenamento e o ciclo de vida próprios do app.

## Modos do Termux

O botão **Modo Termux** oferece quatro níveis, e o padrão é **Sem Termux**:

1. **Sem Termux**: bloqueia o encaminhamento.
2. **Moderado**: aceita somente comandos curtos de consulta da lista permitida (`pwd`, `date`, `whoami`, `uname`, `ls`, `df`, `free`, `getprop`, `termux-info` e `pkg list-installed`, com argumentos restritos). Cada comando continua sendo mostrado para revisão.
3. **Completo**: aceita blocos de shell propostos pelo modelo, mas mantém o limite de 6.000 caracteres, a tela com o comando exato e o toque explícito em **Abrir no Termux**. Também depende da permissão Android/Termux `RUN_COMMAND`.
4. **Completo com autorização**: tem o mesmo escopo do modo Completo, mas exige digitar `AUTORIZO` em cada encaminhamento, além da revisão e da permissão `RUN_COMMAND`.

O modo Completo sem confirmação/autorização não foi implementado: um comando arbitrário pode apagar ou expor dados. O Termux continua sendo um app separado, os comandos rodam com as permissões concedidas ao Termux e a saída permanece no Termux; ela não é retornada automaticamente ao modelo.
