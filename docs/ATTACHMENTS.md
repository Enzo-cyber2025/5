# Câmera, clipe e múltiplos anexos

## Comportamento

- Câmera e clipe à **esquerda do campo de mensagem**, mantendo a chave de ferramentas à direita, junto de Enviar.
- **Câmera:** “Importar foto” abre o gerenciador de arquivos com seleção múltipla de imagens; “Tirar foto” abre o aplicativo de câmera do Android. Após cada captura, “Tirar outra foto” permite acumular mais fotos, e “Concluir” volta à conversa.
- A câmera fica **cinza e desativada no modelo sem projetor**. O clipe continua disponível em ambos os tipos de modelo.
- **Clipe:** seletor `ACTION_OPEN_DOCUMENT`, tipo `*/*`, `EXTRA_ALLOW_MULTIPLE=true`. Não há lista de extensões permitidas, limite fixo de bytes ou número máximo de anexos imposto pelo app. Também é possível importar novos lotes sem substituir os anteriores.
- O indicador de anexos abre uma lista com nome, tamanho, estado pendente/enviado, abertura em aplicativo externo e remoção individual dos pendentes.
- O texto digitado é preservado ao enviar junto dos anexos. Anexos já importados sobrevivem à reabertura da conversa e ficam vinculados à mensagem em um índice separado.
- Excluir uma conversa também remove seus arquivos privados, sem atingir os anexos das outras conversas. Os arquivos originais escolhidos no gerenciador não são apagados.

## Armazenamento e segurança

Os arquivos são copiados para `files/attachments/<hash-da-conversa>/<id>.data`; nome original, MIME, tamanho real e índice da mensagem ficam no `index.json` dessa conversa. O conteúdo de um arquivo não é convertido inteiro em `String`, `Bitmap` ou `byte[]`: a cópia usa **128 KiB de buffer** e contador `long`.

Arquivos temporários só viram anexos após a cópia e a gravação do índice. Cancelamento/erro remove a cópia incompleta, sem descartar os anexos concluídos. A escrita do índice usa `AtomicFile`; temporários `.part` incompletos na pasta da conversa são limpos ao reabrir. Importações em curso não são retomadas automaticamente após encerramento forçado do processo; mantenha o app aberto durante cópias longas ou de provedores de nuvem.

A câmera recebe uma URI `content://` privada pelo `EXTRA_OUTPUT`, não se usa a miniatura retornada em extras. O provider não é exportado: concede acesso temporário somente à URI específica. Arquivos já anexados são expostos para leitura apenas quando o usuário escolhe abri-los. Não foi adicionada permissão de acesso irrestrito ao armazenamento ou de câmera interna; a captura é delegada ao app de câmera do Android.

**“Sem limite fixo no app” não significa armazenamento infinito.** Espaço disponível, memória para os metadados/lista, limites de transporte do Android, permissões, arquivos remotos e comportamento do gerenciador/câmera continuam aplicáveis. Seleções maiores podem ser feitas em vários lotes. Falhas recuperáveis são registradas na lista de anexos; falta extrema de espaço pode impedir também a gravação desse estado. Uma captura cuja gravação do índice falhe pode deixar o original na pasta privada da câmera, sem recuperação automática pela lista. O histórico de mensagens e o índice dos anexos são gravações separadas, não uma transação atômica entre os dois arquivos.

## Importante: anexar não é interpretar

Esta revisão implementa **seleção, captura, armazenamento e vínculo dos arquivos à conversa**. Não implementa análise de imagens, PDF, áudio, vídeo ou extração do conteúdo de arquivos pelo modelo. A própria interface e a mensagem enviada informam isso. O motor recebe a mensagem digitada e um aviso agregado de anexos, não os bytes dos arquivos. Não existe envio oculto dos arquivos para um serviço externo.

O comportamento antigo que lia arquivos de texto inteiros na RAM foi removido. Uma futura etapa de interpretação precisará tratar formatos e orçamento de contexto separadamente, sem confundir limites de inferência com limites de importação.

## Artefato e validação

[Baixar APK diretamente, sem ZIP](https://github.com/Enzo-cyber2025/5/releases/download/gguf-attachments-f129e2c/GGUF-Chat-mobile.apk).

Fonte: `f129e2c88a5c8957355e520543817b5de3d525d7`.
SHA-256: `5b40c17d4fcb256bd9bcae2c1149028f8ca442c7230323970e6f91df6c56e63c`.
Tamanho: 16.753.713 bytes. Android 9+, ARM64 e x86_64.
Mesma chave fixa das revisões mobile e unificada anteriores.

As bibliotecas nativas foram reutilizadas **byte por byte**, verificadas por hash, da revisão Vulkan aprovada `72d4429`. Esta etapa muda o código Java/DEX e acrescenta o provider ao manifesto, sem misturar ou trocar o motor.

- Compilação [34790587186](https://github.com/Enzo-cyber2025/5/actions/runs/34790587186): 106 testes de ferramentas/política/lógica passaram. Inclui a função real de cópia exercitada com um fluxo **simulado** de mais de 3 GiB, heap de 32 MiB, arquivo vazio, cancelamento e falha de saída. Isso não é um teste Android de arquivo físico de 3 GiB.
- 33 regressões DEX→JVM passaram após assinatura, com doubles explícitos para Native/JSON.
- Validação Android final: **PASS**, [34790832355](https://github.com/Enzo-cyber2025/5/actions/runs/34790832355). [Resumo original](../ci-results/34790832355-1/summary.json).

A tentativa Android anterior `34790084230` validou múltiplas fotos, arquivos mistos, arquivo vazio, arquivo físico de 8 MiB, hashes, restauração dos pendentes e duas capturas reais do app de câmera do emulador (1392 × 1856). Detectou que o formatador antigo descartava o texto digitado quando havia anexo. Esse desvio foi corrigido antes da compilação acima. A tentativa `34790707076` parou na preparação do host Vulkan, antes de abrir o emulador; não é resultado de execução do novo APK.


### Resultados do APK final

- Câmera/clipe antes do campo de texto; câmera habilitada no par e desabilitada no modelo normal.
- Duas fotos selecionadas pelo SAF e um segundo lote de seis arquivos (PNG, TXT, ZIP válido, arquivo vazio e binário de 8 MiB). Todos os bytes/tamanhos conferidos por hash; os lotes se acumulam.
- Duas capturas de **1392 × 1856**, 75.094 e 75.295 bytes, via app real da câmera com sensor emulado. Nenhum resultado de câmera ou bitmap foi injetado pelo teste.
- Reinício preservando os pendentes; remoção de um anexo preservando os outros; **nove arquivos vinculados à mensagem, junto do texto digitado**.
- Modelo normal: câmera desabilitada e importação de seis arquivos pelo clipe funcionando, sem misturar anexos de conversas diferentes.
- Exclusão da conversa normal removeu seus arquivos e preservou os nove anexos da outra conversa.
- As regressões anteriores de unificação, olho, barra compacta e Vulkan dos dois componentes também passaram no mesmo APK. Vulkan testado por software (Mesa/Lavapipe), não em GPU física.

[Captura: câmera cinza e seis anexos no modelo normal](../ci-results/34790832355-1/attachments-normal-files.png) · [Menu da câmera](../ci-results/34790832355-1/attachments-camera-menu.png) · [Mensagem e anexos persistidos](../ci-results/34790832355-1/attachments-sent.json).

Publicação e download verificados: [34791386109 — PASS](https://github.com/Enzo-cyber2025/5/actions/runs/34791386109). O runner baixou o APK publicado, comparou byte a byte com o APK aprovado e conferiu o SHA-256 acima. [Saída original da verificação](../ci-results/34791386109-1/publication-checks.json).
