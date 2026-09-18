# Entrega com ganhos consistentes observados — 18/09/2026

## Mudança de critério autorizada pelo usuário

Pedido explícito: “qualquer ganho estavel e valido. e aplique tudo que nao atarpalha o desempenho”.

A aprovação anterior exigia +10% em cada par de texto e mediana +15%. O payload
2b44 **continua reprovado nesse critério original**. Não alteramos medições,
relatórios históricos ou seu resultado. O usuário autorizou uma nova decisão:
aceitar ganhos menores consistentes nas observações, sem relaxar a qualidade.

A política separada `user-stable-observed-v1` exige três pares aquecidos com ganho
em todos os casos de texto com tela ligada, nenhum primeiro texto mais lento,
mediana de tela apagada não inferior e nenhuma observação OFF >3% mais lenta.
O limite de variação OFF é o mesmo anterior; não é garantia de zero regressão em
todo aparelho. Respostas completas, 128 tokens, entradas, parâmetros, prefixo
KV aquecido, rotas estritas e hashes de payload continuam sendo conferidos.

## Resultados usados nesta entrega

- Texto ON: **+17,64%, +7,34%, +9,49%** nos três pares; mediana **+9,49%**.
- Send→primeiro texto ON: **30,95% menos espera** pela mediana das razões.
- Texto OFF: de **−1,63% a +1,30%**, mediana **+0,77%**. Variação pequena,
  não promessa de ganho estável OFF ou paridade de velocidade ON/OFF.
- Reativar imagens retidas no cache: **7,3386× e 7,3968× mais rápido**. Não é
  ganho de 7× em imagens inéditas/primeiro processamento ou em todo o app.
- Mesmas respostas completas nas comparações. Modelo, quantização, conteúdo,
  contexto e limite de saída não foram reduzidos. Modo Vulkan estrito preservado.

São testes em **Vulkan por software no emulador**; consistência observada em
poucas repetições não é certeza estatística, teste no telefone do usuário ou
certificação de todos os modelos. As metas 21×/26× não foram atingidas.

## O que foi efetivamente entregue

`entrega/GGUF-Chat-acelerado.apk`, **51.128.050 bytes**, assinado localmente.

SHA-256: `bd7c45d3c9b80ee583e0d4102595c5ed55242c37aa0394f0befe093c07fd88d2`.

Fonte compilada: `81bc70c8c1025fb8d46f7d99a8f9ee63af95b711`; payload original
`2b444a73090dff9bd6d4ce6d199349cafd5e9ae73b83cc34e05101e7f77727cc`.
Os **146 arquivos não relacionados à assinatura** são idênticos aos do APK
validado. Não reconstruímos o aplicativo com experimentos adicionais antes de
entregá-lo. A assinatura final foi verificada nos esquemas v2 e v3; o arquivo
final com essa nova chave não foi executado novamente no Android, mas seu
conteúdo executável/recursos são byte a byte os já testados.

A verificação v3 usa a faixa real declarada pelo APK. A v2 é verificada
separadamente com override SDK 24–27, pois o verificador seleciona v3 para
minSdk 28+. Esse override não altera o APK nem reduz seu Android mínimo.

## Mudanças que não foram somadas às cegas

- Comunicação direta: incremento mediano +0,75%, primeiro par pior; não adotada.
- Espera bloqueante Vulkan, run 35378808404: testes funcionais passaram, mas
  texto ON mediano **−1,24%** e imagens sem ganho; não adotada. A política nova
  também não aprova essa mudança. Nenhuma economia de CPU foi comprovada.
- RGB, batch2 e QKV: permanecem fora desta entrega. Batch2 (+1,40%) e QKV
  (+0,49%) tiveram pequenos resultados positivos em dois pares exploratórios,
  mas sua combinação com os demais caminhos e regressões ON/OFF não foi
  aprovada. QKV também duplicou 21,62 MiB de pesos. “Aplicar tudo” não significa
  presumir que somar experimentos isolados preserva desempenho e memória.

## Assinatura e dados

Certificado novo: `bc4edf6c222ff6a602b3757fbda64fa2b9f23585add6080cf771f7315ce5b158`.
A chave foi mantida privadamente no momento da assinatura, fora do Git.
Na restauração posterior desta área de trabalho, o keystore e sua senha não
estão presentes. O APK foi recuperado por Git e é exatamente o mesmo arquivo,
com o mesmo certificado; não foi reassinado e nenhuma chave substituta foi
gerada. Não prometer futuras atualizações com esse certificado sem recuperar
a chave. Estado atual: `.delivery/signing-key-availability.json`.

**Assinatura diferente do APK antigo 7295: não é uma atualização compatível
sobre ele. Não desinstale a versão antiga sem preservar conversas, anexos e
modelos fora do app. A desinstalação pode apagar seus dados privados.** Nenhum
comando de instalação, desinstalação ou limpeza de dados do usuário foi executado.
O APK original 323 permanece intacto.

Registros: `.delivery/stable-gain-authorization.json`,
`.delivery/stable-text-acceptance.json`, `.delivery/perceptible-speed-delivery.json`
e `.delivery/gain-release-signature.txt`. O registro antigo
`.delivery/perceptible-text-acceptance.json` é histórico e conserva a reprovação
no critério antigo; a decisão atual está no registro separado de entrega.
