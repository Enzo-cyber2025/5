#!/bin/bash
# =============================================================================
#  EnzoOS — build.sh: monta tudo (kernel, apps, demos, ISO)
#  Requer: nasm (>=2.15) e python3 no PATH.
# =============================================================================
set -e
cd "$(dirname "$0")"
mkdir -p obj release

echo "== EnzoOS: build =="

# ---- ativos gerados (fonte, mapa de teclado, cursor, logotipo, ícones) ----
python3 tools/gengfx.py
python3 tools/genplasma.py

# ---- boot ----
nasm -f bin -o obj/mbr.bin    boot/mbr.asm
nasm -f bin -o obj/stage1.bin boot/stage1.asm

# ---- kernel ----
nasm -f bin -I kernel/ -o obj/kernel.bin kernel/kernel.asm

# ---- aplicativos: fonte .ce (retrocompat) + formato único .ENZ ----
nasm -f bin -I apps/ -o obj/TERMINAL.ce apps/terminal.asm
nasm -f bin -I apps/ -o obj/INFO.ce     apps/info.asm
nasm -f bin -I apps/ -o obj/PAINT.ce    apps/paint.asm
nasm -f bin -I apps/ -o obj/CALC.ce     apps/calc.asm
nasm -f bin -I apps/ -o obj/NOTAS.ce    apps/notas.asm
nasm -f bin -I apps/ -o obj/PLASMA.ce   apps/plasma.asm

python3 tools/mkenz.py obj/TERMINAL.ce obj/TERMINAL.ENZ
python3 tools/mkenz.py obj/INFO.ce     obj/INFO.ENZ
python3 tools/mkenz.py obj/PAINT.ce    obj/PAINT.ENZ
python3 tools/mkenz.py obj/CALC.ce     obj/CALC.ENZ
python3 tools/mkenz.py obj/NOTAS.ce    obj/NOTAS.ENZ
python3 tools/mkenz.py obj/PLASMA.ce   obj/PLASMA.ENZ

# ---- apps novos: .ENZ cru (org 0, sem cabeçalho .ce) ----
nasm -f bin -I apps/ -o obj/files.bin  apps/files.asm
nasm -f bin -I apps/ -o obj/fox.bin    apps/fox.asm
nasm -f bin -I apps/ -o obj/sysmon.bin apps/sysmon.asm
python3 tools/mkenz.py obj/files.bin  obj/FILES.ENZ  --name Files  --w 460 --h 380 --icon 0x7FD8FF
python3 tools/mkenz.py obj/fox.bin    obj/FOX.ENZ    --name EnzoFox --w 560 --h 440 --icon 0x2D9CDB
python3 tools/mkenz.py obj/sysmon.bin obj/SYSMON.ENZ --name SysMon --w 460 --h 360 --icon 0x10A372

# ---- demo do compilador ENZ: mandel.enz -> MANDDEL.ENZ ----
python3 tools/enzc.py apps/mandel.enz obj/mandel.asm
nasm -f bin -o obj/mandel.bin obj/mandel.asm
python3 tools/mkenz.py obj/mandel.bin obj/MANDEL.ENZ --name Mandelbrot \
    --w 520 --h 420 --icon 0xB06FD8 --entry "$(cat obj/mandel.entry)" \
    --imports "$(cat obj/mandel.imports)"

# ---- app de pen-test + binários malformados (hardening) ----
nasm -f bin -I apps/ -o obj/attack.bin apps/attack.asm
python3 tools/mkenz.py obj/attack.bin obj/ATTACK.ENZ --name PenTest \
    --w 460 --h 240 --icon 0xE05555
python3 tools/genfuzz.py obj/CALC.ENZ obj

# ---- demos estrangeiras ----
nasm -f bin -o obj/pe_demo.bin  demos/pe_demo.asm
nasm -f bin -o obj/pe_dll.bin   demos/pe_dll.asm
nasm -f bin -o obj/elf_calc.bin demos/elf_calc.asm
nasm -f bin -l obj/so_demo.lst -o obj/so_demo.bin demos/so_demo.asm

python3 tools/mkpe.py  obj/pe_demo.bin obj/DEMO.EXE
python3 tools/mkpe.py  obj/pe_dll.bin  obj/LIBDEMO.DLL --dll
python3 tools/mkelf.py --exec obj/elf_calc.bin obj/CALC.RUN
python3 tools/mkelf.py --dyn  obj/so_demo.bin obj/so_demo.lst obj/libdemo.so
python3 tools/mkapk.py obj/libdemo.so obj/DEMO.APK
cp demos/SCRIPT.RUN demos/LEIA.TXT obj/

# ---- disco ENZFS persistente (AHCI) com arquivos iniciais ----
python3 tools/mkfs.py release/disk.img \
    LEIA.TXT=obj/LEIA.TXT \
    ENZFS.TXT=demos/ENZFS.TXT \
    DEMOS/MANDEL.TXT=apps/mandel.enz

# ---- ISO bootável (todos os apps em .ENZ) ----
python3 tools/mkiso.py obj/mbr.bin obj/stage1.bin release/enzos.iso \
    obj/kernel.bin \
    obj/TERMINAL.ENZ obj/INFO.ENZ obj/PAINT.ENZ obj/CALC.ENZ \
    obj/NOTAS.ENZ obj/PLASMA.ENZ obj/FILES.ENZ obj/FOX.ENZ \
    obj/SYSMON.ENZ obj/MANDEL.ENZ obj/ATTACK.ENZ \
    obj/TRUNC.ENZ obj/BADENT.ENZ obj/BADIMP.ENZ obj/HUGE.ENZ \
    obj/ZERO.ENZ obj/NOTENZ.ENZ \
    obj/DEMO.EXE obj/CALC.RUN obj/DEMO.APK obj/LIBDEMO.DLL \
    obj/libdemo.so obj/SCRIPT.RUN obj/LEIA.TXT

echo "== pronto: release/enzos.iso + release/disk.img =="
