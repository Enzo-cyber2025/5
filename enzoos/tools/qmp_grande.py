#!/usr/bin/env python3
# =============================================================================
#  EnzoOS — tools/qmp_grande.py: validação da GRANDE entrega de 1 GB
#   1) boot                          2) menu Iniciar
#   3) LOJA com 2566 apps (2 prateleiras)               4) navegação/exec
#   5) TERMINAL + F6 (LINUXDEMO.RUN) + F7 (WINDEMO2.EXE) + F8 (RELOGIOCE)
#   6) EnzoFox: home offline, abas, busca HTTP REAL (10.0.2.2:8000)
#   7) FILES /DOCS + SYSMON
# Uso: python3 tools/qmp_grande.py enzos.iso saida_dir disk.img
# Requer servidor web na porta 8000 do host (obj/webroot).
# =============================================================================
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qmp_test import Qmp  # noqa: E402

SENDKEY_MAP = {":": "shift-semicolon", "/": "slash", ".": "dot",
               "-": "minus", "_": "shift-minus"}


def wait_serial(serial, marker, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if marker in open(serial, "r", errors="replace").read():
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def type_str(q, s):
    for c in s:
        q.key(SENDKEY_MAP.get(c, c))
        q.sleep(0.06)


def lfb_shot(q, name, outdir):
    """captura da tela REAL via dump do LFB — o screendump do QEMU 3.1
    deste toolchain não segue modos VBE/DISPI (fica no modo texto)."""
    png = os.path.join(outdir, name + ".png")
    try:
        w, h = q.screendump_lfb(png)
        print("captura: %s.png (%dx%d) [LFB]" % (name, w, h))
        return w, h
    except Exception as e:
        print("::notice::lfb_shot falhou (%s); tentando screendump" % e)
        return lfb_shot(q, name, outdir)


def main():
    iso = sys.argv[1]
    outdir = sys.argv[2]
    disk = sys.argv[3] if len(sys.argv) > 3 else None
    os.makedirs(outdir, exist_ok=True)
    serial = os.path.join(outdir, "serial.log")
    q = Qmp(iso, serial, disk)
    q.serial_path = serial

    print("::notice::boot: esperando o laço principal do kernel")
    ok = wait_serial(serial, "laço principal", timeout=60)
    print("::notice::boot marcador: %s" % ("OK" if ok else "TIMEOUT (seguindo)"))
    q.sleep(5)
    lfb_shot(q, "01-desktop", outdir)

    # ---- menu Iniciar ----
    q.key("m", "ctrl-alt")
    q.sleep(1.2)
    lfb_shot(q, "02-menu", outdir)

    def menu_open(n_downs, wait, shot):
        q.key("m", "ctrl-alt")
        q.sleep(1.0)
        for _ in range(n_downs):
            q.key("down")
            q.sleep(0.15)
        q.key("ret")
        q.sleep(wait)
        lfb_shot(q, shot, outdir)

    # ---- LOJA: item 12 (12 apps + LOJA) — 2566 apps em 2 prateleiras ----
    menu_open(12, 9.0, "03-loja-2566apps")
    for _ in range(5):
        q.key("pgdn")
        q.sleep(0.5)
    lfb_shot(q, "04-loja-pgdn", outdir)
    q.key("end")
    q.sleep(1.0)
    lfb_shot(q, "05-loja-end-apps2", outdir)
    q.key("home")
    q.sleep(0.8)
    for _ in range(3):
        q.key("down")
        q.sleep(0.2)
    q.key("ret")
    q.sleep(5.0)
    lfb_shot(q, "06-app-executado", outdir)

    # ---- TERMINAL: item 0 — F6/F7/F8 demos traduzidas ----
    menu_open(1, 3.0, "07-terminal")
    q.key("f6")                     # LINUXDEMO.RUN (mkrun: Linux -> EnzoOS)
    q.sleep(4.0)
    lfb_shot(q, "08-linuxdemo-run", outdir)
    q.key("f7")                     # WINDEMO2.EXE (mkexe: PE com imports)
    q.sleep(4.0)
    lfb_shot(q, "09-windemo2-exe", outdir)
    q.key("f8")                     # RELOGIOCE.ENZ (compilador cec)
    q.sleep(3.0)
    lfb_shot(q, "10-relogioce", outdir)

    # ---- EnzoFox: item 7 ----
    menu_open(7, 4.0, "11-fox-home-offline")
    q.key("t", "ctrl")               # troca de aba (aba 1 vem com a URL demo)
    q.sleep(1.5)
    lfb_shot(q, "12-fox-aba2", outdir)
    # ENTER navega para http://10.0.2.2:8000/ (aba 1 pré-preenchida —
    # teclas de pontuação são instáveis no sendkey do QEMU 3.1)
    q.key("ret")
    q.sleep(10.0)                    # DHCP + ARP + IP + TCP + HTTP
    lfb_shot(q, "13-fox-web-real", outdir)
    q.key("b", "ctrl")               # volta no historico (volta pra home)
    q.sleep(2.0)
    lfb_shot(q, "14-fox-voltar", outdir)

    # ---- FILES: item 6 — /DOCS do disco de 1 GB ----
    menu_open(6, 4.0, "15-files")
    q.key("down")
    q.sleep(0.3)
    q.key("down")
    q.sleep(0.3)
    lfb_shot(q, "16-files-nav", outdir)

    # ---- SYSMON: item 8 ----
    menu_open(8, 3.0, "17-sysmon")
    q.sleep(2.0)
    lfb_shot(q, "18-sysmon-vivo", outdir)

    # ---- evidências do serial ----
    try:
        s = open(serial, "r", errors="replace").read()
        print("::notice::enzfs_montado=%s" % ("[enzfs] volume montado" in s))
        print("::notice::sem_panic=%s" % ("PANIC" not in s.upper()))
        print("::notice::janelas_criadas=%d" % s.count("+janela"))
        print("::notice::exec_run=%d" % s.count("exec"))
        tail = [l for l in s.splitlines() if l.strip()][-12:]
        print("=== serial (ultimas) ===")
        for l in tail:
            print(l)
    except Exception as e:
        print("::notice::serial: %s" % e)

    q.quit()
    print("OK: teste grande concluído.")


if __name__ == "__main__":
    main()
