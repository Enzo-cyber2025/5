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

## Execução atual

- Fonte de produção/harness: `81bc70c8c1025fb8d46f7d99a8f9ee63af95b711`.
- CI: `35252559185`, job `105308188440`, em andamento.
- Inclui texto de 128 tokens ON/OFF, renderização/Copy/histórico, decoder Android,
  imagens antes/depois, verificação byte a byte dos embeddings em execução separada,
  carregamento completo de camadas e auditoria dos grafos Vulkan.
- Local: 192 passaram, 70 pulados. O teste Java de identidade/bytes depende do
  compilador do CI. O teste adicional de pós-análise foi adicionado depois do disparo.
- O ggml real foi compilado localmente e o teste de despacho direto/scheduler
  produziu `REAL_GGML_CPU_TENSOR_DISPATCH_BLOCKED_BEFORE_MATH_PASS`. Os bytes de
  saída sentinela permaneceram intocados quando o backend CPU foi recusado;
  CPU explícita voltou a calcular corretamente após sair do escopo.
  Esse teste NÃO executa um modelo numa GPU física.
- `ci/evaluate_projector_app.py` exige sucesso do experimento, arquivos completos,
  contadores consistentes e histórico bruto exatamente igual, inclusive whitespace.
  Não basta comparar strings de apresentação aparadas por `strip()`.

O APK entregue 323 não foi substituído. Não há novo ganho confirmado, aprovação
de release, prova de todas as arquiteturas ou comprovação das metas 21×/26×.
