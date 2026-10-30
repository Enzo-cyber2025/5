#!/usr/bin/env python3
"""mkiso.py — monta a imagem de boot do EnzoOS e a ISO bootável (El Torito +
MBR isohybrid-like), tudo em Python puro, sem xorriso.

Layout da imagem de boot (carregada pelo stage1 em 0x10000):
  +0x0000  stage1.bin (parte A em 0, parte B em 0x200)
  +0x1E0   u32 LBA da imagem (setores de 2048)   [patch]
  +0x1E4   u32 tamanho total da imagem           [patch]
  +0x1EC   u32 assinatura 0x5A5AA5A5
  +0x2000  CEFS: 'CEFS', u32 versão, u16 nº de arquivos, u32 data_start,
           entradas de 32 bytes {nome[20], offset, tamanho, flags}, dados.

Layout da ISO (setores de 2048):
  LBA 0-15   área de sistema (LBA 0 = MBR com patch da imagem)
  LBA 16     Primary Volume Descriptor
  LBA 17     Boot Record VD (El Torito)
  LBA 18     Volume Descriptor Terminator
  LBA 19     catálogo El Torito (validação + entrada no-emulação)
  LBA 20     raiz do diretório ISO9660 (., .., ENZOOS.IMG)
  LBA 21     IMAGEM DE BOOT (o MBR aponta cá; El Torito idem)
"""
import struct, sys, os

SECT = 2048
IMG_LBA = 21
ROOT_LBA = 20

def build_image(stage1: bytes, files: list) -> bytes:
    """files: [(nome, bytes)] — o primeiro DEVE ser KERNEL.BIN."""
    hdr_area = bytearray(0x2000)
    assert len(stage1) <= 0x2000, "stage1 grande demais"
    hdr_area[:len(stage1)] = stage1
    assert struct.unpack_from('<I', hdr_area, 0x1EC)[0] == 0x5A5AA5A5, \
        "stage1 sem assinatura de patch"

    n = len(files)
    data_start = 16 + 32 * n
    blob = bytearray()
    entries = bytearray()
    for name, data in files:
        nm = name.encode()[:19]
        off = len(blob)
        ent = bytearray(32)
        ent[:len(nm)] = nm
        struct.pack_into('<III', ent, 20, off, len(data), 0)
        entries += ent
        blob += data
        blob += b'\0' * ((4 - len(blob) % 4) % 4)

    cefs = bytearray(16)
    cefs[0:4] = b'CEFS'
    struct.pack_into('<I', cefs, 4, 1)              # versão
    struct.pack_into('<H', cefs, 6, n)              # nº de arquivos
    struct.pack_into('<I', cefs, 8, data_start)     # início dos dados
    cefs += entries
    assert len(cefs) == data_start, (len(cefs), data_start)
    cefs += blob

    img = bytearray(hdr_area)
    img += cefs
    # patch: LBA e tamanho
    struct.pack_into('<II', img, 0x1E0, IMG_LBA, len(img))
    return bytes(img)

# ---------------------------------------------------------------------------
# MBR
# ---------------------------------------------------------------------------
def build_mbr(mbr_bin: bytes, iso_sectors: int) -> bytes:
    m = bytearray(mbr_bin[:512])
    struct.pack_into('<II', m, 0x1B0, IMG_LBA * 4, 0x5A5AA5A5)
    # partição 1: tipo 0x17 (oculta), cobre a ISO toda
    total_lb512 = iso_sectors * 4
    p = bytearray(16)
    p[0] = 0x80                      # bootável
    p[1:4] = bytes([0x20, 0x21, 0x00])   # CHS início (aprox.)
    p[4] = 0x17
    p[5:8] = bytes([0xFE, 0xFF, 0xFF])   # CHS fim
    struct.pack_into('<II', p, 8, 64, max(1, total_lb512 - 64))
    m[0x1BE:0x1BE+16] = p
    m[510:512] = b'\x55\xAA'
    return bytes(m)

# ---------------------------------------------------------------------------
# ISO9660
# ---------------------------------------------------------------------------
def dir_record(name: bytes, lba: int, size: int, flags: int, is_dir=False) -> bytes:
    """registro de diretório ISO9660 (33 bytes de base + identificador)"""
    ext = name if is_dir else (name + b';1')
    rec = bytearray()
    rec.append(0)                                  # 0: comprimento (preenchido abaixo)
    rec.append(0)                                  # 1: atributos estendidos
    rec += struct.pack('<I', lba) + struct.pack('>I', lba)      # 2-9: LBA
    rec += struct.pack('<I', size) + struct.pack('>I', size)    # 10-17: tamanho
    rec += bytes(7)                                # 18-24: data/hora (nula)
    rec.append(flags)                              # 25: flags
    rec.append(0)                                  # 26: unidade
    rec.append(0)                                  # 27: interleave
    rec += struct.pack('<HH', 1, 1)                # 28-31: sequência do volume
    rec.append(len(ext))                           # 32: comprimento do identificador
    rec += ext
    if len(rec) % 2:
        rec.append(0)
    rec[0] = len(rec)
    return bytes(rec)

def build_pvd(root_lba: int, root_size: int, vol_size: int) -> bytes:
    pvd = bytearray(SECT)
    pvd[0] = 1                                          # tipo
    pvd[1:6] = b'CD001'
    pvd[6] = 1                                          # versão
    pvd[8:40] = b'ENZO_OS'.ljust(32, b' ')
    pvd[40:72] = b'ENZOOS'.ljust(32, b' ')
    struct.pack_into('<II', pvd, 80, vol_size, vol_size)  # espaço do volume
    struct.pack_into('<HH', pvd, 120, 1, 1)              # conjunto/volume
    struct.pack_into('<H', pvd, 128, SECT)               # tamanho do bloco
    struct.pack_into('<I', pvd, 132, 10)                 # path table size
    struct.pack_into('<I', pvd, 136, 0)                  # L path table
    struct.pack_into('<I', pvd, 140, 0)                  # L opt
    struct.pack_into('<I', pvd, 144, 0)                  # M path table
    struct.pack_into('<I', pvd, 148, 0)                  # M opt
    root = dir_record(b'\x00', root_lba, root_size, 0x02, is_dir=True)
    pvd[156:156+len(root)] = root
    pvd[190:318] = b'EnzoOS'.ljust(128, b' ')           # editora do conjunto
    pvd[318:446] = b'Certamente Executavel'.ljust(128, b' ')
    pvd[518:646] = b'2026'.ljust(128, b' ')             # expira
    pvd[646:774] = b'2026'.ljust(128, b' ')             # efetiva
    pvd[774:902] = b'ENZO_OS'.ljust(128, b' ')          # arquivo de dados? (usado p/ app)
    pvd[902:1030] = b''.ljust(128, b' ')
    pvd[1030:1158] = b''.ljust(128, b' ')
    pvd[1162:1290] = b'ENZO_OS'.ljust(128, b' ')       # reserva do app
    return bytes(pvd)

def build_bvd(cat_lba: int) -> bytes:
    bvd = bytearray(SECT)
    bvd[0] = 0
    bvd[1:6] = b'CD001'
    bvd[6] = 1
    bvd[7:39] = b'EL TORITO SPECIFICATION'.ljust(32, b'\0')
    struct.pack_into('<I', bvd, 0x47, cat_lba)
    return bytes(bvd)

def build_term() -> bytes:
    t = bytearray(SECT)
    t[0] = 255
    t[1:6] = b'CD001'
    t[6] = 1
    return bytes(t)

def build_catalog(img_lba: int) -> bytes:
    cat = bytearray(SECT)
    # validação
    cat[0] = 0x01
    cat[1:3] = b'\x00\x00'              # plataforma 0 = 80x86
    cat[3:5] = b'\x00\x00'
    cat[5:28] = b'ENZO OS BOOT'.ljust(23, b' ')[:23]
    cat[30] = 0x55
    cat[31] = 0xAA
    ck = 0
    for i in range(0, 32, 2):
        if i == 28:
            continue                    # a própria palavra do checksum
        ck = (ck - struct.unpack_from('<H', cat, i)[0]) & 0xFFFF
    struct.pack_into('<H', cat, 28, ck)
    # entrada inicial: sem emulação, carrega 1 setor em 0x7C00
    cat[32] = 0x88                      # bootável
    cat[33] = 0x00                      # sem emulação
    struct.pack_into('<H', cat, 34, 0)  # segmento de carga (0 = 0x7C0)
    cat[36] = 0x00                      # tipo de sistema
    cat[37] = 0x00
    struct.pack_into('<H', cat, 38, 1)  # 1 setor (512)
    struct.pack_into('<I', cat, 40, img_lba)
    return bytes(cat)

def build_root_dir(img_lba: int, img_size: int) -> bytes:
    d = bytearray()
    d += dir_record(b'\x00', ROOT_LBA, 2048, 0x02, is_dir=True)
    d += dir_record(b'\x01', ROOT_LBA, 2048, 0x02, is_dir=True)
    d += dir_record(b'ENZOOS.IMG', img_lba, img_size, 0x00)
    d += b'\0' * (SECT - len(d))
    return bytes(d)

def main():
    if len(sys.argv) < 4:
        print("Uso: mkiso.py mbr.bin stage1.bin saida.iso arquivo1 [arquivo2 ...]")
        sys.exit(1)
    mbr_bin = open(sys.argv[1], 'rb').read()
    stage1 = open(sys.argv[2], 'rb').read()
    out = sys.argv[3]
    files = []
    for f in sys.argv[4:]:
        files.append((os.path.basename(f).upper(), open(f, 'rb').read()))
    assert files[0][0] == 'KERNEL.BIN', "o primeiro arquivo deve ser KERNEL.BIN"

    img = build_image(stage1, files)
    img_sects = (len(img) + SECT - 1) // SECT
    iso_sectors = IMG_LBA + img_sects

    iso = bytearray()
    # área de sistema: 16 setores
    sysarea = bytearray(16 * SECT)
    mbr = build_mbr(mbr_bin, iso_sectors)
    sysarea[:512] = mbr
    iso += sysarea
    iso += build_pvd(ROOT_LBA, 2048, iso_sectors)
    iso += build_bvd(19)
    iso += build_term()
    iso += build_catalog(IMG_LBA)
    iso += build_root_dir(IMG_LBA, len(img))
    assert len(iso) == IMG_LBA * SECT, len(iso)
    iso += img
    # alinhamento opcional
    if len(iso) % SECT:
        iso += b'\0' * (SECT - len(iso) % SECT)

    open(out, 'wb').write(iso)
    print("mkiso: %s (%d KB) — imagem de boot: %d bytes, %d arquivos"
          % (out, len(iso) // 1024, len(img), len(files)))

if __name__ == '__main__':
    main()
