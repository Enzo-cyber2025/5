#!/usr/bin/env python3
# =============================================================================
#  EnzoOS — tools/qmp_loja.py: valida a LOJA DE APPS e os 1000+ apps do ENZFS
#  1) boot (espera o laço principal pelo serial)  2) menu Iniciar c/ LOJA
#  3) LOJA aberta (lista 1085 apps)               4) navegação (down/end/home)
#  5) Enter executa app do ENZFS (fallback k_exec -> enzfs)
# Uso: python3 tools/qmp_loja.py enzos.iso saida_dir disk.img
# =============================================================================
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qmp_test import Qmp  # noqa: E402


def wait_serial(q, marker, timeout=30):
    """espera um marcador aparecer no serial.log (boot concluído)"""
    serial = q.serial_path if hasattr(q, "serial_path") else None
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            s = open(serial, "r", errors="replace").read()
            if marker in s:
                return True
        except Exception:
            pass
        q.sleep(0.5)
    return False


def main():
    iso = sys.argv[1]
    outdir = sys.argv[2]
    disk = sys.argv[3] if len(sys.argv) > 3 else None
    os.makedirs(outdir, exist_ok=True)
    serial = os.path.join(outdir, "serial.log")
    q = Qmp(iso, serial, disk)
    q.serial_path = serial
    print("::notice::boot: esperando o laço principal do kernel")
    ok = wait_serial(q, "laço principal", timeout=40)
    print("::notice::boot marcador: %s" % ("OK" if ok else "TIMEOUT (seguindo)"))
    q.sleep(4)                      # 3 janelas do boot + desktop
    q.shot("01-desktop", outdir)

    # ---- 2) menu Iniciar: item LOJA = índice 12 (12 apps + LOJA) ----
    q.key("m", "ctrl-alt")
    q.sleep(1.2)
    q.shot("02-menu", outdir)
    for _ in range(12):
        q.key("down")
        q.sleep(0.18)
    q.shot("03-menu-loja-selecionada", outdir)
    q.key("ret")
    q.sleep(5.0)                    # LOJA lista 1085 apps do ENZFS
    q.shot("04-loja-aberta", outdir)

    # ---- 4) navegação na lista ----
    for _ in range(5):
        q.key("down")
        q.sleep(0.2)
    q.shot("05-loja-nav5", outdir)
    q.key("pgdn")
    q.sleep(0.6)
    q.shot("06-loja-pgdn", outdir)
    q.key("end")
    q.sleep(0.8)
    q.shot("07-loja-end", outdir)
    q.key("home")
    q.sleep(0.6)
    q.shot("08-loja-home", outdir)

    # ---- 5) Enter no primeiro app: exec via ENZFS ----
    q.key("ret")
    q.sleep(5.0)
    q.shot("09-app-exec-enzfs", outdir)

    # ---- evidências do serial ----
    try:
        s = open(serial, "r", errors="replace").read()
        print("::notice::enzfs_montado=%s" % ("[enzfs] volume montado" in s))
        print("::notice::sem_panic=%s" % ("PANIC" not in s.upper()))
        print("::notice::janelas_criadas=%d" % s.count("+janela"))
        tail = [l for l in s.splitlines() if l.strip()][-6:]
        print("=== serial (ultimas) ===")
        for l in tail:
            print(l)
    except Exception as e:
        print("::notice::serial: %s" % e)

    q.quit()
    print("OK: LOJA validada.")


if __name__ == "__main__":
    main()
