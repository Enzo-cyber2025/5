#!/usr/bin/env python3
# mede quando a janela do app lançado pela LOJA aparece na tela
import os, sys, time
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

from PIL import Image, ImageChops
def shot(p):
    q.shot(os.path.basename(p), outdir)
    return Image.open(p + ".png").convert("RGB")

wait_marker("laço principal")
q.sleep(4)
q.key("m", "ctrl-alt"); q.sleep(1.2)
for _ in range(12):
    q.key("down"); q.sleep(0.18)
q.key("ret"); q.sleep(5)
base = shot(os.path.join(outdir, "base-loja"))
print("::notice::t=0 (LOJA aberta)")

q.key("ret")            # Enter no primeiro app (sel=0 -> ADIV01)
t0 = time.time()
prev = base
for i in range(12):
    q.sleep(2)
    im = shot(os.path.join(outdir, "poll%02d" % i))
    d = ImageChops.difference(prev, im)
    n = sum(1 for p in d.getdata() if p != (0, 0, 0))
    d2 = ImageChops.difference(base, im)
    n2 = sum(1 for p in d2.getdata() if p != (0, 0, 0))
    bb = d2.getbbox()
    print("::notice::t+%2.0fs: diff_vs_prev=%d diff_vs_loja=%d bbox=%s" % (time.time()-t0, n, n2, bb))
    prev = im
    if n2 > 20000 and bb and bb[1] < 400:
        print("::notice::APP VISIVEL em t+%.0fs" % (time.time()-t0))
        break
q.quit()
