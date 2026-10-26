#!/usr/bin/env python3
"""mkelf.py — empacota um payload em um ELF x86-64.

Uso:
  mkelf.py --exec payload.bin saida.run [--base 0x10000000]
      ELF ET_EXEC com um PT_LOAD (endereços absolutos).
  mkelf.py --dyn payload.bin list.lst saida.so
      ELF ET_DYN (biblioteca) com PT_LOAD + PT_DYNAMIC e relocações
      R_X86_64_RELATIVE. Os símbolos `ptr_msg` e `msg2` do .lst definem
      a relocação gerada (prova de carregamento com relocação).
"""
import struct, sys, re

EHDR = 64
PHDR = 56

def build_exec(payload, base=0x10000000):
    off = 0x1000
    total = off + len(payload)
    ehdr = bytearray(EHDR)
    ehdr[0:4] = b'\x7fELF'
    ehdr[4] = 2          # 64 bits
    ehdr[5] = 1          # little endian
    ehdr[6] = 1          # version
    struct.pack_into('<HHIQQQIHHHHHH', ehdr, 16,
                     2,              # e_type ET_EXEC
                     0x3E,           # x86-64
                     1, base + off,  # version, entry
                     EHDR, 0, 0,     # phoff, shoff, flags
                     EHDR, PHDR, 1, 0, 0, 0)
    phdr = struct.pack('<IIQQQQQQ',
                       1,            # PT_LOAD
                       5,            # R+X
                       off, base + off, base + off,
                       len(payload), len(payload),
                       0x1000)
    out = bytearray()
    out += ehdr
    out += phdr
    out += b'\0' * (off - len(out))
    out += payload
    return bytes(out)

def parse_sym(lst_path, name):
    """extrai o valor de um símbolo do listing do nasm"""
    pat = re.compile(r'^\s*\d+\s+([0-9A-Fa-f]+)\s+(?:\S+\s+)?%s\s*:' % re.escape(name), re.M)
    m = pat.search(open(lst_path).read())
    if not m:
        raise SystemExit("mkelf: símbolo %s não achado em %s" % (name, lst_path))
    return int(m.group(1), 16)

def build_dyn(payload, rela_pairs):
    """rela_pairs: lista de (offset_alvo, addend) para R_X86_64_RELATIVE"""
    off = 0x1000                       # payload no arquivo/vaddr
    dyn_off = 0x800                    # PT_DYNAMIC
    rela_off = 0xA00                   # tabela .rela
    total = off + len(payload)
    rela = b''
    for (o, a) in rela_pairs:
        rela += struct.pack('<QQq', o, 8, a)   # r_offset, r_info=8(RELATIVE), r_addend
    dynamic = b''.join(struct.pack('<qQ', t, v) for (t, v) in [
        (7, rela_off), (8, len(rela)), (9, 24), (0, 0)])
    ehdr = bytearray(EHDR)
    ehdr[0:4] = b'\x7fELF'
    ehdr[4] = 2
    ehdr[5] = 1
    ehdr[6] = 1
    struct.pack_into('<HHIQQQIHHHHHH', ehdr, 16,
                     3, 0x3E, 1, off,
                     EHDR, 0, 0, EHDR, PHDR, 2, 0, 0, 0)
    ph1 = struct.pack('<IIQQQQQQ', 1, 5, 0, 0, 0, total, total, 0x1000)
    ph2 = struct.pack('<IIQQQQQQ', 2, 6, dyn_off, dyn_off, dyn_off,
                      len(dynamic), len(dynamic), 8)
    out = bytearray()
    out += ehdr
    out += ph1
    out += ph2
    out += b'\0' * (dyn_off - len(out))
    out += dynamic
    out += b'\0' * (rela_off - len(out))
    out += rela
    out += b'\0' * (off - len(out))
    out += payload
    return bytes(out)

if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    if args[0] == '--exec':
        payload = open(args[1], 'rb').read()
        base = 0x10000000
        if '--base' in args:
            base = int(args[args.index('--base') + 1], 0)
        open(args[2], 'wb').write(build_exec(payload, base))
        print("mkelf: %s (ET_EXEC @0x%X)" % (args[2], base))
    elif args[0] == '--dyn':
        payload = open(args[1], 'rb').read()
        lst = args[2]
        ptr = parse_sym(lst, 'ptr_msg')
        tgt = parse_sym(lst, 'msg2')
        rela = [(0x1000 + ptr, 0x1000 + tgt)]
        open(args[3], 'wb').write(build_dyn(payload, rela))
        print("mkelf: %s (ET_DYN, RELATIVE 0x%X->0x%X)" % (args[3], 0x1000 + ptr, 0x1000 + tgt))
    else:
        print(__doc__)
        sys.exit(1)
