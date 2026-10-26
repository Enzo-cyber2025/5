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

# ---- aplicativos .ce ----
nasm -f bin -I apps/ -o obj/TERMINAL.ce apps/terminal.asm
nasm -f bin -I apps/ -o obj/INFO.ce     apps/info.asm
nasm -f bin -I apps/ -o obj/PAINT.ce    apps/paint.asm
nasm -f bin -I apps/ -o obj/CALC.ce     apps/calc.asm
nasm -f bin -I apps/ -o obj/NOTAS.ce    apps/notas.asm
nasm -f bin -I apps/ -o obj/PLASMA.ce   apps/plasma.asm

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

# ---- ISO bootável ----
python3 tools/mkiso.py obj/mbr.bin obj/stage1.bin release/enzos.iso \
    obj/kernel.bin obj/TERMINAL.ce obj/INFO.ce obj/PAINT.ce obj/CALC.ce \
    obj/NOTAS.ce obj/PLASMA.ce \
    obj/DEMO.EXE obj/CALC.RUN obj/DEMO.APK obj/LIBDEMO.DLL \
    obj/libdemo.so obj/SCRIPT.RUN obj/LEIA.TXT

echo "== pronto: release/enzos.iso =="
