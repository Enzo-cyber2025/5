#!/usr/bin/env python3
# =============================================================================
# mkfat.py — cria uma imagem FAT12 mínima com os arquivos
#   \EFI\BOOT\BOOTX64.EFI  <- kernel bzImage (PEI, EFI stub)
#   \boot\vmlinuz          <- cópia do kernel
#   \NOVALINUX.TXT
#
# FAT12 simples, 1 sector por cluster, com diretórios EFI/, EFI/BOOT e boot/.
# =============================================================================
import sys, struct, math

def mkent(name8_3, attr, clust, size):
    d = bytearray(32)
    fname, fext = '', ''
    if '.' in name8_3:
        fname, fext = name8_3.rsplit('.', 1)
    else:
        fname = name8_3
    b = (fname.upper().replace(' ', '_') or 'NONAME').encode()
    if len(b) > 8: b = b[:8]
    d[0:len(b)] = b
    e = (fext.upper() or '   ').encode()
    if len(e) > 3: e = e[:3]
    d[8:8+len(e)] = e
    d[11] = attr
    d[26] = clust & 0xFF; d[27] = (clust >> 8) & 0xFF
    d[28] = size & 0xFF; d[29] = (size >> 8) & 0xFF
    d[30] = (size >> 16) & 0xFF; d[31] = (size >> 24) & 0xFF
    d[14] = 0; d[15] = 0; d[16] = 0x21; d[17] = 0x00
    return bytes(d)

def fat12_image(files, outpath, total_sectors=65536, sec=512):
    bps = sec
    n_root = 224
    root_size = n_root * 32
    fat_sectors = 32  # FAT12, 512*1.5 bytes ~ 682 entries per sector => plenty
    n_rsv = 1
    root_sectors = root_size // bps
    data_start = n_rsv + fat_sectors + root_sectors

    total_sectors = total_sectors
    data_sectors = total_sectors - data_start
    cluster_count = data_sectors

    # grava clusters
    clusters = {}
    next_cluster = 2
    file_meta = []
    for path, data in files:
        npages = max(1, (len(data) + bps - 1) // bps)
        start = next_cluster
        next_cluster += npages
        file_meta.append((path, start, len(data)))
        for i in range(npages):
            clusters[start + i] = data[i*bps:(i+1)*bps]
    if next_cluster >= cluster_count + 2:
        print("FAT estourou: precisa mais setores. cluster_count=", cluster_count, "next_cluster=", next_cluster)
        sys.exit(1)

    # FAT (12-bit)
    fat = [0] * (2 + cluster_count)
    fat[0] = 0xFF8
    fat[1] = 0xFFFF
    for path, start, size in file_meta:
        npages = max(1, (size + bps - 1) // bps)
        for i in range(npages):
            c = start + i
            nxt = start + i + 1
            fat[c] = 0xFFFF if nxt >= next_cluster else nxt
    fatbuf = bytearray()
    i = 0
    while i < len(fat):
        a = fat[i]; b = fat[i+1] if i+1 < len(fat) else 0
        fatbuf += struct.pack('<H', a | ((b & 0xF) << 8))
        i += 2
        if i < len(fat):
            fatbuf += struct.pack('<H', fat[i])
            i += 1
    fatbuf = bytes(fatbuf[: bps * fat_sectors]).ljust(bps * fat_sectors, b'\x00')

    # bootsector FAT12
    bs = bytearray(bps)
    def set(o, v): bs[o:o+len(v)] = v
    set(0, b'\xEB\x3C\x90')
    set(3, b'NOVALINUX')
    set(11, struct.pack('<H', bps))
    set(13, b'\x01')
    set(14, struct.pack('<H', n_rsv))
    set(16, b'\x02')
    set(17, struct.pack('<H', n_root))
    if total_sectors < 65536:
        set(19, struct.pack('<H', total_sectors))
    else:
        set(19, b'\x00\x00')
        set(32, struct.pack('<I', total_sectors))
    set(21, b'\xF8')
    set(22, struct.pack('<H', fat_sectors))
    set(24, b'\x00\x00'); set(26, b'\x00\x00'); set(28, b'\x00\x00\x00\x00')
    set(36, b'\x80')
    set(38, b'\x12\x34\x56\x78')
    set(43, b'NOVAEFI    ')
    set(54, b'FAT12   ')
    bs[510] = 0x55; bs[511] = 0xAA

    # setores de diretório
    def add_cluster(data):
        nonlocal next_cluster
        c = next_cluster
        clusters[c] = data[:bps]
        next_cluster += 1
        return c

    efi_dir_start = add_cluster(b'\x00'*bps)
    efi_boot_start = add_cluster(b'\x00'*bps)
    boot_dir_start = add_cluster(b'\x00'*bps)

    # dir EFI contém "BOOT"
    clusters[efi_dir_start] = mkent('BOOT', 0x10, efi_boot_start, 0) + b'\x00'*(bps-32)
    # dir EFI/BOOT contém BOOTX64.EFI
    for path, start, size in file_meta:
        if path.upper() == 'EFI/BOOT/BOOTX64.EFI':
            clusters[efi_boot_start] = mkent('BOOTX64.EFI', 0x20, start, size) + b'\x00'*(bps-32)
    # dir boot/ contém vmlinuz
    for path, start, size in file_meta:
        if path.upper() == 'BOOT/VMLINUZ':
            clusters[boot_dir_start] = mkent('VMLINUZ', 0x20, start, size) + b'\x00'*(bps-32)

    root_entries = []
    root_entries.append(mkent('EFI', 0x10, efi_dir_start, 0))
    root_entries.append(mkent('BOOT', 0x10, boot_dir_start, 0))
    root_entries.append(mkent('NOVALINUX.TXT', 0x20, 0, 0))
    root_dir = b''.join(root_entries).ljust(root_size, b'\x00')

    img = bytearray()
    img += bs
    img += fatbuf
    img += root_dir
    for c in sorted(clusters.keys()):
        img += clusters[c]
    img = bytes(img[: total_sectors*bps]).ljust(total_sectors*bps, b'\x00')
    open(outpath, 'wb').write(img)
    print("FAT12 escrita:", outpath, len(img), "bytes")

if __name__ == '__main__':
    k = sys.argv[1]
    data = open(k, 'rb').read()
    # 32MB para caber kernel
    fat12_image([
        ("EFI/BOOT/BOOTX64.EFI", data),
        ("BOOT/VMLINUZ", data),
        ("NOVALINUX.TXT", b"NovaLinux UEFI ISO\n"),
    ], "efi.img", total_sectors=65536, sec=512)
