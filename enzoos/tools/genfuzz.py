#!/usr/bin/env python3
# =============================================================================
#  EnzoOS — tools/genfuzz.py: gera binários malformados para o pen-test
#
#  A partir de um .ENZ válido (base), produz variantes que um loader robusto
#  deve rejeitar sem executar nada nem pânico:
#
#    TRUNC.ENZ   — arquivo cortado no meio do cabeçalho (12 bytes)
#    BADENT.ENZ  — entry RVA fora da imagem (0xFFFFFF00)
#    BADIMP.ENZ  — importa um símbolo que não existe ("nao_existe_12345")
#    HUGE.ENZ    — cabeçalho declara isize gigante (0xFFFFFF00)
#    ZERO.ENZ    — arquivo de zeros
#    NOTENZ.ENZ  — lixo sem magic algum
# =============================================================================
import sys
import struct

def main():
    if len(sys.argv) != 3:
        print("uso: genfuzz.py <base.ENZ> <outdir>")
        sys.exit(1)
    base = open(sys.argv[1], "rb").read()
    out = sys.argv[2]

    def w(name, data):
        open("%s/%s" % (out, name), "wb").write(data)

    # TRUNC: só os primeiros 12 bytes do arquivo
    w("TRUNC.ENZ", base[:12])

    # BADENT: cópia com entry RVA impossível
    bad = bytearray(base)
    struct.pack_into("<I", bad, 8, 0xFFFFFF00)
    w("BADENT.ENZ", bytes(bad))

    # BADIMP: entry válida, mas importa símbolo inexistente
    # (reconstrói a área de imports: nimports=1 + string)
    bad2 = bytearray(base)
    nimp_off = 16
    imp_off = struct.unpack_from("<I", bad2, 48)[0]
    if imp_off == 0 or imp_off > len(base):
        imp_off = len(base)
    struct.pack_into("<I", bad2, nimp_off, 1)
    body = bytes(bad2[:imp_off]) + b"nao_existe_12345\x00"
    w("BADIMP.ENZ", body)

    # HUGE: isize gigante no cabeçalho, arquivo pequeno
    bad3 = bytearray(base)
    struct.pack_into("<I", bad3, 12, 0xFFFFFF00)
    w("HUGE.ENZ", bytes(bad3))

    # ZERO: puro zero
    w("ZERO.ENZ", b"\x00" * 256)

    # NOTENZ: lixo sem magic
    w("NOTENZ.ENZ", b"GARBAGEGARBAGE" * 20)

    print("genfuzz: 6 arquivos malformados em %s" % out)

if __name__ == "__main__":
    main()
