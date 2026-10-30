#!/usr/bin/env python3
# Gera apps/plasma_tab.inc (tabela de seno + paleta) para o PLASMA.CE
import math
sintab = [int(round(math.sin(i/256.0*2*math.pi)*85.0 + 127.5)) & 0xFF for i in range(256)]
def pal(i):
    t = i / 255.0
    if t < 0.25:
        u = t/0.25; return int(10+40*u), int(20+120*u), int(90+140*u)
    if t < 0.5:
        u = (t-0.25)/0.25; return int(50+110*u), int(140+80*u), int(230-140*u)
    if t < 0.75:
        u = (t-0.5)/0.25; return int(160+70*u), int(220-20*u), max(0,int(90-60*u))
    u = (t-0.75)/0.25; return int(230-40*u), int(200-120*u), max(0,int(30-20*u))
lines = ["; apps/plasma_tab.inc - gerado por tools/genplasma.py (nao editar)",
         "align 16", "sintab:"]
lines += ["        db " + ",".join(str(x) for x in sintab[k:k+16]) for k in range(0,256,16)]
lines += ["align 16", "paltab:"]
for k in range(0,256,8):
    row = []
    for i in range(k,k+8):
        r,g,b = pal(i)
        row.append("0xFF%02X%02X%02X" % (r,g,b))
    lines.append("        dd " + ",".join(row))
open('apps/plasma_tab.inc','w').write("\n".join(lines) + "\n")
print("genplasma: plasma_tab.inc gerado")
