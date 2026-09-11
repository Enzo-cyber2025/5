#!/usr/bin/env python3
"""
De-versiona as libs x86_64 REAIS extraídas do GGUF-Chat.apk para que o loader
glibc do host consiga carregá-las (as libs Android usam versionamento "LIBC"
do bionic, que a glibc não conhece).

O que ele faz em cada .so:
  1) Mantém TODOS os bytes de código/dados intactos (nenhum patch em .text).
  2) Marca o tag dinâmico DT_VERSYM como DT_NULL (0). Como VERSYM/VERNEED/
     VERNEEDNUM são as últimas entradas de .dynamic, isso termina o array ali
     e o glibc enxerga a lib como "sem versionamento" (l_info[DT_VERNEED]==NULL,
     então _dl_check_map_versions pula tudo).

Por que não "zerar" os valores (d_ptr=0)?  Porque o glibc faria
  ent = l_addr + 0  ->  lê o header ELF (0x7f 'ELF') como Verneed
  -> "unsupported version 17791 of Verneed record".

Uso:
  python3 deversion.py <lib_de_origem.so> <lib_de_destino.so>
"""
import struct
import sys


def patch(src: str, dst: str) -> None:
    data = bytearray(open(src, 'rb').read())
    assert data[:4] == b'\x7fELF', f'{src} não é ELF'

    # cabeçalho ELF64
    shoff = struct.unpack_from('<Q', data, 0x28)[0]      # e_shoff
    shentsize = struct.unpack_from('<H', data, 0x3A)[0]  # e_shentsize
    shnum = struct.unpack_from('<H', data, 0x3C)[0]      # e_shnum

    dyn_off = dyn_size = None
    for i in range(shnum):
        sh = shoff + i * shentsize
        if struct.unpack_from('<I', data, sh + 4)[0] == 6:  # SHT_DYNAMIC
            dyn_off = struct.unpack_from('<Q', data, sh + 0x18)[0]
            dyn_size = struct.unpack_from('<Q', data, sh + 0x20)[0]
            break
    assert dyn_off is not None, f'{src} sem seção .dynamic'

    done = 0
    for ent in range(dyn_off, dyn_off + dyn_size, 16):
        d_tag = struct.unpack_from('<Q', data, ent)[0]
        if d_tag == 0x6FFFFFF0:  # DT_VERSYM -> DT_NULL (termina o array)
            struct.pack_into('<Q', data, ent, 0)
            done += 1
            print(f'  {src}: DT_VERSYM @0x{ent:x} -> DT_NULL '
                  f'(remove VERSYM/VERNEED/VERNEEDNUM)')
    assert done == 1, f'{src}: esperava 1x DT_VERSYM, achei {done}'

    open(dst, 'wb').write(bytes(data))
    print(f'  -> {dst} escrito ({len(data)} bytes)')


if __name__ == '__main__':
    patch(sys.argv[1], sys.argv[2])
