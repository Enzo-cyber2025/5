#!/usr/bin/env python3
"""Build a BIOS+EFI hard disk and wrap it as a fixed VHD for VirtualBox."""
import os
import struct
import subprocess
import sys
import time
import uuid
import zlib
from pathlib import Path

ROOT = Path("/home/user/5")
sys.path.insert(0, str(ROOT / "src/novaiso"))
from mkiso import write_fat16


def assemble(src: Path, out: Path, text: int):
    obj = Path("/tmp") / (src.stem + ".o")
    subprocess.check_call(["as", "--32", "-o", str(obj), str(src)])
    subprocess.check_call(
        [
            "ld",
            "-m",
            "elf_i386",
            "-Ttext",
            hex(text),
            "--oformat",
            "binary",
            "-o",
            str(out),
            str(obj),
        ]
    )


def crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def guid_bytes(u: uuid.UUID) -> bytes:
    b = u.bytes
    return b[3::-1] + b[5:3:-1] + b[7:5:-1] + b[8:]


def vhd_footer(disk_size: int) -> bytes:
    heads, spt = 16, 63
    cyl = max(1, min(65535, disk_size // (heads * spt * 512)))
    foot = bytearray(512)
    foot[0:8] = b"conectix"
    struct.pack_into(">I", foot, 8, 2)
    struct.pack_into(">I", foot, 12, 0x00010000)
    foot[16:24] = b"\xff" * 8
    struct.pack_into(">I", foot, 24, int(time.time()) - 946684800)
    foot[28:32] = b"nova"
    struct.pack_into(">I", foot, 32, 0x00010000)
    foot[36:40] = b"Wi2k"
    struct.pack_into(">Q", foot, 40, disk_size)
    struct.pack_into(">Q", foot, 48, disk_size)
    struct.pack_into(">H", foot, 56, cyl)
    foot[58] = heads
    foot[59] = spt
    struct.pack_into(">I", foot, 60, 2)  # fixed
    foot[68:84] = uuid.uuid4().bytes
    chk = 0
    for b in foot:
        chk += b
    struct.pack_into(">I", foot, 64, (~chk) & 0xFFFFFFFF)
    return bytes(foot)


def main():
    kern_path = ROOT / "build/linux/arch/x86/boot/bzImage"
    if not kern_path.is_file():
        sys.exit("kernel missing")
    kern = kern_path.read_bytes()

    hdd_dir = ROOT / "src/hddboot"
    mbr_bin = hdd_dir / "mbr.bin"
    stage_bin = hdd_dir / "hddboot.bin"
    assemble(hdd_dir / "mbr.S", mbr_bin, 0x7C00)
    assemble(hdd_dir / "hddboot.S", stage_bin, 0x8000)
    mbr = bytearray(mbr_bin.read_bytes())
    stage = bytearray(stage_bin.read_bytes())
    if len(mbr) > 512:
        sys.exit(f"MBR too big {len(mbr)}")
    mbr.extend(b"\x00" * (512 - len(mbr)))
    mbr[510], mbr[511] = 0x55, 0xAA
    if len(stage) > 8 * 512:
        sys.exit(f"stage2 too big {len(stage)}")

    sector = 512
    disk_mb = 80
    nsec = disk_mb * 1024 * 1024 // sector

    # LBA 0 MBR, LBA 1-8 stage2, LBA 9-33 GPT tables leftover
    # Kernel raw at LBA 64 for the BIOS loader
    kern_lba = 64
    kern_secs = (len(kern) + sector - 1) // sector
    # ESP after kernel, 1 MiB aligned
    esp_lba = ((kern_lba + kern_secs + 2047) // 2048) * 2048
    esp_last = nsec - 34
    if esp_last <= esp_lba + 2048:
        sys.exit("disk too small")

    magic = bytes.fromhex("d4c3b2a11807f6e5")
    pos = bytes(stage).find(magic)
    if pos < 0:
        sys.exit("stage2 magic not found")
    struct.pack_into("<I", stage, pos, kern_lba)
    struct.pack_into("<I", stage, pos + 4, len(kern))
    print("patched HDD loader LBA", kern_lba, "size", len(kern))

    img = bytearray(nsec * sector)
    img[0:512] = mbr
    img[sector:sector + len(stage)] = stage
    img[kern_lba * sector:kern_lba * sector + len(kern)] = kern

    fat_bytes = (esp_last - esp_lba + 1) * sector
    tmp_fat = Path("/tmp/esp-hdd.fat")
    write_fat16({"EFI/BOOT/BOOTX64.EFI": kern}, str(tmp_fat), size=fat_bytes)
    fat = tmp_fat.read_bytes()
    img[esp_lba * sector:esp_lba * sector + len(fat)] = fat[: fat_bytes]

    # Active FAT16 LBA partition covering the ESP (BIOS + some EFI firmware)
    def chs(lba, heads=16, spt=63):
        c = lba // (heads * spt)
        r = lba % (heads * spt)
        h = r // spt
        s = r % spt + 1
        if c > 1023:
            c, h, s = 1023, heads - 1, spt
        return bytes((h, (s & 0x3F) | ((c >> 8) << 6), c & 0xFF))

    part = bytearray(16)
    part[0] = 0x80
    part[1:4] = chs(esp_lba)
    part[4] = 0x0E  # FAT16 LBA
    part[5:8] = chs(esp_last)
    struct.pack_into("<I", part, 8, esp_lba)
    struct.pack_into("<I", part, 12, esp_last - esp_lba + 1)
    img[446:462] = part
    img[510], img[511] = 0x55, 0xAA

    # GPT so Enable-EFI also works
    disk_guid = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeee1")
    part_guid = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeee2")
    efi_type = uuid.UUID("c12a7328-f81f-11d2-ba4b-00a0c93ec93b")
    entries = bytearray(128 * 128)
    e = entries
    e[0:16] = guid_bytes(efi_type)
    e[16:32] = guid_bytes(part_guid)
    struct.pack_into("<Q", e, 32, esp_lba)
    struct.pack_into("<Q", e, 40, esp_last)
    name = "EFI SYSTEM".encode("utf-16le")
    e[56:56 + len(name)] = name
    entries_crc = crc32(entries)

    def make_header(current, backup, entries_lba):
        h = bytearray(sector)
        h[0:8] = b"EFI PART"
        struct.pack_into("<I", h, 8, 0x00010000)
        struct.pack_into("<I", h, 12, 92)
        struct.pack_into("<Q", h, 24, current)
        struct.pack_into("<Q", h, 32, backup)
        struct.pack_into("<Q", h, 40, 34)
        struct.pack_into("<Q", h, 48, nsec - 34)
        h[56:72] = guid_bytes(disk_guid)
        struct.pack_into("<Q", h, 72, entries_lba)
        struct.pack_into("<I", h, 80, 128)
        struct.pack_into("<I", h, 84, 128)
        struct.pack_into("<I", h, 88, entries_crc)
        struct.pack_into("<I", h, 16, crc32(h[:92]))
        return h

    img[sector * 9:sector * 10] = make_header(9, nsec - 1, 10)
    # Don't overwrite stage2 at LBA 1-8; put primary GPT at LBA 9-41 if space
    # Standard GPT is LBA 1 header + LBA 2-33 entries. That collides with stage2.
    # EFI firmware that needs GPT will look at LBA 1. So for EFI-only path
    # they can still boot via the MBR FAT partition (type 0x0E) as an ESP
    # on firmware that accepts MBR ESPs. VirtualBox EFI accepts MBR FAT ESP.
    # Skip writing GPT at LBA 1 to keep stage2 intact.

    out_img = ROOT / "out/NovaLinux-1.0-n5030.img"
    out_vhd = ROOT / "out/NovaLinux-1.0-n5030.vhd"
    out_img.write_bytes(img)
    out_vhd.write_bytes(bytes(img) + vhd_footer(len(img)))
    print("wrote", out_img, len(img))
    print("wrote", out_vhd, out_vhd.stat().st_size)

    import hashlib

    h = hashlib.sha256(out_vhd.read_bytes()).hexdigest()
    (ROOT / "out/NovaLinux-1.0-n5030.vhd.sha256").write_text(
        f"{h}  {out_vhd}\n"
    )
    print("SHA256", h)


if __name__ == "__main__":
    main()
