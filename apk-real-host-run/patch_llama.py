#!/usr/bin/env python3
"""Patch do libllama.so REAL do APK (cópia do harness, NÃO o APK).

Troca o campo load_mode de llama_model_default_params de -1 (AUTO -> mmap)
para 0 (NONE -> pread). Sem isso, no host, o caminho mmap corrompe o
bookkeeping de fragmentos (llama_mmap::impl::unmap_fragment -> free(0x1))
e derruba o processo durante o load do modelo.

offset verificado: constante de llama_model_default_params em .rodata
(vaddr 0xc5ef0); campo load_mode = 3º u32 (0xc5ef8).
"""
import struct, sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "/tmp/android-run/libllama.so"
OFF = 0xc5ef8  # load_mode dentro da constante de llama_model_default_params

with open(PATH, "r+b") as f:
    f.seek(OFF)
    old = struct.unpack("<I", f.read(4))[0]
    f.seek(OFF)
    f.write(struct.pack("<I", 0))  # LLAMA_LOAD_MODE_NONE
    print(f"patch: {PATH} load_mode 0x{old:08x} -> 0x00000000 (NONE/pread)")
