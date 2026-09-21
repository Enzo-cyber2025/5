"""Replace the nonconforming C++ runtime, preserving all llama/ggml binaries."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess

from build_diagnostics import ndk_root, NDK_VERSION

RUNTIME_ENTRIES = {f'lib/{abi}/libc++_shared.so' for abi in ('arm64-v8a', 'x86_64')}


def replace_cpp_runtime(archive, output):
    ndk = ndk_root()
    tools = ndk / 'toolchains/llvm/prebuilt/linux-x86_64'
    result, provenance = {}, {'ndk_version': NDK_VERSION, 'runtimes': {}}
    for abi, triple, machine in (('arm64-v8a', 'aarch64-linux-android', 183),
                                 ('x86_64', 'x86_64-linux-android', 62)):
        name = f'lib/{abi}/libc++_shared.so'
        data = (tools / f'sysroot/usr/lib/{triple}/libc++_shared.so').read_bytes()
        if data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', data, 18)[0] != machine:
            raise ValueError(f'Unexpected official C++ runtime architecture: {abi}')
        result[name] = data
        provenance['runtimes'][name] = {'original_sha256': hashlib.sha256(archive.read(name)).hexdigest(),
                                       'replacement_sha256': hashlib.sha256(data).hexdigest()}
    # Small native ABI regression files travel in the CI artifact, never the APK.
    output.mkdir(parents=True, exist_ok=True)
    (output / 'original-libc++_shared.so').write_bytes(archive.read('lib/x86_64/libc++_shared.so'))
    (output / 'fixed-libc++_shared.so').write_bytes(result['lib/x86_64/libc++_shared.so'])
    (output / 'runtime-provenance.json').write_text(json.dumps(provenance, indent=2))
    root = Path(__file__).resolve().parents[1]
    subprocess.run([str(tools / 'bin/x86_64-linux-android24-clang'), '-O2', '-Wall', '-Wextra', '-Werror',
                    '-fPIE', '-pie', '-Wl,-z,max-page-size=16384',
                    str(root / 'tests/native/runtime_probe.c'), str(root / 'tests/native/runtime_probe_x86_64.S'),
                    '-ldl', '-o', str(output / 'runtime-probe')], check=True)
    return result
