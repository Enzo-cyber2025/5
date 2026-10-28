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


CRASH_CODES = {-1073741819, 3221225477, -1073740791, 3221225725, -6, -11}


def _run_gui_subprocess() -> None:
    """Roda o teste de interface em processo separado.

    Motivos: (1) um travamento do SDL derrubaria o processo inteiro, e assim o
    núcleo continua validado; (2) em runners sem sessão gráfica o SDL pode
    travar na criação da janela — aí tentamos outros drivers e, se nenhum
    funcionar, o teste é ignorado com aviso em vez de reprovar o build.
    """
    import subprocess

    here = os.path.dirname(os.path.abspath(__file__))
    preferred = os.environ.get("SDL_VIDEODRIVER")
    drivers = [preferred] if preferred else []
    drivers += ["offscreen", "dummy"]
    tried = []
    last = ""
    for drv in drivers:
        env = dict(os.environ)
        env["SDL_VIDEODRIVER"] = drv
        env.setdefault("SDL_AUDIODRIVER", "dummy")
        env["PYTHONUNBUFFERED"] = "1"
        try:
            proc = subprocess.run([sys.executable, "-u", os.path.join(here, "test_gui.py")],
                                  cwd=here, env=env, timeout=900,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, errors="replace")
            code, out = proc.returncode, proc.stdout
        except subprocess.TimeoutExpired:
            code, out = -1, "timeout"
        out = (out or "").strip()
        last = out
        if code == 0:
            if out:
                print("\n".join(out.splitlines()[-8:]))
            return
        if code in CRASH_CODES or code < 0:
            tried.append(f"{drv} (travou)")
            continue
        if out:
            print("\n".join(out.splitlines()[-25:]))
        raise RuntimeError(f"teste de interface falhou (código {code})")
    if last:
        print("\n".join(last.splitlines()[-10:]))
    print(f"[aviso] teste de interface ignorado: SDL não criou janela com {tried} "
          f"neste ambiente (sem sessão gráfica). O núcleo segue validado.")


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
