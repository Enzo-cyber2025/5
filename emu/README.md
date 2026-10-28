# emu — tradutor binário dinâmico x86-64 → ARM64, escrito do zero

App de emulação novo, para Android ARM64. Objetivo declarado: executar binários
x86-64 com cache de tradução persistente, e superar `Box64 + DXVK` em perda de
desempenho durante a tradução em tempo real.

## Escopo de "sem bibliotecas preexistentes"

Interpretado como: **nenhuma biblioteca de emulação, tradução ou compatibilidade**
— sem Box64, FEX, QEMU, Dynarmic, Wine, DXVK, nem trechos deles. Todo o
decodificador, IR, emissor ARM64, loader, camada de syscalls e cache são escritos
aqui.

O que **não** é possível evitar, e não está incluído nessa promessa: NDK/libc,
loader Vulkan do Android, ART/DEX, e o toolchain de build. Um app Android que não
use libc nem o loader Vulkan não existe.

## Três correções de arquitetura

### 1. Pré-tradução via GPU (Vulkan) — não funciona para tradução de CPU

A ideia original era usar a GPU com a tela apagada para pré-traduzir. Isso não se
sustenta, por três razões independentes:

- **x86-64 tem comprimento variável (1–15 bytes).** Não se sabe onde termina a
  instrução em `N` sem decodificar `N`. GPU exige trabalho uniforme, independente
  e data-paralelo sobre arrays grandes; decodificação é sequencial, branchy e
  depende de contexto. É o pior caso possível para SIMD.
- **Um tradutor dinâmico só descobre o que executa em runtime.** Saltos indiretos,
  código gerado em runtime e automodificação não são conhecíveis estaticamente.
  Pré-traduzir exige descoberta estática, e a varredura linear de x86 produz
  instruções falsas em offsets errados.
- **Latência de dispatch.** Um launch de compute custa dezenas de µs; um basic
  block traduz em µs unitários. O custo de ida e volta à GPU excede o ganho.

Onde Vulkan compute **realmente** pertence neste projeto:

- **(a) Renderização do guest** — a camada D3D→Vulkan, que é o que DXVK faz. Esse
  é o trabalho de GPU de verdade e a alavanca de performance em jogos.
- **(b) Trabalho genuinamente paralelizável** — hash/validação em lote de entradas
  do cache, varredura de páginas para detectar automodificação, predição de alvos
  de salto indireto. Ganhos modestos e mensuráveis.

### 2. "Tela apagada" — correto, e implementável

A parte certa do pedido. Em Android isso é `WorkManager` com
`setRequiresDeviceIdle(true)` + restrição de carga, ou um foreground service. O
trabalho útil ali é uma **varredura estática do código alcançável a partir dos
pontos de entrada**, aquecendo o cache de tradução. Expectativa honesta: aquece a
maior parte do código quente; saltos indiretos e código gerado em runtime ainda
exigem tradução durante a execução. **Aquece o cache, não substitui o JIT.**

### 3. "Perda menor que Box64 + DXVK" — é meta de benchmark, não garantia de design

Box64 são ~10 anos de trabalho e centenas de milhares de linhas, com um dynarec
ARM64 afinado à mão. Superá-lo partindo do zero é esforço de anos e de equipe. O
que este projeto se compromete a fazer é não ter desvantagem **estrutural**, e
medir com honestidade em cada marco — números reais, não promessa.

Métrica definida agora, para não ser movida depois:

| métrica | como se mede |
|---|---|
| throughput de tradução | blocos básicos traduzidos/s, a frio |
| taxa de acerto do cache | após reabrir o app com o cache persistente |
| custo da tradução em tempo real | MIPS do guest com tradução ativa ÷ MIPS no estado quente |
| referência | o **mesmo** binário guest no **mesmo** aparelho, sob Box64 |

## Estado

### Feito — cache de tradução persistente (`ptc.c`, `ptc.h`)

A peça pedida explicitamente ("salve o que foi traduzido para executar depois sem
retraduzir"). É também a parte crítica de corretude: errar a invalidação faz o
emulador executar código de máquina que não corresponde mais aos bytes do guest —
falha silenciosa e corrupta.

Um acerto exige **três identidades** concordando: `module_id`, `guest_pc` e
`src_hash` (hash dos bytes do próprio bloco). Mudar um byte do código guest muda
`src_hash` e a entrada deixa de bater — é isso que torna automodificação segura.
`module_id` deriva da identidade completa do módulo (nome, tamanho, mtime, hash de
conteúdo), então substituir o arquivo faz os blocos antigos pararem de bater por
construção, e a invalidação é **por módulo**: um DLL atualizado perde só os seus
blocos.

O arquivo é carimbado com o ISA do host e do guest — código ARM64 nunca é
carregado num host x86-64. CRC-32/ISO-HDLC por região mais CRC por registro;
escrita atômica (temporário → `fsync` → `rename`), então uma queda no meio do
save não deixa um cache truncado que pareça válido. FNV-1a e CRC implementados
aqui, sem biblioteca.

`make test` → **52 checks, 0 failures**, compilando com
`-Wall -Wextra -Wshadow -Werror`. Coberto: vetores conhecidos de CRC-32, ida e
volta save/open, bytes de guest alterados no mesmo PC, módulo alterado, módulo
ausente do disco, ISA de host/guest estrangeiro, corrupção, truncamento, magic
inválida, re-tradução substituindo em vez de duplicar, save idempotente, e 5000
blocos recarregados e conferidos byte a byte.

### Feito — decodificador x86-64 (`x86_decode.c`, `x86_decode.h`)

Marco 1. Comprimento e estrutura, do zero, para o modo de 64 bits: prefixos,
REX, mapas de 1 e 2 bytes, e os mapas de 3 bytes `0F 38` e `0F 3A` (ambos com
cobertura total de comprimento — `38` é sempre ModRM sem imediato, `3A` é sempre
ModRM + imm8), ModRM, SIB, deslocamento, imediato e endereçamento RIP-relativo.

A regra de projeto é **nunca deduzir**. O que não está modelado retorna
`X86_UNSUPPORTED`; o que é ilegal em 64 bits retorna `X86_INVALID`; buffer curto
retorna `X86_NEED_MORE`. Um tradutor que recebe qualquer um dos três deve
interpretar o passo ou abortar o bloco — jamais avançar PC por um comprimento
chutado, porque um comprimento errado dessincroniza o fluxo inteiro e nada a
jusante detecta.

Recusado de propósito, em vez de aproximado:

- **VEX (`C4`/`C5`) e EVEX (`62`)** — exigem seu próprio modelo de prefixo.
  Nota: eles reutilizam os slots de LES/LDS/BOUND, então a checagem tem que vir
  **antes** da tabela; caso contrário seriam reportados como ilegais quando são
  apenas não modelados, e o chamador abortaria um bloco que deveria interpretar.
- **`0x67` (address-size override)** — endereçamento de 32 bits muda as regras de
  deslocamento para `rm==6` e `SIB base==5`. Devolver um comprimento calculado
  sob a regra de 64 bits seria um chute, então reporta `UNSUPPORTED`.

`X86_OK` com `mnemonic == NULL` é um estado real e útil: "o comprimento é
confiável, a semântica ainda não foi levantada". É o que um tradutor precisa para
delimitar blocos básicos antes de saber levantar cada instrução.

Imediatos aritméticos são reportados como **bits crus**: se a instrução os
estende depende do opcode (GRP1 `/3` estende, `MOV r8,imm8` não, `PUSH Iz`
estende). Decidir isso nesta camada seria duplicar semântica por opcode dentro do
decodificador de comprimento, então a extensão fica para o lifter. Só `rel8` e
`rel32` são inerentemente assinados, e esses vêm estendidos.

`make test` → **52 + 194 checks, 0 failures**, limpo sob
`-Wall -Wextra -Wshadow -Werror`. Cada comprimento nos testes foi derivado à mão
das regras de encoding, não lido de volta do decodificador — senão um erro de
tabela apareceria como uma resposta errada autoconsistente. Coberto: 50+
encodings com comprimento esperado, decomposição de REX, SIB `base=5` com
`mod=00` (que é `disp32` absoluto e **não** RIP-relativo — errar isso corrompe
silenciosamente todo endereço absoluto em código PIC), alvo RIP-relativo,
classificação de fluxo de controle (`FF /2`, `C3`, `74`, `E9`), LOCK e REP, REX
ignorado quando seguido de prefixo legado, GRP3 com e sem imediato, `imm64`
exigindo REX.W, mnemônicos, decodificação em fluxo de um prólogo de 8
instruções consumindo exatamente todos os bytes, teto de 15 bytes, e a garantia
de que `out` é limpo mesmo em falha (um chamador que reutiliza o struct nunca vê
um `len` obsoleto).

### Feito — leitor de imagens PE (`pe_load.c`, `pe_load.h`, `pe_info.c`)

Marco 2a. Um tradutor não executa um `.exe` que não consegue carregar, e é no
diretório de imports que as "DLLs reais" aparecem: é a lista de funções externas
que o guest espera que existam, e cada uma é um buraco que o tradutor precisa
preencher com uma implementação nativa ou uma ponte. Enumerar essa lista é a
primeira medição honesta de quanto trabalho um binário específico realmente dá.

Cobre cabeçalhos DOS/NT/COFF, optional header PE32 e PE32+, tabela de seções, os
16 diretórios de dados e o diretório de imports percorrido até o fim — nomes e
ordinais, agrupados por DLL. `pe_info` lê um arquivo do disco e imprime o
relatório.

Duas distinções fáceis de inverter, tratadas de propósito:

- **RVA não é deslocamento de arquivo.** Os diretórios de dados são endereços
  virtuais relativos e precisam ser mapeados pela tabela de seções, porque
  `VirtualAddress` e `PointerToRawData` diferem em arquivos reais por causa de
  alinhamento. Um parser que use RVA como offset funciona por acaso em algumas
  imagens e lê lixo em outras. Os fixtures aqui são construídos com os dois
  valores deliberadamente diferentes, e um teste afirma que ler o diretório de
  imports no RVA como se fosse offset **não** encontra os descritores.
- **`OriginalFirstThunk` não é `FirstThunk`.** A ILT guarda os nomes como estão
  no arquivo; a IAT tem o mesmo formato, mas o loader do SO a sobrescreve com os
  endereços resolvidos — é por ela que o guest chama. Os nomes vêm da ILT, com
  fallback para a IAT apenas quando `OriginalFirstThunk` é zero. Nos fixtures a
  IAT é preenchida com thunks zerados: um parser que lesse `FirstThunk`
  reportaria zero funções importadas, e as contagens esperadas falhariam.

O diretório 4 (SECURITY / tabela de certificados) é um deslocamento de arquivo,
não um RVA — a única exceção, e tratá-lo como as outras aponta para fora dos
dados pretendidos.

Recusado em vez de aproximado, com o motivo em `detail`: imagem **gerenciada**
(diretório CLR presente ⇒ contém IL, não código de máquina, e um tradutor de CPU
não tem o que traduzir), **32 bits** (PE32), **máquina que não é x86-64**
(inclusive ARM64, que já é a arquitetura hospedeira — "traduzi-la" não significa
nada) e tabela de seções acima do limite interno (a tabela é o que torna o
mapeamento de RVA correto, então uma tabela cortada invalida qualquer lookup). Em
todos esses casos os campos de cabeçalho já lidos continuam preenchidos: "o que é
este arquivo" é útil mesmo quando "carregue-o" não é.

Tratado como entrada não confiável. Nenhuma conversão de ponteiro para struct em
parte alguma: os campos são lidos por accessors little-endian explícitos que
recebem um offset verificado, porque converter um buffer em struct assume tanto o
padding do compilador quanto que o buffer é tão longo quanto o struct declara — e
para entrada não confiável a segunda suposição é exatamente a que não se pode
fazer. Nomes apontam para dentro do buffer do chamador, e só depois de confirmado
que existe um NUL antes do fim da imagem; um nome sem terminador é
`PE_MALFORMED`, nunca um ponteiro para memória não terminada que estouraria num
`strlen` posterior.

`pe_info` apenas lê e reporta: nada aqui mapeia a imagem como imagem, aplica
relocações, resolve um import ou executa um byte dela.

**Validação contra um binário real.** Fixtures escritos pelo mesmo entendimento
que escreveu o parser provam menos do que parecem — um equívoco aparece nos dois
e se cancela. Por isso o job `real-binary` no Actions baixa um executável Windows
x86-64 genuíno (ripgrep 14.1.1, MIT/Apache-2.0, release pinado por tag, com
`.sha256` publicado ao lado do asset e verificado **antes** do parse), roda o
`pe_info` sobre ele e afirma que o relatório diz `PE_OK`, `x64 (AMD64)`, `PE32+`,
não gerenciado, com `kernel32.dll` e uma enumeração de imports não vazia. O
binário vive em `/tmp` de um runner efêmero: nunca é commitado, e um passo final
afirma que nenhum `.exe`/`.dll`/`.msi` está rastreado no repositório.

**147 checks, 0 falhas**, limpo sob `-Wall -Wextra -Wshadow -Werror` e sob
ASan+UBSan. Suite total do projeto: 52 + 194 + 147 + 6 = **399 checks**.

### Feito — varredura de pré-tradução (`sweep.c`, `sweep.h`, `prewarm.c`)

Marco 2b. É a parte realizável do pedido "pré-traduzir com a tela apagada". Num
Android real a janela é um job do `WorkManager` com `setRequiresDeviceIdle(true)`
(ou um foreground service); o trabalho útil dentro dela é esta varredura: partir
dos pontos de entrada, seguir o código alcançável, decodificar em blocos básicos,
traduzir o que pode ser traduzido e gravar no cache persistente — para que, quando
o app for usado, os blocos já estejam lá.

**Não substitui o JIT.** Saltos indiretos, código gerado em runtime e
automodificação não são conhecíveis estaticamente; continuam sendo traduzidos
durante a execução. A varredura aquece o cache.

Duas propriedades valem mais que velocidade, e ambas são testadas:

- **Interrompível e retomável.** A janela de ociosidade termina sem aviso: a tela
  acende, o aparelho esquenta, a bateria cai, o SO retoma o job. Uma varredura que
  não sabe parar e continuar depois é inútil nessa janela, e uma que recomeça do
  zero desperdiça justamente o motivo de rodar em background. `sweep_run()`
  retorna quando o callback pede, o estado fica no job, e a chamada seguinte
  continua exatamente de onde parou — **nenhum bloco é decodificado duas vezes**. O
  teste compara uma execução em fatias contra uma ininterrupta e exige contadores
  idênticos, incluindo `decode_calls` e o conteúdo do cache.
- **Nunca grava uma tradução que não tem.** Guardar um placeholder para um bloco
  que não pôde ser traduzido seria pior do que não guardar nada: o cache devolveria
  um acerto depois, o emulador executaria código que não corresponde aos bytes do
  guest, e nada a jusante detectaria. Blocos sem tradução correta são contados e
  reportados, jamais cacheados. Quatro blocos não traduzíveis são assertidos como
  *miss*.

**Descoberta é travessia recursiva, não varredura linear.** Varrer x86 linearmente
produz instruções plausíveis em offsets que são o meio de outra instrução ou de um
dado, e aquecer o cache com isso seria gravar ficção. Seguindo ramos diretos a
partir de pontos de entrada reais, só se decodifica em endereços que o fluxo de
controle realmente alcança. O custo é honesto e reportado: um salto indireto
termina o bloco e seu alvo entra na conta de não resolvidos. O teste afirma que os
três endereços de padding entre funções **não** têm bloco — uma varredura linear os
decodificaria — e que um `C3` colocado numa seção não executável nunca é tocado.

**DLLs são varridas a partir das exports**, não só do `DllMain`: um `.exe` tem um
ponto de entrada, uma DLL tem tantos quantos exporta. Por isso o leitor de PE
ganhou a tabela de exports, com forwarder detectado (um forwarder aponta para uma
string, não para código; tratá-lo como código mandaria a varredura para o meio de
uma tabela de nomes).

**Porcentagem e tempo restante.** `prewarm` imprime ambos, e é explícito sobre o
que não sabe. Durante a descoberta o denominador cresce à medida que a worklist é
drenada, então a porcentagem é **provisória e pode andar para trás** — marcada com
`~` e com a razão impressa, em vez de ser suavizada. Durante a tradução a contagem
de blocos é conhecida e o número é exato. O tempo restante é extrapolado da taxa
observada na fase atual e assume que o trabalho que falta custa o que o trabalho
feito custou; blocos variam de tamanho e alguns caminhos recusam de imediato, então
é uma estimativa e está rotulada como tal. O teste exige monotonicidade na fase
exata, `provisional` ligado na fase provisória, 100% e ETA zero no fim, e um ETA
não nulo observado enquanto ainda restava trabalho.

**O que o número de cobertura significa hoje.** Um bloco só é cacheado quando
existe uma tradução ARM64 provavelmente correta para ele. O emissor atual cobre
três instruções (`a64_emit.c`), e o único bloco cuja tradução é demonstravelmente
correta sem um modelo de registradores e flags é o bloco de um único `C3`: o `RET`
do ARM64 tem o mesmo significado e não toca estado algum. Portanto a fração
"traduzido" mede **quanto do emissor está construído**, não quanto do binário seria
pré-traduzível. Está dito assim na saída do `prewarm`, para o número não ser lido
como mais do que é.

**74 checks, 0 falhas**, limpo sob `-Wall -Wextra -Wshadow -Werror` e sob
ASan+UBSan sem vazamentos. Suite do projeto: 52 + 194 + 147 + 74 + 6 = **473**.

No CI, o job `prewarm-real` baixa um bundle Windows x86-64 genuíno (HandBrake
1.11.2, GPL-2.0, tag pinada; o tamanho em bytes declarado pelos metadados do
release é buscado via API e comparado com um valor pinado, e o sha256 é calculado e
publicado como anotação para ser pinado em seguida), enumera todo `.exe` e `.dll`
do pacote e roda a varredura com uma janela ociosa curta, para que a porcentagem e
o tempo restante sejam exercitados como seriam num aparelho cuja janela fecha e
reabre. Módulos que o leitor recusa (32 bits, ARM, gerenciado) são reportados com o
motivo e pulados, e o resto continua. Nada é commitado: um passo final afirma que o
repositório segue sem binários e com o worktree limpo.

### Feito — tradução de ponta a ponta de um `.exe` que chama uma DLL (`translate.c`, `test_translate.c`)

Marco 3. Um executável PE real que chama uma DLL PE real **pela sua tabela de
imports**, ambos traduzidos para ARM64 do zero, executados em hardware ARM64, e o
resultado gravado no cache persistente e reexecutado a partir dele sem retraduzir.

O programa guest, escrito byte a byte no teste:

```
mini.dll  AddThree(rcx) -> rax        app.exe  entry() -> rax
  add rcx, 3                            mov rcx, 42
  mov rax, rcx                          call [rip -> IAT de AddThree]
  ret                                   add rax, 1
                                        ret
```

`42 + 3 + 1 = 46`, assertido em runner aarch64 nativo e sob QEMU, e assertido de
novo executando o código retirado do cache reaberto.

Ambas as imagens são PE estruturalmente reais: cabeçalhos DOS/NT, tabela de
seções, diretórios de dados, tabela de **exports** na DLL e, no executável, um
descritor de import com ILT, slot de IAT e um `FF 15` RIP-relativo apontando para
ele — que é como todo binário Windows chama uma função importada. O deslocamento é
calculado a partir dos endereços, não escrito à mão.

**Subconjunto traduzido** (o que existe hoje, seis formas): `mov r64,imm32`,
`mov r64,r64`, `add r64,imm`, `sub r64,imm`, `call [rip+disp32]`, `ret`.
Mapeamento de registradores: RAX→X0, RCX→X1, e X16 (IP0 no AAPCS, livre para o
tradutor) carrega o alvo resolvido. Constante de 64 bits materializada com
MOVZ + MOVK por chunk não nulo.

**A operação vem do opcode; a codificação vem do sinal do efeito.** Decidir as duas
coisas juntas é o bug mais grave que este marco produziu: escolher a instrução
ARM64 pelo sinal do imediato fazia `sub rax, 5` emitir um **ADD**. Errado,
cacheável e silencioso — exatamente a falha que todo o resto do projeto existe para
impedir. Agora o efeito aritmético é normalizado primeiro (`delta = is_sub ? -imm :
imm`) e a instrução sai dele.

**Recusado, com motivo:** flags e todo branch condicional, operandos de memória
além do slot de import, pilha, qualquer registrador além de RAX e RCX, SIMD, e
imediato fora de ±12 bits. Um trecho que não termina em `RET` é recusado mesmo que
cada instrução tenha traduzido: **um prefixo de uma função não é uma função**. Sem
um alvo de import resolvido o resultado é `TR_NEEDS_TARGET` com o endereço do slot,
nunca um chute — o que força a ordem correta, que é a do loader real: resolver
imports antes de traduzir quem chama.

**O defeito que só a execução revelou.** `CALL`/`RET` do x86-64 usam a **pilha**;
`BLR`/`RET` do AArch64 usam o **link register**. Mapear um no outro sem preservar
X30 produz código errado no momento em que uma função chama *e* retorna — e errado
da pior forma: o `BLR` sobrescreve X30 com o endereço da instrução seguinte, o
`RET` do callee o consome corretamente, e então o `RET` do próprio chamador salta
de volta para esse mesmo endereço e **entra em laço infinito**.

Nada disso é visível por inspeção. Cada encoding da sequência estava correto, a
desmontagem lia como o pretendido, e todas as asserções word-a-word passavam. Só
apareceu quando o código gerado foi executado em hardware aarch64 real — que é
exatamente o argumento pelo método de emitir-e-executar que este projeto usa. No
CI o sintoma foi um job parado nove minutos num passo que leva milissegundos.

Corrigido com um registro de quadro: `STP X29, X30, [SP, #-16]!` na entrada e
`LDP X29, X30, [SP], #16` antes do `RET` final, apenas quando o trecho contém uma
chamada (sem chamada, empurrar um quadro seria código que não faz nada). Os dois
words foram derivados das formas pré- e pós-indexadas de STP/LDP e **decompostos
campo a campo** numa verificação independente — `opc`, `L`, o `imm7` assinado como
múltiplo de 8, `Rt2`, `Rn`, `Rt` — em vez de confiados por parecerem certos.

Isto é um atalho válido para o subconjunto, **não** uma resposta geral, e o
cabeçalho diz isso: um tradutor real precisa modelar a pilha do guest, porque código
guest pode empurrar e desempurrar o endereço de retorno, inspecioná-lo e fazer
unwind através dele. Mapear `call`/`ret` do guest no link register só funciona
enquanto nada mais o toca.

**Resultado medido**, idêntico no runner aarch64 nativo e sob QEMU user-mode:

```
VERDICT arch=aarch64 exe_words=9 const_ok=1 first=ok/46(to=0,sig=0) cached=ok/46(to=0,sig=0)
EXECUTED ON aarch64: app.exe entry -> 46, having called mini.dll!AddThree through its import table
EXECUTED FROM CACHE: 46 with zero retranslation
```

`exe_words=9` porque o endereço hospedeiro real tinha três chunks de 16 bits não
nulos (prólogo + `MOVZ X1` + `MOVZ X16` + 2×`MOVK` + `BLR` + `ADD` + epílogo +
`RET`). `const_ok=1` significa que a sequência `MOVZ`/`MOVK` emitida, relida e
remontada pelo teste, reproduz exatamente o endereço hospedeiro da DLL — um chunk
colocado na posição errada mandaria a chamada para outro lugar.

Código gerado é executado num **processo filho com alarme de 5 s** e o resultado
volta por um pipe. Foi isso que converteu o travamento de nove minutos num
diagnóstico de cinco segundos dizendo "não terminou; morto por sinal". Código
gerado não é confiável por definição — é justamente por isso que o projeto pina
encodings e os executa — então um hang ou um crash dele não pode derrubar a suite
sem dizer qual instrução era.

**Isto não prova que um aplicativo real pode ser traduzido.** O guest usa seis
formas de instrução e dois registradores. Medido num bundle real, esse
subconjunto cobre **0,05% dos blocos**. O que ele prova é que o pipeline inteiro
funciona — PE, decodificação, tradução, resolução de import, emissão, execução,
persistência e reexecução a partir do cache — que é o que nunca tinha sido
demonstrado aqui.

Os 11 encodings ARM64 usados são pinados contra valores derivados à mão das tabelas
do ARMv8-A **e** conferidos por uma derivação independente em Python, porque
validar um encoder com ele mesmo não é validação. Foi assim que uma expectativa
errada minha apareceu: `0xDEADB000` tem `0xDEAD` nos bits 31:16, não 47:32, então o
`MOVK` pertence em `LSL #16` — o encoder estava certo.

**80 checks, 0 falhas.** Suite do projeto: 52 + 194 + 147 + 74 + 156 + 6 = **629**,
tudo limpo sob `-Wall -Wextra -Wshadow -Werror` e ASan+UBSan sem vazamentos.

### Feito — flags, comparação e desvio condicional (`tr_translate_function`)

Marco 4. Sem isto nenhum laço e nenhum `if` traduz, que é o que separa "chamadas
lineares" de código real. Uma função inteira agora é traduzida seguindo o fluxo de
controle, não apenas uma linha reta até o primeiro `RET`.

O programa de demonstração passou a ter um laço de verdade:

```
mini.dll  SumTo(rcx) -> rax        app.exe  entry() -> rax
  xor rax, rax                       mov rcx, 5
loop:                                call [rip -> IAT de SumTo]
  add rax, rcx                       add rax, 1
  sub rcx, 1                         ret
  cmp rcx, 0
  jnz loop
  ret
```

`SumTo(5) = 15`, mais 1 no executável → **16**. Cinco iterações de propósito: uma
comparação errada ou uma direção de desvio errada muda o resultado de forma visível,
em vez de dar um "off by one" que poderia passar por sorte.

**O mapeamento de flags é exato, não aproximado — mas só onde vale.** Depois de um
`SUBS` do AArch64, `N` é o `SF` do x86, `Z` é o `ZF`, `V` é o `OF`, e `C` é a
**negação** de `CF` (AArch64 liga C quando *não* houve borrow; x86 liga CF quando
houve). É por isso que os códigos de condição podem ser usados diretamente, e que
`cmp r, -k` tem que virar `CMN` (`ADDS` com XZR) em vez de um `SUBS` com imediato
negativo — o campo imediato do ARM64 não é assinado. 14 das 16 condições são
cobertas; **`JP`/`JNP` são recusadas**, porque o AArch64 não tem flag de paridade e
escolher um código de condição seria um chute.

**A armadilha central: x86 liga flags em quase toda instrução aritmética; ARM64 só
nas formas com sufixo S.** Emitir um `ADD` comum onde o guest tinha um `add` e
depois deixar um desvio condicional ler o resultado seria ler flags que ninguém
calculou. Então o tradutor rastreia qual instrução deixou flags utilizáveis, e um
desvio condicional só é aceito quando a instrução **imediatamente anterior, contígua
no fluxo guest**, é um `CMP` ou `TEST` modelado. Duas guardas a mais seguem do mesmo
raciocínio: um desvio cujo alvo é o próprio desvio condicional é recusado (as flags
viriam de outro lugar), e `add`/`sub`/`xor` emitem a forma que **não** liga flags —
correto justamente porque nada a jusante tem permissão de lê-las.

**Três passadas**, porque o deslocamento de um desvio não existe até que o tamanho
emitido de cada instrução esteja fixo: planejar e contar, dispor endereços, emitir.
O tamanho em words ARM64 não depende do alvo do desvio, então o layout não precisa
de iteração até ponto fixo. Se no fim a contagem emitida divergir do layout, é erro
interno e não silêncio — uma divergência colocaria **todo** desvio seguinte no
deslocamento errado.

**`RSP` e `RBP` são recusados** como operandos: usá-los implica um modelo de pilha
do guest, e inventar um em silêncio seria pior do que recusar. O mapa de
registradores agora cobre 14 (RAX,RCX,RDX,RBX→X0..X3, RSI,RDI→X4,X5, R8..R15→X6..X13),
com REX.B/REX.R respeitados.

Recusado também: desvio que sai da função, função que termina sem `RET` (traduzir
isso emitiria código que sai do fim), `xor` com dois operandos diferentes (o idioma
de zerar é seguro; um xor real precisa do valor *e* das flags), e qualquer prefixo
que mude significado (`66`, `67`, `F2`, `F3`, `LOCK`, segmento, `REP`).

Os 15 encodings ARM64 (MOVZ, MOVK, ADD/SUB imediato, ADD/SUB/SUBS/ANDS/ADDS
registrador, MOV, BLR, RET, STP, LDP, B, B.cond) são pinados contra valores
derivados à mão **e** conferidos por decomposição independente em Python, campo por
campo. Foi assim que dois erros meus de aritmética apareceram (`tst x0,x0` tem
`rn=0`, e `b.ne -13` é `0x54FFFE61`, não o `0x54FFFF3A` que decodifica para -7) —
em ambos o encoder estava certo.

**Resultado medido**, idêntico no runner aarch64 nativo e sob QEMU user-mode, com o
código recém-traduzido **e** com o código recarregado do cache persistente:

```
VERDICT arch=aarch64 exe_words=9 const_ok=1 first=ok/16(to=0,sig=0) cached=ok/16(to=0,sig=0)
EXECUTED ON aarch64: app.exe entry -> 16, having called mini.dll!SumTo through its
import table, five iterations of a loop driven by cmp/jnz
EXECUTED FROM CACHE: 16 with zero retranslation
```

Ou seja: um `.exe` PE chamou uma função exportada por uma DLL PE através da sua
tabela de imports, a DLL continha um laço de cinco iterações dirigido por
`cmp`/`jnz`, tudo foi traduzido para ARM64 por este código, executou em hardware
real e devolveu o valor certo — e o mesmo valor saiu do cache reaberto sem
retraduzir uma instrução.

**156 checks, 0 falhas** neste teste.

### Feito — medição da superfície de API: Vulkan contra Direct3D em números (`api_map.c`, `api_report.c`)

A pergunta "um jogo em Vulkan precisa de menos tradução que um em DirectX?" mistura
duas coisas que têm de ser separadas antes de poder ser respondida.

**Tradução de CPU** cobre o código de máquina do próprio módulo. É x86-64 nos dois
casos e **100% dele precisa ser traduzido de qualquer maneira**; o código de engine
de um renderizador Vulkan não é, de alguma forma, ARM64. **Tradução de API** cobre o
que o módulo chama para fora. Um jogo Direct3D precisa do D3D reimplementado sobre
Vulkan e do bytecode de shader traduzido de DXBC/DXIL para SPIR-V — é o que DXVK e
VKD3D-Proton são, e são centenas de milhares de linhas. Um jogo Vulkan não precisa
de nenhum dos dois: seus shaders já são SPIR-V e sua API já existe no Android, então
o que resta é um shim fino de loader redirecionando `vulkan-1.dll` para
`libvulkan.so` e trocando a surface win32 por uma android. **A economia de Vulkan é
real e grande, e está inteira na segunda categoria — não reduz a primeira em um
byte.**

`api_report` mede as duas. Por módulo, reporta os bytes de código próprio que exigem
tradução de CPU e divide as funções importadas entre Direct3D, Vulkan, OpenGL,
compiladores de shader, janela/apresentação, áudio, entrada, núcleo do Windows,
DLLs de contrato API-set, bibliotecas de terceiros e o resto — com porcentagens, e
uma linha `SUMMARY` que cabe inteira numa anotação de CI.

**Medido em três aplicações reais**, baixadas no CI, pinadas por tamanho em bytes,
parseadas apenas, nunca commitadas:

| aplicação | módulos | DLLs | funcs | **código x86-64** | d3d | vulkan | gl | núcleo Win | api-set | dinâmica? |
|---|---|---|---|---|---|---|---|---|---|---|
| Godot 4.7.2 win64 (MIT, Vulkan-first) | 2 | 42 | 580 | **107,5 MB** | 0,1% | **0,0%** | 0,0% | 68,7% | 3,6% | **sim** |
| PPSSPP 1.20.4 x64 (GPL-2.0, D3D11 **e** Vulkan) | 1 | 23 | 512 | **14,3 MB** | **0,0%** | **0,0%** | 8,2% | 58,5% | 0,0% | **sim** |
| PPSSPP 1.20.4 **ARM64** (controle) | 0 | — | — | 0 | — | — | — | — | — | — |

**O resultado mais importante é o que invalida a própria pergunta feita desse
jeito.** O Godot é um motor **Vulkan-first** e sua tabela de imports estática mostra
**vulkan = 0,0%**. O PPSSPP tem backends **D3D11 e Vulkan** e mostra **d3d = 0,0% e
vulkan = 0,0%**. Os dois são `dynamic=yes`: carregam o backend gráfico em runtime
via `LoadLibrary`/`GetProcAddress`.

Ou seja, **não se determina a API gráfica de um jogo pela tabela de imports
estática.** O alerta de "limite inferior" que eu tinha embutido no relatório como
uma ressalva de honestidade acabou sendo o **caso dominante**, não um caso de canto
— e é exatamente o que backends que escolhem D3D ou Vulkan em runtime fazem.

E o número que responde à pergunta de fato: **107,5 MB de código x86-64 no Godot e
14,3 MB no PPSSPP precisam de tradução de CPU, independentemente da API gráfica.**
Vulkan não reduz isso.

**O caso de controle.** O build ARM64 nativo do *mesmo* PPSSPP foi **recusado nos
três módulos**, com o motivo, e reportado como não precisando de tradução de CPU
(`refused=3`, `parsed=0`, `code_bytes=0`). É assim que "já é a arquitetura
hospedeira" aparece, e o job afirma isso em vez de deixar passar em silêncio.

A limitação honesta está na saída, não em nota de rodapé: uma tabela de imports
mostra apenas imports **estáticos**, então para um módulo com `LoadLibrary` ou
`GetProcAddress` as porcentagens são um **limite inferior** e o relatório diz isso e
conta quantas funções dessas existem.

**71 checks** no classificador.

### Feito — modelo de pilha do guest (`gstack.c`, `gstack.h`)

Este marco veio de uma medição, não de uma preferência. A varredura de um bundle
real encontrou **64 pontos de entrada que são código de verdade** e traduziu
**nenhum**, e os 64 foram recusados **na primeira instrução**. Dois deles — as
entradas do `.exe` — foram recusados no opcode `0x83` com razão
`register-unmapped`, que é `sub rsp, N`: o ajuste de quadro com que um prólogo
real abre, recusado apenas porque RSP não tinha registrador hospedeiro.

O RSP do guest mapeia para **X14** e o RBP para **X15**. Ambos são *callee-saved*
na AAPCS, e isso é o motivo da escolha, não conveniência: uma tradução que usa a
pilha os salva como registro de quadro, e uma função hospedeira alcançada por um
import resolvido os preserva através da chamada **sem que nada seja emitido**.

Eles **não** são o SP hospedeiro. AArch64 exige SP alinhado a 16 bytes em toda
interface pública; x86-64 garante só 8. Compartilhar o SP transformaria cada
ajuste ímpar do guest numa falha de alinhamento.

**O endereço da arena não é embutido no código.** Quem chama o fornece em X14.
Assim a tradução continua sendo função pura dos bytes do guest e permanece válida
num cache que sobrevive ao processo — que é um dos três requisitos pedidos. Um
teste afirma a consequência: uma tradução que só usa a pilha não materializa
nenhuma constante absoluta.

Passou a traduzir: `push`/`pop r64`, `push imm32`/`imm8`, `leave`, `sub`/`add rsp,
imm`, qualquer movimento reg-reg envolvendo RSP ou RBP, e `mov` de/para
`[rbp-disp]` e `[rsp+disp]`.

Recusado em vez de mirado, cada caso com razão própria:

- **deslocamento não-negativo a partir de RBP** — alcança o quadro do *chamador*
  (RBP salvo, endereço de retorno, argumentos de pilha). Este modelo põe o
  endereço de retorno em X30 e os argumentos em registradores, então ler ali
  devolveria lixo da arena **com forma de valor**.
- **deslocamento negativo a partir de RSP** — a *red zone* do SysV, não mapeada
  abaixo da arena.
- **`push rsp` e `pop rsp`** — o próprio x86 é ambíguo sobre se o valor empurrado
  é o ponteiro pré- ou pós-decremento, e o `STR` pré-indexado do ARM64 responde o
  contrário. Diferença de 8 bytes numa palavra que será lida depois.
- **`ret imm16`** — desempilha argumentos e portanto muda o ponteiro de pilha do
  chamador, que o epílogo restaura incondicionalmente.
- **qualquer base que não seja RSP ou RBP** — ainda não existe modelo geral de
  memória do guest, então dereferenciar através de RAX não tem para onde apontar.

Duas codificações se parecem exatamente com uma base de pilha e não são, e ambas
são verificadas explicitamente porque tratar qualquer uma como base lê a memória
errada **sem sintoma visível**: `mod=00 rm=101` é RIP-relativo, não `[RBP]`; e
`mod=00` com `SIB base=101` é um `disp32` absoluto **sem base nenhuma**. O
decodificador entrega os dois como `sib_base == 5` / `rm == 5`, o mesmo valor que
RBP tem.

A arena fica entre **duas páginas `PROT_NONE`**. O confinamento vem do kernel, não
de checagens emitidas: uma checagem custa instruções em cada `push`, e um laço que
empilha a cada iteração derrota qualquer limite calculado uma vez. O caso
desgarrado é **executado de propósito** na suíte — um laço que empilha para sempre
tem que morrer na página de guarda.

O epílogo restaura X14 e X15 aos valores de entrada, o que torna o ponteiro de
pilha do guest **balanceado no retorno incondicionalmente**: qualquer ajuste que o
guest tenha feito, um retorno antecipado não entrega um ponteiro torto ao
chamador.

O que isto **não** resolve, dito antes de ser descoberto: `call [rip+disp32]` emite
`BLR` passando o estado de registradores do guest sem alteração. Isso é correto
quando o destino é código do guest também traduzido, compartilhando este mapeamento
— que é o que o teste de ponta a ponta exercita. **Não** é correto para uma função
hospedeira de verdade, que espera argumentos em X0..X7 pela AAPCS enquanto o guest
os deixou em RCX, RDX, R8, R9. Essa ponte é trabalho separado e não está feito.

A varredura agora reporta quantas das funções traduzidas **precisam de uma arena
em tempo de chamada**, porque é a diferença entre "produzimos N traduções" e
"conseguimos executar N traduções".

**259 checks** no tradutor (eram 168), incluindo as guards verificadas lendo as
permissões do mapeamento em `/proc/self/maps`.

Executado em ARM64 real e sob QEMU, com marcador próprio no CI:

```
EXECUTED ON aarch64: guest stack model - locals, exact stack arithmetic,
push/pop agreement, and a runaway contained by a guard page
```

#### O que o modelo de pilha revelou em seguida

Com o prólogo destravado, a medição no bundle real mudou de forma informativa:
`refused_at_first_insn` caiu de **64 para 62** e apareceu
**`refused_deeper: 2 (deepest: 1)`** com **`2 function(s) stopped at opcode E8`**.
`E8` é `call rel32`. As duas entradas do `.exe` deixaram de morrer na primeira
instrução — o `sub rsp, N` traduziu — e o bloqueio seguinte agora tem nome: uma
chamada direta a outra função do guest.

E isso deu a pista para os outros 62. Se `fail_op_len == 0`, `fail_insns == 0` e a
razão é `unsupported-opcode`, então o `plan_one` **nunca rodou**: a recusa veio de
uma guarda anterior ao passe 1. Reproduzido aqui — um buffer cuja primeira
instrução é um `RET` simples, traduzível à vontade, devolve exatamente esse
registro quando `code_len` passa do teto.

Ou seja: os 62 **nunca foram 62 opcodes não suportados**. Eram 62 funções que o
tradutor **nunca examinou**, porque a varredura entrega a seção de código inteira
(commit `503979a`, e por bom motivo: limitar a função a uma janela recusa quase
todas as reais) e a seção daquele módulo passava do teto de 1 MiB. A recusa
carregava `TRR_UNSUPPORTED_OP`, o valor com que o registro é inicializado antes do
passe 1 — indistinguível, num histograma, de uma função cuja primeira instrução
realmente estava fora do subconjunto.

Três correções:

- **`TRR_BUFFER`**, uma razão que diz "o buffer foi rejeitado antes de decodificar
  uma instrução". Setada no teto de tamanho, nos casos NULL e vazio, na alocação
  das marcas e no `start_off` além do fim — que tinha o mesmo defeito e não setava
  razão nenhuma.
- O teto sobe de 1 MiB para **`TRF_MAX_CODE_BYTES` (256 MiB)**. O `.text` de um
  módulo real chega a centenas de megabytes; um teto que o rejeita rejeita **todas**
  as exportações do módulo.
- As marcas de descoberta passam a **um bit por byte** do guest em vez de um byte.
  O bitmap é um oitavo da seção, e é o que torna o teto maior pagável — ele é
  alocado e liberado por ponto de entrada.

`pushf` também passou a setar a razão, não só o detalhe: seus chamadores retornam
`TR_OVERFLOW` diretamente e deixariam o sentinela no lugar, o mesmo defeito em outro
caminho.

Um teste fixa a granularidade do bitmap, que é onde uma regressão se esconderia:
dez `push` de um byte compartilham um único byte do bitmap, e uma marca
byte-granular perderia todos depois do primeiro — emitindo uma tradução **curta
que ainda consiste de palavras válidas**.

Suite do projeto: **832**.

### Não feito

Operandos de memória **fora da pilha do guest** (o slot de import RIP-relativo e
os locais em `[rbp-]`/`[rsp+]` são os únicos), `call rel32` direto para outra
função do guest, desenrolar de exceções/SEH, SIMD, as flags que o subconjunto não
produz (paridade, ajuste, e flags de `mul`/`div`/rotação/shift), a **ponte de
convenção de chamada guest→hospedeiro** descrita acima, relocações aplicadas,
resolução de imports em escala e a ponte Win32/API-set para cada função importada,
loader de ELF, mapeamento real da imagem em
memória com relocações aplicadas, resolução de imports e de API sets, camada de
syscalls/Win32, D3D→Vulkan, e o app Android em si — inclusive a ligação desta
varredura ao `WorkManager` e ao estado real de tela apagada, que hoje é modelada
como um orçamento de tempo retomável. VEX/EVEX e `0x67` seguem recusados por
design até serem modelados.

Ler um `.exe` e saber do que ele precisa não é traduzi-lo. Entre este marco e
executar um binário real estão, no mínimo: estado de CPU (registradores e flags),
o lifter, o emissor, o mapeamento com relocações, e uma ponte para cada função
importada — que é o trabalho que o Wine faz, e não o de um dynarec.

### O que os testes pegaram durante o desenvolvimento

Registrado porque é o argumento por trás de escrever os testes primeiro:

- `0x9A` (CALLF Ap) estava marcado como válido — eu tinha zerado a linha
  `0x90-0x9F` inteira por preguiça em vez de conferir opcode a opcode.
- `RET imm16` e `RETF imm16` quebraram quando uma edição por índice de linha
  removeu `case I_W:` do switch em silêncio. Cobertura foi adicionada para os
  **dois** usuários do caso, não só o que falhou.
- VEX/EVEX retornavam `INVALID` em vez de `UNSUPPORTED` por ordem de checagem.
- O cabeçalho prometia imediato sinalizado que a implementação não entregava, e
  a promessa estava errada: a extensão é específica de opcode.
- Duas expectativas erradas eram dos próprios testes (o NOP multibyte canônico é
  6 bytes, não 7; e a asserção de extensão de sinal testava um caso onde a
  extensão não se aplica).

No leitor de PE, todos encontrados por execução e não por revisão:

- `e_lfanew` era escrito no offset `0x7C` em vez de `0x3C`, dentro do cabeçalho
  DOS de 64 bytes. Todo leitor via zero ali e a imagem parecia não ter cabeçalho
  PE nenhum — o parse morria antes de preencher qualquer campo.
- O construtor de fixture recebia o spec por `const` e o copiava, então os
  offsets que ele descobria (descritores, terminador, nome da DLL) nunca voltavam
  para o chamador. Cada teste de corrupção estaria patcheando o offset 0 e
  parecendo significativo sem testar nada.
- `strcmp` com ponteiro NULL: o teste seguiu adiante depois de um parse falho e
  dereferenciou campos nunca preenchidos. Um crash aponta uma linha, não uma
  expectativa — por isso o arquivo ganhou `seq()` e um guard `parsed()` que
  interrompe o teste em vez de continuar.
- Sem o thunk terminador quando o nome longo estava ativo, a varredura seguia
  para os thunks da DLL seguinte e contava 6 em vez de 4. O parser estava certo
  em continuar: um terminador ausente é justamente o que ele não pode inventar.
- "Nome de DLL sem NUL" era testado sobrescrevendo 12 bytes de um nome de 12
  caracteres — o NUL no índice 12 ficava intacto, e o padding zerado logo depois
  terminaria qualquer varredura mesmo assim. O caminho só é alcançável com um
  fixture construído para isso: o nome tem que ser os últimos bytes do arquivo.
- Um teste lia `buffer + RVA` para demonstrar que RVA não é offset, sem checar
  limites — e o RVA era maior que a imagem inteira. O próprio teste estourava o
  heap para provar que o parser não deveria estourar.

Na tradução:

- **O import era resolvido por posição (`exports[0]`) em vez de por nome.** Quando
  `SumTo` foi adicionado à DLL, o executável passou a chamar `AddThree` — e o
  programa **não travou, não caiu e não produziu lixo**: rodou a função errada
  corretamente e devolveu 9, que é `AddThree(5)+1`, um número plausível. Só o valor
  esperado o pegou, e uma expectativa mais fraca não teria pegado. É o modo de falha
  que mais vale registrar aqui: um loader que resolve por posição não falha, ele
  executa outra coisa em silêncio. O teste agora casa o nome importado contra a
  tabela de exports, como um loader real faz, e afirma que o RVA resolvido é o de
  `SumTo` — não apenas que algo resolveu.
- A descoberta de sucessores só empurrava alvos para `JCC`/`JMP` e **não seguia o
  fluxo sequencial** para as demais instruções, então uma função de 6 instruções
  traduzia 1 e reportava `TR_OK`. Não falha alto: produz a tradução de um prefixo
  que parece completa. O contador de instruções foi o que entregou.
- Uma fixture de teste de flags usava `jz +2`, cujo alvo caía fora do buffer, então
  a recusa "sai da função" disparava antes da checagem de flags que o teste queria
  exercer — o teste passaria pelo motivo errado.
- O `RET` final voltava para o meio da própria função: `CALL`/`RET` x86 usam a
  pilha, `BLR`/`RET` ARM64 usam o link register, e X30 não era preservado através
  da chamada. Laço infinito, invisível por inspeção, visível só em hardware real.
  Corrigido com `STP`/`LDP` de quadro.
- `sub rax, 5` emitia **ADD**: a escolha da instrução ARM64 estava keyed no sinal
  do imediato em vez do opcode. Errado, cacheável, silencioso. O teste pegou porque
  compara a word emitida contra `a64_sub_x_imm`, não contra "alguma coisa de 32
  bits".
- Uma expectativa minha de encoding estava errada (`MOVK ... LSL #32` para
  `0xDEADB000`, cujo chunk alto está em `LSL #16`). Pinado duas vezes — pelo
  encoder e por derivação independente — o erro apareceu no lado certo.
- O teste do limite de 12 bits usava `48 05` (`add rax,imm32`), que nem está no
  subconjunto, então a recusa que ele queria exercer era inalcançável. Trocado por
  `48 81` (GRP1 imm32), que está, e o caminho passou a ser realmente testado.

Na medição da superfície de API:

- O classificador foi apontado primeiro para a fixture do *sweep*, que não tem
  tabela de imports nenhuma, e produziu um relatório vazio — a asserção falhou por
  um motivo que não era culpa do classificador.
- Depois afirmei uma porcentagem **inventada** (`25.0%`) em vez da divisão real da
  fixture (60/40). As duas falharam alto, que é o motivo de assertir em vez de
  imprimir.
- Vários passos de CI que liam `$?` para decidir o que reportar morriam no primeiro
  status não zero: o runner invoca `bash -e`, e `set -uo pipefail` **não desliga** o
  errexit. `xargs` devolve 123 quando qualquer invocação falha, e `api_report`
  devolve 1 quando algum módulo de um arquivo de quarenta arquivos é ilegível —
  resultado normal, não falha da medição. Passos que inspecionam status agora dizem
  `set +e` explicitamente.

Na infraestrutura de verificação:

- Um job ARM64 ficou nove minutos num passo que leva milissegundos e não havia como
  saber qual binário era: stdout para um pipe é totalmente bufferizado e um processo
  morto por timeout não faz flush de nada. Cada binário ganhou `timeout` próprio, log
  em arquivo, markers com `fflush` em cada estágio, e uma linha `VERDICT` única no
  fim que sobrevive a qualquer truncamento.
- O passo de diagnóstico **ele mesmo falhou** com exit 1 e não publicou nada. Um passo
  cuja função é explicar uma falha não pode falhar: `set +e`, sem `pipefail`,
  `exit 0` explícito.
- A inserção textual do passo procurava a âncora desde o início do arquivo e a
  encontrou duas vezes no mesmo job, deixando o outro sem nada. Inserção agora é
  escopada à região de texto de cada job, e a contagem de passos é assertida **antes**
  de commitar.
- Duas vezes commitiei código que não compilava ou cujo passo de CI estava errado,
  porque o build estava encadeado através de um pipe cujo exit status vinha do último
  comando, não do compilador. Verificação de status explícita e gates antes do commit.

Na varredura:

- O callback de parada do teste era consultado **antes** do primeiro bloco e pedia
  parada sempre, então a varredura não fazia nada — corretamente, era o que ele
  estava pedindo — e o laço do teste girou 100 mil vezes por 210 segundos. O motor
  estava certo; a semântica do callback no teste estava errada. O laço ganhou um
  detector de "retomada sem progresso", para uma regressão no protocolo de parada
  falhar em milissegundos e não depois de cem mil tentativas.
- Os RVAs dos nomes na tabela de exports estavam escritos à mão (`0x203C`,
  `0x2042`) ao lado dos offsets calculados que ninguém usava. O compilador apontou
  as duas variáveis gravadas e não lidas, o que era o sintoma de que o valor real e
  o valor chutado podiam divergir em silêncio.

No modelo de pilha do guest:

- O helper que provocava a falha na página de guarda era chamado **duas vezes**:
  uma na condição do `CHECK` e outra nos argumentos da mensagem. O macro avalia a
  condição e, em caso de falha, também os argumentos — então cada asserção fazia
  dois `fork()` e a mensagem reportava um sinal **diferente do que foi testado**.
  Chamada agora é feita uma vez e guardada numa variável.
- A mesma asserção falhava sob AddressSanitizer por um motivo que não era um bug
  no código testado: o ASan intercepta `SIGSEGV`, imprime um relatório e sai com
  código não-zero, então `WIFSIGNALED` é falso e o número do sinal nunca chega ao
  pai. Perguntar "qual sinal chegou" tem resposta diferente por build; perguntar
  "a escrita se completou" tem a mesma em todas. A propriedade de confinamento
  passou a ser afirmada **diretamente**, lendo as permissões do mapeamento em
  `/proc/self/maps` (`---p` nas duas guards, `rw-p` na região utilizável), em vez
  de ser inferida de uma falha entregue a alguém.
- `MAP_ANONYMOUS` fica atrás de `__USE_MISC`, que `-std=c11` desliga. Se a flag é
  visível dependia de qual glibc o build usava: exposta na 2.39 do runner aarch64,
  oculta na 2.36 daqui — o mesmo código compilava lá e falhava cá. Pedir o conjunto
  de features explicitamente removeu a dependência, e isso expôs uma colisão
  latente: o teste definia `static void bzero(buf*, size_t)` sobre o `bzero` POSIX,
  que só não colidia enquanto a libc estivesse oculta.
- Uma tradução **bem-sucedida** deixava `out->reason` no sentinela de antes do
  passe 1, ou seja, um resultado que deu certo vinha rotulado com a razão pela qual
  não falhou. Nada lia `reason` quando o status era `TR_OK` — exatamente por isso
  valia corrigir: o primeiro chamador que lesse construiria um histograma contando
  sucessos como recusas.
- O segundo maior balde de recusas num binário real — **62 pontos de entrada** —
  era uma **etiqueta errada**, não uma instrução faltando. Todas as 62 eram
  reportadas como `unsupported-opcode` sem opcode, sem profundidade e sem plano, e
  a causa era um teto de tamanho de buffer anterior ao passe 1 que vazava o valor
  inicial do registro. Sessenta e duas funções que o tradutor nunca olhou foram
  reportadas como 62 que ele tinha examinado e achado fora do subconjunto. O que
  expôs foi o próprio modelo de pilha: ao destravar o prólogo, as duas entradas do
  `.exe` passaram a morrer **uma instrução depois**, e essa mudança de profundidade
  é o que tornou visível que as outras 62 tinham profundidade zero *sem* opcode.
  Um balde de recusa que mistura "não examinei" com "examinei e não sei traduzir"
  manda o trabalho para o lugar errado.
- Três expectativas erradas eram dos próprios testes, não do tradutor: contei as
  palavras emitidas esquecendo o registro de quadro. `push rax; pop rax` entre dois
  ajustes de RSP são 7 palavras, não 6; `push -1` são 9, e o `MOVZ` está no índice
  1 porque o índice 0 é o prólogo — a falha imprimiu `0xA9BF3FEE` e eu tinha
  assertido sobre ele como se fosse a constante.

## Limitação deste ambiente

**Não é possível gerar um APK aqui.** Não há NDK, `javac`, `aapt2`, `zipalign`
nem `apksigner`; há apenas `gcc/g++ 12.2` para x86-64 host, `make` e `python3`.
O núcleo nativo é compilável e testável para o host (a lógica de cache,
decodificação, o leitor de PE e o IR são independentes de arquitetura).

A emissão ARM64 **não** pode ser executada neste sandbox — mas pode no CI. O
workflow `emu ARM64` roda o harness de emitir-e-executar de duas formas
independentes, num runner aarch64 nativo e sob QEMU user-mode num runner x86-64,
e os dois jobs falham se a linha `EXECUTED ON aarch64` não aparecer: um skip não
pode passar por verde.

Nota: `apk-fix/build_apk.py` no repo **não** constrói um APK do zero — ele repara
e assina um APK existente, com `ORIGINAL_APK_SHA256` fixado. Não serve como base
para um app novo.
