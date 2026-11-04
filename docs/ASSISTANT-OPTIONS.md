# Perguntas de esclarecimento e arquivo local de contexto

O botão **Memória** na conversa abre duas opções independentes:

- **Perguntas de esclarecimento**: desligada por padrão. Quando ligada, acrescenta uma instrução ao papel `system` para o modelo perguntar somente quando faltar informação importante ou houver ambiguidade.
- **Salvar contexto automaticamente**: desligado por padrão. Quando ligado, atualiza um retrato textual do histórico da conversa no diretório privado interno do app, ao preparar uma geração. O conteúdo não é enviado pela rede por esse recurso. O botão permite apagar o arquivo.

A cota é configurável entre 1 e 2048 MB (padrão 64 MB), com limite adicional de 8 MB por conversa e reserva de espaço livre. Ao exceder a cota, o app tenta remover primeiro os retratos de conversa mais antigos. Se um retrato individual exceder seu limite, conserva a parte recente e marca que o início foi omitido. Erro de armazenamento não deve interromper a geração: a gravação do arquivo é melhor esforço e deve ser tratada como tal.

O arquivo é um **arquivo local**, não uma janela de contexto infinita: não muda `n_ctx`, não garante que o conteúdo arquivado será reinserido no prompt, e não evita limites de memória/RAM do modelo. As mensagens normais da conversa continuam seguindo o armazenamento e o ciclo de vida próprios do app.

## Termux

Este checkout ainda não contém uma ponte de comandos com o Termux. Portanto, não há quatro modos de acesso funcionais para habilitar neste momento. Não será adicionado um modo de shell irrestrito, sem revisão do comando. Uma futura integração deverá manter o Termux externo ao app, exigir confirmação humana do comando, declarar claramente permissões e não enviar automaticamente a saída do shell de volta ao modelo.
