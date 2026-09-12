#!/usr/bin/env python3
"""Aplica a correção do bug de persistência da fusão (ModelInfo.fromJson).

O bug: no fromJson do ModelInfo, o guard do campo `mmprojPath` foi compilado
com o desvio INVERTIDO (`if-nez` no lugar de `if-eqz`), o que anula qualquer
path válido ao recarregar `models.json` (a fusão não persiste).

Correção: trocar o opcode 0x39 (if-nez) por 0x38 (if-eqz) no bloco
`if (mmprojPath.equals("null"))` do método.

Uso:
    python3 patch_fusion_bug.py GGUF-Chat.apk /tmp/classes-fixed.dex
"""
import sys
import zipfile
import zlib
import hashlib
import struct

# Offset do opcode `if-nez v2, +004h` dentro de classes.dex (localizado por
# androguard: método ModelInfo.fromJson, code-unit 0xa8).
OPCODE_OFFSET = 0x11C28


def patch(apk_path: str, out_dex_path: str) -> None:
    with zipfile.ZipFile(apk_path) as z:
        dex = bytearray(z.read("classes.dex"))

    assert dex[OPCODE_OFFSET] == 0x39, \
        f"opcode inesperado em 0x{OPCODE_OFFSET:X}: {dex[OPCODE_OFFSET]:02x}"
    dex[OPCODE_OFFSET] = 0x38  # if-nez -> if-eqz

    # Recalcula header do dex: signature (SHA-1 de [32:]) e checksum (Adler32 de [12:])
    dex[8:12] = b"\x00" * 4
    dex[12:32] = b"\x00" * 20
    sig = hashlib.sha1(dex[32:]).digest()
    dex[12:32] = sig
    dex[8:12] = struct.pack("<I", zlib.adler32(dex[12:]) & 0xFFFFFFFF)

    with open(out_dex_path, "wb") as f:
        f.write(dex)
    print(f"patch OK: {out_dex_path}  (sha1={hashlib.sha1(dex).hexdigest()[:16]})")


if __name__ == "__main__":
    patch(sys.argv[1], sys.argv[2])
