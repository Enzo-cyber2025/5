# Ganho de texto: aprovação independente da melhoria de imagens

A reativação de imagens passou no run 35280368352: 422,862 → 57,621 s e
417,351 → 56,423 s, respostas e pixels preservados. Isso não comprova ganho no
texto. A assinatura/entrega combinada agora exige **os dois gates**.

O teste de texto compara o APK entregue 323 com o payload já validado 2b444a,
sem recompilar pesos ou ativar experimentos QKV/batch. Ambos são reassinados
somente para testes descartáveis. O payload fora das assinaturas é conferido.

Protocolo: SmolLM2-135M Q4_K_M, GPU 99/todas as camadas, contexto 2048, threads
Auto, temperatura zero, 128 tokens. Três pares intercalados AB/BA/AB, estados ON
e OFF alternados. Cada Engine/estado tem uma geração de aquecimento excluída e
uma continuação medida. Históricos brutos, tokens e rotas GPU devem coincidir.
Sem usar a primeira execução fria como ganho, sem atrasar o controle ou OFF.

Critério definido antes do resultado: cada par ON pelo menos 10% mais rápido em
decode, mediana ON pelo menos 15%, nenhum par OFF mais que 3% mais lento, e sem
piora acima de aproximadamente 5,3% da espera ON pelo primeiro texto. Se falhar,
não apresentar o candidato como aceleração perceptível de texto.

O ganho é medido em emulador Vulkan por software, não certificado para todo
aparelho. Não é aprovação de metas 21×/26× ou paridade exata ON/OFF. A cópia de
pixels/normalização não foi toda transferida para GPU nesse payload. Nenhuma
assinatura nova será produzida pelo entregador sem aprovação independente de
texto e imagens, conforme o pedido ampliado do usuário.

## Resultado do candidato 2b44: entrega bloqueada

Run [35292973655](https://github.com/Enzo-cyber2025/5/actions/runs/35292973655),
fonte 7bcb6a6. O teste Android completou; o job falhou **intencionalmente no gate
numérico**, não na geração. Todos os históricos completos/tokens coincidiram;
continuações mantiveram 204 tokens de prefixo. A avaliação reforçada foi também
reexecutada localmente, sem alterar os limites de aceitação.

| Par | ON anterior → candidato (t/s) | Send → texto ON (s) | OFF anterior → candidato (t/s) |
|---|---|---|---|
| AB | 5,5805 → 6,5651 | 1,0274 → 0,5876 | 8,9016 → 9,0176 |
| BA | 5,9594 → 6,3970 | 0,8335 → 0,5923 | 9,0590 → 8,9111 |
| AB | 5,9373 → 6,5008 | 0,9005 → 0,6218 | 8,8122 → 8,8805 |

Mediana das razões pareadas ON: **+9,4908%**; primeiro texto **30,95% menos
espera**. OFF: **+0,7749%**, variação pequena. Existe melhoria observada no texto,
mas não atingiu o mínimo previamente definido (cada ON +10%, mediana +15%).
Não diminuir esses limites após conhecer os resultados. Nenhum APK de entrega
ou chave persistente foi criado. Os ganhos não certificam o telefone do usuário.

## Nova hipótese isolada, desligada por padrão

`LocalGenerationStream` evita o caminho Binder/ActivityManager apenas para os
três eventos privados de geração, mantendo o mesmo receiver na fila principal,
ordem FIFO, dados exatos e ciclo de vida. Não agrupa tokens, não usa timers, não
mexe em notificações do Android, modelo, orçamento ou cálculo Vulkan. Ao pausar,
registros antigos são desativados; eventos pendentes não atingem a Activity
recriada. O armazenamento da resposta continua sob responsabilidade do serviço.

O APK experimental altera somente `classes.dex`, verificando todos os demais
arquivos byte a byte. `GGUF_LOCAL_STREAM=1` habilita a hipótese apenas no emulador.
A receita normal de build não aplica esse patch. O experimento compara original
323, o APK experimental OFF e o **mesmo APK** ON, com três comparações aquecidas
AB/BA/AB por controle. Exige o gate ON-versus-original e, adicionalmente,
ON-versus-OFF >=3% em cada par/mediana >=5%, sem regressões relevantes no sono
ou primeiro texto. É hipótese ainda não aprovada, não uma entrega acelerada.
