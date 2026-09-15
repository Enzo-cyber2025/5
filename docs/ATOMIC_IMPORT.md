# Importação obrigatoriamente unificada — GGUF Chat

**APROVADO nos testes funcionais Android do próprio APK assinado.**

## [Baixar APK — sem ZIP](https://github.com/Enzo-cyber2025/5/releases/download/gguf-atomic-5cf14ef/GGUF-Chat-mobile.apk)

**Atenção: nova assinatura autorizada. Não atualiza por cima da assinatura anterior. Guarde seus dados fora do app antes de desinstalar qualquer versão.**

## A regra agora é uma transação, não uma tentativa posterior

Ao selecionar **exatamente dois arquivos juntos** no importador de modelos:

1. O app copia os conteúdos para uma pasta temporária privada. **Não adiciona os dois componentes à biblioteca.**
2. Lê os metadados e os tensores de ambos. Exige um componente de linguagem e um projetor visual compatível, em qualquer ordem. Nomes/extensões não decidem o papel.
3. Gera um GGUF físico com uma única tabela de metadados, uma única tabela de tensores e os pesos de ambos.
4. Reabre a saída e compara **todos os nomes, dimensões, tipos e bytes dos tensores** com as entradas. Dimensões de projeção ausentes/incompatíveis, conflitos, truncamentos e estruturas não suportadas causam rejeição.
5. Abre o arquivo no **motor nativo real**, como linguagem e projetor no mesmo caminho. Essa validação de carregamento usa CPU e contexto 512 explicitamente, antes da publicação. O motor exige suporte visual do projetor carregado.
6. Remove as cópias temporárias dos componentes e publica **um único registro e um único arquivo GGUF** na biblioteca, usando gravação atômica do índice.

**Sucesso não pode significar dois arquivos escondidos num cartão.** Se o par não puder ser validado, a operação é recusada com mensagem visível; não é tratada como duas importações bem-sucedidas. Arquivos do provedor são somente lidos: os originais do usuário não são apagados nem modificados. Modelos e conversas existentes não são substituídos pela transação.

Dois modelos de linguagem, dois projetores ou arquivos incompatíveis **não podem ser transformados arbitrariamente em um modelo funcional**. A garantia é: **um GGUF validado ou rejeição explícita**, não aceitar qualquer combinação. Falta de espaço ou memória também pode impedir a validação; isso não é apresentado como sucesso.

O app mantém uma pasta temporária identificada por transação para recuperação após interrupção. Na próxima leitura da biblioteca, saídas não publicadas são descartadas e saídas já referenciadas pelo índice são preservadas. Os testes host cobrem essa recuperação e falha de gravação; isso não é uma homologação de todas as falhas físicas de armazenamento possíveis.

## Reconhecimento de um arquivo importado sozinho

- **GGUF com linguagem + visão no layout suportado:** reconhecido como `VISION_SINGLE_GGUF`; linguagem e projetor apontam para o mesmo arquivo; câmera/olho habilitados. Passa também pelo carregamento nativo antes de ser cadastrado.
- **Modelo somente de linguagem:** reconhecido como não visual, sem olho e com câmera desativada. Ter `mmproj`, `vision` ou `multimodal` no nome não muda isso.
- **Vocabulário contendo tokens de imagem, sem pesos visuais:** não é promovido a modelo visual.
- **Declaração multimodal incompleta, layout não suportado ou estrutura desconhecida:** recebe diagnóstico específico, não uma afirmação falsa de que é um modelo textual válido.

Parâmetros de áudio presentes são preservados, mas esta entrega não afirma suporte de interface/transcrição de áudio. O reconhecimento visual não significa suporte universal a todos os layouts multimodais já existentes.

Pares legados de versões antigas continuam explicitamente identificados como **dois arquivos legados**, não como um GGUF único; não são apagados ou convertidos silenciosamente junto de conversas existentes. Para aplicar a nova garantia ao par antigo, reimporte os dois originais juntos. Importar mais de dois arquivos não é uma solicitação de fusão arbitrária de todos eles; a transação descrita aqui corresponde à seleção de exatamente dois componentes.

## APK e assinatura

- Fonte compilada: `5cf14efd2bfecdfb8c1d5a026d231d9711a5fcaa`.
- llama.cpp v0.4.1: `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`.
- APK: **28.341.710 bytes**, Android 9+ (API 28), ARM64 e x86_64; sem modelos embutidos.
- SHA-256: `5f7247a5ffe663a583ccf46adf161f2e8f27e64780f3aa3a39f070c8259bd840`.
- Certificado novo: `9b658c30f602e0f2ff65c176423cb95bea8fbdeb660c306ab908862f90d9bc3c`.

**Foi necessária uma nova assinatura, usando a alternativa expressamente autorizada.** A chave privada anterior e seu backup não estavam disponíveis no ambiente restaurado; o certificado público do APK anterior não permite recuperar a chave. A nova chave foi criada e guardada localmente com backup, sem envio de material privado ao Git ou à CI.

**Este APK não atualiza por cima da instalação assinada com o certificado anterior `9a368c…`.** Salve conversas, anexos e modelos **fora do app antes de qualquer desinstalação**. Desinstalar apaga os dados privados. Não confunda backup do APK/chave com backup dos dados do usuário.

## Validação

- Compilação de ambas as ABIs, testes Java da transação e regressões host na CI: concluídos antes de assinar.
- Próprio APK assinado convertido de DEX para JVM: **6.794 classes, zero erros; 39 testes PASS**.
- Leitor/unificador do próprio APK: **16 testes PASS**.
- Verificações adicionais nas classes do APK: papéis intrínsecos de linguagem/projetor/arquivo completo, detecção de corrupção de um byte em tensor e estrutura desconhecida não classificada como texto: PASS. Esses testes adicionais usam fixtures estruturais sintéticas, não inferência nativa simulada apresentada como real.
- Android do APK assinado: **PASS** nas duas suítes abaixo.

### Resultados reais e evidências

| Caso | Resultado |
|---|---|
| Gemma 4: par pelo SAF → um arquivo; validação nativa antes de publicar | PASS |
| Todos os 2.012 tensores preservados, hash do GGUF e reinício | PASS |
| Gemma: imagem / imagem após reinício / texto 2 + 2 | `Dog` / `Dog` / `4` |
| GGUF visual externo já completo, criado independentemente com pesos reais | PASS; reconhecido como visual e respondeu `Bus` |
| Modelo textual com nome de arquivo enganoso contendo mmproj/vision | PASS; sem olho e câmera desativada |
| Dois modelos de linguagem reais juntos | Recusados; zero novos registros/arquivos |
| Dois projetores reais juntos | Recusados; zero novos registros/arquivos |
| Segundo arquivo truncado | Recusado; zero novos registros/arquivos |
| Par sintético estruturalmente combinável, mas inválido para o motor | Motor real recusou; zero novos registros/arquivos |
| Biblioteca/conversas preexistentes, originais e reinício após as quatro rejeições | PASS; preservados |
| Tentativa de atualização com certificado novo sobre o anterior | Android bloqueou; dado privado anterior permaneceu intacto |

**Gemma:** [execução 34963510685 concluída com sucesso](https://github.com/Enzo-cyber2025/5/actions/runs/34963510685), [resumo](../ci-results/34963510685-1-gemma4/summary.json), [auditoria de tensores](../ci-results/34963510685-1-gemma4/physical-gemma4-android-tensors.json), [modelo único](../ci-results/34963510685-1-gemma4/physical-gemma4-model.json).

**Regressões e rejeições:** [job 104361865696 concluído com sucesso](https://github.com/Enzo-cyber2025/5/actions/runs/34963331799/job/104361865696), [resumo](../ci-results/34963331799-1-regression/summary.json). Essa execução também continha uma suíte Gemma que falhou porque a checagem da assinatura lia só stdout do ADB. A checagem foi corrigida para ler stderr e o código de saída, e Gemma passou na execução separada acima. Não se apresenta a execução inteira anterior como sucesso: a aprovação vincula cada **job aprovado** ao mesmo SHA-256 do APK, sem recompilar ou reassinar entre eles.

Capturas autênticas: [visual completo e textual na biblioteca](../ci-results/34963331799-1-regression/physical-normal-no-eye.png), [GGUF externo respondendo](../ci-results/34963331799-1-regression/inference-external-single-file.png), [recusa de dois modelos textuais](../ci-results/34963331799-1-regression/physical-atomic-two_real_language_models.png), [recusa pelo motor](../ci-results/34963331799-1-regression/physical-atomic-native_loader_rejects_structurally_mergeable_fake_weights.png), [Gemma com imagem](../ci-results/34963510685-1-gemma4/inference-gemma4-image.png), [Gemma sem imagem](../ci-results/34963510685-1-gemma4/inference-gemma4-text.png).

Também passaram leitura de TXT/PDF/DOCX, duas imagens, PDF digitalizado, histórico de imagens, erros explícitos, duas capturas pela câmera do emulador, anexos múltiplos e limpeza/persistência. Esses acertos funcionais não apagam as limitações de qualidade abaixo.

O par Gemma de referência é o autorizado anteriormente: Unsloth `gemma-4-E2B-it-Q3_K_S.gguf` + `mmproj-F16.gguf`, revisão `0314792d7f1f7e229411f620751375812bb9faf2`. Linguagem **601 tensores** + projetor **1.411** → saída **2.012 tensores / 3.431.306.464 bytes**. Pode diferir dos arquivos exatos do usuário.

## Limites e qualidade

**Qualidade geral de respostas não é garantida pela validação estrutural ou pelo carregamento.** O teste de inferência real comprova os casos executados, não qualquer resposta de qualquer modelo. Resultados semânticos e erros dos modelos pequenos devem ser mantidos separados das verificações funcionais.

Nesta versão, o modelo pequeno respondeu ORCHID corretamente, mas repetiu ORCHID após receber CEDAR como novo prompt de sistema: **FAIL semântico**, embora a nova instrução tenha sido aplicada e persistida. Nas respostas de documentos acertou os códigos, mas repetiu trechos e instruções. Uma saudação falhou; outra métrica marcou PASS por encontrar `hello` dentro de uma instrução repetida, mas a revisão não considera isso obediência. Os relatórios brutos foram mantidos. Detalhes da descrição de duas imagens não são aprovados apenas por conter cão e ônibus.

Os testes Android usam emulador x86_64 e Mesa Vulkan por software. Gemma usa 12 GiB configurados no emulador e swap no host; ARM64 foi compilado. Não há aprovação de GPU física, desempenho ou memória de um aparelho real. A validação de importação usa CPU de forma deliberada; a geração continua respeitando a escolha explícita de CPU/Vulkan, sem fallback silencioso.
