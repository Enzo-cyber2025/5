#!/usr/bin/env python3
"""qmp_test.py — bota o EnzoOS no QEMU via QMP, exercita o sistema
(janelas, demos PE/ELF/APK, Ctrl+C, menu, apps) e tira capturas de tela.

Uso: qmp_test.py enzos.iso pasta_das_capturas/
Requer: qemu-system-x86_64 no PATH. Sem dependências Python externas
(PPM -> PNG é feito com zlib).
"""
import json, os, subprocess, sys, time, zlib, struct

QEMU = "qemu-system-x86_64"

# ---------------------------------------------------------------------------
def ppm_to_png(src, dst):
    data = open(src, 'rb').read()
    if not data.startswith(b'P6'):
        raise RuntimeError("screendump nao eh P6")
    # header: P6\n<w> <h>\n<max>\n
    parts = data.split(b'\n', 3)
    w, h = map(int, parts[1].split())
    raw = parts[3][:(w * h * 3)]
    rows = b''.join(b'\x00' + raw[y*w*3:(y+1)*w*3] for y in range(h))
    def chunk(tag, payload):
        c = struct.pack('>I', len(payload)) + tag + payload
        return c + struct.pack('>I', zlib.crc32(tag + payload) & 0xFFFFFFFF)
    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(rows, 6))
    png += chunk(b'IEND', b'')
    open(dst, 'wb').write(png)
    return w, h

# ---------------------------------------------------------------------------
class Qmp:
    def __init__(self, iso, serial_path):
        self.proc = subprocess.Popen(
            [QEMU, "-m", "2048", "-display", "none", "-qmp", "stdio",
             "-cdrom", iso, "-serial", "file:" + serial_path,
             "-vga", "std", "-no-reboot"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)
        # saudação
        self.readline()
        self.cmd("qmp_capabilities")

    def readline(self):
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("QEMU morreu")
        return json.loads(line)

    def cmd(self, execute, **args):
        msg = {"execute": execute}
        if args:
            msg["arguments"] = args
        self.proc.stdin.write(json.dumps(msg).encode() + b"\n")
        self.proc.stdin.flush()
        # lê até a resposta (ignora eventos)
        while True:
            r = self.readline()
            if "return" in r or "error" in r:
                return r

    def hmp(self, cmdline):
        return self.cmd("human-monitor-command", **{"command-line": cmdline})

    def key(self, k, hold=""):
        self.hmp("sendkey %s%s" % (hold + "-" if hold else "", k))

    def sleep(self, s):
        time.sleep(s)

    def shot(self, name, outdir):
        ppm = os.path.join(outdir, name + ".ppm")
        png = os.path.join(outdir, name + ".png")
        self.cmd("screendump", filename=ppm)
        w, h = ppm_to_png(ppm, png)
        os.remove(ppm)
        print("captura: %s.png (%dx%d)" % (name, w, h))

    def quit(self):
        try:
            self.cmd("quit")
        except Exception:
            pass
        self.proc.wait(timeout=10)

# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    iso = sys.argv[1]
    outdir = sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    serial = os.path.join(outdir, "serial.log")

    q = Qmp(iso, serial)
    try:
        # 1. boot -> área de trabalho com 3 janelas
        q.sleep(5)
        q.shot("01-desktop", outdir)

        # 2. novo terminal (focado)
        q.key("t", "ctrl-alt")
        q.sleep(1)
        q.shot("02-terminal", outdir)

        # 3. demo PE (DEMO.EXE): banner + Collatz + laço longo
        q.key("f1")
        q.sleep(4)
        q.shot("03-demo-pe", outdir)

        # 4. Ctrl+C interrompe o laço longo
        q.key("c", "ctrl")
        q.sleep(1.5)
        q.shot("04-ctrlc", outdir)

        # 5. demo ELF (CALC.RUN)
        q.key("f2")
        q.sleep(2.5)
        q.shot("05-demo-elf", outdir)

        # 6. demo APK (manifesto AXML + dex + libs)
        q.key("f3")
        q.sleep(3)
        q.shot("06-demo-apk", outdir)

        # 7. DLL PE
        q.key("f4")
        q.sleep(2.5)
        q.shot("07-demo-dll", outdir)

        # 8. calculadora com teclado: 12+34=
        q.key("c", "ctrl-alt")
        q.sleep(1)
        for k in ["1", "2", "shift-equal", "3", "4", "equal"]:
            q.key(k)
            q.sleep(0.25)
        q.sleep(0.5)
        q.shot("08-calc", outdir)

        # 9. menu Iniciar
        q.key("m", "ctrl-alt")
        q.sleep(1)
        q.shot("09-menu", outdir)
        q.key("esc")
        q.sleep(0.5)

        # 10. informações do sistema
        q.key("i", "ctrl-alt")
        q.sleep(1.5)
        q.shot("10-info", outdir)

        # 11. plasma + 1 s de animação
        q.sleep(1.5)
        q.shot("11-plasma", outdir)

        # 12. watchdog: executa o DEMO.EXE e espera o watchdog matar
        q.key("t", "ctrl-alt")
        q.sleep(1)
        q.key("f1")
        print("aguardando o watchdog (ate 12 s)...")
        q.sleep(12)
        q.shot("12-watchdog", outdir)
    finally:
        q.quit()

    print("serial: %s" % serial)
    with open(serial) as f:
        log = f.read()
    print("--- serial (ultimas linhas) ---")
    print("\n".join(log.splitlines()[-12:]))

if __name__ == '__main__':
    main()
