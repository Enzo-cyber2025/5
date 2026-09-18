# Primeiro mobile aprovado versus APK entregue

Pedido: link para baixar e comparação com o primeiro APK que funcionou.

## Identificação sem trocar a referência

A primeira **entrega mobile com aprovação funcional explícita** encontrada no
histórico desta sessão é o commit `2ae661f530f96e65730d02dfc5d63a6db3743ac4`:

- APK: SHA `409985de54388cbcb1429a8db4cd26139cc47a5764864c6cd4b408c75f07099f`.
- 16.741.431 bytes; fonte nativa `120e7dc`; llama `a7a98e0`.
- Aprovação Android `34785696254`: importação, carga e inferência de TEXTO com
  projetor carregado. **Ainda não avaliava fotos/anexos.**
- É a referência documental adotada, não uma afirmação de qual arquivo o usuário
  instalou primeiro no próprio telefone. Houve reparos anteriores a essa entrega.

Atual para download: `entrega/GGUF-Chat-acelerado.apk`, 51.128.050 bytes,
SHA `bd7c45d3c9b80ee583e0d4102595c5ed55242c37aa0394f0befe093c07fd88d2`.
Não inclui os experimentos de QKV/batch2 ou prefixo multimodal ainda em avaliação.

## Ganhos que JÁ foram medidos — contra outra referência

A comparação aquecida `35292973655` usou o APK funcional **posterior 323fd5**,
não o primeiro 409985de. Contra 323fd5, o conteúdo executável da entrega atual teve:

- texto com tela acesa: +17,64%, +7,34% e +9,49% de tokens/s de decode;
  mediana das razões +9,49%;
- primeiro texto visível: 30,95% menos espera pela mediana das razões;
- texto com tela apagada: mediana +0,77%, incluindo um par -1,63%; não ganho
  consistente em todos os pares nem paridade ON/OFF;
- reativar duas fotos já processadas após excluir uma: 422,86 → 57,62 s e
  417,35 → 56,42 s (7,34×/7,40×). Não é o primeiro processamento de fotos novas.

Vulkan por software no emulador. Não dividir velocidades de runners diferentes
para inventar uma comparação direta 409985de → atual.

## Novo ensaio direto (resultado inicialmente pendente)

`first-working.yml` extrai o APK original 409985de diretamente do commit histórico
e usa o APK **exato do download**, bd7c45d. Não compila, modifica nem reassina
nenhum deles. As assinaturas incompatíveis exigem instalações limpas exclusivamente
em emuladores descartáveis; nunca no telefone/dados do usuário.

CPU e Vulkan são jobs separados. Três pares AB/BA/AB por backend, cada um com
tela acesa/apagada e uma resposta de aquecimento excluída. Mesmo SmolLM2-135M
Q4_K_M, prompts, contexto 2048, threads 2, sampling greedy e orçamento 128.
Cada resposta medida deve realmente produzir os 128 tokens. Sem knobs de
velocidade; para expor o Vulkan por software usa-se o mesmo seletor de dispositivo
nos dois APKs. Sem offload Vulkan real, esse braço falha em vez de apresentar CPU
como GPU. Somente a versão atual pode provar a política estrita de todos os
cálculos; o primeiro APK não a tinha.

O APK inicial não oferece os contadores modernos de decode/primeiro texto.
Por isso a métrica comum é **marcador no dispositivo imediatamente antes do
clique Enviar → conclusão nativa**, incluindo prefill e geração. O timestamp é
do log do dispositivo, não o instante em que o observador detectou o fim.
Não apresentar `tokens / intervalo total` como tokens/s de decode, nem como
Send→primeiro texto visível. Não fazer polling de UI durante a geração.

Os motores e seus detalhes internos são os que cada APK entregava: llama
`a7a98e0` versus `b29c606`, ubatch 64 versus 32, batch 128 em ambos. Não modificar
o original para aparentar igualdade de implementação. É uma comparação entre
produtos completos com controles públicos iguais, não isolamento de um kernel.
Respostas completas diferentes bloqueiam uma alegação de ganho com qualidade
preservada, mesmo que tempos tenham sido coletados. Uma comparação concluída
pode mostrar regressão; `PASS_DIRECT_COMPARISON` não significa necessariamente
melhora. Fotos ficam **não comparáveis** ao primeiro APK, porque ele não tinha
essa função.
