# Um botão “Importar GGUF”, com seleção múltipla

[Baixar APK — sem ZIP](https://github.com/Enzo-cyber2025/5/releases/download/gguf-import-ui-368f85e/GGUF-Chat-mobile.apk)

**28.345.800 bytes · Android 9+ · ARM64/x86_64 · modelos não incluídos.**

## Correção

Com a biblioteca vazia, **Criar/Nova conversa → aviso → Importar** abre uma tela com apenas **Importar GGUF**. A tela antiga com “Importar modelo GGUF” e “Importar 2 GGUFs” foi substituída pelo redirecionamento à mesma tela única, inclusive ao restaurar a Activity antiga ou iniciar o app por ela.

O botão abre o seletor de arquivos com **seleção múltipla habilitada**. Não há um botão separado nem limite artificial de dois arquivos. No seletor Android, use os ícones de seleção ou mantenha pressionado o primeiro arquivo e acrescente os demais.

As regras existentes continuam: dois componentes compatíveis selecionados juntos passam pela unificação atômica em um GGUF físico validado; lotes maiores seguem a importação sequencial. Seleção múltipla não significa que quaisquer modelos incompatíveis possam ser fundidos.

## Mesma assinatura

Foi mantido o certificado do último APK `gguf-progress-dba56b2`:

`9b658c30f602e0f2ff65c176423cb95bea8fbdeb660c306ab908862f90d9bc3c`

O teste executou **`adb install -r` sobre esse último APK público**, confirmou o dado privado antes e depois de abrir a atualização e não precisou desinstalá-lo. A chave privada preservada foi usada localmente; nenhuma chave nova foi criada ou enviada ao GitHub.

SHA-256 deste APK: `086a125ae5e503718b3999bff1d2ad98b06498e0edf770471c7db07e8afaa813`.

## Validação desta alteração

[Execução Android 34978739703](https://github.com/Enzo-cyber2025/5/actions/runs/34978739703), job **104413168346: SUCCESS**, com o mesmo APK assinado da entrega.

- Atualização com assinatura igual e dado privado preservado após abrir o app.
- Biblioteca vazia: aviso de nova conversa leva a apenas um botão de importação.
- Entrada pela Activity antiga com o app aberto e com o processo parado: mesma tela única.
- Seleção real de **dois GGUFs** pelo gerenciador Android: um arquivo/registro visual, carregamento nativo de linguagem e visão no mesmo caminho e auditoria independente dos tensores preservados.
- Seleção real de **três GGUFs textuais**: todos importados, bytes conferidos e registros preservados após reiniciar.
- **39 testes JVM e 16 testes do leitor** extraído do APK passaram.

### Capturas reais conferidas

[Único botão após o aviso](../ci-results/34978739703-1/physical-import-ui-empty-library.png) · [Entrada antiga redirecionada](../ci-results/34978739703-1/physical-import-ui-legacy-cold.png) · [Três arquivos selecionados](../ci-results/34978739703-1/physical-import-ui-three-selected.png) · [Par importado em um GGUF](../ci-results/34978739703-1/physical-import-ui-pair-imported.png) · [Resumo](../ci-results/34978739703-1/summary.json).

As imagens foram obtidas por `adb screencap` e abertas para conferência. Não foram recriadas ou geradas.

## Escopo e preservação

Esta é uma alteração de navegação/interface. Foi recompilado o DEX da última versão aprovada, aplicando a mesma alteração integrada ao gerador de builds completos. A comparação do APK assinado decodificado confirmou que **somente MainActivity e ModelsActivity mudaram; as outras 6.802 classes permaneceram iguais**. Bibliotecas nativas, recursos, assets e segundo DEX são byte a byte iguais à última entrega.

Os percentuais, transação de importação e motor anterior foram preservados. Esta execução testa o fluxo de importação, não repete a bateria completa de inferência Gemma/documentos/câmera da versão-base. As limitações anteriores de qualidade dos modelos, GPU física e áudio continuam válidas. O teste é em emulador, não homologação de aparelho físico.

A publicação exige o job aprovado, a mesma assinatura, os hashes dos componentes e das capturas, e uma comparação byte a byte do download público com o APK aprovado.
