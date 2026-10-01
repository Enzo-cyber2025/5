#!/usr/bin/env python3
"""Sintaxe do código nativo no host, antes de gastar uma rodada de emulador.

O CI compila o nativo com o NDK: um erro de digitação custa ~25 minutos de fila e
emulador. Este script faz a parte barata aqui — `g++ -fsyntax-only` no mesmo
arquivo que o NDK compila, com as MESMAS declarações que os patches do pipeline
adicionam ao llama.cpp (sem elas o compilador não veria funções que existem na
build real) e com stubs mínimos só para `jni.h`/`android/log.h`.

O que ele NÃO faz: linkar, gerar código, medir nada. Só encontra erro de
compilação que o NDK encontraria mais tarde.

Uso: python3 scripts/check_native_syntax.py
Sai 0 quando a sintaxe está correta, 1 quando há erro de compilação e 0 com
"SKIP" quando falta ferramenta/checkout neste host (falta de material não é
falha do código).
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'apk-fix/native'
CLONE = ROOT / '.cache/llama-mobile'
INCLUDES = ['include', 'ggml/include', 'tools/mtmd', 'common', 'ggml/src']

STUBS = {
    'android/log.h': '''#pragma once
#include <cstdarg>
#define ANDROID_LOG_INFO 4
#define ANDROID_LOG_ERROR 6
int __android_log_print(int prio, const char *tag, const char *fmt, ...);
int __android_log_write(int prio, const char *tag, const char *text);
''',
    'sys/system_properties.h': '''#pragma once
#define PROP_VALUE_MAX 92
int __system_property_get(const char *name, char *value);
''',
}

TRANSLATION_UNITS = ['mobile.cpp', 'cpu_probe.cpp']


def jni_include():
    """jni.h real (o único header do Android que este host consegue ter)."""
    candidates = sorted((ROOT / '.venv').glob('lib/*/site-packages/jdk4py/java-runtime/include'))
    candidates += sorted(Path(sys.prefix).glob('lib/*/site-packages/jdk4py/java-runtime/include'))
    for directory in candidates:
        if (directory / 'jni.h').is_file() and (directory / 'linux/jni_md.h').is_file():
            return [directory, directory / 'linux']
    return None


def patch_upstream():
    """Aplica as declarações que o pipeline adiciona ao llama.cpp (como no CI)."""
    sys.path.insert(0, str(ROOT / 'apk-fix'))
    from strict_vulkan_patches import apply as strict_vulkan
    from projector_patches import patch_projector
    from projector_batch_patches import patch_projector_batch
    from projector_qkv_patches import patch_projector_qkv
    from image_upload_patches import patch_image_upload
    from vulkan_patches import patch_token_readback
    strict_vulkan(CLONE)
    patch_projector(CLONE)
    patch_projector_batch(CLONE)
    patch_projector_qkv(CLONE)
    patch_image_upload(CLONE)
    graph = CLONE / 'src/llama-graph.cpp'
    graph.write_text(patch_token_readback(graph.read_text()))


def restore_upstream():
    subprocess.run(['git', '-C', str(CLONE), 'restore', '--source=HEAD', '--worktree', '.'],
                   check=False, capture_output=True)


def main():
    compiler = shutil.which('g++')
    if not compiler:
        print('SKIP: g++ indisponível neste host')
        return 0
    if not CLONE.is_dir():
        print('SKIP: checkout do llama.cpp ausente (.cache/llama-mobile)')
        return 0
    jni = jni_include()
    if not jni:
        print('SKIP: jni.h não encontrado (.venv com jdk4py)')
        return 0
    with tempfile.TemporaryDirectory() as work:
        stubs = Path(work)
        for name, body in STUBS.items():
            target = stubs / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
        patch_upstream()
        try:
            failures = []
            for unit in TRANSLATION_UNITS:
                command = [compiler, '-fsyntax-only', '-std=c++17', '-I', str(stubs),
                           '-I', str(NATIVE)]
                for directory in jni + [CLONE / include for include in INCLUDES]:
                    command += ['-I', str(directory)]
                command.append(str(NATIVE / unit))
                result = subprocess.run(command, capture_output=True, text=True)
                errors = [line for line in result.stderr.splitlines() if ' error: ' in line]
                print(f'{unit}: {len(errors)} erro(s)')
                for line in errors[:20]:
                    print('  ' + line)
                if result.returncode:
                    failures.append(unit)
            if failures:
                print('FALHA: ' + ', '.join(failures))
                return 1
        finally:
            restore_upstream()
    print(f"nativo: sintaxe ok ({', '.join(TRANSLATION_UNITS)}) com stubs de jni/android")
    return 0


if __name__ == '__main__':
    sys.exit(main())
