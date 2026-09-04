# NEURA — linguagem de programação leve, focada em IA

**Download:** [`NeuraStudio.exe`](./NeuraStudio.exe) — compilador/IDE já compilado para Windows x64. Sem instalação, sem dependências, arquivo único (~240 KB).

## O que é
NEURA é uma linguagem de script minimalista, em português, com **tensores e redes neurais nativas na linguagem** (não em biblioteca externa). O `.exe` traz o interpretador completo + uma IDE gráfica (editor, console, 7 exemplos prontos, F5 para executar, F1 para a referência).

## Exemplo — XOR resolvido por uma rede neural
```
semente(42)

seja X = tensor([[0,0], [0,1], [1,0], [1,1]])
seja Y = tensor([[0],   [1],   [1],   [0]])

seja rede = modelo("xor")
camada(rede, 2, 8, "tanh")
camada(rede, 8, 1, "sigmoide")
taxa(rede, 0.5)

treina(rede, X, Y, 4000)
imprime(prever(rede, X))
```
Saída: `tensor(4x1)[0.0124; 0.9811; 0.9814; 0.0224]`

## Referência rápida
| Área | Recursos |
|---|---|
| Variáveis | `seja`, `var` |
| Controle | `se / senao`, `enquanto`, `para i = 0 ate n : passo`, `quebra`, `continua` |
| Funções | `func nome(a, b) { retorna a + b }` (recursão suportada) |
| Operadores | `+ - * / % **`, `== != < > <= >=`, `e ou nao`, `@` (produto matricial) |
| Gerais | `imprime texto numero tipo tamanho lista adiciona` |
| Matemática | `raiz abs exp log sin cos piso teto arred pot min max aleatorio semente` |
| Tensores | `tensor zeros aleatorios transposta multiplica argmax soma media linhas colunas`, indexação `t[i, j]` |
| Redes neurais | `modelo camada taxa perda treina prever resumo` |
| **E/S binária** | `abrir fechar posicao`, `esc_u8 esc_u16 esc_u32 esc_u64 esc_f32`, `esc_bytes esc_texto esc_zeros esc_tensor` (little-endian) |
| **Pesos** | `gauss preenche constante desvio` |
| Ativações | `relu`, `sigmoide`, `tanh`, `softmax` |
| Perdas | `eqm` (erro quadrático médio), `entropia` (entropia cruzada) |

A E/S binária permite escrever formatos de arquivo reais na própria linguagem — veja [`gguf_gen/make_gguf.nr`](./gguf_gen/make_gguf.nr), um gerador de GGUF de 300M de parâmetros escrito em NEURA.

Treinamento usa retropropagação completa com gradiente descendente; softmax + entropia cruzada têm gradiente otimizado.

## Como usar
1. Baixe o `.exe`.
2. Execute (Windows 10/11 x64). O SmartScreen pode pedir "Mais informações → Executar assim mesmo" por ser binário sem assinatura.
3. Escolha um exemplo no menu suspenso, clique **Carregar** e pressione **F5**.
4. Salve seus programas com extensão `.nr`.
