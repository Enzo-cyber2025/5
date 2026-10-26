#!/usr/bin/env python3
"""selftest.py — verificação estática (sem QEMU) da ISO e dos formatos que o
kernel do EnzoOS analisa em tempo de execução. Replica em Python a lógica de
pe_run (kernel/pe.inc), elf_run (kernel/elf.inc), zip_find (kernel/zip.inc),
axml_run (kernel/axml.inc) e do cabeçalho .ce (kernel/k.inc).

Uso: selftest.py release/enzos.iso
"""
import struct, sys, zlib

fails = []

def check(cond, msg):
    print(("  [ok] " if cond else "  [FALHA] ") + msg)
    if not cond:
        fails.append(msg)

# ---------------------------------------------------------------------------
def test_iso(iso):
    print("== ISO ==")
    d = open(iso, 'rb').read()
    check(d[16*2048+1:16*2048+6] == b'CD001', "PVD ISO9660 no LBA16")
    check(d[17*2048+1:17*2048+6] == b'CD001' and d[17*2048] == 0,
          "Boot Record VD no LBA17")
    cat = int.from_bytes(d[17*2048+0x47:17*2048+0x4B], 'little')
    check(cat == 19, "catálogo El Torito aponta para LBA19")
    # checksum do catálogo
    ck = 0
    for i in range(0, 32, 2):
        ck = (ck - int.from_bytes(d[19*2048+i:19*2048+i+2], 'little')) & 0xFFFF
    check(ck == 0, "checksum do catálogo El Torito válido")
    check(d[19*2048+32] == 0x88, "entrada inicial de boot válida")
    load = int.from_bytes(d[19*2048+40:19*2048+44], 'little')
    nsec = int.from_bytes(d[19*2048+38:19*2048+40], 'little')
    check(load == 21 and nsec == 1, "El Torito carrega 1 setor do LBA21")
    check(d[0x1FE:0x200] == b'\x55\xAA', "MBR com assinatura")
    check(int.from_bytes(d[0x1B4:0x1B8], 'little') == 0x5A5AA5A5,
          "MBR com assinatura de patch")
    check(int.from_bytes(d[0x1B0:0x1B4], 'little') == 21 * 4,
          "MBR aponta para a imagem (LBA512 = 84)")

    img = d[21*2048:]
    check(len(img) > 0x2000, "imagem carregada")
    check(int.from_bytes(img[0x1E0:0x1E4], 'little') == 21,
          "patch LBA da imagem")
    # tamanho declarado no registro ISO9660 ENZOOS.IMG
    root = d[20*2048:]
    p = 0
    imgsz = None
    while p < len(root) and root[p]:
        ln = root[p]
        flags = root[p+25]
        nlen = root[p+32]
        if flags & 0x02 == 0:
            imgsz = int.from_bytes(root[p+10:p+14], 'little')
        p += ln
    check(imgsz is not None and imgsz > 0x2000, "ENZOOS.IMG no diretório ISO (%s)" % imgsz)
    check(int.from_bytes(img[0x1E4:0x1E8], 'little') == imgsz,
          "patch de tamanho da imagem")

    # CEFS
    cefs = img[0x2000:]
    check(cefs[:4] == b'CEFS', "CEFS no offset 0x2000")
    n = int.from_bytes(cefs[6:8], 'little')
    ds = int.from_bytes(cefs[8:12], 'little')
    check(0 < n <= 32, "contagem de arquivos (%d)" % n)
    files = []
    for i in range(n):
        e = cefs[16+i*32:16+(i+1)*32]
        name = e[:20].split(b'\x00')[0].decode()
        off = int.from_bytes(e[20:24], 'little')
        size = int.from_bytes(e[24:28], 'little')
        check(len(name) > 0 and off + size <= len(cefs) - ds,
              "entrada %d: %s (%d bytes)" % (i, name, size))
        files.append((name, cefs[ds+off:ds+off+size]))
    check(files[0][0] == 'KERNEL.BIN', "entrada 0 é KERNEL.BIN")
    return dict(files), d

# ---------------------------------------------------------------------------
def test_kernel(kern):
    print("== KERNEL.BIN ==")
    check(kern[:4] == b'CE01', "assinatura do kernel")
    entry = int.from_bytes(kern[8:12], 'little')
    size = int.from_bytes(kern[12:16], 'little')
    check(0 < entry < len(kern), "entry=0x%X dentro do kernel (%d bytes)" % (entry, len(kern)))
    check(kern[entry:entry+2] != b'\x00\x00', "entry não é nulo")

def test_ce(name, blob):
    print("== %s (.ce) ==" % name)
    check(blob[:4] == b'CE01', "assinatura")
    hdrsz = int.from_bytes(blob[4:6], 'little')
    entry = int.from_bytes(blob[8:12], 'little')
    isize = int.from_bytes(blob[12:16], 'little')
    w = int.from_bytes(blob[20:22], 'little')
    h = int.from_bytes(blob[22:24], 'little')
    check(hdrsz == 64, "tamanho de cabeçalho 64")
    check(0 < entry < isize <= len(blob), "entry=0x%X, isize=%d" % (entry, isize))
    check(120 <= w <= 1920 and 90 <= h <= 1080, "janela %dx%d" % (w, h))
    name = blob[28:48].split(b'\x00')[0].decode(errors='replace')
    check(len(name) > 0, "nome: %s" % name)

# ---------------------------------------------------------------------------
def test_pe(name, blob, want_dll):
    print("== %s (PE) ==" % name)
    check(blob[:2] == b'MZ', "assinatura MZ")
    lfanew = int.from_bytes(blob[0x3C:0x40], 'little')
    check(blob[lfanew:lfanew+4] == b'PE\x00\x00', "assinatura PE")
    machine = int.from_bytes(blob[lfanew+4:lfanew+6], 'little')
    nsects = int.from_bytes(blob[lfanew+6:lfanew+8], 'little')
    opt = lfanew + 24
    magic = int.from_bytes(blob[opt:opt+2], 'little')
    chars = int.from_bytes(blob[lfanew+22:lfanew+24], 'little')
    entry = int.from_bytes(blob[opt+16:opt+20], 'little')
    imgsz = int.from_bytes(blob[opt+56:opt+60], 'little')
    imgbase = int.from_bytes(blob[opt+24:opt+32], 'little')
    check(machine == 0x8664, "machine x86-64")
    check(magic == 0x20B, "PE32+")
    check(bool(chars & 0x2000) == want_dll, "flag %s" % ("DLL" if want_dll else "EXE"))
    check(entry < imgsz, "entry 0x%X < SizeOfImage 0x%X" % (entry, imgsz))
    check(imgsz <= 0x08000000, "SizeOfImage dentro do limite")
    secoff = opt + int.from_bytes(blob[lfanew+20:lfanew+22], 'little')
    raw0 = None
    for i in range(nsects):
        s = blob[secoff+i*40:secoff+(i+1)*40]
        vsz = int.from_bytes(s[8:12], 'little')
        raw = int.from_bytes(s[20:24], 'little')
        rsz = int.from_bytes(s[16:20], 'little')
        check(raw + rsz <= len(blob), "seção %d: dados brutos dentro do arquivo" % i)
        if i == 0:
            raw0 = raw
    # entry aponta para bytes não-nulos no mapeamento
    if raw0 is not None:
        off = raw0 + (entry & 0xFFF)
        check(off < len(blob) and blob[off] != 0, "código no entry não-nulo")

# ---------------------------------------------------------------------------
def test_elf(name, blob, want_type):
    print("== %s (ELF) ==" % name)
    check(blob[:4] == b'\x7fELF', "assinatura")
    check(blob[4] == 2 and blob[5] == 1, "64 bits little-endian")
    etype = int.from_bytes(blob[16:18], 'little')
    entry = int.from_bytes(blob[24:32], 'little')
    phoff = int.from_bytes(blob[32:40], 'little')
    phentsz = int.from_bytes(blob[54:56], 'little')
    phnum = int.from_bytes(blob[56:58], 'little')
    check(etype == want_type, "e_type %d" % etype)
    check(phentsz == 56 and 0 < phnum <= 8, "%d program headers" % phnum)
    loads = []
    dynamic = None
    for i in range(phnum):
        ph = blob[phoff+i*56:phoff+(i+1)*56]
        p_type = int.from_bytes(ph[0:4], 'little')
        off = int.from_bytes(ph[8:16], 'little')
        va = int.from_bytes(ph[16:24], 'little')
        fsz = int.from_bytes(ph[32:40], 'little')
        if p_type == 1:
            loads.append((off, va, fsz))
            check(off + fsz <= len(blob), "PT_LOAD dentro do arquivo")
        elif p_type == 2:
            dynamic = (off, fsz)
    check(len(loads) >= 1, "PT_LOAD presente")
    off, va, fsz = loads[0]
    check(va <= entry < va + fsz, "entry 0x%X dentro do PT_LOAD" % entry)
    if etype == 2:   # ET_EXEC
        check(va >= 0x10000000, "base 0x%X (PE_BASE < ELF_BASE)" % va)
    if etype == 3:   # ET_DYN — valida relocações como o kernel
        check(dynamic is not None, "PT_DYNAMIC presente")
        doff, dsz = dynamic
        rela_off = relasz = None
        ents = [(int.from_bytes(blob[doff+i:doff+i+8],'little'),
                 int.from_bytes(blob[doff+i+8:doff+i+16],'little'))
                for i in range(0, dsz, 16)]
        for t, v in ents:
            if t == 7: rela_off = v
            if t == 8: relasz = v
        check(rela_off is not None, "DT_RELA")
        check(relasz is not None and relasz > 0, "DT_RELASZ")
        nrela = relasz // 24
        for i in range(nrela):
            r = blob[rela_off+i*24:rela_off+(i+1)*24]
            r_off = int.from_bytes(r[0:8], 'little')
            r_info = int.from_bytes(r[8:16], 'little')
            addend = int.from_bytes(r[16:24], 'little', signed=True)
            check(r_info == 8, "reloc %d: R_X86_64_RELATIVE" % i)
            check(r_off < fsz and addend < fsz, "reloc %d dentro do PT_LOAD" % i)

# ---------------------------------------------------------------------------
def test_apk(name, blob):
    print("== %s (APK/ZIP) ==" % name)
    # EOCD (como zip_find)
    eocd = blob.rfind(b'PK\x05\x06')
    check(eocd > 0, "EOCD encontrada")
    cd_size = int.from_bytes(blob[eocd+12:eocd+16], 'little')
    cd_off = int.from_bytes(blob[eocd+16:eocd+20], 'little')
    check(cd_size < 4 * 1024 * 1024 and cd_off + cd_size == eocd,
          "diretório central coerente (%d bytes)" % cd_size)
    names = {}
    p = cd_off
    while p < cd_off + cd_size:
        assert blob[p:p+4] == b'PK\x01\x02'
        method = int.from_bytes(blob[p+10:p+12], 'little')
        csize = int.from_bytes(blob[p+20:p+24], 'little')
        usize = int.from_bytes(blob[p+24:p+28], 'little')
        nlen = int.from_bytes(blob[p+28:p+30], 'little')
        elen = int.from_bytes(blob[p+30:p+32], 'little')
        clen = int.from_bytes(blob[p+32:p+34], 'little')
        lho = int.from_bytes(blob[p+42:p+46], 'little')
        nm = blob[p+46:p+46+nlen].decode()
        names[nm] = (method, csize, usize, lho)
        p += 46 + nlen + elen + clen
    for nm in ('AndroidManifest.xml', 'classes.dex', 'lib/arm64-v8a/libdemo.so'):
        check(nm in names, "contém %s" % nm)
    check('assets/nota.txt' in names and names['assets/nota.txt'][0] == 8,
          "assets/nota.txt comprimido (DEFLATE)")
    # valida os cabeçalhos locais como o kernel faz
    for nm, (method, csize, usize, lho) in names.items():
        check(blob[lho:lho+4] == b'PK\x03\x04', "cabeçalho local de %s" % nm)
        if method == 8:
            data_off = lho + 30 + int.from_bytes(blob[lho+26:lho+28], 'little')
            raw = blob[data_off:data_off+csize]
            out = zlib.decompressobj(-15).decompress(raw)
            check(len(out) == usize, "inflate de %s (%d bytes)" % (nm, usize))
    # dex
    dex = names['classes.dex']
    d = blob[dex[3]+30+int.from_bytes(blob[dex[3]+26:dex[3]+28],'little'):][:30]
    check(d[:8] == b'dex\n035\x00', "classes.dex válido")
    # AXML — mesma lógica do kernel
    m = names['AndroidManifest.xml']
    axml = blob[m[3]+30+int.from_bytes(blob[m[3]+26:m[3]+28],'little'):][:m[2]]
    test_axml(axml)
    return names

def test_axml(axml):
    print("== AndroidManifest.xml (AXML) ==")
    check(int.from_bytes(axml[0:2], 'little') == 0x0003, "documento AXML")
    # string pool
    sp = axml[8:]
    sp_type = int.from_bytes(sp[0:2], 'little')
    check(sp_type == 0x0001, "string pool")
    nstr = int.from_bytes(sp[8:12], 'little')
    str_off = int.from_bytes(sp[20:24], 'little')
    def getstr(idx):
        # como o kernel: array de offsets após o cabeçalho (28 bytes),
        # dados em stringsStart; UTF-16LE com u16 de comprimento
        o = int.from_bytes(sp[28+idx*4:32+idx*4], 'little')
        ln = int.from_bytes(sp[str_off+o:str_off+o+2], 'little')
        return sp[str_off+o+2:str_off+o+2+ln*2].decode('utf-16-le')
    # varre os chunks procurando elementos com atributos
    p = 8                              # filhos do documento começam após o cabeçalho
    end = len(axml)
    found = []
    while p + 8 <= end:
        ctype = int.from_bytes(axml[p:p+2], 'little')
        csize = int.from_bytes(axml[p+4:p+8], 'little')
        if ctype == 0x0102:
            name = int.from_bytes(axml[p+20:p+24], 'little')
            attr_start = int.from_bytes(axml[p+24:p+26], 'little')
            nattr = int.from_bytes(axml[p+28:p+30], 'little')
            for a in range(nattr):
                b = p + attr_start + a * 20
                an = int.from_bytes(axml[b+4:b+8], 'little')
                dtype = axml[b+15]
                data = int.from_bytes(axml[b+16:b+20], 'little')
                val = getstr(data) if dtype == 3 else str(data)
                found.append((getstr(name), getstr(an), val))
        if csize <= 0:
            break
        p += csize
    attrs = {(e, a): v for (e, a, v) in found}
    check(('manifest', 'package') in attrs, "package: %s" % attrs.get(('manifest', 'package')))
    check(('manifest', 'versionName') in attrs, "versionName: %s" % attrs.get(('manifest', 'versionName')))
    check(('uses-permission', 'name') in attrs, "uses-permission")
    check(('activity', 'name') in attrs, "activity: %s" % attrs.get(('activity', 'name')))
    check(('application', 'label') in attrs, "label: %s" % attrs.get(('application', 'label')))

# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    files, raw = test_iso(sys.argv[1])
    test_kernel(files['KERNEL.BIN'])
    for name in ('TERMINAL.CE', 'INFO.CE', 'PAINT.CE', 'CALC.CE', 'NOTAS.CE', 'PLASMA.CE'):
        if name in files:
            test_ce(name, files[name])
        else:
            check(False, "%s ausente" % name)
    test_pe('DEMO.EXE', files['DEMO.EXE'], False)
    test_pe('LIBDEMO.DLL', files['LIBDEMO.DLL'], True)
    test_elf('CALC.RUN', files['CALC.RUN'], 2)
    test_elf('LIBDEMO.SO', files['LIBDEMO.SO'], 3)
    test_apk('DEMO.APK', files['DEMO.APK'])

    print()
    if fails:
        print("SELFTEST: %d falhas" % len(fails))
        sys.exit(1)
    print("SELFTEST: tudo ok")

if __name__ == '__main__':
    main()
