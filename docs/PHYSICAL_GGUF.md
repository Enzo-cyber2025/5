# GGUF físico único, análise dos parâmetros e prompts de sistema

## Estado

**Revalidação do APK assinado: PASS funcional na execução 34892580054. Qualidade geral das respostas não aprovada.** Após a entrega unsigned anterior, o usuário autorizou qualquer assinatura; foi criada uma nova chave persistente, cujo backup privado foi fornecido separadamente. O Android desta rodada executou os bytes exatos do APK assinado de entrega, não uma assinatura descartável. [Relatório atual, arquivo instalável e capturas](SIGNED_PHYSICAL.md).

A nova release é `gguf-physical-4fa8dbc`. A release `gguf-inference-e37df03` é anterior e não contém estas alterações. Os resultados abaixo documentam a implementação e as rodadas históricas; os da assinatura atual estão no relatório acima.

## Unificação física

Selecionar juntos um GGUF de linguagem e seu projetor de visão compatível agora cria **um único arquivo `.gguf`** na pasta privada de modelos:

1. Leitura e validação das duas tabelas GGUF v2/v3 little-endian: metadados, tipos, dimensões, offsets, alinhamento, sobreposição e intervalo de cada tensor.
2. Identificação dos papéis pelos parâmetros e tensores; não pelo nome `mmproj`.
3. Verificação da dimensão de saída declarada do projetor contra o embedding de linguagem. Isso não garante que dois componentes quaisquer foram treinados juntos; ainda é necessário selecionar o projetor correto.
4. Reescrita de um cabeçalho, uma tabela de metadados e uma tabela de tensores. Offsets são recalculados, dados copiados em blocos de 128 KiB, sem carregar o arquivo inteiro em RAM. Não é concatenação de dois GGUFs nem ZIP disfarçado.
5. Metadados gerais de linguagem ficam no espaço principal; metadados gerais do projetor, incluindo nome/origem/licença quando presentes, ficam em `ggufchat.projector.general.*`, evitando colisões. Parâmetros `clip.*` permanecem acessíveis ao motor.
6. Uma entrada persistente, com `path == mmprojPath`: ambos os caminhos apontam ao **mesmo arquivo**, não a duas cópias. Tamanho contado uma vez.
7. Originais privados removidos somente após verificar a nova entrada persistida, preservando arquivos referenciados por outras unidades. Falha de preparação não altera os originais. O índice é substituído por rename atômico após `fsync` do arquivo; não apaga o índice anterior para tentar outro rename.

A operação exige espaço temporário para originais + resultado. A seleção atual recusa dois arquivos com o mesmo nome exibido pelo provedor: os nomes são usados para correlacionar a seleção com os novos registros, não para inferir multimodalidade. Shards precisam ser reunidos previamente. Tabelas malformadas, quantizações desconhecidas, tensores duplicados/conflitantes e dimensões incompatíveis geram erro. Há limites de segurança no leitor de cabeçalhos (128 MiB, contagens/strings/dimensões limitadas); não são cotas para anexos de conversa.

Pares legados de duas entradas/arquivos continuam legíveis como **par legado (2 arquivos)**; não são apresentados como GGUF físico único. Para convertê-los nesta revisão, reimporte a seleção dos dois originais. Encerramento forçado durante a operação ainda pode deixar arquivo de trabalho órfão; o índice não deve referenciar resultado antes de terminar a escrita. Não é uma transação conjunta entre todos os arquivos, histórico de chats e falha elétrica.

## Como o modelo é identificado

O importador analisa os bytes no worker antes de salvar o modelo. O resultado fica no campo `capability`, preservado no JSON:

| Resultado | Evidência exigida / interpretação |
| --- | --- |
| `VISION_SINGLE_GGUF` | Arquitetura/tokenizer/tensor de linguagem e parâmetros `clip.has_vision_encoder`, `clip.projector_type`, blocos de visão, tensores de encoder e projetor no mesmo GGUF |
| `VISION_PROJECTOR` | Parâmetros e pesos de visão/projeção, sem a parte de linguagem |
| `IMAGE_TOKENS_ONLY` | Tokens especiais de imagem no vocabulário, sem pesos de visão; não habilita câmera nem olho |
| `MULTIMODAL_DECLARED_INCOMPLETE` | Declarações multimodais sem o conjunto de pesos esperado |
| `MULTIMODAL_LAYOUT_UNSUPPORTED` / áudio declarado | Indícios de outra disposição/modalidade; não se finge que o motor atual sabe executá-la |
| `TEXT_ONLY` | Modelo sem o conjunto multimodal identificado |

Identificação não substitui validação completa do grafo. O carregador nativo continua verificando tensores, shapes, arquitetura e compatibilidade; erros não viram sucesso. O layout de visão integrado suportado aqui é o usado pelo `mtmd`/CLIP da revisão b6500 (`clip.*`, `v.*`, `mm.*` e variantes suportadas pelo motor). Não há promessa de executar toda arquitetura ou convenção de nomes existente.

O app abre o **mesmo arquivo** nos carregadores de linguagem e visão. O carregador de linguagem deixa somente os namespaces de mídia para o mtmd e mantém sua checagem exata de quantidade/shapes dos tensores de linguagem. Não desativa globalmente a validação de tensores. Vulkan continua explícito para linguagem/projetor, sem retry silencioso da unidade em CPU. O scheduler ainda pode executar operações não suportadas em CPU.

Um GGUF válido como arquivo não implica compatibilidade universal com outros aplicativos. A execução integrada requer um motor que saiba lidar com os dois conjuntos de pesos; esta revisão adapta o b6500 para isso.

## GGUF único vindo de fora

Um arquivo completo com o layout suportado pode ser importado sozinho. Nenhum nome especial, segundo arquivo ou marcador privado `ggufchat.*` é exigido para a detecção.

**Pesquisa pública:** não foi encontrado um exemplo público verificável, pronto para download em um único GGUF completo, entre os exemplos examinados. Os cartões/comandos de LLaVA [2](https://huggingface.co/MoMonir/llava-llama-3-8b-v1_1-GGUF) e Moondream [3](https://huggingface.co/vikhyatk/moondream2/discussions/12) pedem modelo + mmproj separados. A listagem [bitsoko/moondream1-GGUF](https://huggingface.co/api/models/bitsoko/moondream1-GGUF) consultada continha apenas `.gitattributes`, não um modelo para testar. “Uma quantização .gguf” ou um pacote de modelo não comprova encoder/projetor embutidos.

Por isso, o teste de importação externa usa **um arquivo escrito independentemente pelo GGUFWriter upstream**, fora do app, com pesos reais SmolVLM-256M + projetor e nome neutro. Não se apresenta essa fixture como um modelo público encontrado pronto/unificado. Ela comprova que o app aceita o layout completo sem depender de metadados privados do próprio unificador.

## Prompts de sistema

- **Padrão global:** botão “Prompt de sistema global” na tela principal.
- **Por conversa:** chave de ferramentas → “Sistema”. Substitui o padrão global daquela conversa.
- Edição livre, presets de assistente em português, programação e análise de documentos.
- “Usar padrão global” remove a substituição da conversa; “Restaurar padrão” restaura o global.
- Cancelar não salva. Campo vazio salvo é uma instrução vazia explícita, diferente de herdar o global.
- `systemPrompt` viaja no JSON do chat, inclusive ao reabrir. O global usa preferências privadas.
- A instrução entra no papel **system** antes da aplicação do template nativo, não como mensagem de usuário. Acréscimos de busca/pensamento e instruções de tratamento de anexos são preservados.
- Máximo explícito de 32.768 caracteres e limite de contexto do modelo; sem corte automático. Edição por conversa bloqueada durante carregamento/geração. Logs de diagnóstico registram tamanho/escopo/hash, não o texto personalizado.

Configurar uma instrução não garante que um modelo pequeno consiga segui-la. Respostas reais e falhas semânticas ficam registradas separadamente da verificação de persistência/encaminhamento.

## Evidências já obtidas

Execução [34870246962](https://github.com/Enzo-cyber2025/5/actions/runs/34870246962), revisão `fbc2441`, **resultado global FAIL**:

- Compilação ARM64 + x86_64 e **122 testes de ferramentas/Java PASS**.
- Seleção SAF real → um arquivo privado, persistência após reinício, **471 tensores comparados por nome, shape, tipo e SHA-256 com os originais: PASS**.
- Carregamento de linguagem/projetor do mesmo arquivo em Vulkan por software; imagem → `Dog.`: PASS.
- GGUF único do escritor independente, importado sozinho, imagem → `Bus.`: PASS.
- Modelo normal renomeado para conter `mmproj`: classificado corretamente por parâmetros como `TEXT_ONLY`, sem olho.
- **Falha restante daquela execução:** um filtro antigo de nome no seletor de conversa ainda escondia esse modelo normal. Corrigido na revisão seguinte; os testes de prompts não tinham sido alcançados. Essa execução não é aprovação completa.

[Auditoria dos 471 tensores](../ci-results/34870246962-1/physical-tensor-proof.json) · [Resumo original](../ci-results/34870246962-1/summary.json).

Rodada anterior com assinatura descartável: [34871626419 — PASS funcional](https://github.com/Enzo-cyber2025/5/actions/runs/34871626419). O APK mudou após a evidência anterior e foi novamente compilado e testado. Resultados abaixo.


### Regressões da compilação original

Revisão `4fa8dbca578a70df91798c3b80b24d66f6c485f0`, APK sem assinatura **21.724.952 bytes**, SHA-256 `93ddb8a94c35bebce45db4c0bfcc2517895f4573701c363c30f402427151111c`:

- 122 testes de ferramentas/Java passaram na CI com JDK.
- APK real traduzido DEX→JVM: **6.792 classes, zero erros de tradução, 39 regressões PASS**, incluindo roundtrip de `systemPrompt` (null, vazio, literal “null”, português), capacidade multimodal/caminho único e preservação do índice após falha de rename.
- **14 verificações PASS** do leitor/unificador a partir desse APK traduzido: nomes enganosos, parâmetros, tokens sem pesos, arquivo completo, tensores preservados, offsets, truncamento e entradas incompatíveis. A suíte inclui uma verificação estrutural do adaptador nativo; não substitui o teste de inferência Android.
- Os mesmos 39 + 14 testes passaram também localmente. O primeiro ensaio JVM do candidato anterior encontrou limitações dos doubles Android/JSON e do tradutor com método estático de interface; a serialização foi isolada da UI, o double JSON ganhou os métodos padrão e o comparador passou a ser explícito. Não se tratou esses erros de infraestrutura como sucesso.


## Resultado Android anterior (assinatura descartável)

Todas as oito verificações funcionais de unificação/parâmetros/prompts passaram, além das regressões de câmera/SAF/anexos e leitura real de documentos/imagens:

- **Um arquivo privado de 278.824.896 bytes**, com 471 tensores de linguagem + visão. Comparação independente de todos os nomes, shapes, tipos e hashes dos tensores com os dois originais: PASS.
- SHA-256 do GGUF unificado do teste: `6ba9ca75ac0a80adcc380220252ef1d016153149521b815079710ede777ab4e9`.
- Persistência, linguagem e projetor carregados do mesmo arquivo, inferência visual em Vulkan por software: PASS.
- Arquivo único escrito pelo GGUFWriter upstream, importado sozinho e usado para reconhecer ônibus: PASS. Não foi um segundo arquivo baixado/associado automaticamente.
- Nome enganoso contendo `mmproj` não transforma o modelo de texto em projetor e não o esconde mais no seletor: PASS.
- Prompt global, substituição por conversa, JSON, reinício, aplicação na geração e restauração dos padrões: PASS funcional.
- Exclusão isolada do arquivo unificado: PASS.

**Falha de qualidade do prompt por conversa:** o global continha `ORCHID-5291` e o modelo respondeu esse código corretamente. Depois da edição, o chat persistido continha `CEDAR-8624`, e o log de aplicação registrou seu hash correto (`086cf2cc980f019efb196aec6faefbb4a1a41be4f9c524be677bd2438b62219b`). Mesmo assim, o modelo de 135M repetiu `ORCHID-5291`, presente no histórico anterior. **Resultado semântico FAIL**, preservado no relatório; não foi “corrigido” apagando o histórico nem falsificando a resposta. Prompts são encaminhados ao modelo, não uma garantia de obediência dele.

Continuam as limitações de qualidade vistas antes: documentos com códigos corretos acompanhados de texto inventado, detalhes/anexo inexistente na resposta de duas imagens, saudação incorreta e falso positivo lexical por repetir a pergunta. Veja respostas integrais, não apenas o status agregado.

[Resumo completo](../ci-results/34871626419-1/summary.json) · [471 tensores](../ci-results/34871626419-1/physical-tensor-proof.json) · [Respostas aos prompts](../ci-results/34871626419-1/system-response-quality.json) · [Chat com a instrução persistida](../ci-results/34871626419-1/inference-system-chat-chat.json).

**Capturas reais:** [um GGUF na biblioteca](../ci-results/34871626419-1/physical-one-file.png), [modelo normal sem olho](../ci-results/34871626419-1/physical-normal-no-eye.png), [prompt da conversa](../ci-results/34871626419-1/system-chat-editor.png), [prompt global](../ci-results/34871626419-1/system-global-editor.png), [visão com arquivo único externo](../ci-results/34871626419-1/inference-external-single-file.png).

## Entrega anterior sem assinatura (histórico)

A entrega anterior foi `.delivery/GGUF-Chat-mobile-unsigned.apk`, sem assinatura e não instalável. Naquela etapa o usuário havia escolhido aguardar a chave anterior, e não foi criada outra chave fixa.

A cópia testada apenas no emulador tinha SHA-256 `09c48dba831f613554a1bb101bc62bf41c346d748c61a7cb59c7f6e2a741b1ca`; não era o arquivo unsigned entregue. **Essa pendência foi superada pela autorização posterior de uma nova assinatura**, seguida da execução completa 34892580054 nos bytes assinados de entrega. Não confunda esses hashes/rodadas. A nova chave não permite atualizar por cima de um APK com certificado diferente. [Entrega assinada atual](SIGNED_PHYSICAL.md).
