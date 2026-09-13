# Revisão mobile — GGUF + mmproj

## Artefato

- Pacote: `com.ggufchat.app`, versão 2.0.
- Android mínimo: **9 / API 28**, coerente com a compilação nativa.
- ABIs: `arm64-v8a` e `x86_64`.
- Fonte desta build: `120e7dc7bfbab569820d8e9016db57027c2f505e`.
- Motor recompilado integralmente: llama.cpp / ggml / mtmd b6500, commit `a7a98e0fffed794396b3fbad4dcdbbc184963645`, NDK `28.2.13676358`.
- SHA-256 do APK assinado: `409985de54388cbcb1429a8db4cd26139cc47a5764864c6cd4b408c75f07099f`.
- Certificado SHA-256: `68f248a224075d66df9ff97ba336556b0a84b724112e644c28e607612da633f5`.
- Assinatura v3 verificada. **É a nova chave fixa autorizada pelo usuário, não a chave perdida do APK anterior.**

## Correções

### Carregamento e memória

A ponte antiga recebia o caminho do projetor, mas não o carregava. A nova implementação usa `mtmd_init_from_file` e verifica o suporte de visão do contexto realmente criado. Falha do projetor faz o carregamento falhar, em vez de informar sucesso sem ele.

O motor usa componentes compilados juntos, sem misturar ABIs de versões diferentes. Handles têm posse compartilhada durante operações em andamento; cancelamento e destruição não liberam um contexto ainda em uso.

O padrão passa a ser **CPU, contexto 1024**, com batches limitados. CPU usa uma lista vazia de aceleradores, evitando criar um dispositivo Vulkan nesse modo. A verificação conservadora de memória considera os dois arquivos, o contexto e uma reserva; recusa a carga quando a estimativa supera 70% de `MemAvailable`. Isso não é garantia contra o low-memory killer ou defeitos de drivers e pode recusar modelos grandes.

No Vulkan, o dispositivo só entra no cache após inicialização completa; a destruição também protege o caso de `VkDevice` nulo. A consulta da capacidade de armazenamento de 16 bits permanece: não são fabricados recursos suportados. Vulkan continua opcional; esta revisão é validada em **CPU**, não em GPU física.

### Associação e apresentação

Selecione juntos **um GGUF de linguagem e o mmproj compatível** no seletor de arquivos do Android. A transação registra os IDs existentes **antes do primeiro arquivo ser copiado**. Apenas os novos registros daquela seleção podem ser associados. Reimportar arquivos com os mesmos nomes não deve trocar associações anteriores.

O par aparece em **um único cartão**, identificado por `GGUF + mmproj`. O projetor associado não aparece como outro modelo independente. Os arquivos continuam separados: concatenar seus bytes não produziria um GGUF válido.

### Interface

- Ferramentas em uma única linha com rolagem horizontal.
- Espaçamento de **10 pixels físicos** entre blocos.
- Botões de 36 dp e texto de 12 sp, em uma linha com reticências quando necessário.
- Ferramentas inicialmente recolhidas, alternadas pela **chave inglesa ao lado de Enviar**.
- Redução aplicada também à navegação e a locais que substituíam os parâmetros de tamanho dos botões.

## Validação

**Teste final aprovado:** https://github.com/Enzo-cyber2025/5/actions/runs/34785696254

[Evidências e capturas](../ci-results/34785696254-1/summary.json). No PID `4979`, o carregamento registrou `GGUF_PROJECTOR_LOADED vision=1 audio=0`; a mensagem concluiu com `GGUF_NATIVE_COMPLETE tokens=34 reason=eog projector=1`. O assistant foi salvo após o prompt e o processo permaneceu vivo durante carga/geração. Cartão único, espaçamento de 10 px, recolhimento da barra e reimportação também passaram.

Compilação: https://github.com/Enzo-cyber2025/5/actions/runs/34784725708

- 97 testes de ferramentas/empacotamento/política UTF-8.
- 33 testes JVM nas classes traduzidas do APK final. Esses testes usam doubles explícitos de Native/JSON e não são prova de inferência.
- O teste Android usa os arquivos reais abaixo, seleção múltipla SAF, hashes dos arquivos copiados, associação persistida, carregamento nativo do projetor e mensagem enviada pela interface.
- A conclusão exige log nativo, assistant persistido após o prompt exato e o mesmo PID vivo durante carga/geração. Reimportação posterior é intencional e reinicia a atividade/processo para verificar o fluxo de importação novamente.
- Apenas a coleta de XML da interface pode ser repetida quando o DocumentsUI ainda não produziu um dump. Não se repete o envio para esconder crash ou falha de geração.

### Arquivos reais usados

Repositório Hugging Face: https://huggingface.co/ggml-org/SmolVLM-256M-Instruct-GGUF

| Arquivo | Bytes | SHA-256 |
|---|---:|---|
| `SmolVLM-256M-Instruct-Q8_0.gguf` | 175054528 | `2a31195d3769c0b0fd0a4906201666108834848db768af11de1d2cef7cd35e65` |
| `mmproj-SmolVLM-256M-Instruct-Q8_0.gguf` | 103769856 | `7e943f7c53f0382a6fc41b6ee0c2def63ba4fded9ab8ed039cc9e2ab905e0edd` |

Os modelos não são incluídos no APK nem no Git. `ci/mobile-models.sh` baixa e confere os hashes.

## Limites importantes

- O Galaxy A55 5G de 8 GB **não foi reproduzido fisicamente**. O teste é Android 15/API 35, x86_64, emulador configurado com 6 GB. ARM64 foi compilado, mas não executado em um A55 nesta sessão.
- Carregar o mmproj e responder texto **não prova inferência de imagem**. Esta revisão não acrescenta um caminho de envio de bitmaps/anexos para avaliação mtmd; não deve ser anunciada como reconhecimento de fotos validado.
- O teste de mensagem comprova execução e persistência, não qualidade/pertinência das respostas de um modelo de 256 milhões de parâmetros.
- A proteção de memória é uma estimativa. Os nomes e logs do modelo que caiu no aparelho não foram fornecidos; não se afirma ter reproduzido aquele mesmo crash.

## Assinatura e recompilação

A chave privada fica em `.signing/`, ignorada pelo Git, fora dos artefatos e logs. `scripts/sign_mobile.py` reutiliza essa chave, verifica o certificado e recusa gerar outra silenciosamente. O repositório sozinho não contém a chave privada.

A CI compila um APK sem assinatura e o transfere pela mesma branch em `.delivery/`. A assinatura é local. O APK já assinado volta à CI para teste; o hash em `summary.json` precisa coincidir com o entregue.

`GGUF_REUSE_TESTED_NATIVE=0` é o padrão atual do workflow e recompila as duas ABIs. O cache opcional tem hashes de bibliotecas, fontes e receita de compilação; uma mudança nativa exige recompilar, não reaproveitar o binário anterior.

**Instalação sobre a versão antiga:** como o certificado anterior foi perdido, será necessário desinstalá-la antes. Isso pode apagar conversas e modelos internos; faça backup/exportação antes. Atualizações produzidas com esta nova chave fixa podem manter a assinatura daqui em diante.
