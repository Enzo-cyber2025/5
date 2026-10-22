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

### Não feito

Decodificador x86-64, IR, emissor ARM64, loader de PE/ELF, camada de syscalls,
D3D→Vulkan, e o app Android em si.

## Limitação deste ambiente

**Não é possível gerar um APK aqui.** Não há NDK, `javac`, `aapt2`, `zipalign`
nem `apksigner`; há apenas `gcc/g++ 12.2` para x86-64 host, `make` e `python3`.
O núcleo nativo é compilável e testável para o host (a lógica de cache,
decodificação e IR é independente de arquitetura); a emissão de código ARM64 pode
ser escrita e verificada por round-trip de assembler, mas não executada aqui.

Nota: `apk-fix/build_apk.py` no repo **não** constrói um APK do zero — ele repara
e assina um APK existente, com `ORIGINAL_APK_SHA256` fixado. Não serve como base
para um app novo.
