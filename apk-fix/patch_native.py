"""Add the missing libdl dependency to the original JNI bridge, not its machine code."""
from patch_generation import patch_generation
import os
from pathlib import Path
import struct
import subprocess

JNI_ENTRIES = {'lib/arm64-v8a/libaijni.so', 'lib/x86_64/libaijni.so'}


def executable_sections(data):
    if data[:6] != b'\x7fELF\x02\x01':
        raise ValueError('Expected little-endian ELF64 JNI bridge')
    shoff = struct.unpack_from('<Q', data, 40)[0]
    entsize, count, strings = struct.unpack_from('<HHH', data, 58)
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, shoff + i * entsize) for i in range(count)]
    names_section = sections[strings]
    names = data[names_section[4]:names_section[4] + names_section[5]]
    kept = {}
    for section in sections:
        name = names[section[0]:].split(b'\0', 1)[0].decode()
        if section[2] & 4 or name in ('.rodata', '.data'):
            kept[name] = (section[3], section[5], data[section[4]:section[4] + section[5]])
    if '.text' not in kept:
        raise ValueError('No executable JNI code found')
    return (data[18:20], kept)  # architecture, addresses, sizes and actual code/data


def patch_jni(data, path):
    tool = str(Path(os.environ.get('PATCHELF', '.venv/bin/patchelf')).resolve())
    path.write_bytes(data)
    def query(flag):
        return subprocess.check_output([tool, flag, str(path)], text=True).strip()
    before_needed = query('--print-needed').splitlines()
    soname = query('--print-soname')
    if sorted(before_needed) != ['libc.so', 'liblog.so'] or soname != 'libaijni.so':
        raise ValueError('JNI dependencies differ from pinned original, or already repaired')
    before_code = executable_sections(data)
    subprocess.run([tool, '--add-needed', 'libdl.so', str(path)], check=True)
    patched = path.read_bytes()
    if sorted(query('--print-needed').splitlines()) != ['libc.so', 'libdl.so', 'liblog.so']:
        raise ValueError('Unexpected patched JNI dependencies')
    if query('--print-soname') != soname or executable_sections(patched) != before_code:
        raise ValueError('JNI executable code/data, architecture or SONAME changed')
    return patched


def patch_archive_jni(archive, work):
    names = {n for n in archive.namelist() if n.endswith('/libaijni.so')}
    if names != JNI_ENTRIES:
        raise ValueError('Unexpected JNI architecture set')
    return {name: patch_jni(patch_generation(archive.read(name)), work / (name.split('/')[1] + '.so')) for name in sorted(names)}
