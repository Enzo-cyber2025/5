#!/usr/bin/env python3
"""Aplica TODAS as correcoes de dex no classes.dex do GGUF-Chat.apk.

Correcoes (offsets absolutos dentro de classes.dex, verificados contra o
APK original GGUF-Chat.apk):

  1) FUSAO NAO PERSISTIA  (ModelInfo.fromJson)
     Guard do campo `mmprojPath` compilado com desvio invertido
     (`if-nez` no lugar de `if-eqz`), anulando o path ao recarregar
     models.json. Troca o opcode 0x39 (if-nez) por 0x38 (if-eqz).

  2) VerifyError DE LAUNCH  (MainActivity.showMmprojPicker)
     `Ui.dp(Context;F)I` era chamado com registrador int (v1/v6 reusados
     apos `move-result`), rejeitado pelo verificador do ART:
       "[0x58] register v1 has type Integer but expected Float"
     Os dois invoke redundantes sao substituidos por `move v7,v1` e
     `move v8,v6` (mesmos valores: right=left=dp(14), bottom=top=dp(10)),
     mantendo o tamanho do metodo (branches intactos).

Uso:
    python3 patch_dex.py GGUF-Chat.apk classes-fixed.dex
"""
import sys
import zipfile
import zlib
import hashlib
import struct

PATCHES = [
    # (offset, bytes_origem_hex, bytes_novos_hex, rotulo)
    (0x11C28, "39", "38", "fusao-fromJson-if"),
    (0x11190,
     "71 20 42 02 1b 00 0a 07 71 20 42 02 6b 00 0a 08",
     "01 17 00 00 00 00 01 68 00 00 00 00 00 00 00 00",
     "showMmprojPicker-dp"),
]


def patch(apk_path: str, out_dex_path: str) -> None:
    with zipfile.ZipFile(apk_path) as z:
        dex = bytearray(z.read("classes.dex"))

    for off, old_hex, new_hex, label in PATCHES:
        old = bytes.fromhex(old_hex)
        new = bytes.fromhex(new_hex)
        got = bytes(dex[off:off + len(old)])
        assert got == old, (
            "%s: bytes inesperados em 0x%X (got=%s want=%s)"
            % (label, off, got.hex(" "), old.hex(" "))
        )
        dex[off:off + len(new)] = new
        print("patch [%s] OK em 0x%X" % (label, off))

    # Recalcula cabecalho: signature (SHA-1 de [32:]) e checksum (Adler32 de [12:])
    dex[8:12] = b"\x00" * 4
    dex[12:32] = b"\x00" * 20
    dex[12:32] = hashlib.sha1(bytes(dex[32:])).digest()
    dex[8:12] = struct.pack("<I", zlib.adler32(bytes(dex[12:])) & 0xFFFFFFFF)

    with open(out_dex_path, "wb") as f:
        f.write(dex)
    print("patch OK: %s  (sha1=%s)" % (out_dex_path, hashlib.sha1(dex).hexdigest()))


if __name__ == "__main__":
    patch(sys.argv[1], sys.argv[2])
