# Vulkan com tela acesa e apagada — resultado misto

## Entrega funcional, não aprovação da meta de velocidade

APK assinado: `.delivery/GGUF-Chat-mobile.apk`.
SHA-256: `8a994b58efc0a65a0851534402eacb5f0c305ff534a100075a88e5c5dbf95399`.
Fonte/native: `0e8fdd1557694b1ea538bdb323684e9ad6853a56`.
Baseline: último APK entregue, `e7ee730c5c8bc2c774375ded631fb4725bb364d09d05ea2e857cb9e38f8f69d9`.

**Não foi demonstrada grande aceleração, melhora do tempo total nos dois estados, máximo possível, 5 segundos ou 15–20 tokens/s na GPU do celular. O tempo total com tela acesa piorou no teste.**

O APK exato passou no comparativo funcional [35140030394](https://github.com/Enzo-cyber2025/5/actions/runs/35140030394), tentativa 1, job 104941952652, commit de teste `d5a3d8e99c56fb98a140e40bd5065b647e58a1ec`. Evidências reais: `ci-results/35140030394-1/`. Verificador `python3 ci/verify_vulkan_acceptance.py`: `SIGNED_VULKAN_AWAKE_ASLEEP_ACCEPTANCE_PASS`. Esse nome representa aprovação **funcional**, não aprovação de ganho de desempenho.

## Alterações implementadas

- Após seleção terminal do token no backend, exportar somente o token, sem copiar novamente os arrays auxiliares de vocabulário. Caminho parcialmente suportado continua com os descritores e fallback CPU originais.
- Uma leitura do token escolhido e um `accept`, evitando getters sincronizantes redundantes no caminho terminal.
- Enfileirar o próximo decode Vulkan antes da entrega JNI dos textos posteriores; primeiro texto continua imediato. Texto já amostrado é preservado mesmo se o decode seguinte falhar ou for cancelado.
- Texto comum em streaming permanece no TextView original. Painéis de código só são montados quando necessários; histórico, linguagem, seleção, rolagem horizontal e Copiar preservados.

Sem mudança dos pesos, quantização, contexto configurado, parâmetros de amostragem, limite de saída ou batching 128/32. Não se habilitou quantização adicional de ativações nem se atribuiu ganho a opções já habilitadas no upstream.

## Medições reais: Vulkan por software, não GPU física

Mesmo emulador Android 35 x86_64 e software Vulkan, SmolLM2-135M Q4_K_M, hash `2e8040ceae7815abe0dcb3540b9995eaa1fa0d2ca9e797d0a635ae4433c68c2d`, contexto 2048, GPU layers 99, threads Auto. Uma primeira resposta de aquecimento excluída e três primeiras respostas medidas por estado, em cada versão. Todas as respostas determinísticas comparadas produziram os mesmos 128 tokens e o mesmo texto entre versões; o limite de teste é 128 nas duas versões, não um corte novo para aparentar velocidade.

| Mediana da primeira resposta | Tela acesa: antes → depois | Tela apagada: antes → depois |
|---|---:|---:|
| Tempo total nativo | **71,011 → 72,047 s (piora de 1,46%)** | **40,609 → 39,887 s (redução de 1,78%)** |
| Primeiro texto nativo | 5,542 → 5,365 s | 5,346 → 4,999 s |
| Decode tokens/s | **1,955 → 1,912 (piora)** | 3,626 → 3,674 |
| Enviar → primeiro texto na UI | 5,607 → 5,424 s | Não se mede primeira renderização com a tela apagada |

Totais individuais antes/depois, em segundos:
- Acesa: `[70,586; 71,329; 71,011]` → `[72,494; 72,047; 72,011]`.
- Apagada: `[43,992; 40,400; 40,609]` → `[39,254; 39,887; 40,437]`.

Ambas as versões usam métricas v3, com prefill sincronizado antes de iniciar a medição de decode. Tempo total nativo não inclui importação ou carregamento inicial do modelo. Enviar→UI é uma medição separada. **4,999 s é primeiro texto nativo, não conclusão da resposta em 5 segundos.**

Continuações com reutilização real de prefixo, **uma observação por estado/versão**, não medianas:

| Continuação | Primeiro texto nativo | Decode tokens/s | Total nativo |
|---|---:|---:|---:|
| Acesa | 9,894 → 9,745 s | 1,914 → 1,861 | **76,778 → 78,523 s (piora)** |
| Apagada | 9,068 → 8,894 s | 3,586 → 3,612 | 44,763 → 44,330 s |

Os ganhos observados são pequenos e não estabelecem significância estatística nem causalidade isolada. Há contenção de CPU no Vulkan por software; não extrapolar para GPU ARM, outro driver ou outro GGUF. As variantes ARM foram compiladas, não executadas em GPU física neste comparativo. Não comparar números absolutos de execuções distintas de CI como se fossem pares controlados.

## Preservação verificada no APK assinado

- Instalação por cima do baseline com a mesma chave, preservando JSONs de modelos e conversas; modelo reutilizado após atualização com hash de arquivo conferido.
- Respostas greedy idênticas em ambos os estados, incluindo continuação. O teste não avalia a qualidade linguística dessas respostas: o texto pouco coerente aparece nas duas versões e não foi substituído por resposta artificial.
- Amostragem não greedy concluiu em ambas as versões. Seeds derivadas de nanoTime são diferentes: isso é teste de conclusão/fallback, **não prova de igualdade com seed fixa**.
- Tela realmente apagada durante geração, resposta salva, notificação e limpeza do serviço conferidas por logs/estado Android; screenshot após acordar não foi usado sozinho como prova.
- Produção DEX: código streaming/histórico e clipboard exato passaram; fixtures sintéticas identificadas como tais. Texto comum: 256 appends exatos no TextView original.
- Decodificador Android, conteúdo sem extensão, orientação, transparência, redimensionamento e rejeição de corrupção; imagem real selecionada por SAF, bytes conferidos, encoder e geração reais retornaram ` Dog.` com metadados ausentes simulados explicitamente.
- Screenshots genuínos de código, texto comum, inferência visual e rodapés revisados; hashes registrados em `.delivery/vulkan-acceptance.json`.

## Limitação visual e falhas anteriores mantidas

O build amplo [35136143899](https://github.com/Enzo-cyber2025/5/actions/runs/35136143899) compilou o native/UI, passou 168 regressões (2 skips), serialização DEX e entrega do unsigned, mas **o workflow inteiro falhou**: a imagem de ônibus no GGUF externo recebeu ` CERO EMIOFSELLA.`.

Comparação independente dos APKs assinados exatos [35138528110](https://github.com/Enzo-cyber2025/5/actions/runs/35138528110) concluiu `PASS_EQUALITY_ONLY`: **as duas versões responderam exatamente ` CERO EMIOFSELLA.`; ambas falharam semanticamente**. Não se introduziu diferença nesse caso, mas ele continua incorreto. Não é aprovação universal de reconhecimento de imagens/modelos/codecs.

O comparativo anterior 35137025361 falhou no harness ao tentar reimportar o modelo que a atualização já havia preservado. Não tinha série AFTER de velocidade e não foi usado para produzir a tabela. O teste corrigido reutiliza ID e confere hash; a execução 35140030394 completou todas as séries.

## Assinatura e instalação

Certificado SHA-256: `7295130ab387cd5123c1faab79c96f3ca8d8eb694ae7b15c611086d48b5898a0`, **igual ao último APK e7ee entregue**. Atualização sobre e7ee preservando dados passou; não é necessário desinstalá-lo. Versões históricas com certificado 4f75 continuam incompatíveis: não desinstalar sem preservar/exportar dados.

A chave privada foi preservada, não publicada. O download é APK, não ZIP. Trata-se de uma versão funcional com alterações no pipeline Vulkan e resultado de desempenho misto, não de uma recomendação baseada em aceleração comprovada nos dois estados.
