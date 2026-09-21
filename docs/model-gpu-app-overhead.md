# Modelo na GPU; host sem cópias de histórico desnecessárias

## Política

Em modo Vulkan, qualquer pedido de GPU usa todas as camadas (`INT_MAX`), todos
os pesos recebem override para o buffer do dispositivo Vulkan selecionado e o
projetor usa esse mesmo dispositivo. Não há retomada automática em CPU.

A alteração `81bc70c` acrescenta recusa de carregamento parcial ou sem confirmação:
o número de camadas carregadas deve ser positivo e igual ao total informado pelo
carregador. Isso ocorre antes da criação do contexto. O novo registro é
`GGUF_MODEL_ALL_LAYERS`. Esse registro **não substitui** a proteção real do grafo:
o scheduler verifica todos os splits antes de submeter qualquer um, e o despacho
direto também recusa operações tensorais fora do dispositivo selecionado.
Metadados/view/reshape/permute/transpose não executam cálculo de tensor.

Interface, arquivos, tokenização, preparação de imagens, controles e transferências
podem usar CPU. CPU escolhida explicitamente continua sendo um modo distinto;
não é fallback. Vulkan por software no emulador continua executando sobre a CPU
do servidor: não certifica uso ou velocidade de uma GPU física do usuário.
Um modelo/operação incompatível com Vulkan deve falhar claramente, não trocar
precisão, parâmetros, conteúdo ou backend para completar a resposta.

## Menos cópias no caminho comum do app

`AttachmentInference.prepare` criava um StringBuilder vazio e concatenava seu
resultado a cada mensagem, inclusive respostas longas sem anexos. Agora o builder
é criado somente ao encontrar um anexo daquela mensagem. Sem prefixo, o texto
imutável já existente é reaproveitado. A lista intermediária também recebe a
capacidade correta antecipadamente. Limpeza de marcadores, ordem, anexos
excluídos, conteúdo e renderização do prompt são preservados.

É uma redução de alocações/cópias, não uma medição de MB economizados no app
inteiro nem uma alegação de ganho de tokens/s.

## Teste anterior e correção do método

A execução `35245429844` terminou em FAIL por timeout na primeira imagem do
baseline. Nenhuma comparação do candidato foi concluída. O harness exigia
`content == prompt`; o APK real grava
`Arquivo anexado: N arquivo(s)\n\nAnexos vinculados a esta mensagem para leitura.\n\nPROMPT`.
Isso foi conferido nas instruções DEX do APK 323, não apenas presumido.

Agora o texto persistido esperado é composto exatamente a partir da quantidade
de anexos pendentes, mantendo a verificação exata do texto digitado e sem relaxar
para substring. Logs e chats também são salvos ao expirar o prazo. A duração
limite de visão é 1200 s por resposta, sem diminuir fotos ou orçamento de tokens.
A ausência de logs finais antigos impede afirmar retrospectivamente que o modelo
terminou: o defeito no harness não converte aquele FAIL em PASS.

## Execução concluída

Fonte **81bc70c**, CI **35252559185**, job **105308188440**: SUCCESS em
2026-09-17 às 19:04:37 UTC. APK experimental
`2b444a73090dff9bd6d4ce6d199349cafd5e9ae73b83cc34e05101e7f77727cc`.

Passaram texto ON/OFF com 128 tokens, carregamento completo, auditoria de grafos,
Copy/streaming/histórico, decoder Android, imagem real e avisos/limpeza após sono.
A verificação separada recalculou **10 hits** do cache no projetor Vulkan e
comparou seus embeddings byte a byte. Cinco screenshots reais foram revisados.
A fixture de código declara corretamente que seus dados são sintéticos de UI,
não código produzido pelo modelo. O pós-check local comparou o histórico bruto
completo dos **10 pares**, inclusive espaços, e recalculou as taxas nativas.

Host CI: **30 passaram, 3 pulados**. A suíte local naquele momento tinha 192
passados e 70 pulados. O teste adicional de pós-análise foi executado localmente,
não atribuído ao job mais antigo. O ggml real também foi compilado localmente:
`REAL_GGML_CPU_TENSOR_DISPATCH_BLOCKED_BEFORE_MATH_PASS`.

### Observações de imagens (uma amostra por célula)

Tempo nativo até o primeiro token, **não latência visual completa durante sono**:

| Etapa | ON antes → depois | OFF antes → depois | Encodes antes → depois |
|---|---:|---:|---:|
| Primeira imagem A | 216,90 → 197,70 s | 184,57 → 182,74 s | 5 → 5 |
| Acrescentar B, mantendo A | 398,62 → 222,34 s | 362,85 → 204,77 s | 10 → 5 |
| Desativar A, manter B | 205,84 → 34,33 s | 191,10 → 31,46 s | 5 → 0 |
| Reativar A | 399,87 → 57,06 s | 365,65 → 50,70 s | 10 → 0 |

O benefício confirmado é evitar recodificações em imagens ainda presentes no
cache. **Não é um encoder mais rápido para imagem inédita**; a primeira imagem
continua exigindo cinco encodes. Não multiplicar esses resultados pelos de outros
runners/rodadas nem interpretá-los como 7× na geração de tokens do app inteiro.

### Texto e limites metodológicos

Uma observação por estado/versão, sem warmup e ordem fixa:
ON 2,09012 → 3,53865 tokens/s; OFF 4,27489 → 4,25574 tokens/s.
O primeiro texto ON do controle esperou 24,265 s até a UI; o candidato, 4,140 s.
Esse primeiro controle foi frio e inclui inicialização: **não atribuir a queda
24→4 às otimizações**. Não há significância estatística ou repetibilidade
certificada. ON continua abaixo de OFF; os ganhos 21×/26× não foram comprovados.

Esses resultados são anteriores à reorganização RGB experimental da fonte
5e66e0f. Não são evidência de velocidade dessa outra alteração.

Evidências: `ci-results/35252559185-1`,
`.delivery/projector-cache-investigation.json` e
`.delivery/projector-raw-response-check.json`. Ambos os testes terminaram, sem
necessidade de tratar um monitor interrompido como aprovação. O APK entregue
323 não foi substituído; nenhum candidato tem aprovação universal/de release.
