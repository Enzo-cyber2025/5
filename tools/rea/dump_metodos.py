#!/usr/bin/env python3
"""Fase 2 (R.E.A.) - dump de bytecode de classes/metodos selecionados.

Uso: python3 dump_metodos.py <alvo.apk> <regex_de_classes> [<regex_de_metodos>]
Imprime o bytecode (formato smali simplificado) para evidencia no relatorio.
"""
import re
import sys
import zipfile

from androguard.core.dex import DEX


def main():
    apk, cls_rx = sys.argv[1], re.compile(sys.argv[2])
    mth_rx = re.compile(sys.argv[3]) if len(sys.argv) > 3 else None
    z = zipfile.ZipFile(apk)
    for n in sorted(x for x in z.namelist() if re.fullmatch(r"classes\d*\.dex", x)):
        for c in DEX(z.read(n)).get_classes():
            if not cls_rx.search(c.get_name()):
                continue
            print(f"\n===== {c.get_name()}  ({n}) =====")
            for f in c.get_fields():
                print(f"  .field {f.get_access_flags_string():18s} {f.get_name()} {f.get_descriptor()}")
            for m in c.get_methods():
                if mth_rx and not mth_rx.search(m.get_name()):
                    continue
                print(f"\n  .method {m.get_access_flags_string()} {m.get_name()}{m.get_descriptor()}")
                code = m.get_code()
                if not code:
                    continue
                for ins in code.get_bc().get_instructions():
                    print(f"      {ins.get_name():28s} {ins.get_output()}")
                try:
                    for t in code.get_tries() or []:
                        print(f"      .catch {t}")
                except Exception as exc:  # androguard 4.x: TryItem e opaco
                    print(f"      .catch <indisponivel: {exc.__class__.__name__}>")
                print("  .end method")


if __name__ == "__main__":
    main()
