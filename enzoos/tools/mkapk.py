#!/usr/bin/env python3
"""mkapk.py — constrói o DEMO.APK (Android) com manifesto AXML binário,
classes.dex válido, biblioteca nativa ELF e um arquivo comprimido (DEFLATE)
para exercitar o descompressor do kernel.

Uso: mkapk.py libdemo.so saida.apk
"""
import struct, sys, zipfile, io

NS_ANDROID = "http://schemas.android.com/apk/res/android"

# ----------------------------------------------------------------------------
# AXML (binary XML do Android)
# ----------------------------------------------------------------------------
def build_axml() -> bytes:
    strings = [
        "manifest", "package", "versionCode", "versionName",     # 0-3
        "uses-sdk", "minSdkVersion",                              # 4-5
        "uses-permission", "application", "label", "debuggable", # 6-9
        "activity", "name", "android", NS_ANDROID,               # 10-13
        "com.enzoos.demo", "1.0", "Demo EnzoOS", ".MainActivity",# 14-17
        "android.permission.INTERNET",                            # 18
        "android.permission.VIBRATE",                             # 19
        "android.permission.CAMERA",                              # 20
    ]
    # ---- string pool (UTF-16) ----
    blob = bytearray()
    offsets = []
    for s in strings:
        offsets.append(len(blob))
        u = s.encode('utf-16-le')
        blob += struct.pack('<H', len(s)) + u
    pool_hdr_size = 28
    pool_size = pool_hdr_size + 4 * len(strings) + len(blob)
    pool = bytearray()
    pool += struct.pack('<HHIIIIII', 0x0001, pool_hdr_size, pool_size,
                        len(strings), 0, 0,
                        pool_hdr_size + 4 * len(strings), 0)
    for o in offsets:
        pool += struct.pack('<I', o)
    pool += blob
    pool += b'\0' * ((8 - len(pool) % 8) % 8)
    # corrige o tamanho
    struct.pack_into('<I', pool, 4, len(pool))

    def attr(ns, name, raw, dtype, data):
        return struct.pack('<IIIHBBI', ns, name, raw, 8, 0, dtype, data)

    TYPE_STRING = 3
    TYPE_INT = 0x10
    TYPE_BOOLEAN = 0x12

    def elem(name_idx, attrs, start=True):
        body = struct.pack('<IIIIHHHHHH',
                           1, 0xFFFFFFFF,          # linha, comentário
                           0xFFFFFFFF,             # ns
                           name_idx,
                           36, 20, len(attrs),     # attrStart (offset no chunk), attrSize, attrCount
                           0, 0, 0)                # id/class/style
        body += b''.join(attrs)
        size = 8 + len(body)
        return struct.pack('<HHI', 0x0102 if start else 0x0103, 16, size) + body

    def ns_chunk(prefix, uri, start=True):
        body = struct.pack('<IIII', 1, 0xFFFFFFFF, prefix, uri)
        return struct.pack('<HHI', 0x0100 if start else 0x0101, 16, 24) + body

    chunks = bytearray()
    chunks += pool
    chunks += ns_chunk(12, 13, True)
    # <manifest package versionCode versionName>
    chunks += elem(0, [
        attr(0xFFFFFFFF, 1, 14, TYPE_STRING, 14),    # package
        attr(0xFFFFFFFF, 2, 0xFFFFFFFF, TYPE_INT, 1),  # versionCode (int)
        attr(0xFFFFFFFF, 3, 15, TYPE_STRING, 15),    # versionName
    ])
    # <uses-sdk minSdkVersion=21>
    chunks += elem(4, [attr(0xFFFFFFFF, 5, 0xFFFFFFFF, TYPE_INT, 21)])
    # <uses-permission android:name=...> ×3
    for perm in (18, 19, 20):
        chunks += elem(6, [attr(13, 11, perm, TYPE_STRING, perm)])
    # <application label debuggable>
    chunks += elem(7, [
        attr(0xFFFFFFFF, 8, 16, TYPE_STRING, 16),    # label
        attr(0xFFFFFFFF, 9, 0xFFFFFFFF, TYPE_BOOLEAN, 1),  # debuggable
    ])
    # <activity android:name=".MainActivity">
    chunks += elem(10, [attr(13, 11, 17, TYPE_STRING, 17)])
    chunks += elem(10, [], start=False)
    chunks += elem(7, [], start=False)
    chunks += elem(6, [], start=False)
    chunks += elem(6, [], start=False)
    chunks += elem(6, [], start=False)
    chunks += elem(4, [], start=False)
    chunks += elem(0, [], start=False)
    chunks += ns_chunk(12, 13, False)

    hdr = struct.pack('<HHI', 0x0003, 8, 8 + len(chunks))
    return hdr + bytes(chunks)

# ----------------------------------------------------------------------------
# DEX mínimo (formato válido, 2 classes)
# ----------------------------------------------------------------------------
def build_dex() -> bytes:
    strs = [
        "Lcom/enzoos/demo/MainActivity;",   # 0
        "Lcom/enzoos/demo/Util;",           # 1
        "Landroid/app/Activity;",           # 2
        "Ljava/lang/Object;",               # 3
        "MainActivity",                     # 4 (nome simples)
        "Util",                             # 5
        "onCreate",                         # 6
        "soma",                             # 7
    ]
    # string data (uleb128 len + bytes + NUL)
    sdata = bytearray()
    soff = []
    for s in strs:
        soff.append(len(sdata))
        n = len(s)
        # uleb128
        while True:
            b = n & 0x7F
            n >>= 7
            if n:
                sdata.append(b | 0x80)
            else:
                sdata.append(b)
                break
        sdata += s.encode() + b'\0'

    HDR = 112
    string_ids_off = HDR
    type_ids_off = string_ids_off + 4 * len(strs)
    class_defs_off = type_ids_off + 4 * 4
    data_off = class_defs_off + 2 * 32
    total = data_off + len(sdata)

    hdr = bytearray(HDR)
    hdr[0:8] = b'dex\n035\x00'
    struct.pack_into('<I', hdr, 8, 0)              # checksum (não verificado)
    struct.pack_into('<I', hdr, 32, total)         # file_size
    struct.pack_into('<I', hdr, 36, HDR)           # header_size
    struct.pack_into('<I', hdr, 40, 0x12345678)    # endian_tag
    struct.pack_into('<I', hdr, 56, len(strs))     # string_ids_size
    struct.pack_into('<I', hdr, 60, string_ids_off)
    struct.pack_into('<I', hdr, 64, 4)             # type_ids_size
    struct.pack_into('<I', hdr, 68, type_ids_off)
    struct.pack_into('<I', hdr, 96, 2)             # class_defs_size
    struct.pack_into('<I', hdr, 100, class_defs_off)
    struct.pack_into('<I', hdr, 112 - 8, len(sdata))  # data_size (aprox)

    out = bytearray(hdr)
    for o in soff:
        out += struct.pack('<I', o)
    # type_ids: 0..3 → string idx 0..3
    for i in range(4):
        out += struct.pack('<I', i)
    # class_defs (32 bytes cada): class_idx, access, super_idx, interfaces_off,
    # source_file_idx, annotations_off, class_data_off, static_values_off
    out += struct.pack('<IIIIIIII', 0, 1, 2, 0, 4, 0, 0, 0)
    out += struct.pack('<IIIIIIII', 1, 1, 3, 0, 5, 0, 0, 0)
    out += sdata
    out += b'\0' * ((4 - len(out) % 4) % 4)
    struct.pack_into('<I', out, 32, len(out))      # file_size real
    return bytes(out)

# ----------------------------------------------------------------------------
def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    so = open(sys.argv[1], 'rb').read()
    out = sys.argv[2]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('AndroidManifest.xml', build_axml(), zipfile.ZIP_STORED)
        z.writestr('classes.dex', build_dex(), zipfile.ZIP_STORED)
        z.writestr('lib/arm64-v8a/libdemo.so', so, zipfile.ZIP_STORED)
        z.writestr('lib/x86_64/libdemo.so', so, zipfile.ZIP_STORED)
        # comprimido — exercita o inflate do kernel
        z.writestr('assets/nota.txt',
                   b"EnzoOS Demo APK\nEste arquivo esta comprimido com DEFLATE\n"
                   b"e o kernel o descomprime ao listar/executar o APK.\n" * 4,
                   zipfile.ZIP_DEFLATED)
        z.writestr('META-INF/MANIFEST.MF',
                   b"Manifest-Version: 1.0\nCreated-By: EnzoOS mkapk\n",
                   zipfile.ZIP_STORED)
    open(out, 'wb').write(buf.getvalue())
    print("mkapk: %s (%d bytes)" % (out, len(buf.getvalue())))

if __name__ == '__main__':
    main()
