#!/usr/bin/env python3
"""mkpe.py — empacota um payload em um PE (Portable Executable) x86-64.

Uso: mkpe.py payload.bin saida.exe [--dll] [--entry N]

O payload é posicionado no RVA 0x1000 (seção .text). Sem imports e sem
relocações (código freestanding/PIE) — o tradutor PE do EnzoOS carrega em
PE_BASE e executa o AddressOfEntryPoint.
"""
import struct, sys

def build(payload: bytes, dll=False, entry_rva=0x1000) -> bytes:
    FILE_ALIGN = 0x200
    SECT_ALIGN = 0x1000
    sect_raw = 0x200                       # PointerToRawData
    raw_size = (len(payload) + FILE_ALIGN - 1) & ~(FILE_ALIGN - 1)
    size_img = 0x2000                      # headers + .text
    size_hdr = 0x200                       # DOS+PE+COFF+OPT cabem em 0x200

    # ---- DOS header ----
    dos = bytearray(0x40)
    dos[0:2] = b'MZ'
    struct.pack_into('<I', dos, 0x3C, 0x40)

    # ---- COFF ----
    chars = 0x2022 if dll else 0x0022      # EXECUTABLE_IMAGE [+ DLL]
    coff = struct.pack('<HHIIIHH',
                       0x8664,             # Machine AMD64
                       1,                  # NumberOfSections
                       0,                  # TimeDateStamp
                       0, 0,               # símbolos
                       240,                # SizeOfOptionalHeader (PE32+)
                       chars)

    # ---- Optional PE32+ ----
    opt = bytearray(240)
    struct.pack_into('<H', opt, 0, 0x20B)          # Magic
    struct.pack_into('<I', opt, 16, entry_rva)     # AddressOfEntryPoint
    struct.pack_into('<Q', opt, 24, 0x140000000)   # ImageBase
    struct.pack_into('<I', opt, 32, SECT_ALIGN)
    struct.pack_into('<I', opt, 36, FILE_ALIGN)
    struct.pack_into('<I', opt, 56, size_img)      # SizeOfImage
    struct.pack_into('<I', opt, 60, size_hdr)      # SizeOfHeaders
    struct.pack_into('<H', opt, 68, 3)             # Subsystem console
    # NumberOfRvaAndSizes em 108; DataDirs zeradas (sem imports/relocs)

    # ---- seção .text ----
    sect = struct.pack('<8sIIIIIIHHI',
                       b'.text\0\0\0',
                       len(payload),       # VirtualSize
                       0x1000,             # VirtualAddress
                       raw_size,           # SizeOfRawData
                       sect_raw,           # PointerToRawData
                       0, 0, 0, 0,
                       0x60000020)         # CODE|EXECUTE|READ

    out = bytearray()
    out += dos
    out += b'PE\0\0'
    out += coff
    out += opt
    out += sect
    out += b'\0' * (sect_raw - len(out))
    out += payload
    out += b'\0' * (raw_size - len(payload))
    return bytes(out)

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    dll = '--dll' in sys.argv
    entry = 0x1000
    if '--entry' in sys.argv:
        entry = 0x1000 + int(sys.argv[sys.argv.index('--entry') + 1], 0)
    data = open(sys.argv[1], 'rb').read()
    open(sys.argv[2], 'wb').write(build(data, dll, entry))
    print("mkpe: %s (%d bytes)%s" % (sys.argv[2], len(data), " [DLL]" if dll else ""))
