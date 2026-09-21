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

### Experimento concluído: não adotar a comunicação direta

Run [35295026946](https://github.com/Enzo-cyber2025/5/actions/runs/35295026946),
fonte `5897a03`, concluiu em 45m43s com testes funcionais bem-sucedidos, mas seu
resultado de velocidade é **`NO_MATERIAL_ADDITIONAL_GAIN`**. Sucesso do job não
significa aprovação da aceleração.

No **mesmo APK**, rota ON versus OFF, razões pareadas de tokens/s com tela
ligada: **0,992622; 1,007493; 1,015878**. Mediana **+0,7493%**, primeiro par
ligeiramente pior. Espera até primeiro texto também ficou ligeiramente pior
(mediana da razão OFF/ON 0,982694). Sono praticamente inalterado. Não atende o
critério adicional predefinido; permanece desligado e fora da receita normal.

A comparação do APK experimental ON contra o original 323 chegou a mediana
+39,77% nesta outra máquina do CI. **Não atribuir esse ganho à comunicação
direta:** o controle OFF do mesmo APK já apresentava praticamente toda essa
vantagem. Não comparar velocidades absolutas entre runners, substituir o
resultado +9,49% do payload 2b44, ou selecionar só o melhor runner para aprovar.

Históricos completos, 128 tokens, aquecimento/cache, rotas estritas e cálculos
dos dois comparativos foram revalidados localmente. Todos os hashes de
bibliotecas nativas **declarados pelo relatório** coincidem com o APK base 2b44
local. Código/Copy passou. Relatório completo e proveniência ficam em
`.delivery/local-stream-experiment.json`.

#### Reconexão e sincronização

Após a reconexão pelo Arena, o relatório foi recuperado por **Git autenticado**
do commit `d2d1709986522d80f473f9bb311968f21ed852ac`. Seu objeto Git completo é
`9666311cc9f6feb4c007277746d8c37cc30645d8`, SHA-256
`4d0cc63c2045c454583754b1046b5862c30df0e91260b0c78c28f0487d61de48`.
Isso substitui a dependência da leitura pública usada durante a interrupção da
conexão. O status final do job também foi confirmado pela API autenticada.

O download do artefato binário experimental 10527654696 encontrou EOF no Azure.
Isso é uma falha de transporte, não outra falha de autenticação. Não afirmar
verificação binária local desse APK; sua comparação byte a byte permanece a
executada pelo builder do CI. Não é necessário publicar um APK experimental
rejeitado para recuperar essa cópia: os registros autenticados já permitem
recomputar a rejeição.

Os gates de imagens e texto do payload 2b44 foram recalculados novamente:
imagens aprovadas, texto abaixo do critério. Nenhum limite foi relaxado, nenhuma
chave persistente foi criada, nenhum APK final foi assinado ou liberado. O APK
original permanece byte a byte intacto.


## Decisão posterior autorizada: ganho pequeno consistente é válido

Em 18/09/2026, o usuário autorizou explicitamente qualquer ganho estável. A
política original acima não foi modificada: o resultado +9,49% continua abaixo
de +15%. A nova política separada `user-stable-observed-v1` aprovou os três pares
positivos do payload 2b44, com qualidade preservada e controles de regressão.
A entrega foi assinada sem modificar seu conteúdo não relacionado à assinatura.
Veja [a decisão atual e suas limitações](stable-speed-delivery.md).
