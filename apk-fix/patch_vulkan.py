"""Route four Vulkan imports to a core-extension adapter; preserve all machine code."""
from pathlib import Path
import struct
import subprocess

from build_diagnostics import ndk_root
from patch_native import executable_sections

ABIS = ('arm64-v8a', 'x86_64')
VULKAN_ENTRIES = {f'lib/{abi}/libggml-vulkan.so' for abi in ABIS}
COMPAT_ENTRIES = {f'lib/{abi}/libggufvk.so' for abi in ABIS}
IMPORTS = {b'vkGetInstanceProcAddr', b'vkGetDeviceProcAddr',
           b'vkGetPhysicalDeviceFeatures2', b'vkCmdCopyBuffer'}


def patch_imports(data):
    before = executable_sections(data)
    shoff = struct.unpack_from('<Q', data, 40)[0]
    size, count, names_index = struct.unpack_from('<HHH', data, 58)
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, shoff + i * size) for i in range(count)]
    names_section = sections[names_index]
    names = data[names_section[4]:names_section[4] + names_section[5]]
    sections = {names[s[0]:].split(b'\0', 1)[0].decode(): s for s in sections}
    if '.hash' in sections:
        raise ValueError('Unexpected SysV symbol hash; cannot rename safely')
    hashed_start = struct.unpack_from('<I', data, sections['.gnu.hash'][4] + 4)[0]
    strings, symbols = sections['.dynstr'], sections['.dynsym']
    string_data = data[strings[4]:strings[4] + strings[5]]
    output = bytearray(data)
    found = set()
    for index, offset in enumerate(range(symbols[4], symbols[4] + symbols[5], symbols[9])):
        name_offset, _, _, section, _, _ = struct.unpack_from('<IBBHQQ', data, offset)
        name = string_data[name_offset:].split(b'\0', 1)[0]
        if name not in IMPORTS:
            continue
        if section != 0 or index >= hashed_start or name in found:
            raise ValueError('Vulkan symbol is defined, hashed, or duplicated')
        version = struct.unpack_from('<H', data, sections['.gnu.version'][4] + index * 2)[0]
        if version != 1:
            raise ValueError('Unexpected Vulkan symbol version')
        found.add(name)
        position = strings[4] + name_offset
        output[position:position + 2] = b'gf'
    if found != IMPORTS:
        raise ValueError('Unexpected Vulkan imports')
    dynamic = sections['.dynamic']
    needed = []
    for offset in range(dynamic[4], dynamic[4] + dynamic[5], 16):
        tag, value = struct.unpack_from('<QQ', data, offset)
        if tag == 1 and string_data[value:].split(b'\0', 1)[0] == b'libvulkan.so':
            needed.append(strings[4] + value)
    if len(needed) != 1:
        raise ValueError('Expected exactly one system Vulkan dependency')
    position = needed[0]
    output[position:position + len(b'libvulkan.so')] = b'libggufvk.so'
    output = bytes(output)
    if len(output) != len(data) or executable_sections(output) != before:
        raise ValueError('Vulkan code/data/address changed')
    return output


def build_vulkan_compat(archive, work):
    tools = ndk_root() / 'toolchains/llvm/prebuilt/linux-x86_64/bin'
    source = Path(__file__).resolve().parent / 'native/vulkan_compat.c'
    result = {}
    for abi, target in zip(ABIS, ('aarch64-linux-android', 'x86_64-linux-android')):
        entry = f'lib/{abi}/libggml-vulkan.so'
        result[entry] = patch_imports(archive.read(entry))
        output = work / f'{abi}-vulkan-compat.so'
        subprocess.run([str(tools / f'{target}24-clang'), '-shared', '-fPIC', '-O2',
                        '-Wall', '-Wextra', '-Werror', '-Wl,--no-undefined',
                        '-Wl,-z,max-page-size=16384', '-Wl,-soname,libggufvk.so',
                        str(source), '-ldl', '-llog', '-o', str(output)], check=True)
        result[f'lib/{abi}/libggufvk.so'] = output.read_bytes()
    return result
