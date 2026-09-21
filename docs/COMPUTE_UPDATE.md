# Processamento local com a tela apagada — alteração em validação

**Estado: candidato assinado, ainda sem aprovação final/publicação.** Não confundir os testes da versão anterior com aprovação deste APK.

## Recusa de memória

O carregador anterior calculava `arquivos × 1,5 + contexto × 262144 + 268435456` e recusava a carga acima de 70% de `MemAvailable`. Isso não é uma medida do consumo real: páginas mapeadas de arquivos podem ser recuperadas pelo sistema e o cache depende da arquitetura.

A recusa baseada nessa fórmula foi removida. A memória disponível continua registrada para diagnóstico, mas o carregamento real de linguagem, contexto e projetor precisa dar certo antes de um par ser registrado. O microbatch caiu de 64 para 32 para reduzir buffers temporários. Não foi adicionada uma aprovação falsa nem retirado o carregamento nativo obrigatório.

## Execução em segundo plano

- Importações passam por um serviço em primeiro plano que possui a fila e o worker, em vez de depender apenas de uma thread criada pela Activity.
- Geração mantém o serviço existente, agora com tipo `specialUse`, descrito no manifesto como processamento local de IA iniciado pelo usuário. Não simula reprodução de mídia ou sincronização de rede.
- `PARTIAL_WAKE_LOCK` mantém a CPU disponível sem acender a tela. Leases de dez minutos são renovadas enquanto há trabalho, com liberação ao terminar ou destruir o serviço.
- Notificação persistente durante a importação, com etapa/percentual medidos e cancelamento. Etapas nativas sem contador continuam indeterminadas; cancelar pode aguardar a etapa nativa terminar.
- Sem boot receiver, alarmes exatos, reinício silencioso ou serviço exportado.

Referências oficiais: [tipos de foreground service](https://developer.android.com/develop/background-work/services/fgs/service-types#special-use) e [boas práticas de wake locks](https://developer.android.com/develop/background-work/background-tasks/awake/wakelock/best-practices).

Isso permite executar trabalho iniciado pelo usuário com a tela apagada, mas **não oferece imunidade a encerramento forçado, reinício, esgotamento real de memória ou políticas agressivas do fabricante**. Se o aparelho restringir o app, revise suas configurações de bateria e notificações. A adoção de `specialUse` não constitui aprovação de política da Google Play.

## Junção e identificação

- Reutilização dos cabeçalhos já lidos no staging privado, evitando analisar novamente o vocabulário e as tabelas dos dois componentes.
- Transferências por `FileChannel.transferTo`, limitadas a blocos de 4 MiB, com fallback bufferizado quando a transferência retorna zero; buffers limitados, sem carregar o GGUF inteiro no heap Java.
- Mantidas a conferência independente de cada tensor, tipo, dimensões e bytes, a sincronização dos arquivos e a publicação atômica de um único GGUF.
- Identificação exige matriz de embeddings coerente com a dimensão declarada, pesos do encoder visual e matrizes do projetor. Marcadores, nomes de arquivo ou vetores isolados não bastam.
- Tabela de quantizações alinhada ao motor fixado `llama.cpp v0.4.1`, incluindo os formatos NVFP4, Q1_0 e Q2_0. Reconhecer os formatos não equivale a testar inferência em todos os modelos/backends que os usam.
- Layouts externos não suportados continuam identificados como incompletos/não suportados, sem fingir suporte universal. Pesos de áudio podem ser preservados em um GGUF de visão, mas não foi adicionada interface de áudio.

## Interface

Ícones vetoriais de traço para os controles, sem depender de fonte emoji; tipografia dos botões um pouco menor, aparência visual mais compacta e cantos menos arredondados. A seleção múltipla continua no único botão **Importar GGUF**. A barra de ferramentas mantém uma linha, inicialmente oculta, e os intervalos de 10 pixels.

## Assinatura — atenção antes de instalar

A chave privada anterior não estava disponível no ambiente restaurado. Foi aplicada a autorização anterior do usuário para outra assinatura quando não fosse possível manter a mesma.

- Certificado anterior: `9b658c30f602e0f2ff65c176423cb95bea8fbdeb660c306ab908862f90d9bc3c`.
- Certificado do candidato: `3dd851d414caaa20d06ea22391e75b752aab0d26c749168b3353dd389b1332da`.

**Não é uma atualização compatível por cima da instalação anterior. Não desinstale sem antes preservar os dados necessários:** o Android pode apagar modelos privados e conversas na desinstalação. Os arquivos originais externos usados na importação não são modificados pelo app. A nova chave e seu backup foram criados localmente; não foram enviados ao GitHub.

## Plano de aceitação

APK candidato SHA-256 `0c45fd2e6c318da3ebb961bbd461c56d7401161c31a1869157f509550e4b05d1`, código `febe2ec5aa6b311f86ec9fe8fa4ae2f3cd7b6cca`.

A compilação executa testes de fonte, conversão do DEX para JVM, leitor GGUF e regressões Android. A suíte assinada exige importação real com tela apagada, serviço/lock ativos, progresso novo, auditoria dos tensores, encerramento do serviço, liberação do lock, geração nativa e resposta persistida ainda com a tela apagada. Inclui o par público Gemma 4 em emulador configurado com 8 GiB; isso não é homologação de RAM/GPU de um celular físico nem identificação dos arquivos particulares do usuário.

A primeira execução assinada foi **rejeitada**: a asserção de liberação procurava o nome também no histórico retido de wake locks do Android. A verificação foi corrigida para ler estritamente a lista de locks **ativos**, rejeitar dumps sem essa seção e conservar os relatórios de energia separadamente. A nova execução ainda precisa terminar e suas capturas ser conferidas antes de publicar.
