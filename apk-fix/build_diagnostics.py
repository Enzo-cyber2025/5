"""Build a tiny Android stderr/logcat bridge with a pinned NDK; never alter Vulkan."""
import os
from pathlib import Path
import subprocess

NDK_VERSION = '27.2.12479018'
DIAGNOSTIC_ENTRIES = {f'lib/{abi}/libggufdiagnostics.so' for abi in ('arm64-v8a', 'x86_64')}


def build_diagnostics(work):
    ndk = Path(os.environ.get('ANDROID_NDK_HOME',
        str(Path(os.environ.get('ANDROID_HOME', '.cache/android-sdk')) / 'ndk' / NDK_VERSION)))
    properties = ndk / 'source.properties'
    if not properties.is_file() or f'Pkg.Revision = {NDK_VERSION}' not in properties.read_text():
        raise ValueError(f'Android NDK {NDK_VERSION} required via ANDROID_NDK_HOME')
    tools = ndk / 'toolchains/llvm/prebuilt/linux-x86_64/bin'
    source = Path(__file__).resolve().parent / 'native/diagnostics.c'
    result = {}
    for abi, target in (('arm64-v8a', 'aarch64-linux-android'), ('x86_64', 'x86_64-linux-android')):
        output = work / f'{abi}-diagnostics.so'
        subprocess.run([str(tools / f'{target}24-clang'), '-shared', '-fPIC', '-O2',
                        '-D_GNU_SOURCE', '-Wall', '-Wextra', '-Werror',
                        '-Wl,--no-undefined', '-Wl,-z,max-page-size=16384',
                        '-Wl,-soname,libggufdiagnostics.so', str(source), '-llog', '-ldl',
                        '-o', str(output)], check=True)
        result[f'lib/{abi}/libggufdiagnostics.so'] = output.read_bytes()
    return result
