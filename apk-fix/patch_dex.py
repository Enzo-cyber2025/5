#!/usr/bin/env python3
"""Conservative, size-preserving repairs for the ORIGINAL GGUF Chat 2.0 DEX.

The full repair (file guards + configuration-aware cache) is in
smali/EngineManager.smali and is applied by build_apk.py after these patches.
Unknown or already-patched DEX files are deliberately rejected.
"""
import hashlib
from pathlib import Path
import struct
import sys
import zipfile
import zlib

ORIGINAL_DEX_SHA256 = "2ef843184d5ae3b65e7fd79ea06b29cacd0249d6738c353e5d332b9b334e6f2c"
PATCHES = [
    (0xB470, "39 02 04 00", "38 02 04 00", "Chat.fromJson preserves modelPath"),
    (0xB4A6, "39 02 04 00", "38 02 04 00", "Chat.fromJson preserves mmprojPath"),
    (0x11C28, "39 02 04 00", "38 02 04 00", "ModelInfo.fromJson preserves mmprojPath"),
    (0x11190,
     "71 20 42 02 1b 00 0a 07 71 20 42 02 6b 00 0a 08",
     "01 17 00 00 00 00 01 68 00 00 00 00 00 00 00 00",
     "MainActivity.showMmprojPicker int/float VerifyError"),
    (0xD808, "39 00 04 00", "38 00 04 00", "EngineManager.load preserves mmprojPath"),
]


def patch_bytes(original: bytes) -> bytes:
    if hashlib.sha256(original).hexdigest() != ORIGINAL_DEX_SHA256:
        raise ValueError("DEX desconhecido ou já modificado; use o APK original fixado no README.")
    dex = bytearray(original)
    for offset, old_hex, new_hex, label in PATCHES:
        old, new = bytes.fromhex(old_hex), bytes.fromhex(new_hex)
        if len(old) != len(new) or dex[offset:offset + len(old)] != old:
            raise ValueError(f"Bytes inesperados: {label} em 0x{offset:X}")
        dex[offset:offset + len(old)] = new
    dex[12:32] = hashlib.sha1(dex[32:]).digest()
    dex[8:12] = struct.pack("<I", zlib.adler32(dex[12:]) & 0xFFFFFFFF)
    return bytes(dex)


def patch(apk_path: str, out_dex_path: str) -> None:
    if Path(apk_path).resolve() == Path(out_dex_path).resolve():
        raise ValueError("A saída não pode sobrescrever o APK original.")
    with zipfile.ZipFile(apk_path) as archive:
        data = patch_bytes(archive.read("classes.dex"))
    Path(out_dex_path).write_bytes(data)
    print(f"{len(PATCHES)} patches aplicados: {out_dex_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("Uso: patch_dex.py APK_ORIGINAL DEX_SAIDA")
    patch(*sys.argv[1:])
