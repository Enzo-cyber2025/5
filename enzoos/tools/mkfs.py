#!/usr/bin/env python3
# =============================================================================
#  EnzoOS — tools/mkfs.py: cria uma imagem de disco ENZFS (para o QEMU/CI)
#
#  Superbloco (setor 0):
#    +0  "ENZFS1.0"  +8 dd block_size(4096)  +12 dd nblocks
#    +16 dd bitmap_blk(1)  +20 dd inode_blk(2)  +24 dd data_blk(6)
#    +28 dd n_inodes(256)  +32 dq swap_lba  +40 dd swap_slots
#  Inode (64 B): flags(1=arq,2=dir), size, blocks[13], ctime
#  Entrada de diretório (32 B): name[24], ino, rsv
#  Área de troca (swap_lba): "SWP\0" + dd rsv + dd slots + slots*4 KB
#
#  Uso: python3 tools/mkfs.py disk.img arquivo1 arquivo2 ... [--swap N]
#       (arquivos entram na raiz; "dir/" cria diretório; "dir/arq" aninha)
# =============================================================================
import sys
import struct
import argparse
import time

BLOCK = 4096
SECT = 512
NINODES = 256
INODE_TBL_BLOCKS = 4          # 256 * 64 B = 16 KB
BITMAP_BLK = 1
INODE_BLK = 2
DATA_BLK = 6
DIRENTS_PER_BLOCK = 128

INO_ROOT = 0


class Fs:
    def __init__(self, nblocks, swap_slots):
        self.nblocks = nblocks
        self.swap_slots = swap_slots
        self.blocks = [bytearray(BLOCK) for _ in range(nblocks)]
        self.inodes = [bytearray(64) for _ in range(NINODES)]
        # raiz
        self.inodes[0][0:4] = struct.pack("<I", 2)     # diretório
        self.bitmap_set(0)                              # superbloco
        for b in range(BITMAP_BLK, DATA_BLK):
            self.bitmap_set(b)

    # ---- bitmap ----
    def bitmap_set(self, blk):
        self.blocks[BITMAP_BLK][blk >> 3] |= 1 << (blk & 7)

    def alloc_block(self):
        for b in range(DATA_BLK, self.nblocks):
            if not (self.blocks[BITMAP_BLK][b >> 3] & (1 << (b & 7))):
                self.bitmap_set(b)
                self.blocks[b] = bytearray(BLOCK)
                return b
        raise RuntimeError("disco cheio")

    def alloc_inode(self, flags, size):
        for i in range(1, NINODES):
            if self.inodes[i][0:4] == b"\0\0\0\0":
                self.inodes[i][0:4] = struct.pack("<I", flags)
                self.inodes[i][4:8] = struct.pack("<I", size)
                self.inodes[i][60:64] = struct.pack("<I", int(time.time()))
                return i
        raise RuntimeError("sem inodes")

    # ---- diretórios ----
    def add_dirent(self, dino, name, ino):
        if len(name) > 23:
            raise RuntimeError(f"nome longo: {name}")
        for bi in range(13):
            blk = struct.unpack_from("<I", self.inodes[dino], 8 + bi * 4)[0]
            if blk == 0:
                blk = self.alloc_block()
                struct.pack_into("<I", self.inodes[dino], 8 + bi * 4, blk)
            data = self.blocks[blk]
            for e in range(DIRENTS_PER_BLOCK):
                off = e * 32
                if data[off] == 0:
                    data[off:off + 24] = name.encode() + b"\0" * (24 - len(name))
                    struct.pack_into("<I", data, off + 24, ino)
                    return
        raise RuntimeError("diretório cheio")

    def mkdir(self, parent, name):
        ino = self.alloc_inode(2, 0)
        self.add_dirent(parent, name, ino)
        return ino

    def write_file(self, parent, name, content):
        need = (len(content) + BLOCK - 1) // BLOCK
        if need > 13:
            raise RuntimeError(f"arquivo grande demais: {name}")
        ino = self.alloc_inode(1, len(content))
        for bi in range(need):
            blk = self.alloc_block()
            struct.pack_into("<I", self.inodes[ino], 8 + bi * 4, blk)
            chunk = content[bi * BLOCK:(bi + 1) * BLOCK]
            self.blocks[blk][0:len(chunk)] = chunk
        self.add_dirent(parent, name, ino)
        return ino

    # ---- serialização ----
    def build(self):
        # inodes -> blocos 2..5
        for i, ino in enumerate(self.inodes):
            off = i * 64
            for bi in range(4):
                b = INODE_BLK + bi
                o2 = off - bi * BLOCK
                if 0 <= o2 < BLOCK:
                    self.blocks[b][o2:o2 + 64] = ino
        # dados
        nblocks = self.nblocks
        swap_lba = nblocks * (BLOCK // SECT)
        total_sectors = swap_lba + 1 + self.swap_slots * 8
        img = bytearray(total_sectors * SECT)
        for b in range(nblocks):
            img[b * BLOCK:(b + 1) * BLOCK] = self.blocks[b]
        # superbloco
        sb = bytearray(BLOCK)
        sb[0:8] = b"ENZFS1.0"
        struct.pack_into("<I", sb, 8, BLOCK)
        struct.pack_into("<I", sb, 12, nblocks)
        struct.pack_into("<I", sb, 16, BITMAP_BLK)
        struct.pack_into("<I", sb, 20, INODE_BLK)
        struct.pack_into("<I", sb, 24, DATA_BLK)
        struct.pack_into("<I", sb, 28, NINODES)
        struct.pack_into("<Q", sb, 32, swap_lba)
        struct.pack_into("<I", sb, 40, self.swap_slots)
        img[0:BLOCK] = sb
        # cabeçalho da área de troca
        sw = bytearray(SECT)
        sw[0:4] = b"SWP\0"
        struct.pack_into("<I", sw, 8, self.swap_slots)
        img[swap_lba * SECT:(swap_lba + 1) * SECT] = sw
        return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("files", nargs="*",
                    help="arquivos; 'dir/' cria diretório; 'dir/arq' aninha")
    ap.add_argument("--blocks", type=int, default=2048)
    ap.add_argument("--swap", type=int, default=2048)
    a = ap.parse_args()

    fs = Fs(a.blocks, a.swap)
    dirs = {"": INO_ROOT}
    for spec in a.files:
        # formato: "destino=arquivo_local" ou só "arquivo_local" (basename)
        if "=" in spec:
            dest, local = spec.split("=", 1)
        else:
            dest, local = spec, spec.split("/")[-1]
        parts = dest.strip("/").split("/")
        parent = INO_ROOT
        for i, p in enumerate(parts):
            last = i == len(parts) - 1
            if not last:
                key = "/".join(parts[:i + 1])
                if key not in dirs:
                    dirs[key] = fs.mkdir(parent, p)
                parent = dirs[key]
            else:
                if not p:
                    continue
                fs.write_file(parent, p, open(local, "rb").read())
    img = fs.build()
    with open(a.out, "wb") as f:
        f.write(img)
    print(f"mkfs: {a.out} — {a.blocks} blocos, swap {a.swap} slots, "
          f"{len(img) // 1024} KB")


if __name__ == "__main__":
    main()
