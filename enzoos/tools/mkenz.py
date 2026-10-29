#!/usr/bin/env python3
# =============================================================================
#  EnzoOS — tools/mkenz.py: gera arquivos .ENZ (EnzoOS Native eXecutable)
#
#  Cabeçalho de 64 bytes:
#    +0  "ENZ1"      +4 dw hdrsz(64)  +6 dw flags   +8 dd entry RVA
#    +12 dd isize    +16 dd nimports  +20 dw win_w  +22 dw win_h
#    +24 dd cor      +28 db nome[20]  +48 dd imp_off +52 dd sdk(2)
#  Layout do arquivo: [cabeçalho 64][imagem isize][strings de import ASCIZ]
#
#  Entrada: um app .ce (cabeçalho CE01 — a imagem é reaproveitada 1:1) ou um
#  .bin cru montado com "org 0" (entry --entry, default 0).
#
#  Uso:
#    python3 tools/mkenz.py obj/CALC.ce obj/CALC.ENZ
#    python3 tools/mkenz.py obj/fox.bin obj/FOX.ENZ --name Fox --w 560 --h 420 \
#        --icon 0x2D9CDB --imports "rect,text,net_get,exit"
# =============================================================================
import sys
import argparse
import struct

# ordem EXATA de k_exports no kernel (índices 1..36 da tabela do app)
ALL_IMPORTS = [
    "rect", "text", "blit", "title", "uptime", "file_open", "files_count",
    "file_name", "exec", "conout_read", "rand", "invalidate", "alloc", "free",
    "sysinfo", "time", "exit", "beep", "self", "px", "line", "grad", "round",
    "blend", "fs_open", "fs_list", "fs_read", "fs_write", "fs_creat",
    "fs_mkdir", "fs_unlink", "net_get", "swap_info", "swap_force", "hpet_ns",
    "tone",
]


def main():
    ap = argparse.ArgumentParser(description="Gera app .ENZ")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--name", help="nome do app (default: do cabeçalho .ce)")
    ap.add_argument("--icon", type=lambda x: int(x, 0), default=None)
    ap.add_argument("--w", type=int, default=None)
    ap.add_argument("--h", type=int, default=None)
    ap.add_argument("--entry", type=lambda x: int(x, 0), default=None,
                    help="entry RVA (default: do .ce, ou 0 para .bin cru)")
    ap.add_argument("--imports", default="all",
                    help="'all' ou lista separada por vírgula")
    a = ap.parse_args()

    data = open(a.src, "rb").read()

    if data[:4] == b"CE01" and len(data) >= 64:
        entry, _ = struct.unpack_from("<II", data, 8)
        w, h = struct.unpack_from("<HH", data, 20)
        icon = struct.unpack_from("<I", data, 24)[0]
        name = data[28:48].split(b"\0")[0].decode("ascii", "replace")
        # no .ce o campo isize guarda o tamanho do arquivo inteiro
        image = data[64:]
        isize = len(image)
    else:
        # .bin cru (org 0): a imagem começa logo após o cabeçalho .ENZ de 64
        # bytes — o kernel soma o entry ao ENDEREÇO DO ARQUIVO INTEIRO, então
        # entry=0 faria o app executar os bytes "ENZ1" do cabeçalho (panic)
        entry = a.entry if a.entry is not None else 64
        image = data
        isize = len(image)
        w, h, icon, name = 480, 320, 0x2D9CDB, "App"

    if a.entry is not None:
        entry = a.entry
    if a.w is not None:
        w = a.w
    if a.h is not None:
        h = a.h
    if a.icon is not None:
        icon = a.icon
    if a.name is not None:
        name = a.name

    if a.imports == "all":
        imps = list(ALL_IMPORTS)
    else:
        imps = [s.strip() for s in a.imports.split(",") if s.strip()]
        for s in imps:
            if s not in ALL_IMPORTS:
                print(f"mkenz: import desconhecido '{s}'", file=sys.stderr)
                sys.exit(1)

    hdr = bytearray(64)
    hdr[0:4] = b"ENZ1"
    struct.pack_into("<HH", hdr, 4, 64, 0)
    struct.pack_into("<I", hdr, 8, entry)
    struct.pack_into("<I", hdr, 12, isize)
    struct.pack_into("<I", hdr, 16, len(imps))
    struct.pack_into("<HH", hdr, 20, max(160, w), max(120, h))
    struct.pack_into("<I", hdr, 24, icon & 0xFFFFFF)
    nb = name.encode("ascii", "replace")[:19]
    hdr[28:28 + len(nb)] = nb
    struct.pack_into("<I", hdr, 48, 64 + isize)
    struct.pack_into("<I", hdr, 52, 2)          # sdk = 2 (.ENZ)

    blob = b"".join(s.encode() + b"\0" for s in imps)
    with open(a.dst, "wb") as f:
        f.write(bytes(hdr))
        f.write(image)
        f.write(blob)
    print(f"mkenz: {a.dst} ({64 + isize + len(blob)} bytes, "
          f"{len(imps)} imports, {isize} de imagem, {w}x{h})")


if __name__ == "__main__":
    main()
