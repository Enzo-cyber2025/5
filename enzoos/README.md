# EnzoOS

**Um sistema operacional completo escrito em Assembly x86-64 puro** — do setor
de boot ao desktop com janelas, passando por kernel, drivers, sistema de
arquivos e tradutores de executáveis PE (.exe/.dll), ELF (.run/.so) e APK.
**Sem uma linha de C.** Cada byte do kernel e dos aplicativos é montado com
[NASM](https://nasm.us) (`nasm -f bin` — kernel binário puro, sem linker).

> "Certamente Executável" — formato nativo `.ce`

![CI](https://github.com/Enzo-cyber2025/5/actions/workflows/enzoos-ci.yml/badge.svg)

## O que é

* **Boot próprio** — MBR + stage1 em modo real que detecta a VESA, monta a
  tabela E820 e carrega o kernel em modo longo (64 bits) **sem GRUB**.
* **Kernel gráfico** — framebuffer linear, janelas com composição,
  barra de tarefas, menu Iniciar, cursor do mouse, relógio na bandeja.
* **Drivers** — controlador PS/2 (teclado + mouse), PIT, PIC, RTC, porta
  serial (log de boot), VIA VT82C586B (tempo real da placa do N5030).
* **CEFS** — sistema de arquivos embutido na imagem de boot.
* **Tradutores de binários** — o kernel **executa de verdade**:
  * **PE/COFF x86-64** (`.exe` e `.dll`) com carregamento de seções;
  * **ELF x86-64** (`.run` ET_EXEC e `.so` ET_DYN) com relocações
    `R_X86_64_RELATIVE` aplicadas;
  * **APK/Android** — descomprime o ZIP (com **inflate DEFLATE próprio**),
    lê o `AndroidManifest.xml` binário (AXML), o `classes.dex` e as libs
    nativas.
* **Apps `.ce`** — Terminal, Info, Paint, Calculadora, Notas e Plasma
  (demo de efeito plasma com paleta gerada por tabela).
* **Interpretador SCRIPT.RUN** — mini-lote que executa programas em sequência.
* **Watchdog** — processo travado em laço infinito é detectado e morto
  (Ctrl+C também funciona).
* **API de apps** — 19 ponteiros de função (janela, gráficos, texto, arquivos,
  console, alocação) passados em tabela; eventos INIT/PAINT/MOUSE/KEY/TICK/QUIT.

Otimizado para o **Acer Aspire 3 N5030 / Intel UHD Graphics 605**
(modo VESA 1280×1024@32, PS/2, VIA VT82C586B para relógio).

## Compilando

Requisitos: `nasm` (≥ 2.15) e `python3`.

```bash
bash build.sh          # monta tudo: kernel, apps, demos e release/enzos.iso
python3 tools/selftest.py release/enzos.iso   # verificação estática dos formatos
```

Teste no QEMU (com capturas de tela via QMP):

```bash
python3 tools/qmp_test.py release/enzos.iso screenshots/
```

Ou interativo:

```bash
qemu-system-x86_64 -m 2048 -cdrom release/enzos.iso
```

## Como usar

| Tecla | Ação |
| --- | --- |
| `Ctrl+Alt+T` | novo Terminal |
| `Ctrl+Alt+C` | Calculadora |
| `Ctrl+Alt+I` | Informações do sistema |
| `Ctrl+Alt+P` | Paint (desenhe com o mouse) |
| `Ctrl+Alt+N` | Notas |
| `Ctrl+Alt+S` | Plasma |
| `Ctrl+Alt+M` | menu Iniciar |
| `F1`–`F5` (no Terminal) | demos **PE**, **ELF**, **APK**, **DLL**, script |
| `Ctrl+C` | interrompe o programa em execução |

O mouse arrasta janelas pela barra de título, fecha (`×`), minimiza (`_`)
e usa o menu Iniciar. No Paint, o botão direito apaga; na Calculadora,
digite `12+34=` e veja o resultado.

## Estrutura

```
enzoos/
├── boot/          MBR + stage1 (modo real → modo longo)
├── kernel/        o kernel inteiro (arquivo por módulo, tudo .asm)
│   ├── kernel.asm entrada; k.inc constantes/API
│   ├── gfx.inc    framebuffer, fonte 8×16, composição de janelas
│   ├── wm.inc     janelas, barra de tarefas, menu, cursor
│   ├── ps2.inc    teclado e mouse PS/2
│   ├── intr.inc   IDT, PIC, PIT, exceções, syscalls (int 0x80)
│   ├── exec.inc   execução de binários estrangeiros + watchdog + Ctrl+C
│   ├── pe.inc     tradutor PE/COFF (.exe/.dll)
│   ├── elf.inc    tradutor ELF (.run/.so) com relocações
│   ├── zip.inc    ZIP (deflate/inflate), AXML e DEX (APK)
│   ├── inflate/   descompressor DEFLATE em assembly
│   ├── cefs.inc   sistema de arquivos CEFS + lançador de apps .ce
│   ├── mm.inc     alocador de heap; cpu.inc CPUID; serial.inc UART16550
│   └── lib.inc    memcpy/memzero/strcmp/…
├── apps/          apps .ce: terminal, info, paint, calc, notas, plasma
├── demos/         payloads-fonte das demos (montados + empacotados)
├── tools/         geradores e empacotadores em Python puro
│   ├── gengfx.py     fonte, keymap, cursor, logotipo e ícones
│   ├── genplasma.py  tabelas de seno/paleta do Plasma
│   ├── mkpe.py       PE32+ (.exe/.dll)
│   ├── mkelf.py      ELF64 (ET_EXEC/ET_DYN com .rela)
│   ├── mkapk.py      APK (AXML + DEX + ZIP)
│   ├── mkiso.py      imagem de boot + ISO El Torito + MBR hibrido
│   ├── selftest.py   verificação estática de todos os formatos
│   └── qmp_test.py   boot no QEMU via QMP + capturas de tela
├── build.sh       build completo
└── release/       enzos.iso — a ISO bootável
```

## Formatos suportados (os tradutores)

| Formato | Arquivo | O que o kernel faz |
| --- | --- | --- |
| `.exe` PE32+ | `DEMO.EXE` | valida DOS/PE, mapeia seções em `PE_BASE`, zera BSS, executa o entry point com int 0x80 (write/exit) |
| `.dll` PE32+ | `LIBDEMO.DLL` | idem + relatório de exportações; flag `IMAGE_FILE_DLL` |
| `.run` ELF64 ET_EXEC | `CALC.RUN` | mapeia PT_LOAD nos endereços absolutos e executa |
| `.so` ELF64 ET_DYN | `libdemo.so` | mapeia na base fixa `ELF_BASE`, lê `PT_DYNAMIC`, aplica relocações `R_X86_64_RELATIVE` e executa |
| `.apk` ZIP | `DEMO.APK` | acha arquivos pelo diretório central, **infla** DEFLATE, interpreta o `AndroidManifest.xml` binário (package, versão, permissões, activity), lê o cabeçalho do `classes.dex` e executa as libs nativas ELF |
| `.ce` nativo | 6 apps | cabeçalho de 64 bytes, entry, argv em memória compartilhada com o kernel |

Todos os payloads de demonstração em `demos/` são 100% position-independent
(`lea` rip-relativo), escritos em Assembly à mão.

## Protocolo de boot (resumo)

1. BIOS carrega o MBR (LBA 0) em 0x7C00; ele se copia para 0x600, valida a
   assinatura `0x5A5AA5A5`, lê o primeiro setor da imagem de boot para
   0x7C00 e salta.
2. Stage1 **parte A** valida a assinatura, lê os campos de patch
   (LBA/tamanho da imagem, offset do CEFS), varre os modos VESA, monta a
   tabela E820 e carrega a imagem inteira em `0x10000` por blocos.
3. Stage1 **parte B** habilita o modo longo, monta páginas, copia o
   KERNEL.BIN do CEFS para `0x100000`, monta os boot params em `0xE00`
   (framebuffer, e820, imagem) e salta para o kernel.
4. O kernel inicializa IDT/PIC/PIT/PS/2/serial, monta o CEFS, abre as
   janelas e assume o desktop.

A ISO é hibrida: El Torito (sem emulação) para BIOS/CD **e** MBR com tabela
de partições para pendrive — os dois caminhos chegam ao mesmo stage1.

## CI

O [GitHub Actions](.github/workflows/enzoos-ci.yml) faz o build completo, roda o
autoteste estático, bota o sistema no QEMU via QMP, exercita janelas e as
demos PE/ELF/APK/DLL, tira ~12 capturas de tela e publica tudo como
artefatos (ISO + PNGs + log serial).

## Licença

Código escrito para este projeto. NASM e QEMU são ferramentas externas usadas
apenas para montagem e teste.
