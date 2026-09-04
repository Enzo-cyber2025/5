# InterFrame AI

**Interpolação de frames por IA — offline.** Um único `.exe` para Windows x64, sem
dependências, com uma rede neural **projetada e treinada do zero para este projeto**.

Você entrega um vídeo (ou uma pasta de frames) e recebe o mesmo vídeo com
**2×, 3×, 4× ou 8× mais frames**, com a duração preservada e a taxa de quadros
multiplicada. Um clipe de 30 fps a 4× vira 120 fps.

---

## ⚠️ Leia isto primeiro — o que este programa **não** faz

**Ele não injeta frames em jogos em execução.** Não existe aqui nenhum modo
"ativar e ganhar FPS". Isso não é limitação de implementação, é física — e
qualquer `.exe` que prometa isso num Pentium N5030 está mentindo para você.

Os números abaixo são **medidos**, não estimados (`--bench` os reproduz):

| | |
|---|---|
| Orçamento de um frame a 60 fps | **16,6 ms** — e a rede rodaria *além* do jogo já renderizando |
| Custo real medido deste modelo a 720p | **5.391 ms por frame** (nesta máquina, 2 núcleos) |
| Estimativa no N5030 | **6.000–12.000 ms por frame** |
| Fator pelo qual estoura o orçamento | **~325× aqui, ~400–700× no N5030** |

E há um segundo motivo, independente de velocidade: **frame generation adiciona
latência por definição.** Para inventar o frame *entre* A e B é preciso segurar A
até B existir. São +16 a +33 ms de input lag no mínimo, *mesmo com um modelo
instantâneo*. "Sem queda de FPS e sem latência" é contraditório com a técnica.

Por isso a NVIDIA exige um bloco de silício dedicado (Optical Flow Accelerator)
**e** uma RTX série 40 **e** uma base acima de ~45 fps — e mesmo assim adiciona
latência. Frame gen *multiplica* uma base alta; nunca resgata uma base baixa.

**O que este programa entrega é real e funciona:** o mesmo princípio técnico de
RIFE / Flowframes / SVP, aplicado offline. Roda no seu PC, não encosta no jogo, e
produz vídeo genuinamente mais fluido. O preço é tempo de processamento — medido
e documentado abaixo, sem otimismo.

---

## Download

**Link direto do `.exe`:**

```
https://github.com/Enzo-cyber2025/5/raw/arena/01a06952-5/dist/InterFrameAI.exe
```

Página do arquivo (com botão *Download raw*):

```
https://github.com/Enzo-cyber2025/5/blob/arena/01a06952-5/dist/InterFrameAI.exe
```

Tamanho: **428.544 bytes** (~419 KiB). Sem instalador, sem `.dll`, sem
dependência de terceiros. Os pesos treinados estão embutidos no binário —
verificado byte a byte contra o blob FP16 exportado (offset 231.072, 76.395
valores, todos não-nulos).

> **Por que o link aponta para um arquivo do repositório e não para um Release?**
> O ambiente de compilação usado aqui não alcança `uploads.github.com`, então o
> upload de *assets* de Release falha. Commitar o binário mantém o link direto
> funcionando normalmente no seu navegador.

---

## Requisitos

- Windows 10 ou 11, x64. Usa o Universal CRT, nativo dessas versões.
- Nenhum outro software para sequences de PNG/BMP.
- **Opcional:** `ffmpeg.exe` na mesma pasta do `.exe` para ler/gravar MP4, MKV,
  WebM, MOV, GIF. Sem ele o programa continua 100% funcional com pastas de
  frames — e avisa isso na interface.
- **4 GB de RAM são suficientes.** O pico medido a 1080p é ~121 MB.

Não há exigência de GPU. Tudo roda em CPU, em SSE2 — que é exatamente o conjunto
de instruções que o Goldmont Plus do N5030 tem (ele não tem AVX).

---

## Como usar

### Interface gráfica

1. Dois cliques em `InterFrameAI.exe` (ou arraste um arquivo/pasta para a janela).
2. **Input** — pasta com frames `.png`/`.bmp`, ou arquivo de vídeo.
3. **Output** — o caminho é sugerido automaticamente:
   - `.png` ou `.bmp` → grava uma **pasta de frames** (zero dependências)
   - `.mp4` / `.mkv` / `.webm` → grava **vídeo** (precisa do `ffmpeg.exe`)
4. **Multiplier** — 2, 3, 4 ou 8.
5. **Start interpolation.** Barra de progresso e log mostram o andamento.

| Controle | O que faz |
|---|---|
| **Threads** | `Auto` usa todos os núcleos. Em máquinas fracas, fixar em 2 reduz pressão de memória. |
| **Tile (px)** | Tamanho do bloco processado. Menor = menos RAM. `Auto` deriva do orçamento de memória. |
| **Fast mode (half res)** | Roda a rede em meia resolução e reamplstra o resultado. **3,9× mais rápido** e ~4× menos tráfego de memória, com perda de detalhe fino. **Recomendado para o N5030.** |

### Linha de comando

```bat
InterFrameAI.exe --info                 :: dados do modelo e da máquina
InterFrameAI.exe --selftest             :: teste de sanidade embutido
InterFrameAI.exe --bench                :: mede o throughput real por resolução

InterFrameAI.exe entrada.mp4 saida.mp4 -m 4
InterFrameAI.exe C:\frames_in C:\frames_out.png -m 2 -t 4
InterFrameAI.exe clip.mp4 clip_fast.mp4 -m 4 --scale 0.5
```

Opções: `-m` multiplicador · `-t` threads (0 = auto) · `--tile` px (0 = auto) ·
`--mem` orçamento em MB · `--scale` 1.0 ou 0.5 (modo rápido).

---

## Desempenho: medido, não prometido

Rodando `--bench` nesta máquina de compilação (2 núcleos visíveis, sem GPU),
com os pesos reais embutidos:

| Resolução | 1 thread | 2 threads | frames/s (2 thr) |
|---|---|---|---|
| 320×240 | 733 ms | **555 ms** | 1,80 |
| 640×360 | 2.552 ms | **1.341 ms** | 0,75 |
| 854×480 | 4.479 ms | **2.226 ms** | 0,45 |
| 1280×720 | 10.126 ms | **5.391 ms** | 0,19 |
| 1920×1080 | 24.463 ms | **12.240 ms** | 0,08 |

Modo rápido (`--scale 0.5`) medido no profiler: 720p cai de 5.288 ms para
**1.375 ms** — **3,85× mais rápido**.

O custo escala linearmente com o número de pixels, como deveria: 76.032
MACs por pixel × pixels do frame.

### Estimativa para o Pentium N5030

Não há um N5030 neste ambiente, então isto é **estimativa**, e está marcada como
tal. O Goldmont Plus tem núcleo individual bem mais fraco e DDR4 single-channel
(~19 GB/s), mas tem 4 núcleos contra os 2 medidos aqui — os dois efeitos se
compensam parcialmente:

| Cenário | Estimativa por frame |
|---|---|
| 1080p, qualidade total | ~12–25 s |
| 720p, qualidade total | ~6–12 s |
| 720p, modo rápido | ~2–4 s |
| 480p, modo rápido | ~0,7–1,5 s |
| 360p, modo rápido | ~0,4–0,8 s |

Tempo total para um clipe de **10 s a 30 fps**:

| Configuração | 2× (299 frames) | 4× (897 frames) |
|---|---|---|
| 360p, modo rápido | ~2–4 min | ~6–12 min |
| 480p, modo rápido | ~3,5–7 min | ~10–22 min |
| 720p, modo rápido | ~10–20 min | ~30–60 min |
| 720p, qualidade total | ~30–60 min | ~1,5–3 h |

**Recomendação prática para o seu hardware:** use o *Fast mode* e trabalhe em
480p ou 720p. Rode como processo de fundo — não é interativo e não foi
projetado para ser.

---

## O modelo

**NDRI — Narrow-Deep Residual Interpolator.** Arquitetura e pesos são originais
deste projeto; nada foi baixado de terceiros.

| | |
|---|---|
| Parâmetros | **76.395** (~75K, conforme especificado) |
| Largura / profundidade | 24 canais · 14 blocos residuais |
| Dilatações | `1 1 1 2 2 4 4 4 2 2 1 1 1 1` (ampulheta) |
| Campo receptivo | ~57 px **sem gastar um parâmetro extra** |
| Entrada | 13 canais: `I0`, `I1`, blend linear, diferença `I1−I0`, e `t` |
| Saída | **resíduo** sobre o blend `(1−t)·I0 + t·I1` |
| Ativação | LeakyReLU (0,1) — sem parâmetros |
| Quantização | **IEEE-754 binary16** → 149,2 KiB no binário |
| Aritmética | FP32 com vetorização SSE2 |

Decisões de projeto que importam:

- **Estreita e profunda**, como pedido. Profundidade compra campo receptivo;
  estreiteza mantém o footprint — e portanto o tráfego de memória — pequeno.
- **Resíduo sobre o blend linear.** A rede nunca inventa um frame do zero: ela
  prevê a *correção* do cross-fade. Isso transforma "alucinar uma imagem" em
  "remover o ghosting", que é o que um modelo de 75K parâmetros consegue
  realmente aprender.
- **`t` é um canal de entrada**, então **uma única rede atende todos os
  multiplicadores** (2×, 3×, 4×, 8×) sem pesos separados.
- **Sobre a quantização 16-bit que você pediu:** ela corta o modelo pela metade e
  reduz tráfego de memória, que é o gargalo do N5030. Mas o Goldmont Plus não tem
  SIMD FP16, então o compute continua em FP32 — **FP16 aqui é armazenamento, não
  aritmética**. O ganho real é footprint e banda, não FLOPS.

### Treinamento

- **Framework:** NumPy puro, com **backpropagation escrita à mão**. PyTorch não
  estava disponível no ambiente (rede restrita a PyPI e GitHub).
- **Dataset:** **sintético, gerado durante o treino** — nenhuma base externa.
  Texturas com espectro 1/f (estatística de imagem natural), formas estruturadas
  e **duas camadas com movimento independente**, o que produz oclusão e
  desoclusão reais. O ground truth é amostrado analiticamente no instante `t` da
  mesma cena de alta resolução, então a supervisão não carrega erro de
  interpolação.
- **Loss:** L1 + 0,25 × L1 das diferenças espaciais de primeira ordem — mantém
  bordas que o L1 puro borra, o principal modo de falha de redes pequenas.
- **Otimizador:** Adam, lr 2e-3, cosine schedule com warmup, 6.000 steps,
  batch 8, patches 48×48, `max_motion` 13, EMA de pesos.
- **Custo:** 57,9 min em 2 núcleos (13,8 amostras/s).
- **Métrica de honestidade:** toda avaliação imprime o ganho **sobre o blend
  linear**. Uma rede de interpolação que não vence um cross-fade ingênuo não
  serve para nada, então essa comparação nunca fica escondida atrás de um PSNR
  absoluto.

### Resultado

Checkpoint selecionado: **step 5.500** (melhor ganho no conjunto de validação).

Validação usada durante o treino (48 patches, 96 px, movimento ≤12):

```
PSNR 18.384 dB   vs blend linear 16.433 dB   =>  ganho +1.952 dB
erro médio (L1) 16,8% menor que o blend
```

Avaliação **independente** posterior, com outra semente e outras 64 amostras
(`tools/quality_demo.py`, reproduzível):

| | modelo | blend linear |
|---|---|---|
| PSNR médio | **20,900 dB** | 19,224 dB |
| ganho médio | **+1,675 dB** | — |
| ganho mediano | +1,679 dB | — |
| desvio padrão | 0,933 dB | — |
| **pior caso** | **−2,182 dB** | — |
| melhor caso | +3,691 dB | — |
| vence o blend em | **96,9% dos casos** | — |
| erro médio L1 | **14,6% menor** | — |

Teste de estresse **fora da distribuição** (movimento ≤22, bem acima do treino):
ganho médio **+1,582 dB**, pior caso **+0,224 dB**, vence em **100%** dos casos.
Com movimento grande o blend ingênuo produz ghosting severo, então o modelo tem
mais o que corrigir e nunca perde.

**O pior caso de −2,18 dB é real e está aqui de propósito.** Em ~3% das amostras
o modelo produz um frame ligeiramente pior que um cross-fade. Não é um defeito a
esconder, é o comportamento esperado de uma rede de 75K parâmetros.

Quantização para FP16 (o que você pediu):

```
erro relativo médio de quantização : 0,0179 %
custo em PSNR de armazenar em 16 bits : -0,0000 dB   (nenhum mensurável)
diferença máxima de pixel FP32 vs FP16 : 0,067 / 255
```

Ou seja: **FP16 saiu de graça** — metade do tamanho, perda indetectável.

---

## Verificação

Não há máquina Windows neste ambiente, então o `.exe` pôde ser **compilado,
inspecionado e publicado, mas não executado**. Em vez de fingir o contrário, eis
o que foi verificado — e como.

> **Sobre reprodutibilidade:** o requisito da entrega foi *somente o `.exe`, sem
> código fonte*, e este repositório respeita isso — contém apenas o binário e
> este README. Os resultados abaixo foram produzidos por um harness de testes
> real (`verify_all.sh`, `parity.py`, `test_codec.py`, `test_e2e.py`,
> `quality_demo.py`, `inspect_pe.py`) que existe e roda, mas **não está
> publicado aqui**. Consequência honesta: você pode conferir os números, mas não
> pode reexecutá-los a partir deste repositório. Se quiser auditá-los, me peça o
> fonte e eu entrego por outro canal ou publico num repositório separado.

| Verificação | Método | Resultado |
|---|---|---|
| **Backpropagation correta** | Gradient check numérico em **float64** contra diferenças finitas, nos 14 blocos + projeções | pior erro relativo **2,181e-08** |
| **Convolução dilatada + adjunta** | im2col e operador adjunto contra implementação ingênua de referência e contra a transposta explícita, d = 1/2/4 | erro **~1e-16** (precisão de máquina) |
| **Paridade Python ↔ C** | O motor C é independente de plataforma; um build Linux nativo roda **exatamente** a mesma aritmética do `.exe`, comparado à referência NumPy com os mesmos pesos FP16 | **11/11 casos**, pior diff **5,07e-07** |
| **Codec PNG** | Arquivos escritos pelo Pillow (níveis 0/6/9) lidos pelo codec C, e vice-versa — pixel a pixel | **34/34** |
| **CRC-32 / Adler-32 / DEFLATE** | Validados pelo `zlib` do Python | todos corretos |
| **Codec BMP** | Ida e volta contra o Pillow, inclusive dims ímpares | **4/4** |
| **Pipeline ponta a ponta** | Sequências PNG/BMP nos multiplicadores 2/3/4/8 | **16/16** — contagem `(n−1)·m+1` exata |
| **Ordem dos frames** | Natural sort (`f2` antes de `f10`) | brilho `[0,10,20,30,40,120,200,210,220]` — ordem e pontos médios exatos |
| **Bridge ffmpeg (MP4)** | MP4 → MP4 com ffmpeg 7.0.2 real | 30 fps → **120 fps**, duração preservada |
| **PE do `.exe`** | Header, subsystem, seções e tabela de imports inspecionados | x86-64 PE32+, **WINDOWS_GUI**, **zero DLLs de terceiros** |
| **Pesos embutidos** | Blob FP16 comparado byte a byte com o array C e procurado dentro do `.exe` | **idêntico**, offset 231.072 |
| **Vazamento de fonte** | Busca de marcadores de código no binário | nenhum |

### Bugs reais que esses testes encontraram

Nenhum destes era hipotético; todos foram corrigidos e têm teste de regressão:

1. **Limites invertidos na convolução dilatada — `max(0, +shift)` em vez de
   `max(0, −shift)`.** Num lado da borda isso descartava taps; no outro lia
   *antes* do início do buffer — uma **leitura fora dos limites** de verdade.
   Ficou invisível enquanto os pesos eram placeholder zero, porque taps nulos são
   pulados. Só apareceu com os pesos treinados. Diagnosticado por um perfil de
   erro versus distância da borda: exato (4e-07) a ≥20 px, até 4,4e-01 na borda.
   Os 11 casos de paridade agora incluem imagens 5×5 e 12×9, onde *todo* pixel é
   borda, para que o bug não possa voltar silenciosamente.
2. **`popen(cmd, "rb")`** — o glibc rejeita o sufixo `b` com `EINVAL`; é um
   Windows-ism do `_popen`. Quebrava todo o caminho de vídeo em Linux.
3. **Alinhamento de byte em blocos DEFLATE *stored*** — zerar o buffer de bits
   descartava dados já consumidos, corrompendo qualquer PNG incomprimível.
4. **Árvore Huffman de símbolo único** — zlib emite isso para o código de
   distância em blocos sem back-references; o decodificador canônico falhava no
   bit `1`.
5. **Deflate sem fallback *stored*** — **expandia** o arquivo em 5,5% para dados
   incomprimíveis. Agora o overhead é de 11 bytes, o mínimo possível.
6. **Amostragem de PNG 16-bit** lendo o byte baixo do canal como canal seguinte.
7. **CRC do IHDR** lendo 17 bytes de um buffer de 8 (out-of-bounds).
8. **Colisão de nome** entre o `HWND` do botão Cancel e a flag atômica de
   cancelamento.
9. **`OUT` é uma macro vazia nos headers do Windows** (herança do RPC/SAL), então
   `free(OUT)` compilava como `free()` e o build Windows falhava.
10. **Harness de gradient check** restaurando pesos por *rebinding* em vez de
    in-place, o que fazia as sondas seguintes lerem `num = 0.0` e reportarem um
    falso FAIL.

### Duas medições que eu mesmo invalidei

- **O benchmark original era lixo.** Foi medido com pesos placeholder zero, onde
  `if (w == 0.0f) continue;` pula todo o multiply-accumulate. Reportava 936 ms a
  720p; o custo real era **27.922 ms** — 30× pior. Descoberto porque um profiler
  que não checava código de retorno "media" 425 ms para um trabalho que
  exigiria 250 GFLOP/s de 2 núcleos: fisicamente impossível. O profiler agora
  verifica o retorno e falha em voz alta.
- **O self-test original era enganoso.** Avaliava em gradientes com bordas duras
  — fora da distribuição de treino — e imprimia "9,0% **pior** que o blend".
  Reescrito para gerar conteúdo com a mesma receita estatística do treino
  (texturas 1/f, duas camadas móveis, motion blur), implementada
  independentemente em C. Agora reporta **+8,5% de precisão** e **+0,734 dB**.

### Otimização que saiu dessa investigação

O perfil mostrou que a convolução planar original fazia **576 passadas completas
sobre a imagem por bloco** (`Cout × Cin`), sustentando ~0,45 MAC/cycle.
Reescrita com layout **HWC intercalado** e caminho **SSE2 processando 4 pixels
por vez**, com os acumuladores em registradores e cada vetor de peso reutilizado
nos 4 pixels:

| | antes | depois |
|---|---|---|
| 1280×720, 2 threads | 27.922 ms | **5.288 ms** |
| 128×128, 2 threads | 751 ms | **150 ms** |
| MAC/cycle por thread | ~0,45 | ~2,2 |

**5,28× mais rápido**, com a paridade Python↔C inalterada em 5,07e-07 e a
qualidade idêntica (+0,734 dB no self-test, antes e depois). A borda continua no
caminho escalar explícito, então a semântica de zero-padding é a mesma por
construção.

Fica em SSE2 de propósito: **o Goldmont Plus do N5030 não tem AVX nem FMA**, e um
binário com AVX morreria com `SIGILL` exatamente na máquina a que se destina.

---

## Limitações reais

- **Não é tempo real.** Veja a abertura. Nenhuma configuração muda isso.
- **Lento em hardware fraco.** Mesmo otimizado: minutos a dezenas de minutos por
  clipe curto no N5030. É uma ferramenta offline.
- **Treinado em dados sintéticos.** O gerador produz estatística de imagem
  natural e oclusão real, mas não é footage de câmera. Em textura muito fina
  (grama, água, cabelo) espere mais artefatos do que um modelo treinado em
  Vimeo-90K com dias de GPU.
- **Perde do blend em ~3% dos casos** (pior caso −2,18 dB). Documentado acima.
- **Movimento grande.** O campo receptivo é ~57 px; deslocamentos maiores por par
  de frames degradam a qualidade — reduza o multiplicador.
- **Caminhos Unicode fora do code page ANSI.** A interface usa as APIs `A` do
  Win32 de ponta a ponta. Acentuação em português funciona; caracteres fora do
  code page da máquina podem falhar.
- **PNG entrelaçado (Adam7)** não é suportado — o erro é explícito, não silencioso.
- **Nunca executado em Windows.** Compilado, inspecionado, com pesos verificados
  byte a byte e aritmética validada num build nativo idêntico — mas sem teste de
  runtime em Windows. Esta é a maior lacuna residual e não posso fechá-la daqui.

---

## O que há neste repositório

Conforme o requisito da entrega:

```
dist/InterFrameAI.exe   o programa (428.544 bytes)
README.md               este arquivo
```

**Nada mais.** Sem código fonte, sem scripts de build, sem harness de testes —
eles foram usados para produzir e validar o binário, e permanecem fora do
repositório.

O binário é autossuficiente: os pesos FP16 treinados estão embutidos nele
(verificado byte a byte contra o blob exportado, offset 231.072, 76.395 valores,
todos não-nulos). Não há arquivo de modelo para baixar separadamente, nem
configuração, nem instalação.

Para referência, o que foi construído para chegar aqui — descrito, não
publicado: um modelo NDRI (76.395 parâmetros) com backpropagation escrita à mão
em NumPy puro; um motor de inferência em C com convolução dilatada vetorizada em
SSE2, tiling e threads; codecs DEFLATE/PNG/BMP escritos à mão; uma interface
Win32; e uma ponte opcional para ffmpeg.

---

## Licença

O código deste projeto é original. O `ffmpeg.exe` **não** é distribuído aqui — é
um programa separado, GPL/LGPL, obtido em [ffmpeg.org](https://ffmpeg.org) se
você quiser suporte a contêineres de vídeo. Mantê-lo como processo externo e
opcional evita qualquer conflito de licença com este binário.
