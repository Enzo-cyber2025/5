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
