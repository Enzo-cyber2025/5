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

### Não feito

Lifter (IR a partir do que o decodificador já entrega), emissor ARM64, loader de
PE/ELF, camada de syscalls, D3D→Vulkan, varredura estática em background, e o app
Android em si. VEX/EVEX e `0x67` seguem recusados por design até serem modelados.

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

## Limitação deste ambiente

**Não é possível gerar um APK aqui.** Não há NDK, `javac`, `aapt2`, `zipalign`
nem `apksigner`; há apenas `gcc/g++ 12.2` para x86-64 host, `make` e `python3`.
O núcleo nativo é compilável e testável para o host (a lógica de cache,
decodificação e IR é independente de arquitetura); a emissão de código ARM64 pode
ser escrita e verificada por round-trip de assembler, mas não executada aqui.

Nota: `apk-fix/build_apk.py` no repo **não** constrói um APK do zero — ele repara
e assina um APK existente, com `ORIGINAL_APK_SHA256` fixado. Não serve como base
para um app novo.
