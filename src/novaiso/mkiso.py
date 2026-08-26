#!/usr/bin/env python3
"""ISO9660 + El Torito BIOS/UEFI writer for NovaLinux."""
import datetime
import struct
import sys
from pathlib import Path

SECTOR = 2048


def pad(n, a=SECTOR):
    return (a - (n % a)) % a


def both(s, n):
    if n == 16:
        return struct.pack("<H", s) + struct.pack(">H", s)
    return struct.pack("<I", s) + struct.pack(">I", s)


def a_chars(s, n):
    b = s.encode("ascii", "replace")[:n]
    return b + b" " * (n - len(b))


def d_chars(s, n):
    b = "".join(c if c.isalnum() or c in "_." else "_" for c in s.upper()).encode("ascii")[:n]
    return b + b" " * (n - len(b))


def dec_datetime(dt=None):
    if dt is None:
        dt = datetime.datetime.utcnow()
    return f"{dt.year:04d}{dt.month:02d}{dt.day:02d}{dt.hour:02d}{dt.minute:02d}{dt.second:02d}00".encode() + b"\x00"


def dir_datetime(dt=None):
    if dt is None:
        dt = datetime.datetime.utcnow()
    return bytes([dt.year - 1900, dt.month, dt.day, dt.hour, dt.minute, dt.second, 0])


class Node:
    def __init__(self, name, data=None, children=None, is_dir=False):
        self.name = name
        self.data = data or b""
        self.children = children or []
        self.is_dir = is_dir
        self.lba = 0
        self.size = 0


def add_tree(parent, path: Path):
    for p in sorted(path.iterdir(), key=lambda x: x.name.upper()):
        if p.name.startswith("."):
            continue
        if p.is_dir():
            n = Node(p.name, is_dir=True)
            add_tree(n, p)
            parent.children.append(n)
        else:
            parent.children.append(Node(p.name, data=p.read_bytes()))


def dir_record(name, lba, size, is_dir, ident_raw=None):
    if ident_raw is not None:
        ident = ident_raw
    else:
        if name in (".", ".."):
            ident = b"\x00" if name == "." else b"\x01"
        else:
            nm = name.upper()
            if is_dir:
                ident = nm.encode("ascii", "replace")
            elif "." in nm:
                ident = nm.encode("ascii", "replace")
            else:
                ident = (nm + ";1").encode("ascii", "replace")
    flags = 0x02 if is_dir else 0x00
    rec = bytearray()
    rec += b"\x00"
    rec += b"\x00"
    rec += both(lba, 32)
    rec += both(size, 32)
    rec += dir_datetime()
    rec.append(flags)
    rec += b"\x00\x00"
    rec += both(1, 16)
    rec.append(len(ident))
    rec += ident
    if len(rec) % 2:
        rec += b"\x00"
    rec[0] = len(rec)
    return bytes(rec)


def eltorito_boot_entry(media, sector_count, rba, load_seg=0, sys_type=0):
    """El Torito 32-byte boot entry. Offsets per spec:
    0 bootable, 1 media, 2-3 load segment, 4 sys type, 6-7 sector count, 8-11 RBA.
    """
    e = bytearray(32)
    e[0] = 0x88
    e[1] = media
    struct.pack_into("<H", e, 2, load_seg)
    e[4] = sys_type
    struct.pack_into("<H", e, 6, sector_count)
    struct.pack_into("<I", e, 8, rba)
    return bytes(e)


def find(node, parts):
    if not parts:
        return node
    for c in node.children:
        if c.name == parts[0]:
            return find(c, parts[1:])
    return None


def write_iso(src_dir, out_path, boot_fat_rel="boot/uefi.img"):
    src = Path(src_dir)
    root = Node("", is_dir=True)
    add_tree(root, src)

    files = []

    def collect(n):
        if n.is_dir:
            for c in n.children:
                collect(c)
        else:
            files.append(n)

    collect(root)

    pvd_lba, br_lba, term_lba, cat_lba, next_lba = 16, 17, 18, 19, 20

    def assign_dirs(node):
        nonlocal next_lba
        recs = dir_record(".", 0, 0, True) + dir_record("..", 0, 0, True)
        for c in node.children:
            recs += dir_record(c.name, 0, 0, c.is_dir)
        size = len(recs) + pad(len(recs))
        node.lba = next_lba
        node.size = size
        next_lba += size // SECTOR
        for c in node.children:
            if c.is_dir:
                assign_dirs(c)

    assign_dirs(root)
    for f in files:
        f.size = len(f.data)
        f.lba = next_lba
        next_lba += (f.size + SECTOR - 1) // SECTOR

    boot_node = find(root, boot_fat_rel.split("/"))
    if boot_node is None:
        raise SystemExit("UEFI FAT image not found")

    def build_dir(node, parent):
        recs = dir_record(".", node.lba, node.size, True) + dir_record("..", parent.lba, parent.size, True)
        for c in node.children:
            recs += dir_record(c.name, c.lba, c.size if c.size else len(c.data), c.is_dir)
        recs += b"\x00" * pad(len(recs))
        node.raw = recs
        node.size = len(recs)
        for c in node.children:
            if c.is_dir:
                build_dir(c, node)

    build_dir(root, root)

    pt_le = bytes([1, 0]) + struct.pack("<I", root.lba) + struct.pack("<H", 1) + b"\x00\x00"
    pt_le += b"\x00" * pad(len(pt_le))
    pt_be = bytes([1, 0]) + struct.pack(">I", root.lba) + struct.pack(">H", 1) + b"\x00\x00"
    pt_be += b"\x00" * pad(len(pt_be))
    pt_lba = next_lba
    next_lba += len(pt_le) // SECTOR
    pt_be_lba = next_lba
    next_lba += len(pt_be) // SECTOR
    volume_size = next_lba

    pvd = bytearray(SECTOR)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[6] = 1
    pvd[8:40] = a_chars("NOVALINUX", 32)
    pvd[40:72] = d_chars("NOVALINUX_1_0", 32)
    pvd[80:88] = both(volume_size, 32)
    pvd[120:124] = both(1, 16)
    pvd[124:128] = both(1, 16)
    pvd[128:132] = both(SECTOR, 16)
    pvd[132:140] = both(len(pt_le), 32)
    pvd[140:144] = struct.pack("<I", pt_lba)
    pvd[148:152] = struct.pack(">I", pt_be_lba)
    root_rec = dir_record(".", root.lba, root.size, True)
    pvd[156:156 + len(root_rec)] = root_rec
    pvd[318:446] = a_chars("NOVALINUX", 128)
    pvd[446:574] = a_chars("NOVA PROJECT", 128)
    pvd[574:702] = a_chars("NOVALINUX 1.0", 128)
    pvd[813:830] = dec_datetime()
    pvd[830:847] = dec_datetime()
    pvd[847:864] = b"0" * 16 + b"\x00"
    pvd[881] = 1

    br = bytearray(SECTOR)
    br[0] = 0
    br[1:6] = b"CD001"
    br[6] = 1
    br[7:39] = a_chars("EL TORITO SPECIFICATION", 32)
    br[71:75] = struct.pack("<I", cat_lba)

    term = bytearray(SECTOR)
    term[0] = 255
    term[1:6] = b"CD001"
    term[6] = 1

    bios_node = find(root, ["boot", "biosboot.bin"])
    kern_node = find(root, ["boot", "vmlinuz"])
    if bios_node is not None and kern_node is not None:
        magic = bytes.fromhex("d4c3b2a11807f6e5")
        pos = bios_node.data.find(magic)
        if pos >= 0:
            patched = bytearray(bios_node.data)
            struct.pack_into("<I", patched, pos, kern_node.lba)
            struct.pack_into("<I", patched, pos + 4, kern_node.size)
            bios_node.data = bytes(patched)
            print("patched BIOS loader LBA", kern_node.lba, "size", kern_node.size)
        bd = bytearray(bios_node.data)
        if len(bd) >= 512:
            bd[510], bd[511] = 0x55, 0xAA
            bios_node.data = bytes(bd)

    cat = bytearray(SECTOR)
    cat[0] = 0x01
    cat[1] = 0x00
    cat[30] = 0x55
    cat[31] = 0xAA
    s = 0
    for i in range(0, 32, 2):
        s = (s + cat[i] + (cat[i + 1] << 8)) & 0xFFFF
    chk = (-s) & 0xFFFF
    cat[28] = chk & 0xFF
    cat[29] = (chk >> 8) & 0xFF

    if bios_node is not None:
        bios_secs = max(4, (len(bios_node.data) + 511) // 512)
        cat[32:64] = eltorito_boot_entry(0x00, bios_secs, bios_node.lba)
        cat[64] = 0x91
        cat[65] = 0xEF
        cat[66:68] = struct.pack("<H", 1)
        efi_ent = 96
        print("BIOS entry sectors", bios_secs, "lba", bios_node.lba)
    else:
        print("WARNING: no biosboot.bin")
        cat[32] = 0x91
        cat[33] = 0xEF
        cat[34:36] = struct.pack("<H", 1)
        efi_ent = 64

    load_sectors = min(0xFFFF, (boot_node.size + 511) // 512)
    cat[efi_ent:efi_ent + 32] = eltorito_boot_entry(0x00, load_sectors, boot_node.lba)
    print("EFI entry sectors", load_sectors, "lba", boot_node.lba)

    img = bytearray(volume_size * SECTOR)
    img[pvd_lba * SECTOR:(pvd_lba + 1) * SECTOR] = pvd
    img[br_lba * SECTOR:(br_lba + 1) * SECTOR] = br
    img[term_lba * SECTOR:(term_lba + 1) * SECTOR] = term
    img[cat_lba * SECTOR:(cat_lba + 1) * SECTOR] = cat
    img[pt_lba * SECTOR:pt_lba * SECTOR + len(pt_le)] = pt_le
    img[pt_be_lba * SECTOR:pt_be_lba * SECTOR + len(pt_be)] = pt_be

    def write_dirs(node):
        img[node.lba * SECTOR:node.lba * SECTOR + node.size] = node.raw
        for c in node.children:
            if c.is_dir:
                write_dirs(c)
            else:
                img[c.lba * SECTOR:c.lba * SECTOR + len(c.data)] = c.data

    write_dirs(root)
    Path(out_path).write_bytes(img)
    print("wrote", out_path, "bytes", len(img), "sectors", volume_size)


def write_fat16(files: dict, out_path, size=16 * 1024 * 1024):
    bps = 512
    spc = 8
    reserved = 32
    nfats = 2
    nsectors = size // bps
    root_ent = 512
    root_secs = (root_ent * 32 + bps - 1) // bps
    fat_secs = 1
    while True:
        data_secs = nsectors - reserved - nfats * fat_secs - root_secs
        nclus = data_secs // spc
        need = (nclus + 2) * 2
        fs = (need + bps - 1) // bps
        if fs <= fat_secs:
            fat_secs = fs
            break
        fat_secs = fs
    img = bytearray(size)
    img[0:3] = b"\xeb\x3c\x90"
    img[3:11] = b"MSWIN4.1"
    struct.pack_into("<H", img, 11, bps)
    img[13] = spc
    struct.pack_into("<H", img, 14, reserved)
    img[16] = nfats
    struct.pack_into("<H", img, 17, root_ent)
    if nsectors < 65536:
        struct.pack_into("<H", img, 19, nsectors)
    else:
        struct.pack_into("<I", img, 32, nsectors)
    img[21] = 0xF8
    struct.pack_into("<H", img, 22, fat_secs)
    struct.pack_into("<H", img, 24, 32)
    struct.pack_into("<H", img, 26, 2)
    img[38] = 0x29
    img[39:43] = b"NOVA"
    img[43:54] = b"NOVALINUX  "
    img[54:62] = b"FAT16   "
    img[510] = 0x55
    img[511] = 0xAA

    fat_off = reserved * bps
    fat = bytearray(fat_secs * bps)
    fat[0:4] = b"\xf8\xff\xff\xff"
    next_clus = 2
    root_off = (reserved + nfats * fat_secs) * bps
    data_off = root_off + root_secs * bps
    dirs = {"": []}

    def fat_set(cl, val):
        struct.pack_into("<H", fat, cl * 2, val)

    def alloc_chain(nbytes):
        nonlocal next_clus
        nclus_need = max(1, (nbytes + spc * bps - 1) // (spc * bps))
        first = next_clus
        for i in range(nclus_need):
            cl = next_clus
            next_clus += 1
            fat_set(cl, 0xFFFF if i == nclus_need - 1 else cl + 1)
        return first

    def write_chain(first, data):
        cl = first
        off = 0
        while off < len(data):
            pos = data_off + (cl - 2) * spc * bps
            chunk = data[off:off + spc * bps]
            img[pos:pos + len(chunk)] = chunk
            off += spc * bps
            nxt = struct.unpack_from("<H", fat, cl * 2)[0]
            if nxt >= 0xFFF8:
                break
            cl = nxt

    def add_entry(parent, name, is_dir, first_clus, fsize):
        if "." in name and not is_dir:
            base, ext = name.rsplit(".", 1)
        else:
            base, ext = name, ""
        base = "".join(c for c in base.upper() if c.isalnum() or c in "_")[:8].ljust(8)
        ext = "".join(c for c in ext.upper() if c.isalnum())[:3].ljust(3)
        e = bytearray(32)
        e[0:8] = base.encode("ascii")
        e[8:11] = ext.encode("ascii")
        e[11] = 0x10 if is_dir else 0x20
        struct.pack_into("<H", e, 26, first_clus)
        struct.pack_into("<I", e, 28, fsize)
        dirs.setdefault(parent, []).append(bytes(e))

    efi_first = alloc_chain(spc * bps)
    add_entry("", "EFI", True, efi_first, 0)
    dirs["EFI"] = []
    boot_first = alloc_chain(spc * bps)
    add_entry("EFI", "BOOT", True, boot_first, 0)
    dirs["EFI/BOOT"] = []
    for rel, data in files.items():
        rel = rel.replace("\\", "/").lstrip("/")
        parent = "/".join(rel.split("/")[:-1])
        name = rel.split("/")[-1]
        first = alloc_chain(len(data))
        write_chain(first, data)
        add_entry(parent, name, False, first, len(data))
    img[root_off:root_off + len(b"".join(dirs.get("", [])))] = b"".join(dirs.get("", []))
    write_chain(efi_first, b"".join(dirs.get("EFI", [])))
    write_chain(boot_first, b"".join(dirs.get("EFI/BOOT", [])))
    img[fat_off:fat_off + len(fat)] = fat
    img[fat_off + fat_secs * bps:fat_off + 2 * fat_secs * bps] = fat
    Path(out_path).write_bytes(img)
    print("wrote FAT", out_path, "size", len(img))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: mkiso.py <iso-root-dir> <out.iso>")
        sys.exit(1)
    write_iso(sys.argv[1], sys.argv[2])
