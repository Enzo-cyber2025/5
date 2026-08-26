#!/usr/bin/env python3
"""Create a GPT disk image with an EFI System Partition containing BOOTX64.EFI."""
import struct
import uuid
import zlib
from pathlib import Path
import sys

sys.path.insert(0, "/home/user/5/src/novaiso")
from mkiso import write_fat16


def crc32(data):
    return zlib.crc32(data) & 0xFFFFFFFF


def write_gpt_disk(efi_files: dict, out_path: str, disk_mb=64):
    sector = 512
    nsec = disk_mb * 1024 * 1024 // sector
    img = bytearray(nsec * sector)

    # Protective MBR
    img[446] = 0x00
    img[450] = 0xEE
    img[454:458] = struct.pack("<I", 1)
    img[458:462] = struct.pack("<I", nsec - 1)
    img[510] = 0x55
    img[511] = 0xAA

    part_start = 2048  # 1 MiB
    # FAT size: rest minus 34 backup GPT sectors
    part_last = nsec - 34
    part_secs = part_last - part_start + 1
    fat_bytes = part_secs * sector

    tmp_fat = Path("/tmp/esp.fat")
    write_fat16(efi_files, str(tmp_fat), size=fat_bytes)
    fat = tmp_fat.read_bytes()
    if len(fat) > fat_bytes:
        raise SystemExit("ESP too small")
    img[part_start * sector:part_start * sector + len(fat)] = fat

    disk_guid = uuid.UUID("12345678-1234-1234-1234-1234567890ab")
    part_guid = uuid.UUID("abcdef01-2345-6789-abcd-ef0123456789")
    efi_type = uuid.UUID("c12a7328-f81f-11d2-ba4b-00a0c93ec93b")

    def guid_bytes(u: uuid.UUID):
        b = u.bytes
        # GPT uses mixed-endian
        return b[3::-1] + b[5:3:-1] + b[7:5:-1] + b[8:]

    # Partition entry array (LBA 2, 128 entries * 128 = 16384 = 32 sectors)
    entries = bytearray(128 * 128)
    e = entries
    e[0:16] = guid_bytes(efi_type)
    e[16:32] = guid_bytes(part_guid)
    struct.pack_into("<Q", e, 32, part_start)
    struct.pack_into("<Q", e, 40, part_last)
    name = "EFI SYSTEM".encode("utf-16le")
    e[56:56 + len(name)] = name
    entries_crc = crc32(entries)

    def make_header(current, backup, entries_lba):
        h = bytearray(sector)
        h[0:8] = b"EFI PART"
        struct.pack_into("<I", h, 8, 0x00010000)
        struct.pack_into("<I", h, 12, 92)
        # crc at 16 later
        struct.pack_into("<Q", h, 24, current)
        struct.pack_into("<Q", h, 32, backup)
        struct.pack_into("<Q", h, 40, 34)  # first usable
        struct.pack_into("<Q", h, 48, nsec - 34)
        h[56:72] = guid_bytes(disk_guid)
        struct.pack_into("<Q", h, 72, entries_lba)
        struct.pack_into("<I", h, 80, 128)
        struct.pack_into("<I", h, 84, 128)
        struct.pack_into("<I", h, 88, entries_crc)
        struct.pack_into("<I", h, 16, crc32(h[:92]))
        return h

    img[sector:sector * 2] = make_header(1, nsec - 1, 2)
    img[sector * 2:sector * 2 + len(entries)] = entries
    # backup entries at nsec-33, header at nsec-1
    img[(nsec - 33) * sector:(nsec - 33) * sector + len(entries)] = entries
    img[(nsec - 1) * sector:nsec * sector] = make_header(nsec - 1, 1, nsec - 33)

    Path(out_path).write_bytes(img)
    print("wrote disk", out_path, "bytes", len(img))


if __name__ == "__main__":
    kern = Path(sys.argv[1]).read_bytes()
    write_gpt_disk({"EFI/BOOT/BOOTX64.EFI": kern}, sys.argv[2])
