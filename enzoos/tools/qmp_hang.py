#!/usr/bin/env python3
# congela a VM após o launch e extrai RIP + contexto
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qmp_test import Qmp

iso, outdir = sys.argv[1], sys.argv[2]
os.makedirs(outdir, exist_ok=True)
serial = os.path.join(outdir, "serial.log")
q = Qmp(iso, serial, sys.argv[3] if len(sys.argv) > 3 else None)
q.serial_path = serial

def wait_marker(m, t=40):
    t0 = time.time()
    while time.time() - t0 < t:
        try:
            if m in open(serial, errors="replace").read():
                return True
        except Exception:
            pass
        q.sleep(0.5)
    return False

wait_marker("laço principal")
q.sleep(4)
q.key("m", "ctrl-alt"); q.sleep(1.2)
for _ in range(12):
    q.key("down"); q.sleep(0.18)
q.key("ret"); q.sleep(5)
q.key("ret"); q.sleep(6)          # lança ADIV01 -> congela

q.cmd("stop")
regs = q.hmp("info registers").get("return", "")
for ln in regs.splitlines():
    if any(k in ln for k in ("RIP=", "RSP=", "RAX=", "RBX=", "RCX=", "RDX=", "RSI=", "RDI=")):
        print("REG:", ln.strip())
import re
m = re.search(r"RIP=([0-9a-f]+)", regs)
if m:
    rip = int(m.group(1), 16)
    code = q.hmp("xp /24i 0x%X" % (rip - 32)).get("return", "")
    print("=== codigo ao redor do RIP ===")
    print(code)
    # pilha
    st = q.hmp("xp /16gx 0x%X" % (rip & ~0xF)).get("return", "")
# pilha: enderecos de retorno no range do kernel
st = q.hmp("xp /48gx 0x%X" % 0x8bf10).get("return", "")
import re
print("=== pilha (retornos no kernel 0x100000-0x200000) ===")
for m in re.finditer(r"0x([0-9a-f]{16})", st):
    v = int(m.group(1), 16)
    if 0x100000 <= v < 0x200000:
        print("  ret 0x%X" % v)
q.cmd("cont")
q.quit()
