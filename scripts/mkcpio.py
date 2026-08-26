#!/usr/bin/env python3
"""Write a newc cpio archive from a directory (no host cpio needed)."""
import os
import stat
import sys
from pathlib import Path


def align4(n):
    return (4 - (n % 4)) % 4


def file_type(mode):
    return mode & 0o170000


def walk(root: Path):
    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        filenames.sort()
        p = Path(dirpath)
        rel = p.relative_to(root).as_posix()
        if rel == ".":
            rel = ""
        entries.append(p)
        for fn in filenames:
            entries.append(p / fn)
    return entries


def pack(root, out_path):
    root = Path(root)
    blobs = []

    def add(name, mode, data, ino, uid=0, gid=0, nlink=1, rdev=0, mtime=0):
        name = name.lstrip("/")
        if name == "":
            name = "."
        name_b = name.encode("utf-8") + b"\x00"
        namesize = len(name_b)
        filesize = len(data)
        hdr = (
            "070701"
            + f"{ino:08x}{mode:08x}{uid:08x}{gid:08x}{nlink:08x}{mtime:08x}"
            + f"{filesize:08x}{0:08x}{0:08x}{0:08x}{rdev:08x}{namesize:08x}{0:08x}"
        ).encode("ascii")
        pad1 = b"\x00" * align4(len(hdr) + namesize)
        pad2 = b"\x00" * align4(filesize)
        blobs.append(hdr + name_b + pad1 + data + pad2)

    ino = 1
    for p in walk(root):
        rel = p.relative_to(root).as_posix()
        st = p.lstat()
        mode = st.st_mode
        if stat.S_ISDIR(mode):
            add(rel if rel != "." else ".", mode, b"", ino, nlink=2)
        elif stat.S_ISLNK(mode):
            tgt = os.readlink(p).encode("utf-8")
            add(rel, mode, tgt, ino)
        elif stat.S_ISREG(mode):
            add(rel, mode, p.read_bytes(), ino)
        ino += 1
    add("TRAILER!!!", 0, b"", ino)
    Path(out_path).write_bytes(b"".join(blobs))
    print("cpio", out_path, "bytes", sum(len(b) for b in blobs))


if __name__ == "__main__":
    pack(sys.argv[1], sys.argv[2])
