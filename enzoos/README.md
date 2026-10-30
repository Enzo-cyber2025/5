# EnzoOS

**Um sistema operacional completo escrito em Assembly x86-64 puro** — do setor
de boot ao desktop com janelas, rede TCP/IP real, áudio, disco SATA persistente,
swap por demand paging e compilador próprio. **Sem uma linha de C.** Cada byte
do kernel e dos aplicativos é montado com [NASM](https://nasm.us)
(`nasm -f bin` — kernel binário puro, sem linker).

> Apps no formato único **`.ENZ`** — linkagem dinâmica por nome
> ("ENZ1" — EnzoOS Native eXecutable); o `.ce` antigo segue como
> retrocompatibilidade.

![CI](https://github.com/Enzo-cyber2025/5/actions/workflows/enzoos-ci.yml/badge.svg)

## O que é

* **Boot próprio** — MBR + stage1 em modo real que detecta a VESA, monta a
  tabela E820 e carrega o kernel em modo longo (64 bits) **sem GRUB**.
* **Kernel gráfico** — framebuffer linear, janelas com composição,
  barra de tarefas translúcida, menu Iniciar arredondado, cursor do mouse,
  relógio na bandeja.
* **Nova renderização** (`kernel/gfx2.inc`): **alpha blending**, gradientes,
  cantos arredondados, sombras suaves, linhas de Wu anti-aliased, círculos —
  todo o compose de janelas/menu/taskbar usa as novas primitivas.
* **Drivers nativos**:
  * **PS/2** (teclado + mouse), **PIT**, **PIC**, **RTC**, porta serial (log);
  * **AHCI/SATA** — leitura e escrita de blocos no disco real;
  * **HPET** — timer de alta resolução (nanossegundos);
  * **Intel HDA** — áudio 48 kHz/16 bits estéreo (CORB/RIRB + BDL), com
    fallback para o PC speaker;
  * **Intel e1000** — rede Ethernet completa: MAC, anéis TX/RX com polling.
* **Pilha de rede própria** (`kernel/net.inc`): ARP, IPv4, UDP, **cliente
  DHCP**, **TCP** (three-way handshake, retransmissão, ACKs) e **HTTP 1.0** —
  checksums de cabeçalho em hardware nenhum: tudo calculado à mão.
* **ENZFS** (`kernel/enzfs.inc`) — sistema de arquivos persistente no disco
  SATA: superbloco, bitmap de blocos, inodes de 64 B, diretórios de 128
  entradas, **leitura, escrita, creat, mkdir e unlink**.
* **Swap REAL** (`kernel/swap.inc`) — **demand paging** com `#PF` transparente:
  páginas de aplicativos saem para a área de troca no SATA e voltam sem o app
  perceber; o SysMon mostra contadores ao vivo.
* **Formato `.ENZ`** — header de 64 bytes + imagem + **strings de importação
  resolvidas por nome** contra `k_exports` (36 APIs): linkagem dinâmica de
  verdade. `tools/mkenz.py` gera o arquivo.
* **Compilador `enzc.py`** — linguagem **ENZ** (C-like, inteiros 32 bits):
  globais, vetores, funções com até 6 parâmetros, `if/else`, `while`,
  `break`, `return`, operadores completos, strings e chamadas às 36 APIs.
  Gera x86-64 puro. Demo: `apps/mandel.enz` → **MANDDEL.ENZ** (Mandelbrot
  em ponto fixo, renderizado dentro do SO).
* **Tradutores de binários** — o kernel **executa de verdade**:
  * **PE/COFF x86-64** (`.exe` e `.dll`) com carregamento de seções;
  * **ELF x86-64** (`.run` ET_EXEC e `.so` ET_DYN) com relocações
    `R_X86_64_RELATIVE` aplicadas;
  * **APK/Android** — descomprime o ZIP (com **inflate DEFLATE próprio**),
    lê o `AndroidManifest.xml` binário (AXML), o `classes.dex` e as libs.
* **Apps** (todos `.ENZ`): Terminal, Info, Paint, Calculadora, Notas, Plasma,
  **FILES** (navegador do ENZFS), **EnzoFox** (navegador HTTP real pela e1000)
  e **SysMon** (swap/HPET/uptime + teste de áudio), além do **Mandelbrot**
  compilado da linguagem ENZ.
* **Interpretador SCRIPT.RUN**, **watchdog** de processos travados e
  **Ctrl+C** funcionando.

Otimizado para o **Acer Aspire 3 N5030 / Intel UHD Graphics 605**
(modo VESA 1280×1024@32, PS/2, AHCI, e1000 — drivers nativos, sem BIOS).

## Compilando

```bash
bash build.sh          # requer: nasm >= 2.15 e python3
```

Saídas: `release/enzos.iso` (ISO bootável com tudo) e `release/disk.img`
(disco ENZFS com arquivos iniciais + área de swap).

## Rodando no QEMU

```bash
qemu-system-x86_64 -m 2048 -machine q35 -boot d \
  -drive id=cd0,if=none,format=raw,media=cdrom,file=release/enzos.iso \
  -device ide-cd,drive=cd0,bus=ahci0.0 \
  -drive id=hd0,if=none,format=raw,file=release/disk.img \
  -device ide-hd,drive=hd0,bus=ahci0.1 \
  -netdev user,id=n0 -device e1000,netdev=n0 \
  -device intel-hda -device hda-duplex        # áudio (opcional)
```

Na rede do QEMU (`-netdev user`), o host é `10.0.2.2`. Abra o **EnzoFox**,
digite `http://10.0.2.2:8000/` e Enter — com `python3 -m http.server 8000`
na máquina host, a página aparece renderizada no SO.

## Formato .ENZ

```
+0  "ENZ1"        +4 dw hdrsz(64)   +6 dw flags    +8 dd entry RVA
+12 dd isize      +16 dd nimports   +20 dw win_w   +22 dw win_h
+24 dd cor ícone  +28 db nome[20]   +48 dd imp_off +52 dd sdk(2)
arquivo = [header 64][imagem isize][imports ASCIZ]
```

No carregamento (`kernel/enz.inc`), cada nome de import é resolvido contra
`k_exports` e a tabela própria do app recebe os ponteiros — índice 1..36 na
mesma ordem de `k_exports`:

```
1 rect      2 text       3 blit     4 title     5 uptime   6 file_open
7 files_count  8 file_name  9 exec  10 conout_read  11 rand  12 invalidate
13 alloc    14 free       15 sysinfo 16 time     17 exit    18 beep
19 self     20 px         21 line   22 grad      23 round   24 blend
25 fs_open  26 fs_list    27 fs_read 28 fs_write 29 fs_creat 30 fs_mkdir
31 fs_unlink 32 net_get   33 swap_info 34 swap_force 35 hpet_ns 36 tone
```

Eventos enviados ao app: `INIT` (w/h), `PAINT`, `MOUSE` (x/y/botões/press),
`KEY`, `TICK`, `QUIT`.

## Linguagem ENZ (`tools/enzc.py`)

```c
int pal[32];

void init() {                             // roda uma vez
    int i = 0;
    while (i < 32) {
        pal[i] = 0xFF000000 | (i * 8 << 16);
        i = i + 1;
    }
}

void paint() {                            // desenha a janela
    int x = 0;
    while (x < win_w) {
        px(x, 10, pal[x % 32]);
        x = x + 1;
    }
    text(8, 30, "escrito em ENZ", 0xFFFFFF);
}
```

Handlers: `init`, `paint`, `tick`, `key(k)`, `mouse(x, y, b, p)`.
Compilar: `python3 tools/enzc.py app.enz app.asm && nasm -f bin -o app.bin
app.asm && python3 tools/mkenz.py app.bin APP.ENZ --name App --imports all`.

## Ferramentas

| arquivo | o que faz |
|---|---|
| `tools/mkenz.py` | gera apps `.ENZ` (de `.ce` ou de `.bin` cru) |
| `tools/enzc.py` | compilador da linguagem ENZ → x86-64 |
| `tools/mkfs.py` | cria o disco ENZFS (+ área de swap) |
| `tools/mkiso.py` | ISO bootável El Torito com CEFS embutido |
| `tools/mkpe.py` / `mkelf.py` / `mkapk.py` | demos PE/ELF/APK |
| `tools/selftest.py` | verificação estática da ISO (tudo, inclusive `.ENZ`) |
| `tools/qmp_test.py` | bota no QEMU (q35/AHCI/e1000), exercita e tira capturas |

## CI

O [GitHub Actions](.github/workflows/enzoos-ci.yml) compila tudo, roda o
`selftest.py`, sobe o QEMU **q35 com AHCI + e1000**, serve uma página HTTP na
porta 8000 do runner, abre o **EnzoFox** e fotografa a página baixada —
as capturas e a ISO vão para os artefatos. O serial precisa conter
`[net] conectado via DHCP` e `[enzfs] volume montado`, senão o CI falha.

## Layout do repositório

```
boot/     MBR + stage1 (modo real → longo)
kernel/   kernel: mm, intr, gfx+gfx2, wm, cefs+enzfs, swap, ahci, hpet,
          e1000, net, hda, pe, elf, zip, axml, enz
apps/     apps em assembly (.asm) + mandel.enz (linguagem ENZ)
demos/    fontes das demos PE/ELF/APK
tools/    mkenz, enzc, mkfs, mkiso, mkpe, mkelf, mkapk, selftest, qmp_test
release/  enzos.iso + disk.img (gerados)
```
