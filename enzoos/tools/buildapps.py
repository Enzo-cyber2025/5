#!/usr/bin/env python3
# =============================================================================
#  EnzoOS — tools/buildapps.py: compila em lote os apps gerados (ENZ -> .ENZ)
#
#  1. gera as fontes (tools/genapps.py, importado)
#  2. enzc (compilador ENZ, importado) -> NASM
#  3. nasm -> binario org 0
#  4. empacota .ENZ (mesmo formato do tools/mkenz.py)
#
#  Uso: python3 tools/buildapps.py [escala]
#  Saida: obj/apps/<NOME>.ENZ + obj/apps/manifest.json
# =============================================================================
import json
import os
import struct
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import enzc

ALL_IMPORTS = [
    "rect", "text", "blit", "title", "uptime", "file_open", "files_count",
    "file_name", "exec", "conout_read", "rand", "invalidate", "alloc", "free",
    "sysinfo", "time", "exit", "beep", "self", "px", "line", "grad", "round",
    "blend", "fs_open", "fs_list", "fs_read", "fs_write", "fs_creat",
    "fs_mkdir", "fs_unlink", "net_get", "swap_info", "swap_force", "hpet_ns",
    "tone",
]

SCALE = float(sys.argv[1]) if len(sys.argv) > 1 else 1.15
GEN = os.path.join(ROOT, "apps", "gen")
OUTD = os.path.join(ROOT, "obj", "apps")
OBJ = os.path.join(ROOT, "obj")


def compile_enz(src_path, asm_path):
    """Compila uma fonte ENZ -> NASM. Retorna (imports, entry_rva)."""
    src = open(src_path, encoding="utf-8").read()
    toks = enzc.lex(src)
    globs, funcs = enzc.Parser(toks).program()
    if "paint" not in [f[0] for f in funcs]:
        raise RuntimeError("sem paint()")
    g = enzc.Gen(globs, funcs)
    asm = g.run()
    with open(asm_path, "w", encoding="utf-8") as f:
        f.write(asm)
    imports = [n for n in ALL_IMPORTS if n in g.used_api]
    return imports, g.entry_rva


def package(bin_path, dst, name, w, h, icon, entry, imports):
    data = open(bin_path, "rb").read()
    hdr = bytearray(64)
    hdr[0:4] = b"ENZ1"
    struct.pack_into("<HH", hdr, 4, 64, 0)
    struct.pack_into("<I", hdr, 8, entry)
    struct.pack_into("<I", hdr, 12, len(data))
    struct.pack_into("<I", hdr, 16, len(imports))
    struct.pack_into("<HH", hdr, 20, max(160, w), max(120, h))
    struct.pack_into("<I", hdr, 24, icon & 0xFFFFFF)
    nb = name.encode("ascii", "replace")[:19]
    hdr[28:28 + len(nb)] = nb
    struct.pack_into("<I", hdr, 48, 64 + len(data))
    struct.pack_into("<I", hdr, 52, 2)
    blob = b"".join(s.encode() + b"\0" for s in imports)
    with open(dst, "wb") as f:
        f.write(bytes(hdr))
        f.write(data)
        f.write(blob)
    return 64 + len(data) + len(blob)


def build_one(app):
    name = app["name"]
    src = os.path.join(GEN, name + ".enz")
    asm = os.path.join(OUTD, name + ".asm")
    binp = os.path.join(OUTD, name + ".bin")
    dst = os.path.join(OUTD, name + ".ENZ")
    try:
        return _build_inner(app, name, src, asm, binp, dst)
    except BaseException as e:
        raise RuntimeError("[%s] %s" % (name, e))


def _build_inner(app, name, src, asm, binp, dst):
    imports, entry = compile_enz(src, asm)
    r = subprocess.run(["nasm", "-f", "bin", "-o", binp, asm],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("nasm %s: %s" % (name, r.stderr.strip()[:400]))
    size = package(binp, dst, name, app["w"], app["h"], app["icon"],
                   entry, imports)
    os.remove(asm)
    os.remove(binp)
    return dict(name=name, size=size, cat=app["cat"], icon=app["icon"],
                w=app["w"], h=app["h"])


def main():
    os.makedirs(OUTD, exist_ok=True)
    # 1. gera fontes
    r = subprocess.run([sys.executable, os.path.join(HERE, "genapps.py"),
                        GEN, str(SCALE)], capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        print(r.stderr)
        sys.exit(1)
    apps = json.load(open(os.path.join(GEN, "manifest.json")))
    # limpa .ENZ antigos
    for f in os.listdir(OUTD):
        if f.endswith(".ENZ"):
            os.remove(os.path.join(OUTD, f))
    manifest = []
    fails = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(build_one, a): a for a in apps}
        done = 0
        for fu in futs:
            try:
                manifest.append(fu.result())
            except Exception as e:
                fails.append(str(e))
            done += 1
            if done % 200 == 0:
                print("  %d/%d" % (done, len(apps)))
    if fails:
        print("FALHAS (%d):" % len(fails))
        for f in fails[:20]:
            print("  " + f)
        sys.exit(1)
    manifest.sort(key=lambda m: m["name"])
    with open(os.path.join(OUTD, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    total = sum(m["size"] for m in manifest)
    cats = {}
    for m in manifest:
        cats[m["cat"]] = cats.get(m["cat"], 0) + 1
    print("buildapps: %d apps .ENZ em obj/apps (%d KB total) — %s"
          % (len(manifest), total // 1024, cats))


if __name__ == "__main__":
    main()
