# APK assinado — GGUF físico único, identificação e leitura real

**Estado: APK assinado e instalável; aceitação Android PASS funcional em 26min55s. Qualidade geral das respostas NÃO aprovada.**

O usuário autorizou uma nova assinatura. Foi criada uma chave persistente local; seu backup privado foi fornecido separadamente e não foi publicado no GitHub. Não é a chave descartável dos testes anteriores.

## [Baixar o APK diretamente — sem ZIP](https://github.com/Enzo-cyber2025/5/releases/download/gguf-physical-4fa8dbc/GGUF-Chat-mobile.apk)

Publicação [34895580156 — PASS](https://github.com/Enzo-cyber2025/5/actions/runs/34895580156): download público sem autenticação comparado byte a byte com o APK testado; tamanho e digest do asset GitHub conferidos. [Comprovante](../ci-results/34895580156-1/publication.json).

## Arquivo e instalação

- APK standalone: `.delivery/GGUF-Chat-mobile.apk`, **21.730.287 bytes**; não é ZIP de distribuição.
- Android 9+ (API 28), ARM64 e x86_64. Modelos não incluídos.
- Fonte compilada: `4fa8dbca578a70df91798c3b80b24d66f6c485f0`.
- SHA-256 do APK: `4d1697c2ee9b80ba38a03ee78ab0241dc8aa3d5464c956707e2412be70b11ce6`.
- SHA-256 do certificado: `9a368c9a1e4f3b3b0b6ecfb86aa3768d633a925855afba27eab3b9189177955a`.
- RSA 3072; verificação apksigner PASS com assinatura v3. Não se afirma verificação v2.
- Todas as entradas internas do ZIP são byte a byte idênticas ao APK unsigned `93ddb8a94c35bebce45db4c0bfcc2517895f4573701c363c30f402427151111c`. A assinatura não recompilou nem substituiu o código.

**A assinatura mudou em relação à release anterior.** Não instala como atualização sobre um APK com outro certificado. **Salve conversas, anexos e originais dos modelos fora do app antes de desinstalar a versão anterior.** A desinstalação apaga os dados privados do aplicativo. O backup da chave de assinatura não contém esses dados. Guarde esse backup para futuras versões com a mesma assinatura.

## Escopo da revalidação

A execução concluída [34892580054](https://github.com/Enzo-cyber2025/5/actions/runs/34892580054) instala e exercita **os mesmos bytes assinados destinados à entrega**, sem reassiná-los para o emulador. Testou, nesta ordem:

1. Seleção SAF de linguagem + projetor reais; unificação em um único GGUF físico; auditoria independente de todos os 471 tensores; reinício e exclusão isolada.
2. Linguagem e projetor carregados do mesmo caminho; inferência visual; importação de um GGUF único escrito fora do app; identificação por parâmetros mesmo com nome enganoso.
3. Prompts globais e por conversa: interface, cancelar/restaurar, persistência JSON, reinício e aplicação efetiva na geração. Qualidade semântica avaliada separadamente.
4. Fotos múltiplas no gerenciador, duas capturas pela câmera do emulador, anexos mistos/vazios/grandes, persistência e remoção; câmera desativada para modelo sem visão e clipe preservado.
5. Conteúdo real de TXT/PDF/DOCX, fotos de cão/ônibus, duas imagens, PDF digitalizado, reinício, excesso de contexto e formatos/imagens inválidos com erros explícitos.

Localmente, o APK assinado passou em **39 regressões DEX→JVM** (6.792 classes, zero erros de tradução) e **14 verificações do leitor/unificador extraído do APK**. A suíte de fontes desta rodada teve 106 PASS e 16 skips por requisitos de ambiente; a compilação original tinha 122 PASS na CI com JDK. Nenhum skip é contado como PASS. A primeira tentativa local precisou restaurar o APK original de referência ausente; os dois erros por arquivo ausente desapareceram após o download com hash verificado.

## Resultados conferidos no APK assinado

**Todas as oito verificações de GGUF físico/parâmetros/prompts passaram**, assim como as regressões de anexos e conteúdo. A conclusão da execução foi conferida diretamente na API do GitHub, além do observador local.

| Verificação | Resultado real |
| --- | --- |
| Linguagem + projetor importados juntos | Um GGUF privado de **278.824.896 bytes**, 273 + 198 = **471 tensores**; todos os nomes, shapes, tipos e hashes preservados |
| GGUF unificado, linguagem e projetor no mesmo arquivo | Imagem → `Dog.`; persistência após reinício e exclusão isolada PASS |
| GGUF único de escritor independente, importado sozinho | Imagem → `Bus.`; `VISION_SINGLE_GGUF`, mesmo `path` e `mmprojPath` |
| Modelo de texto com `mmproj` no nome | `TEXT_ONLY`, sem olho, câmera desativada, ainda selecionável para conversar |
| TXT / PDF / DOCX | Códigos corretos `TULIP-6419` / `MAPLE-7382` / `SILVER-2857`, com texto adicional inadequado nas respostas |
| Fotos / reinício / PDF digitalizado | `White dog.` e `Bus.` nos testes correspondentes |
| Câmera e anexos | Duas capturas diferentes 1392×1856, fotos múltiplas, armazenamento byte-exato, persistência, remoção e associação à mensagem PASS |
| Prompts | Edição, cancelar/restaurar, JSON, reinício e aplicação na geração PASS; obediência semântica por conversa FAIL |

SHA-256 do GGUF físico produzido: `6ba9ca75ac0a80adcc380220252ef1d016153149521b815079710ede777ab4e9`.

### Qualidade: falhas preservadas, não escondidas pelo PASS funcional

- **Prompt por conversa FAIL:** após o global `ORCHID-5291`, foi salvo e aplicado `CEDAR-8624` no papel system. O log registra o hash correto `086cf2cc980f019efb196aec6faefbb4a1a41be4f9c524be677bd2438b62219b`. Mesmo assim, o modelo de 135M respondeu novamente `The reference code is "ORCHID-5291".`. O histórico não foi apagado para fabricar sucesso.
- **PDF:** o código correto foi seguido de uma “Página 2” e conteúdo inventados. DOCX/TXT também tiveram acréscimos ou repetição das instruções. O teste comprova chegada do conteúdo, não fidelidade total da resposta.
- **Duas imagens:** reconheceu cão/ônibus, mas inventou detalhes e um terceiro `frame-c.jpg` inexistente.
- **Recuperação:** desativar a leitura permitiu gerar novamente. A saudação após rejeitar imagem no modelo normal falhou; após excesso de conteúdo, o teste lexical marcou PASS porque a resposta repetiu `Reply in English with hello.` — isso **não é uma saudação correta**. Após imagem quebrada respondeu `Hello!`.

[Resumo integral](../ci-results/34892580054-1/summary.json) · [Auditoria de todos os 471 tensores](../ci-results/34892580054-1/physical-tensor-proof.json) · [Proveniência assinada](../ci-results/34892580054-1/physical-signed-provenance.json) · [Qualidade dos prompts](../ci-results/34892580054-1/system-response-quality.json) · [Qualidade da recuperação](../ci-results/34892580054-1/inference-recovery-quality.json).

**Capturas reais desta rodada:** [GGUF único na biblioteca](../ci-results/34892580054-1/physical-one-file.png), [prompt editado](../ci-results/34892580054-1/system-chat-editor.png), [PDF e resposta completa](../ci-results/34892580054-1/inference-record-pdf.png), [anexos após câmera](../ci-results/34892580054-1/attachments-camera-added.png), [inferência do GGUF externo](../ci-results/34892580054-1/inference-external-single-file.png).

## Limites que continuam valendo

- Android, câmera e **Vulkan por software (Mesa) no emulador**. Não é validação de GPU/câmera física; o scheduler pode executar operações não suportadas em CPU. Não há retry silencioso da unidade inteira em CPU.
- GGUF v2/v3 little-endian, layout CLIP/mtmd suportado no b6500. Nem toda arquitetura/modalidade é suportada. Tokens de imagem sozinhos não habilitam visão; o grafo nativo ainda é validado ao carregar.
- O arquivo externo de teste foi gerado pelo GGUFWriter upstream com pesos reais SmolVLM-256M + projetor. **Não foi encontrado um download público já unificado verificável** entre os exemplos pesquisados; não se apresenta a fixture como um desses downloads.
- Unificação exige espaço para originais + resultado. Pares legados continuam com dois arquivos até reimportar; não são renomeados como um GGUF físico único.
- Armazenamento de anexos sem cota artificial de tipo/tamanho/quantidade, sujeito ao provedor, Android e disco. Isso não significa que todo binário possa ser interpretado.
- Leitura: até 131.072 caracteres, imagens preparadas a 8 MP e reduzidas até 1.024px no maior lado, contexto de 8.192 tokens; falhas explícitas em vez de truncamento silencioso. Áudio/vídeo, arquivos compactados genéricos, planilhas, apresentações e Office antigo não têm interpretação nesta etapa.
- Modelos pequenos podem inventar conteúdo e desobedecer instruções apesar de receberem corretamente documentos e prompts. PASS funcional não é aprovação geral da qualidade.

Detalhes de implementação e resultados anteriores: `docs/PHYSICAL_GGUF.md`. A release anterior `gguf-inference-e37df03` permanece histórica e não contém unificação física nem prompts editáveis.

## Ocorrências de infraestrutura da publicação

A primeira publicação (34895466180) foi bloqueada com HTTP 403 ao criar a release apontando ao commit antigo de compilação. O publicador passou a marcar o commit atual de publicação; fonte compilada, hash do APK, assinatura e teste aceito continuaram fixados e inalterados. A nova execução 34895580156 publicou e verificou o download com sucesso.

Um fluxo legado de reparo (34895466148), disparado pelo commit de documentação sem o marcador de entrega, falhou na preparação `android-actions/setup-android@v3`, antes de recompilar. Ele não forneceu nem substituiu este APK. Os commits seguintes usam `[apk delivery]` e dispensam esse fluxo legado; a aceitação válida é a execução assinada 34892580054.

## Teste posterior de outro modelo, sem projetor externo

O mesmo APK passou no teste isolado [34896578127](https://github.com/Enzo-cyber2025/5/actions/runs/34896578127) com SmolVLM-500M em um único GGUF completo preparado fora do app. Android limpo, 489 tensores, nenhum par importado, nenhuma dependência de mmproj separado: cão, ônibus, reinício e texto passaram. Não é um download originalmente distribuído unificado; não altera as falhas semânticas dos modelos/testes anteriores. [Relatório e capturas](STANDALONE_500M.md).
