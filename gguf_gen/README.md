# make_gguf.py — gerador de GGUF profundo e estreito

Cria um modelo GGUF de ~300M de parâmetros com pesos aleatórios, arquitetura estilo LLaMA, **profunda e estreita**.

## Uso

```bash
python make_gguf.py --out modelo-300m.gguf --verify    # 85 camadas x 512 = 300.24M
python make_gguf.py --dry-run                          # só mostra a arquitetura
python make_gguf.py --auto-depth --target-params 500e6 # calibra n_layer/n_ff sozinho
python make_gguf.py --dtype f32                        # ou --dtype bf16
```

Requer apenas Python 3.8+ e numpy. O escritor GGUF v3 é implementado do zero, sem o pacote `gguf`.

## Configuração padrão

| | |
|---|---|
| camadas | **85** (profundo) |
| hidden size | **512** (estreito) |
| heads q / kv | 8 / 4 — GQA, head_dim 64 |
| feed-forward | 1536 (SwiGLU) |
| vocabulário | 32000 |
| parâmetros | **300.242.432** |
| arquivo (f16) | 573 MiB, 768 tensores |

Razão profundidade/largura de 0,166 camadas por unidade de largura — para comparar, o LLaMA-7B fica em 0,0078. Este modelo é ~21x mais profundo em relação à largura.

## Detalhes de implementação

- **Streaming**: tensores são gerados e gravados um a um; o pico de RAM é o maior tensor (~31 MiB), não o modelo inteiro. Escrita em dois passes (planejar offsets → gravar dados).
- **Init escalada pela profundidade**: projeções que escrevem no residual (`attn_output`, `ffn_down`) usam `std / sqrt(2·n_layer)`, no estilo GPT-2/DeepNet. Sem isso, 85 camadas empilhadas explodem a variância do residual.
- **Ordem das dimensões**: o GGUF grava `ne` invertido em relação ao PyTorch — um peso `(out, in)` vira `ne = [in, out]`.
- **Normas em F32** (como o llama.cpp faz) e tokenizer sintético de 32k tokens, para o arquivo carregar sem metadados faltando.
- **BF16** convertido à mão com round-to-nearest-even.

## Verificação

`--verify` relê o arquivo com um parser independente do escritor e confere magic, versão, contagem de tensores, soma de parâmetros, vocabulário e truncamento.

Saída validada também pela biblioteca oficial `gguf`: 768 tensores, 300.242.432 parâmetros, shapes e tipos corretos, `attn_q.std = 0.02790` (esperado 0.02795) e `attn_output.std = 0.00214` (esperado 0.00214, escalado pela profundidade).

---

# make_gguf.nr — a mesma coisa, escrita em NEURA

Versão do gerador escrita **na própria linguagem NEURA**, rodando dentro do `NeuraStudio.exe`.
Para isso a NEURA 1.1 ganhou E/S binária: `abrir`, `esc_u8/u16/u32/u64/f32`, `esc_bytes`, `esc_texto`, `esc_zeros`, `esc_tensor` (f32/f16/bf16), mais `preenche`, `constante`, `gauss` e `desvio` para os pesos.

```
NeuraStudio.exe  ->  Abrir  ->  make_gguf.nr  ->  F5
```

Produz o mesmo modelo: **768 tensores, 300.242.432 parâmetros, 574 MiB, em ~19 s**.
O arquivo resultante é lido sem erros pela biblioteca oficial `gguf`, com `attn_output.std = 0.002140` (esperado 0.002144, escalado por `sqrt(2·85)`).

O programa calcula o tamanho exato do cabeçalho antes de escrever qualquer byte — e confere o próprio cálculo em tempo de execução, comparando `posicao(f)` com o valor previsto.
