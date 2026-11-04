#!/usr/bin/env python3
# debug do menu: onde está menu_sel? (diff de memória antes/depois de um "down")
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qmp_test import Qmp

iso, outdir = sys.argv[1], sys.argv[2]
os.makedirs(outdir, exist_ok=True)
serial = os.path.join(outdir, "serial.log")
q = Qmp(iso, serial, sys.argv[3] if len(sys.argv) > 3 else None)
q.boot_fb()
q.sleep(3)

import re
def dump(a, n):
    out = {}
    r = q.hmp("xp /%duwx 0x%X" % (n, a)).get("return", "")
    vals = re.findall(r"0x([0-9a-f]{8,16})", r)
    for i, v in enumerate(vals):
        out[a + i*4] = int(v, 16)
    return out

BASE = 0x10D000  # região do wnd_count (0x10D6AC no run20)
before = dump(BASE, 1024)
q.key("m", "ctrl-alt")
q.sleep(1.0)
after_open = dump(BASE, 1024)
ch_open = {k: (before.get(k), v) for k, v in after_open.items() if before.get(k) != v}
print("::notice::mudou ao abrir menu:", {hex(k): (hex(v[0]) if v[0] is not None else None, hex(v[1])) for k, v in ch_open.items()})
q.key("down"); q.sleep(0.4)
after_d1 = dump(BASE, 1024)
ch_d1 = {k: (after_open.get(k), v) for k, v in after_d1.items() if after_open.get(k) != v}
print("::notice::mudou apos 1 down:", {hex(k): (hex(v[0]) if v[0] is not None else None, hex(v[1])) for k, v in ch_d1.items()})
for _ in range(11):
    q.key("down"); q.sleep(0.15)
q.sleep(0.5)
after_d12 = dump(BASE, 1024)
ch_d12 = {k: (after_d1.get(k), v) for k, v in after_d12.items() if after_d1.get(k) != v}
print("::notice::mudou apos 12 downs:", {hex(k): (hex(v[0]) if v[0] is not None else None, hex(v[1])) for k, v in ch_d12.items()})
q.shot("d1-menu-12downs", outdir)
q.key("ret")
q.sleep(3)
after_ret = dump(BASE, 1024)
ch_ret = {k: (after_d12.get(k), v) for k, v in after_ret.items() if after_d12.get(k) != v}
print("::notice::mudou apos ENTER:", {hex(k): (hex(v[0]) if v[0] is not None else None, hex(v[1])) for k, v in ch_ret.items()})
q.shot("d2-apos-enter", outdir)
s = open(serial, errors="replace").read()
print("::notice::+janela count:", s.count("+janela"))
print("::notice::ultimas serial:", [l for l in s.splitlines() if l.strip()][-6:])
q.quit()
