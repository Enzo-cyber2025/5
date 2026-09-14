# Leitura real dos anexos — APK com aceitação funcional concluída

Esta revisão substitui a entrega de uma contagem de arquivos por conteúdo real no motor. **Aceitação funcional Android PASS; qualidade geral das respostas não aprovada.**

[Baixar APK diretamente, sem ZIP](https://github.com/Enzo-cyber2025/5/releases/download/gguf-inference-e37df03/GGUF-Chat-mobile.apk) — 21,72 MB, Android 9+, ARM64 e x86_64. Modelos não incluídos.

## O que mudou

- **Imagens:** decodificação dos pixels, correção de orientação EXIF e envio ao `mtmd_tokenize`; o motor executa `mtmd_helper_eval_chunk_single`, que calcula os embeddings pelo projetor e os avalia no contexto do modelo. Isso não é uma legenda inventada a partir do nome do arquivo.
- **Texto:** leitura UTF-8 ou UTF-16 com BOM; TXT, Markdown, CSV, JSON, código e outros arquivos de texto válidos. Bytes binários/encoding inválido geram erro, não uma falsa leitura.
- **PDF:** PDFBox-Android extrai texto por página. Páginas sem texto são renderizadas e enviadas como imagens quando há um modelo de visão; sem visão, há aviso explícito. Figuras presentes em páginas que já possuem texto não são interpretadas separadamente.
- **DOCX/ODT:** extração do texto principal do XML dentro do documento. Imagens, objetos incorporados, layout, cabeçalhos/rodapés e comentários não são um leitor Office completo.
- O conteúdo entra no turno correto da conversa antes de aplicar o template do modelo. Anexos antigos continuam disponíveis ao fazer outra pergunta ou reabrir a conversa.
- A lista oferece **Desativar leitura / Ativar leitura** sem apagar o arquivo, inclusive para anexos de mensagens já enviadas. É possível recuperar uma conversa após erro de formato ou excesso de contexto.
- Preparação e leitura ocorrem no worker do serviço de geração, não na thread da interface. Cancelamento é verificado na leitura e antes da inferência; uma solicitação de parar não é apagada ao entrar no novo método nativo.

## Limites explícitos

Continuam livres de uma cota fixa de importação a quantidade, o tipo e o tamanho dos arquivos — condicionados ao armazenamento/Android/provedor. Isso não torna infinito o contexto do modelo.

A inferência tem limites distintos: 131.072 caracteres extraídos por preparação, 8 megapixels preparados por chamada e o contexto configurado do modelo, atualmente limitado pelo motor a 8.192 tokens. **Excesso gera erro: não há truncamento silencioso de documentos para fingir leitura integral.** Para várias imagens, use contexto maior e, se necessário, divida a análise ou desative arquivos na lista.

Imagens são reduzidas para até 1.024 pixels no maior lado; PDFs visuais também são renderizados com resolução limitada. Originais permanecem intactos. A precisão de OCR, detalhes pequenos e respostas depende do modelo/projetor escolhido; não é garantia de compreensão perfeita.

**Áudio/vídeo, arquivos compactados genéricos, Office binário antigo, planilhas/apresentações e outros binários não possuem leitor/transcritor nesta etapa.** São importáveis, mas a leitura para com aviso até desativar esses anexos ou usar um formato suportado. PDFs protegidos também não têm fluxo de senha.

Modelos sem visão continuam lendo documentos de texto; imagens exigem um par GGUF + mmproj compatível com visão. Ter um caminho de projetor associado não basta se o próprio projetor não suporta imagem: o nativo verifica essa capacidade.

## Privacidade e segurança

Nenhum arquivo é enviado a uma API de interpretação. A leitura é local. Caminhos de imagem são derivados exclusivamente do índice privado da conversa, nunca de texto digitado ou instruções contidas no documento. Marcadores de mídia em texto externo são escapados. DOCX/ODT não executam macros, rejeitam DTD e limitam o XML descompactado. As dependências têm versões e SHA-256 fixados em `ci/document-libraries.json`.

Pixels preparados ficam em cache privado e são apagados ao terminar/falhar. Após encerramento forçado, resíduos desse cache são limpos na próxima preparação. Original e índice de anexos seguem o armazenamento da revisão anterior; as limitações de transação entre índice e histórico continuam descritas em `ATTACHMENTS.md`.

## Assinatura

A chave anterior não estava disponível no ambiente restaurado. **O usuário autorizou uma nova chave**, e um backup privado separado foi preparado e apresentado. Ele não está no Git nem na release.

Certificado novo SHA-256: `35a93f1428120a740adbe95be2621ee9b03fe4342aa363814bdfea0acb2cf7cf`.

Essa assinatura **não atualiza por cima da versão anterior**. Salve conversas, anexos importantes e originais dos modelos fora do aplicativo antes de desinstalá-lo. O backup da chave não é backup dos dados do app.

## APK e testes

- Fonte: `e37df03054f56c9e3a041504461e7121ccff6387`.
- APK: 21.717.999 bytes, SHA-256 `3d17116aac387bbda402ddad2f7dc19b42115eec33d7ec89f7c20dde9a87f2c9`.
- Compilação dos dois ABIs e regressões: [34843655661 — PASS](https://github.com/Enzo-cyber2025/5/actions/runs/34843655661).
- APK assinado traduzido DEX→JVM: 6.778 classes, zero erros; 33 regressões passaram. Esses testes usam doubles explícitos, não comprovam inferência Android.
- Teste Android: [34848915081 — PASS funcional, 29m4s](https://github.com/Enzo-cyber2025/5/actions/runs/34848915081).

O teste Android exige respostas baseadas em códigos presentes somente nos arquivos TXT/PDF/DOCX, reconhecimento de fotos diferentes com nomes neutros, duas imagens juntas, retomada após reinício, PDF visual e falhas explícitas com recuperação pela interface. A execução Vulkan usa Mesa por software no emulador, não uma GPU física; o scheduler pode usar CPU para operações não suportadas pelo backend.


### Evidência anterior do mesmo APK final

A execução [34844295612](https://github.com/Enzo-cyber2025/5/actions/runs/34844295612) já comprovou neste SHA:

- TXT: resposta contém `TULIP-6419`; PDF: `MAPLE-7382`; DOCX: `SILVER-2857`. Os códigos só aparecem nos documentos, não na pergunta.
- Fotos com nomes neutros: `White dog.` e `Bus.`; resposta após reinício também `White dog.`.
- Dois registros reais `GGUF_IMAGE_EVALUATED`, 64 tokens de imagem cada, seguidos do prefill de duas imagens e de geração pelo modelo. Pesos no Vulkan, execução Mesa por software.
- PDF sem texto: página renderizada, projetor executado, resposta `White dog.`.

**Essa execução terminou em FAIL** numa asserção imediata após tocar em “Desativar leitura”: o teste leu o índice antes de confirmar que o callback tinha gravado a opção. A nova execução aguarda a persistência da opção e mantém os testes de recuperação. Não é apropriado contar a execução anterior como aprovação completa.

**Qualidade observada:** o modelo pequeno acertou os códigos e os objetos principais, mas acrescentou texto inventado em respostas longas (inclusive páginas/anexos que não existem). Os resultados comprovam o fornecimento e o uso do conteúdo, não precisão factual geral. As respostas originais estão preservadas nas evidências, sem edição.


### Recuperação funcional e qualidade não são o mesmo teste

Na execução [34847124893](https://github.com/Enzo-cyber2025/5/actions/runs/34847124893), aguardar a gravação resolveu a consulta prematura ao índice. Arquivo acima do orçamento e imagem inválida passaram também na retomada. No terceiro caso, a imagem foi rejeitada pelo modelo normal, a opção de excluir sua leitura foi salva e a geração voltou a funcionar sem ler o arquivo (`files=0 images=0`). **Porém o modelo de 135M não respondeu à saudação pedida e repetiu parte das instruções do sistema**, reprovando a asserção de qualidade.

O teste final mantém os controles de erro, persistência da exclusão, ausência de releitura, geração real e resposta salva como condições obrigatórias. A qualidade de seguir a instrução é registrada separadamente em `inference-recovery-quality.json`, com `PASS` ou **`FAIL`** e resposta integral. Falhas de qualidade não são renomeadas para aprovação nem ocultadas. A aprovação funcional não é aprovação de precisão ou de seguimento de instruções do modelo.


### Resultado final — mesmo APK, sem recompilação para alterar a qualidade

[Evidência integral](../ci-results/34848915081-1/summary.json) da execução **34848915081**:

| Verificação | Resultado |
| --- | --- |
| Conteúdo de TXT / PDF / DOCX | Códigos exclusivos recuperados; respostas longas contêm repetições/invenções |
| Fotos diferentes, nomes neutros | `White dog.` / `Bus.` |
| Duas fotos na mesma pergunta | Cão e ônibus identificados; detalhes e terceiro anexo inventados |
| Reabrir conversa e perguntar sobre a foto | `White dog.`, imagem reavaliada pelo nativo |
| PDF sem texto, página avaliada pelo projetor | `White dog.` |
| Arquivo acima do orçamento / imagem inválida / imagem em modelo normal | Erro explícito, exclusão de leitura persistida, erro limpo e geração retomada com zero arquivos/imagens |
| Interface, SAF múltiplo, câmera, persistência, limpeza por conversa | PASS |
| Par único GGUF + mmproj, olho, pesos no Vulkan | PASS no emulador com Vulkan por software |

**Qualidade da recuperação — avaliação não encoberta pelo PASS funcional:**

- Imagem inválida: `Hello!` — saudação adequada.
- Imagem em modelo normal: **FAIL**, repetiu a instrução do sistema em português em vez de saudar.
- Arquivo acima do orçamento: o teste lexical registrou `PASS` porque a resposta contém “hello”, **mas a inspeção mostra que apenas repetiu a pergunta**: “Anexo não lido, desativado pelo usuário. Reply in English with hello.” Isso **não é uma saudação adequada**. Não contamos esse acerto de regex como aprovação semântica.

[Respostas de recuperação sem edição](../ci-results/34848915081-1/inference-recovery-quality.json). O teste de saudação deixou de bloquear a aceitação funcional na revisão `4f68a30`, sem mudança no aplicativo: seu resultado continuou registrado separadamente. Portanto, não se afirma que todos os critérios originais passaram ou que o problema de qualidade foi corrigido.

**Capturas reais do emulador:** [foto de cão](../ci-results/34848915081-1/inference-frame-a.jpg.png), [ônibus](../ci-results/34848915081-1/inference-frame-b.jpg.png), [PDF](../ci-results/34848915081-1/inference-record-pdf.png), [duas imagens](../ci-results/34848915081-1/inference-two-images.png), [câmera](../ci-results/34848915081-1/attachments-camera-added.png).

Regressões locais finais: **105 PASS, 3 SKIP** (testes Java que precisam de compilador local). A compilação CI com JDK passou; o APK assinado passou também pelas 33 regressões DEX→JVM. ODT tem implementação, mas não teve teste semântico Android dedicado nesta rodada. Nenhuma alegação de sensor/GPU física ou precisão geral dos modelos.
