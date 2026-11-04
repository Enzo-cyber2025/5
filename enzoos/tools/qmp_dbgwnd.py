#!/usr/bin/env python3
# debug: geometria das janelas após LOJA + exec de app do ENZFS
import os, sys, time, struct, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qmp_test import Qmp

iso, outdir = sys.argv[1], sys.argv[2]
os.makedirs(outdir, exist_ok=True)
serial = os.path.join(outdir, "serial.log")
q = Qmp(iso, serial, sys.argv[3] if len(sys.argv) > 3 else None)
q.serial_path = serial

def wait_marker(marker, timeout=40):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if marker in open(serial, errors="replace").read():
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

def kread(a, n):
    r = q.hmp("xp /%duwx 0x%X" % (n, a)).get("return", "")
    vals = re.findall(r"0x([0-9a-f]{8,16})", r)
    return [int(v, 16) for v in vals]

# acha magic 0x13572468 (varre kernel)
magic_addr = 0
for base in range(0x100000, 0x140000, 0x1000):
    vals = kread(base, 1024)
    for i, v in enumerate(vals):
        if v == 0x13572468:
            magic_addr = base + i*4
            break
    if magic_addr: break
print("::notice::magic@0x%X" % magic_addr)
wcount = kread(magic_addr+4, 1)[0]
print("::notice::wnd_count=%d" % wcount)

def wnd_info(slot):
    a = magic_addr + 8 + slot*0x1000  # ? — usa varredura por título
# melhor: varrer 0x10D000..0x110000 por títulos e decodar W_X/Y/W/H
base = (magic_addr + 8) & ~0xFFF
for a in range(base, base + 0x3000, 4):
    vals = kread(a, 8)
    if len(vals) < 8: continue
    nxt, prv, x, y, w, h = vals[0], vals[1], vals[2], vals[3], vals[4], vals[5]
    if 0 <= x < 640 and 0 <= y < 480 and 0 < w <= 640 and 0 < h <= 480 and nxt != 0:
        # título: +40
        tv = kread(a+40, 4)
        t = b""
        for v in tv:
            t += struct.pack("<I", v & 0xFFFFFFFF)
        tt = t.split(b"\x00")[0].decode(errors="replace")
        if tt and any(c.isalnum() for c in tt):
            print("wnd @0x%X: next=0x%X x=%d y=%d w=%d h=%d title=%r" % (a, nxt, x, y, w, h, tt))
# lança o SEXTO app da lista (5 downs + Enter) — prova que a seleção move
for _ in range(5):
    q.key("down"); q.sleep(0.25)
q.key("ret"); q.sleep(8)
q.shot("dbg-app", outdir)

def dec(a):
    v = kread(a, 12)
    return dict(next=v[0], prev=v[2], x=v[4], y=v[5], w=v[6], h=v[7], app=v[18] if len(v)>18 else None, flags=v[19] if len(v)>19 else None)

def title(a):
    tv = kread(a+40, 8)
    t = b""
    for x in tv:
        t += struct.pack("<I", x & 0xFFFFFFFF)
    return t.split(b"\x00")[0].decode(errors="replace")

# varre entradas válidas
for a in range(base, base + 0x3000, 4):
    v = kread(a, 8)
    if len(v) < 8: continue
    if v[0] == 0 and v[1] == 0 and v[2] == 0 and v[3] == 0: continue
    x, y, w, h = v[4], v[5], v[6], v[7]
    if 0 <= x < 640 and 0 <= y < 480 and 40 <= w <= 640 and 40 <= h <= 480:
        tt = title(a)
        if tt and any(c.isalnum() for c in tt):
            d = dec(a)
            print("wnd @0x%X: next=0x%X prev=0x%X x=%d y=%d w=%d h=%d flags=%s title=%r" % (a, d['next'], d['prev'], x, y, w, h, d['flags'], tt))
print("::notice::wnd_count final=%d" % kread(magic_addr+4,1)[0])
q.quit()
