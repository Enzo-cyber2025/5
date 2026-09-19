# Por que o decoder Vulkan está preso em ~1 GFLOPS (e onde estão os 2-3×)

## Medições (lavapipe, o mesmo driver Vulkan do emulador de aceitação)

Sonda de teto `ci/lab_compute/ceiling.comp`, bloco 32, 8192 grupos, 128 iterações,
3 repetições, mesmo runner, run 35469710547
(`ci-results/35469710547-1-llvmpipe-lab/physical-llvmpipe-ceiling.txt`):

| padrão | forma por iteração | GMAC/s |
|---|---|---:|
| 0 | 1 carga vec4 + 1 FMA vec4 (4 MACs) | 0,736 |
| 2 | 1 carga vec4 + `dot()` | 0,754 |
| 3 | nibble + `dot()` (forma do DMMV) | 0,720 |
| 4 | nibble + acumulação elemento a elemento | 0,723 |
| 7 | 1 carga vec4 + 4 acumuladores independentes (ILP 4) | 0,708 |
| 8 | **só cargas** (4 somas, sem FMA) | 0,768 |
| 9 | **4 FMA independentes, nenhuma carga** | **2,449** |
| 10 | 1 carga + 4 FMA encadeados | 0,747 |

Modelo: **uma carga de 16 bytes custa ~1,27 ns; quatro MACs custam ~0,54 ns**.
Tudo que faz uma carga por iteração fica em ~0,7 GMAC/s; a mesma conta sem
carga nenhuma chega a 2,45 GMAC/s (3,4×). ILP não muda nada (7 ≈ 0); cargas
sozinhas (8) são tão lentas quanto cargas+FMAs (0). Ou seja: **o caminho de
decodificação é limitado por número de cargas, não por FMA nem por dependência**.

Isso explica todos os resultados nulos anteriores: o patch de acumuladores
(`dmmv_accum_lab_patches`) e o de linhas por grupo de trabalho
(`row_tile_patches`) mudam a *forma* do acumulador, não a **contagem de cargas**
por MAC — e por isso mediram 0.

## O que o kernel real faz

`mul_mat_vec.comp`, caminho `K_PER_ITER == 8` com `dequantize4` (Q5_0, via
`data_a_packed16`), por 8 valores e por linha:

| carga | quantidade |
|---|---:|
| `qh[0]`, `qh[1]` (16 bits cada, repetidas nas duas chamadas) | 4 |
| `qs[iqs/2]` (16 bits cada) | 2 |
| `get_dm` → `d` (16 bits) | 1 |
| B: 2 × vec4 (compartilhadas por NUM_ROWS linhas) | 2 |
| **total** | **9 cargas / 8 MACs = 1,1 carga por MAC** |

9 × 1,27 ns = 1,43 ns/MAC ⇒ 0,70 GMAC/s. O perfil de ops mede 0,6-0,65 GMAC/s
nos matvecs n=1 (1,0-1,3 GFLOPS) e 2,2-2,75 GMAC/s nos `MUL_MAT` em lote — o
lote amortiza a mesma carga em 30 colunas, exatamente o modelo acima.

Distribuição do tempo de decodificação por token (perfil 35156484592-1,
268 ms/token): gate+up q5_0 88 ms, vocabulário q8_0 43 ms, qkv 34 ms,
down q6_K 21 ms, o_proj q5_0 20 ms, down q4_K 14 ms, atenção 20 ms,
RMS_NORM 12 ms, ROPE 7 ms, GLU+misc 9 ms.

## Correção proposta (bit a bit idêntica)

Reempacotar os pesos quantizados **na memória da GPU, no momento da carga**
(nunca no arquivo GGUF), num layout alinhado em 4 bytes que preserve os mesmos
bits: para Q5_0, bloco de 24 bytes

```
[u32: d (f16) + 16 bits de preenchimento] [u32: qh] [uvec4: qs]
```

O shader passa a extrair exatamente os mesmos campos com as mesmas expressões
(`rowtmp *= dm.x` continua depois do `dot`), portanto o resultado é **idêntico
bit a bit** — sem mudança de precisão, de arredondamento ou de ordem de soma.
Cargas por 8 valores e por linha caem de 7 para 3; com NUM_ROWS=2 o total cai de
9 para 4 cargas por 8 MACs, ou seja ~0,5 carga/MAC ⇒ ~1,6 GMAC/s (2,3×) nesses
matvecs. O mesmo tratamento vale para Q8_0 (vocabulário), Q4_K e Q6_K.

Custo de memória: 24/22 bytes por bloco Q5_0 (+9% nos tensores Q5_0, ~+3% no
modelo) e 36/34 em Q8_0 (+6%).

Estimativa conservadora sobre o token inteiro, se só Q5_0 e Q8_0 melhorarem:
268 ms → ~171 ms (1,57×); incluindo Q4_K/Q6_K, ~1,7-2,0×. O restante
(atenção, RMS_NORM, ROPE, GLU: ~48 ms) também é feito de cargas pequenas e é o
próximo alvo.

## Validação

1. Laboratório `llvmpipe-lab` (host, mesmo driver): controle puro vs variante,
   `llama-bench` decodificação, perfil de ops por tipo e **comparação do texto
   greedy** — só vale se o texto for idêntico.
2. Harness de aceitação no emulador: três pares alternados, tela ligada e
   apagada, saídas completas e contadores nativos iguais.

## Atualização: a comparação com dados em cache subestimava o efeito

Run 35471983921 (probe), mesmo runner, três formatos para os mesmos 8 MACs:

| padrão | cargas por 8 MACs | leitura | GMAC/s |
|---|---:|---|---:|
| 0 | 1 (vec4) | janela de 1 MB em cache | 0,737 |
| 11 | 5 (a forma fixada do Q5_0) | janela em cache | 1,005 |
| 12 | 2 (bloco alinhado) | janela em cache | 1,134 |
| 13 | 5 (a forma fixada do Q5_0) | **stream de 256 MiB** | 1,145 |
| 14 | 2 (bloco alinhado) | **stream de 256 MiB** | **1,659** |
| 15 | 1 (vec4 contígua) | stream de 256 MiB | 1,443 |

Em cache, tirar 3 das 5 cargas vale 1,13x. Com os pesos vindo da memória de
verdade (100 MB por token, como no modelo), vale **1,45x** — e uma única carga
vetorial (15) não supera o par de palavras alinhadas (14), porque lê o dobro de
bytes por MAC.

Isto é o contrário da conclusão anterior: a contagem de cargas não importa
quando tudo cabe em cache, e importa muito quando não cabe. As medições de
11/12 (e o "padrão 11 == padrão 12") mediam o caso errado.

Observação de método: os absolutos variam até 3x entre runners (p0 = 2,319
GMAC/s no run 35470651775, 0,737 no 35471983921). Só razões dentro do mesmo run
valem.

## O que implementar agora

Reempacotar Q5_0 e Q8_0 na memória da GPU, no upload, para blocos alinhados em 4
bytes que preservam exatamente os mesmos bits:

```
Q5_0  22 B -> 24 B : [u32: d(f16) | qh] [uvec4: 16 bytes de nibbles]
Q8_0  34 B -> 36 B : [u32: d(f16) | 0]  [uvec4: 8 palavras de 4 int8]
```

Cada 8 valores passa de cinco cargas (dois pedaços do qh, dois pedaços de qs,
a escala) para duas. Os valores são montados com as mesmas expressões, então o
resultado é bit a bit o mesmo: nenhuma mudança de precisão, GGUF intacto.

Custo de memória: +9% nos tensores Q5_0 e +6% nos Q8_0 (alguns MB, não os 538 MB
da expansão para F32 que já foi rejeitada).

Escopo: Q5_0+Q8_0 somam 19,3 s dos 37,4 s medidos no perfil de 128 tokens (52%).
Com 1,45x neles, o token inteiro cai ~1,3x. Para o 2x ainda faltam: o mesmo
tratamento nos K-quants (q4_K/q6_K, 4,5 s), o caminho de atenuação
(FLASH_ATTN a 0,88 GFLOPS/s, 2,8 s) e as operações pequenas (norm 1,5 s, rope
1,0 s, glu 0,6 s — cada uma pagando a taxa fixa de despacho do driver).
