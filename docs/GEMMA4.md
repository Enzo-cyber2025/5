> **Histórico:** relatório do APK anterior `f228a5…`, com certificado `9a368c…`. A nova transação obrigatória e a mudança de assinatura estão em [ATOMIC_IMPORT.md](ATOMIC_IMPORT.md).

# Gemma 4 — unificação física e assinatura preservada

**PASS funcional no APK efetivamente assinado. Gemma 4: imagem, reinício e texto sem anexos passaram. Qualidade geral de modelos pequenos não aprovada.**

## [Baixar APK diretamente — sem ZIP](https://github.com/Enzo-cyber2025/5/releases/download/gguf-gemma4-ca7d8f1/GGUF-Chat-mobile.apk)

**Publicação verificada:** [execução 34909764328](https://github.com/Enzo-cyber2025/5/actions/runs/34909764328), PASS. Assinatura criptográfica conferida novamente; a CI baixou o APK público sem autenticação e confirmou bytes idênticos ao APK testado. O tamanho e o hash do asset também foram conferidos pela API do GitHub.

## Correção

- Motor nativo atualizado para llama.cpp **v0.4.1**, commit `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`, com suporte de linguagem/visão Gemma 4 e aplicação do template Jinja. O b6500 anterior não foi presumido compatível.
- Identificação pelos metadados e tensores reais: linguagem, projetor visual e modelo visual completo são papéis distintos. Tokens de imagem ou nome `mmproj` não bastam para transformar um modelo textual em visual. Arquivos desconhecidos não são simplesmente tratados como um segundo modelo de linguagem.
- Suporte às chaves separadas `clip.vision.projector_type` e `clip.audio.projector_type` presentes no projetor Gemma 4.
- Unificação material: um arquivo GGUF contendo os tensores de linguagem e projetor. Ambos os carregadores nativos utilizam o **mesmo caminho**; não há dois arquivos escondidos atrás de um cartão.
- Adaptação da nova API `mtmd_input_text`: atribuição explícita do comprimento total em bytes UTF-8 e das duas opções booleanas. Um candidato anterior truncava o texto em um byte e foi rejeitado, não publicado.

## Par público usado, autorizado como referência

Repositório: [unsloth/gemma-4-E2B-it-GGUF](https://huggingface.co/unsloth/gemma-4-E2B-it-GGUF/tree/0314792d7f1f7e229411f620751375812bb9faf2), revisão fixa `0314792d7f1f7e229411f620751375812bb9faf2`.

| Entrada real | Tamanho em bytes | Identificação | Tensores |
|---|---:|---|---:|
| `gemma-4-E2B-it-Q3_K_S.gguf` | 2.445.652.064 | `TEXT_ONLY`, arquitetura `gemma4` | 601 |
| `mmproj-F16.gguf` | 985.654.080 | `VISION_PROJECTOR`, arquitetura `clip` | 1.411 |
| Saída unificada | **3.431.306.464** | **`VISION_SINGLE_GGUF`**, arquitetura `gemma4` | **2.012** |

Os tensores são preservados integralmente, incluindo os de áudio disponíveis. A auditoria independente compara nomes, formas, tipos e SHA-256 de cada tensor. O arquivo unificado Android também deve corresponder byte a byte ao hash esperado:

`cb17b173deb6b62c1b8a2e914ea9bbdde75ae8a9a41baef23aaff2d074056066`

Hashes das entradas:

- Linguagem: `80d155f647d3a896669b1d1605b494b97ee9dbd1dcafd27957394134c280d270`.
- Projetor: `140be8d7849741f88c50757d529b84373ee8e27052cc2236855b537f4a8215fa`.

Metadados efetivamente encontrados: encoders visual e de áudio presentes, tipos `gemma4v` e `gemma4a`, projeção visual de dimensão 1536. A [auditoria host com os pesos reais](../ci-results/34901434105-1/physical-gemma4-host.json) é separada da execução nativa Android.

Exemplos de tensores realmente auditados (dimensões na ordem do leitor GGUF, não deduzidas do nome do arquivo):

| Tensor | Dimensões |
|---|---|
| `token_embd.weight` | `[1536, 262144]` |
| `per_layer_model_proj.weight` | `[1536, 8960]` |
| `per_layer_token_embd.weight` | `[8960, 262144]` |
| `v.patch_embd.weight` | `[16, 16, 3, 768]` |
| `mm.input_projection.weight` | `[768, 1536]` |

**Este par público pode diferir dos arquivos exatos do usuário.** Não foi afirmada validação universal de qualquer quantização/projetor ou de qualquer layout multimodal externo.

## APK e assinatura

- APK compilado, sem modelos embutidos; **28.341.709 bytes**, Android 9+ (API 28), ARM64 e x86_64.
- Fonte do APK e das bibliotecas nativas: `ca7d8f129b598e46b19a23b5bc453d355d79dea3`; compilação [34903469034](https://github.com/Enzo-cyber2025/5/actions/runs/34903469034).
- SHA-256 do APK assinado: `f228a5d150348da37b365de541c99021b06fcb4eaa2713712cae816f0c10dbbc`.
- Certificado SHA-256: `9a368c9a1e4f3b3b0b6ecfb86aa3768d633a925855afba27eab3b9189177955a`.
- **Mesma chave persistente da entrega `gguf-physical-4fa8dbc`.** Não foi necessária assinatura substituta. Verificação criptográfica do APK e equivalência de todas as entradas ZIP ao APK original sem assinatura: PASS.
- Classes do APK efetivamente assinado: 6.792 traduzidas para JVM, zero erros, **39 testes PASS**; leitor/unificador físico **16 testes PASS**. Ferramentas/harness: **99 testes PASS**, incluindo seleção exata no SAF e distinção entre recortes visuais e imagens de origem. O adaptador C++ foi compilado contra os headers atuais e testado com texto UTF-8.

A atualização sobre o APK anterior foi executada de fato com `adb install -r`, mantendo um arquivo de prova nos dados privados. Isso verifica compatibilidade da assinatura e preservação desse dado de teste, não uma auditoria de toda biblioteca/conversa antiga possível. Instalações de outra linhagem de assinatura podem ser incompatíveis: **não desinstale sem antes guardar seus dados fora do app**.

## Evidência Android

A primeira rodada corrigida [34905302632, suíte Gemma 4](../ci-results/34905302632-1-gemma4/summary.json) passou: atualização mantendo dado privado, importação pelo SAF, 2.012 tensores preservados, somente um GGUF persistido, carregamento nativo visual e retomada após reinício. Respostas reais: **“Dog” / “Dog”**. Os originais foram removidos do armazenamento de teste antes da inferência.

A rodada ampliada **[34907162049](https://github.com/Enzo-cyber2025/5/actions/runs/34907162049) concluiu com sucesso**, incluindo os mesmos controles físicos e de assinatura e um teste textual independente. [Resumo completo](../ci-results/34907162049-1-gemma4/summary.json) e [auditoria Android dos 2.012 tensores](../ci-results/34907162049-1-gemma4/physical-gemma4-android-tensors.json).

| Teste Gemma 4 | Resposta real | Resultado |
|---|---|---|
| Imagem: animal principal | `Dog` | PASS |
| Mesma conversa após reiniciar, imagem preservada | `Dog` | PASS |
| Nova conversa, sem anexos: 2 + 2 | `4` | PASS |

Capturas autênticas do emulador: [GGUF físico único](../ci-results/34907162049-1-gemma4/physical-gemma4-one-file.png), [imagem](../ci-results/34907162049-1-gemma4/inference-gemma4-image.png), [reinício](../ci-results/34907162049-1-gemma4/inference-gemma4-restart.png), [texto](../ci-results/34907162049-1-gemma4/inference-gemma4-text.png).

Gemma ampliado e regressões são execuções distintas, ambas concluídas com sucesso e vinculadas ao **mesmo SHA-256 do APK assinado**, sem recompilação ou nova assinatura entre elas. A publicação verifica as duas procedências e compara o APK baixado publicamente aos bytes testados.

As [regressões do mesmo APK assinado](../ci-results/34905302632-1-regression/summary.json), execução **34905302632 concluída com sucesso**, passaram funcionalmente:

- 8 verificações de GGUF físico, importação externa independente, classificação intrínseca, prompts, reinício e exclusão isolada.
- Seleção real de fotos/arquivos pelo SAF, arquivos vazios/grandes e bytes idênticos, rascunho, vínculo à mensagem, remoção e limpeza isolada. Câmera desativada para modelo não visual; clipe continua disponível.
- Duas capturas reais pela aplicação de câmera do emulador, ambas 1392×1856, com bytes/hashes diferentes. Não são fotografias de câmera física.
- 11 verificações de conteúdo/erros: TXT `TULIP-6419`, PDF `MAPLE-7382`, DOCX `SILVER-2857`, cão, ônibus, histórico visual após reinício, duas imagens, PDF digitalizado e rejeições explícitas de excesso de contexto/imagem inválida/imagem em modelo textual.

**Qualidade das respostas, separada do PASS funcional:** o modelo pequeno acertou ORCHID no prompt global, mas continuou respondendo ORCHID depois da substituição por CEDAR (**FAIL semântico**, apesar de a nova instrução ter sido aplicada e persistida). Nas respostas de documentos repetiu trechos e instruções, além de acertar os códigos. Reconheceu cão/ônibus; isso não valida todo detalhe da descrição.

A saudação após remover uma imagem de modelo textual falhou. Após desativar o anexo excessivo, a métrica automática registrou PASS por encontrar a palavra `hello`, mas a resposta real apenas repetiu `Reply in English with hello.`: **na revisão, isso não é considerado obediência à saudação**. O resultado bruto fica preservado, sem ocultar esse falso positivo. Após remover a imagem inválida, respondeu `Hello!`.

Os testes não confundem recortes com anexos: um único arquivo de imagem pode gerar vários chunks visuais. Exigem contagem exata das imagens de origem, tokens visuais efetivamente avaliados e backend declarado; não apenas presença de biblioteca Vulkan. A seleção SAF escolhe os dois GGUFs explicitamente, sem selecionar também um XML de diagnóstico da tela Recentes.

## Como usar após instalar a atualização

1. Em **Importar → Importar .gguf**, selecione juntos o GGUF de linguagem e o projetor compatível.
2. Aguarde a conclusão. O modelo deve aparecer como visual, com o olho, e corresponder a um GGUF físico único.
3. Abra uma nova conversa com esse modelo. Use a câmera/Importar foto ou o clipe para anexar conteúdo e envie a pergunta.

Registros antigos de uma importação malsucedida não são automaticamente reinterpretados/unificados ao abrir a biblioteca. Reimporte o par; não apague indiscriminadamente modelos ou conversas antigas. A unificação precisa de espaço temporário para entradas e saída, além do arquivo definitivo. Mantenha cópias dos originais fora dos dados privados do app.

## Limitações

- Android emulado API 35, x86_64, Mesa **Vulkan por software**, não GPU física. ARM64 foi compilado, mas esta rodada não executou um aparelho ARM64.
- Gemma: 12 GiB configurados no emulador, contexto 1024, swap no host. Não é aprovação de consumo de RAM ou desempenho em aparelho real. Uma rodada ultrapassou o limite de 600 segundos após avaliar a imagem e preencher o contexto; a repetição permite 1200 segundos por resposta. Isso não é ocultado como teste de desempenho aprovado.
- Pesos de áudio preservados **não** significam interface de entrada de áudio ou transcrição testada. O escopo aqui é imagem e texto.
- A qualidade geral de modelos pequenos não é aprovada por acertos em cão/ônibus/códigos. Falhas semânticas históricas permanecem em [SIGNED_PHYSICAL.md](SIGNED_PHYSICAL.md); os resultados desta versão devem ser registrados separadamente.
- O teste externo SmolVLM de GGUF único usa empacotamento independente de pesos reais, não um download público originalmente já unificado. [Teste histórico isolado de 500M](STANDALONE_500M.md) também não substitui o teste Gemma 4.
- Anexos não suportados ou que excedem o orçamento de inferência devem causar erro explícito; importação de qualquer formato não implica interpretação de qualquer formato. Sem truncamento silencioso como solução para esses limites.
