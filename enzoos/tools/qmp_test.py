#!/usr/bin/env python3
"""qmp_test.py — bota o EnzoOS no QEMU via QMP, exercita o sistema
(janelas, demos PE/ELF/APK, Ctrl+C, menu, apps, ENZFS, EnzoFox com HTTP
REAL pela placa e1000) e tira capturas de tela.

Uso: qmp_test.py enzos.iso pasta_das_capturas/ [disk.img]
Requer: qemu-system-x86_64 no PATH. Sem dependências Python externas
(PPM -> PNG é feito com zlib).

Máquina: q35 — ISO e disco no AHCI, rede e1000 (user-net). Um servidor
HTTP local na porta 8000 serve a página que o EnzoFox baixa
(10.0.2.2:8000 no user-net é o host).
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
    def __init__(self, iso, serial_path, disk=None):
        args = [QEMU, "-m", "2048", "-display", "none", "-qmp", "stdio",
                "-machine", "q35", "-boot", "d",
                "-device", "ahci,id=sata0",
                "-drive", "id=cd0,if=none,format=raw,media=cdrom,file=" + iso,
                "-device", "ide-cd,drive=cd0,bus=sata0.0",
                "-serial", "file:" + serial_path,
                "-vga", "std", "-no-reboot"]
        if disk:
            args += ["-drive", "id=hd0,if=none,format=raw,file=" + disk,
                     "-device", "ide-hd,drive=hd0,bus=sata0.1"]
        args += ["-netdev", "user,id=n0",
                 "-device", "e1000,netdev=n0"]
        self.notes = []
        self.proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)
        # saudação
        self.readline()
        self.cmd("qmp_capabilities")

    def readline(self):
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError(
                    "QEMU morreu. Output dele:\n" + "\n".join(self.notes))
            s = line.decode(errors="replace").strip()
            if not s:
                continue
            if not s.startswith("{"):
                self.notes.append(s)      # aviso/erro do QEMU (não é JSON)
                continue
            return json.loads(s)

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

    def vga_text(self):
        """lê o buffer de texto VGA (0xB8000) — mostra o que a BIOS escreveu"""
        import re as _re
        r = self.hmp("xp /2000xw 0xb8000")
        words = _re.findall(r"0x([0-9a-f]{8})", r.get("return", ""))
        chars = []
        for w in words:
            c = int(w, 16) & 0xFF
            chars.append(chr(c) if 32 <= c < 127 else " ")
        s = "".join(chars)
        lines = [s[i:i + 80].rstrip() for i in range(0, len(s), 80)]
        return "\n".join(l for l in lines if l)

    def quit(self):
        try:
            self.cmd("quit")
        except Exception:
            pass
        self.proc.wait(timeout=10)

# ---------------------------------------------------------------------------
WEBROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "webroot")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    iso = sys.argv[1]
    outdir = sys.argv[2]
    disk = sys.argv[3] if len(sys.argv) > 3 else None
    os.makedirs(outdir, exist_ok=True)
    serial = os.path.join(outdir, "serial.log")

    # servidor HTTP que o EnzoFox vai baixar (10.0.2.2:8000 no user-net)
    httpd = subprocess.Popen(
        [sys.executable, "-m", "http.server", "8000", "--bind", "127.0.0.1"],
        cwd=WEBROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    q = Qmp(iso, serial, disk)
    try:
        # 1. boot -> área de trabalho com 3 janelas (DHCP+AHCI+swap no meio)
        q.sleep(8)
        w, h = q.shot("01-desktop", outdir)
        if (w, h) == (720, 400):
            print("MODO TEXTO 720x400: o boot nao chegou ao modo grafico")
            print("--- texto da tela (VGA 0xB8000) ---")
            print(q.vga_text())
            with open(serial) as f:
                s = f.read()
            print("--- serial (%d bytes) ---" % len(s))
            print(s[:800])
            sys.exit(1)

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

        # helper: abre o app N do menu Iniciar (0 = primeiro)
        def launch_menu_app(idx):
            q.key("m", "ctrl-alt")
            q.sleep(0.8)
            for _ in range(idx):
                q.key("down")
                q.sleep(0.15)
            q.key("ret")
            q.sleep(0.8)

        # 13. FILES: navegador do ENZFS (disco AHCI persistente)
        launch_menu_app(6)                 # FILES.ENZ (7º app da ISO)
        q.sleep(2)
        q.shot("13-files", outdir)

        # 14. EnzoFox: HTTP REAL pela e1000 (10.0.2.2:8000 = host)
        launch_menu_app(7)                 # FOX.ENZ
        q.sleep(1.5)
        q.key("ret")                       # Enter baixa a URL padrão
        print("aguardando o HTTP (ate 10 s)...")
        q.sleep(10)
        q.shot("14-fox", outdir)

        # 15. SysMon: swap, HPET, uptime
        launch_menu_app(8)                 # SYSMON.ENZ
        q.sleep(2)
        q.shot("15-sysmon", outdir)

        # 16. Mandelbrot: app escrito na linguagem ENZ (enzc.py)
        launch_menu_app(9)                 # MANDEL.ENZ
        q.sleep(4)
        q.shot("16-mandel", outdir)
    finally:
        q.quit()
        httpd.terminate()

    print("serial: %s" % serial)
    with open(serial) as f:
        log = f.read()
    print("--- serial (ultimas linhas) ---")
    print("\n".join(log.splitlines()[-16:]))

    # validações que devem fechar o CI em vermelho se quebrarem
    ok = True
    if "[net] conectado via DHCP" not in log:
        print("FALHOU: e1000/DHCP nao conectou (serial sem '[net] conectado')")
        ok = False
    if "[enzfs] volume montado" not in log:
        print("FALHOU: ENZFS nao montou o disco AHCI")
        ok = False
    if not ok:
        sys.exit(1)
    print("OK: rede e1000+DHCP e ENZFS validados pelo serial.")

if __name__ == '__main__':
    main()
