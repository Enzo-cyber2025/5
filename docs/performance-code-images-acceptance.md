# APK com caixas de código, leitura de imagens e alterações de desempenho

## Resultado: testes funcionais passaram; meta de velocidade não comprovada

APK: `.delivery/GGUF-Chat-mobile.apk` (Android 9+, ARM64 e x86_64).
SHA-256: `e7ee730c5c8bc2c774375ded631fb4725bb364d09d05ea2e857cb9e38f8f69d9`.
Fonte/native: `06c46f76329ed4cb0e93e03cd857910d391d33a3`.

Execução do APK assinado: [35127872319](https://github.com/Enzo-cyber2025/5/actions/runs/35127872319), tentativa 1, job 104901287470, **success**. Evidências em `ci-results/35127872319-1/`. O verificador `ci/verify_performance_acceptance.py` passou sobre essas evidências reais e sobre o APK exato; seus testes unitários sintéticos não contam como testes Android.

**Não foi demonstrada a meta de 15–20 tokens/s no aparelho do usuário. Há regressão observada no CPU automático com a tela acesa. Aprovação funcional não significa aprovação dessa meta nem melhora universal de desempenho.**

## Funcionalidade verificada

- Renderizador do APK real: painéis de código com linguagem, texto monoespaçado, rolagem horizontal e Copiar. Testes de clipboard exato em streaming e histórico usaram conteúdo sintético explicitamente identificado, não código gerado pelo modelo.
- Decodificador Android real: conteúdo sem extensão, transparência sobre branco, redimensionamento, orientação EXIF e rejeição de arquivo corrompido.
- Seleção SAF dos dois GGUFs e importação como modelo visual físico único. Imagem real importada via SAF, com hash dos bytes conferido. O teste omitiu deliberadamente o MIME e o `mmprojPath` redundante da conversa para exercitar o reconhecimento por conteúdo e a detecção do encoder no GGUF. O encoder visual processou a imagem e a resposta real foi `Dog.`. Isso não identifica retrospectivamente a causa exata da imagem que falhou no aparelho do usuário.
- Respostas determinísticas idênticas entre versões nos casos CPU automático, CPU manual e Vulkan; mesmo modelo, quantização, prompts e limite de 128 tokens por resposta de teste. Não houve substituição por modelo menor entre versões nem injeção de resposta/métrica.
- Geração CPU com tela acesa/apagada, Vulkan por software com tela apagada, persistência exata da resposta, notificação e encerramento do serviço. Vulkan físico e Vulkan com tela acesa não foram medidos nesta execução.
- Medição real Enviar→primeiro texto na UI da versão nova. Não há essa instrumentação de UI na versão antiga; a comparação abaixo usa o primeiro texto **nativo**, não uma comparação completa do tempo desde o toque em Enviar.

## Medições: Android 35 x86_64 emulado, não telefone

SmolLM2-135M Q4_K_M, contexto 2048; configuração CPU Auto nas duas versões (antes resolvia 1 thread, depois 2 neste emulador). Uma repetição de aquecimento excluída e três pares medidos por estado de tela. Os tempos totais abaixo vão de conteúdo preparado até conclusão nativa e não incluem importação, carregamento inicial do modelo ou toda a preparação de anexos.

| Caso CPU Auto | Primeiro texto nativo, antes → depois | Decode tokens/s, antes → depois | Tempo total, antes → depois |
|---|---:|---:|---:|
| Tela acesa, primeira resposta | 17,085 → 10,227 s | **9,98 → 4,49** | **29,906 → 38,730 s** |
| Tela acesa, continuação | 1,923 → 1,631 s | 8,59 → 8,28 | 16,789 → 17,093 s |
| Tela apagada, primeira resposta | 16,108 → 8,709 s | 16,45 → 27,39 | 23,888 → 13,417 s |
| Tela apagada, continuação | 2,016 → 1,363 s | 14,45 → 23,15 | 10,846 → 7,027 s |

O ganho com tela apagada não apaga a regressão com tela acesa. A resolução diferente de threads e a concorrência com a renderização no emulador são fatores a investigar, não uma causa física já provada. Não extrapolar esses números para ARM ou para outro GGUF.

Vulkan **por software**, uma observação por versão, tela apagada: primeiro texto nativo 21,557 → 4,709 s; tempo total 54,049 → 36,058 s. O sampler teve seleção real no backend. Isso é evidência funcional e observação de latência, **não benchmark estatístico de GPU física**. A versão 3 dos contadores sincroniza a conclusão do prefill antes de iniciar o relógio de decode; mudar essa atribuição de tempo não constitui aceleração por si só. Por isso não usamos o aumento isolado do contador de decode Vulkan como prova de ganho.

As variantes ARM dotprod/i8mm foram compiladas e inspecionadas no APK exato (`.delivery/performance-arm-isa.json`), mas não executadas em hardware ARM neste teste.

## Instalação e assinatura

Certificado: `7295130ab387cd5123c1faab79c96f3ca8d8eb694ae7b15c611086d48b5898a0`.

**É diferente do certificado da versão 3baa anteriormente entregue. Não há atualização direta compatível.** O Android recusou a instalação por cima e manteve os dados antigos no teste. Apenas o emulador descartável foi desinstalado para prosseguir. No aparelho real, desinstalar apaga conversas/modelos no armazenamento privado: preservar/exportar os dados antes de qualquer desinstalação. Autorização para qualquer assinatura não é autorização para apagar os dados silenciosamente.

## Falhas anteriores preservadas

- Build 35122790161: compilação e regressões de código passaram; execução completa falhou no roteiro antigo de multisseleção SAF, antes da inferência. Não declarar esse workflow inteiro como sucesso.
- 35125326321: código/decoder passaram; baseline Vulkan não enumerou o dispositivo CPU-type porque faltava a opção explícita exclusiva do emulador. Comparação incompleta, não aprovada.
- 35127256380: seleção exata SAF passou; o roteiro tentou ler a biblioteca antes de sua criação assíncrona. Corrigido para aguardar o arquivo ausente, sem ignorar JSON inválido ou erros de I/O.
- 35127872319: execução corrigida completa passou. Não representa certificação de todas as arquiteturas, formatos de imagem, qualidade semântica, OEMs ou modelos. Resultados parciais/falhas históricas de outras suítes não foram convertidos em sucesso.
