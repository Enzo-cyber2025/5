#!/usr/bin/env python3
"""Prepare the pinned llama.cpp checkout used by the llvmpipe host lab.

LAB_PATCHES is a comma separated list of modules in apk-fix/ whose ``apply``
function patches the pinned source. Empty means a clean upstream build, which is
the control for every comparison. The script records the applied patches and the
compile flags they need; it never touches the delivered APK.
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

PIN = 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'
SRC = Path(os.environ.get('LAB_LLAMA_SRC', '.cache/llama-host'))
FLAGS = Path(str(SRC) + '.lab-flags')


def clone_pinned():
    if (SRC / '.git').is_dir():
        assert subprocess.check_output(['git', '-C', str(SRC), 'rev-parse', 'HEAD'], text=True).strip() == PIN
        return
    subprocess.check_call(['git', 'clone', '--depth', '1', '--branch', 'v0.4.1',
                           'https://github.com/ggml-org/llama.cpp', str(SRC)])
    assert subprocess.check_output(['git', '-C', str(SRC), 'rev-parse', 'HEAD'], text=True).strip() == PIN


def main():
    requested = [name.strip() for name in os.environ.get('LAB_PATCHES', '').split(',') if name.strip()]
    clone_pinned()
    sys.path.insert(0, str(Path('apk-fix').resolve()))
    applied, flags = [], []
    for name in requested:
        module = __import__(name)
        assert callable(module.apply), name
        result = module.apply(SRC)
        applied.append(name)
        for flag in getattr(module, 'LAB_COMPILE_FLAGS', ()):  # optional per-patch flags
            if flag not in flags:
                flags.append(flag)
        print(f'{name}: {result}')
    FLAGS.write_text(' '.join(flags) + '\n' + ' '.join(applied) + '\n')
    tree = subprocess.check_output(['git', '-C', str(SRC), 'diff', '--stat'], text=True)
    digest = hashlib.sha256(tree.encode()).hexdigest()
    print(f'applied={applied}')
    print(f'compile_flags={flags}')
    print(f'worktree_diff_sha256={digest}')
    print(tree)


if __name__ == '__main__':
    main()
