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

### Não feito

Lifter (IR a partir do que o decodificador já entrega), emissor ARM64 além das
três instruções do harness, loader de ELF, mapeamento real da imagem em memória
com relocações aplicadas, resolução de imports, camada de syscalls/Win32,
D3D→Vulkan, varredura estática em background, e o app Android em si. VEX/EVEX e
`0x67` seguem recusados por design até serem modelados.

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
