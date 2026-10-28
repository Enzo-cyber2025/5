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
        qtrace = serial_path.replace("serial.log", "qtrace.log")
        pcap = serial_path.replace("serial.log", "traffic.pcap")
        args = [QEMU, "-m", "2048", "-display", "none", "-qmp", "stdio",
                "-machine", "q35", "-boot", "d",
                "-device", "ahci,id=sata0",
                "-drive", "id=cd0,if=none,format=raw,media=cdrom,file=" + iso,
                "-device", "ide-cd,drive=cd0,bus=sata0.0",
                "-serial", "file:" + serial_path,
                "-vga", "std", "-no-reboot",
                "-d", "int,guest_errors,cpu_reset,trace:ahci_*,trace:handle_*,trace:e1000*",
                "-D", qtrace]
        if disk:
            args += ["-drive", "id=hd0,if=none,format=raw,file=" + disk,
                     "-device", "ide-hd,drive=hd0,bus=sata0.1"]
        args += ["-netdev", "user,id=n0",
                 "-device", "e1000,netdev=n0",
                 "-object", "filter-dump,id=fdump,netdev=n0,file=" + pcap,
                 "-device", "intel-hda",
                 "-device", "hda-duplex"]
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
        return w, h

    def vga_text(self):
        """lê o buffer de texto VGA (0xB8000) — mostra o que a BIOS escreveu"""
        import re as _re
        r = self.hmp("xp /2000xw 0xb8000")
        words = _re.findall(r"0x([0-9a-f]{8})", r.get("return", ""))
        chars = []
        for w in words:
            v = int(w, 16)
            for c in (v & 0xFFFF, (v >> 16) & 0xFFFF):
                ch = c & 0xFF
                chars.append(chr(ch) if 32 <= ch < 127 else " ")
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
            try:
                print(q.vga_text())
            except Exception:
                pass
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
        q.shot("09b-menu-esc", outdir)   # bissec: menu fechou?

        # 10. informações do sistema
        q.key("i", "ctrl-alt")
        q.sleep(0.4)
        q.shot("09c-info-abriu", outdir)  # bissec: INFO abriu?
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
    except Exception as e:
        print("--- QEMU morreu no meio do teste: %s ---" % repr(e))
        # serial resumido
        try:
            with open(serial) as f:
                sl = f.read().splitlines()
            body = "\n".join(sl)
            print("--- serial %d linhas; marcadores: eth_copiado=%d "
                  "canarios_rx=%d" % (
                      len(sl), body.count("[eth] payload copiado"),
                      body.count("0x000000000008EF")))
            print("--- ultimas 4 ---")
            print("\n".join(sl[-4:]))
        except Exception:
            pass
        # qtrace resumido por ultimo (annotations preservam o final)
        try:
            qt = os.path.join(outdir, "qtrace.log")
            with open(qt, "rb") as f:
                lines = f.read().decode(errors="replace").splitlines()
            inv = [l for l in lines if "Invalid" in l]
            addr = []
            for l in inv:
                for tok in l.replace(",", " ").split():
                    if tok.startswith("0x") and len(tok) >= 6:
                        addr.append(tok)
                        break
            vlines = [l for l in lines if " v=" in l or l.startswith("v=")]
            print("=== qtrace: %d linhas; invalid=%d primeiros: %s" %
                  (len(lines), len(inv), " ".join(addr[:5])))
            ah = [l for l in lines if "ahci" in l.lower()]
            print("=== ahci trace ultimas 6 ===")
            print("\n".join(ah[-6:]) if ah else "(nenhum)")
            print("=== v ultimas 2 ===")
            print("\n".join(vlines[-2:]))
        except Exception as e2:
            print("(sem qtrace: %s)" % e2)
        # pcap mesmo no timeout
        try:
            import struct as _st
            with open(os.path.join(outdir, "traffic.pcap"), "rb") as f:
                pd = f.read()
            pkts = []
            if pd[:4] in (b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4"):
                off = 24
                while off + 16 <= len(pd):
                    ts, tu, incl, orig = _st.unpack_from("<IIII", pd, off)
                    off += 16
                    if off + incl > len(pd):
                        break
                    pkts.append(pd[off:off + incl])
                    off += incl
            with open(os.path.join(outdir, "traffic.txt"), "w") as f:
                f.write("pcap timeout: %d pacotes\n" % len(pkts))
                for i, p in enumerate(pkts[:24]):
                    f.write("[%02d] %s et=0x%04x len=%d\n" %
                            (i, "TX" if p[0:6] == b"\x52\x54\x00" else "RX",
                             int.from_bytes(p[12:14], "big"), len(p)))
        except Exception as e3:
            print("(sem pcap no timeout: %s)" % e3)
        sys.stdout.flush()
        try:
            q.quit()
        except Exception:
            q.proc.kill()
        httpd.terminate()
        sys.exit(1)
    finally:
        try:
            q.quit()
        except Exception:
            pass
        httpd.terminate()

    print("serial: %s" % serial)
    with open(serial) as f:
        log = f.read()
    slines = log.splitlines()

    # validações que devem fechar o CI em vermelho se quebrarem
    ok = True
    if "[net] conectado via DHCP" not in log:
        print("FALHOU: e1000/DHCP nao conectou (serial sem '[net] conectado')")
        print("::error::DHCP nao conectou")
        ok = False
    if "[enzfs] volume montado" not in log:
        print("FALHOU: ENZFS nao montou o disco AHCI")
        print("::error::ENZFS nao montou")
        ok = False
    if "[net] HTTP ok" not in log:
        print("FALHOU: EnzoFox nao baixou a pagina (serial sem '[net] HTTP ok')")
        print("::error::HTTP do EnzoFox falhou")
        ok = False
    # canarios via annotations (legiveis pela API mesmo com log bloqueado)
    for pat in ("[net] conectado", "[net] HTTP ok", "[hda]", "panic"):
        hits = [l for l in slines if pat in l]
        for h in hits[-6:]:
            print("::notice::%s" % h[:200])
    for h in slines[-14:]:
        print("::notice::tail %s" % h[:200])
    print("=== serial (%d linhas; ultimas 8) ===" % len(slines))
    print("\n".join(slines[-8:]))
    # marcadores do caminho dhcp (uma linha so, antes do cap)
    print("=== marcadores ===")
    print("eth_copiado=%d canarios_dhcp=%d canarios_eth=%d "
          "canarios_e1000=%d ethlog=%d" % (
              log.count("[eth] payload copiado"),
              log.count("0x000000000008EFC"),
              log.count("0x000000000013"),
              log.count("0x000000000014"),
              len([l for l in slines if "[eth]" in l])))
    # resumo por tags (o cap de annotations corta o meio do serial)
    print("=== resumo do boot ===")
    ahci_line = "(ausente)"
    ahci_hex = ""
    hits = [l for l in slines if "[ahci]" in l]
    if hits:
        ahci_line = hits[0]
        i = slines.index(hits[0])
        hx = [l for l in slines[i+1:i+8] if l.startswith("0x")]
        ahci_hex = " ".join(hx[:6])
    for tag in ["[enzfs]", "[e1000]", "[net]"]:
        hits = [l for l in slines if tag in l]
        print("%-9s %s" % (tag + ":", hits[0] if hits else "(ausente)"))
    print("[ahci]:  %s" % ahci_line)
    if ahci_hex:
        print("diag: %s" % ahci_hex)

    # trace AHCI do QEMU primeiro (o cap de annotations do GitHub mostra
    # so as ~10 ultimas linhas do output — o bloco critico vem por ultimo)
    try:
        with open(os.path.join(outdir, "qtrace.log")) as f:
            qtl = [l.rstrip() for l in f]
        ah = [l for l in qtl if "ahci" in l.lower()]
        kw = [l for l in qtl if "[1]" in l and "read" not in l]
        print("=== trace porta[1] nao-reads (%d; ultimas 8) ===" % len(kw))
        print("\n".join(kw[-8:]) if kw else "(nenhum)")
    except Exception as e:
        print("(sem qtrace: %s)" % e)
    # diag PCI: as leituras cruas após 'laço principal'
    try:
        i = next(i for i, l in enumerate(slines) if "la" + "\u00e7" + "o principal" in l)
        print("=== diag pci (00:1f.2 / 00:00.0 / dev2 / dev1) ===")
        print(" ; ".join(slines[i+1:i+5]))
    except StopIteration:
        pass
    # linhas do panic (vec/rip/cr2/dumps)
    panic = ""
    try:
        i = next(i for i, l in enumerate(slines) if "PANICO" in l)
        panic = slines[i] + " | " + (slines[i+1] if i+1 < len(slines) else "")
    except StopIteration:
        pass
    # ===== pcap: o que realmente passou pela netdev (filter-dump) =====
    try:
        import struct as _st
        with open(os.path.join(outdir, "traffic.pcap"), "rb") as f:
            pd = f.read()
        mag = pd[:4]
        pkts = []
        if mag in (b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4"):
            off = 24
            while off + 16 <= len(pd):
                ts, tu, incl, orig = _st.unpack_from("<IIII", pd, off)
                off += 16
                if off + incl > len(pd):
                    break
                pkts.append(pd[off:off + incl])
                off += incl
        lines = []
        for i, p in enumerate(pkts[:24]):
            d = "TX" if p[0:6] == b"\x52\x54\x00" else "RX"
            et = int.from_bytes(p[12:14], "big")
            desc = "et=0x%04x len=%d" % (et, len(p))
            if et == 0x0800 and len(p) >= 34:
                src = ".".join(str(b) for b in p[26:30])
                dst = ".".join(str(b) for b in p[30:34])
                proto = p[23]
                desc += " ip %s->%s p=%d" % (src, dst, proto)
                if proto == 17 and len(p) >= 42:
                    sp = int.from_bytes(p[34:36], "big")
                    dp = int.from_bytes(p[36:38], "big")
                    desc += " udp %d->%d" % (sp, dp)
                    if 67 in (sp, dp) and len(p) >= 43:
                        desc += " bootp op=%d" % p[42]
            lines.append("[%02d] %s %s" % (i, d, desc))
        print("=== pcap (%d pacotes; primeiros 24) ===" % len(pkts))
        print("\n".join(lines) if lines else "(nenhum pacote)")
        with open(os.path.join(outdir, "traffic.txt"), "w") as f:
            f.write("pcap %d pacotes\n" % len(pkts) + "\n".join(lines) + "\n")
    except Exception as e:
        print("(sem pcap: %s)" % e)

    # ===== bloco final: o que as annotations do CI vao mostrar =====
    print("=== resumo do boot ===")
    for tag in ["[enzfs]", "[e1000]", "[net]"]:
        hits = [l for l in slines if tag in l]
        print("%-9s %s" % (tag + ":", hits[0] if hits else "(ausente)"))
    print("[ahci]:   %s" % ahci_line)
    print("panic:    %s" % (panic[:160] if panic else "nenhum"))
    print("=== serial (ultimas 4) ===")
    print("\n".join(slines[-4:]))
    if not ok:
        if "[net] conectado via DHCP" not in log:
            print("FALHOU: e1000/DHCP nao conectou (serial sem '[net] conectado')")
        if "[enzfs] volume montado" not in log:
            print("FALHOU: ENZFS nao montou o disco AHCI")
        sys.exit(1)
    print("OK: rede e1000+DHCP e ENZFS validados pelo serial.")

if __name__ == '__main__':
    main()
