#!/usr/bin/env python3
"""Roda todos os testes sem dependências externas (nem pytest).

Uso:  python tests/run_tests.py            # núcleo + interface
      python tests/run_tests.py --core     # só o núcleo
"""
from __future__ import annotations

import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))

# Windows com saída redirecionada usa cp1252 e quebra em acentos/ setas.
try:                                    # pragma: no cover
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "src"))


def _run_gui_subprocess() -> None:
    """Roda o teste de interface em processo separado.

    Um travamento do SDL (raro, mas possível em runners sem sessão gráfica)
    derrubaria o processo inteiro — assim o núcleo continua sendo validado.
    """
    import subprocess

    here = os.path.dirname(os.path.abspath(__file__))
    env = dict(os.environ)
    env.setdefault("SDL_VIDEODRIVER", "dummy")
    env.setdefault("SDL_AUDIODRIVER", "dummy")
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.run([sys.executable, "-u", os.path.join(here, "test_gui.py")],
                          cwd=here, env=env, timeout=600,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, errors="replace")
    tail = "\n".join(proc.stdout.strip().splitlines()[-25:])
    if tail:
        print(tail)
    if proc.returncode != 0:
        raise RuntimeError(f"teste de interface falhou (código {proc.returncode})")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    import test_core

    tests = [(name, fn) for name, fn in sorted(vars(test_core).items())
             if name.startswith("test_") and callable(fn)]
    if "--core" not in argv:
        tests.append(("test_gui_smoke", _run_gui_subprocess))

    failures = 0
    t_start = time.perf_counter()
    for name, fn in tests:
        t0 = time.perf_counter()
        try:
            fn()
            print(f"  ok    {name}  ({time.perf_counter() - t0:.2f}s)")
        except Exception:
            failures += 1
            print(f"  FALHA {name}  ({time.perf_counter() - t0:.2f}s)")
            traceback.print_exc()
    total = time.perf_counter() - t_start
    print("-" * 60)
    print(f"{len(tests) - failures}/{len(tests)} testes passaram em {total:.1f}s")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
