#!/usr/bin/env python3
# =============================================================================
#  EnzoOS — tools/genapps.py: gera N apps ENZ reais a partir dos templates
#
#  Uso: python3 tools/genapps.py [dir_destino] [escala]
#  Escreve apps/gen/NAME.enz + manifest.json (name, w, h, icon, categoria).
# =============================================================================
import json
import os
import sys
import colorsys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app_templates as T
import app_templates2 as V

OUT = sys.argv[1] if len(sys.argv) > 1 else "apps/gen"
SCALE = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0


def col(h, s, v):
    """HSV -> cor 0xRRGGBB."""
    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360.0, s, v)
    return (int(r * 255) << 16) | (int(g * 255) << 8) | int(b * 255)


def pal(i, base=0):
    """Paleta harmonica para o app i."""
    h = (base + i * 47) % 360
    bg = 0x10141F
    fg = 0xE8ECF4
    dig = col(h, 0.55, 0.95)
    on = col(h, 0.75, 1.0)
    off = col((h + 20) % 360, 0.35, 0.22)
    btn = col((h + 180) % 360, 0.45, 0.32)
    return dict(bg=bg, fg=fg, fg2=col(h, 0.2, 0.65), dig=dig, on=on, off=off,
                btn=btn, hl=on)


APPS = []          # (nome, categoria, fonte, w, h, icon)


def add(name, cat, src_fn):
    src, w, h = src_fn
    # anexa o auxiliar de 7 segmentos quando o app o usa
    if "seg_init()" in src and "void seg_init" not in src:
        src = src + "\n" + T.seg7_code() + "\n"
    APPS.append(dict(name=name, cat=cat, src=src, w=w, h=h,
                     icon=col(len(APPS) * 47, 0.6, 0.85)))


def n_of(base):
    return max(1, round(base * SCALE))


# ============================================================== UTIL ========
for i in range(n_of(12)):
    p = dict(name="REL%02d" % (i + 1),
             title="Relogio %d" % (i + 1), **pal(i))
    add("REL%02d" % (i + 1), "UTIL", T.t_relogio(p))

for i in range(n_of(12)):
    p = dict(name="CRONO%02d" % (i + 1),
             title="Cronometro %d" % (i + 1), **pal(i + 30))
    add("CRONO%02d" % (i + 1), "UTIL", T.t_crono(p))

for i in range(n_of(12)):
    p = dict(name="TIMER%02d" % (i + 1), title="Timer %d" % (i + 1),
             start=60 + i * 30, add=15 + i * 5, freq=600 + i * 40, **pal(i + 60))
    add("TIMER%02d" % (i + 1), "UTIL", T.t_timer(p))

for i in range(n_of(12)):
    p = dict(name="CONT%02d" % (i + 1), title="Contador %d" % (i + 1),
             step=1 + (i % 3), **pal(i + 90))
    add("CONT%02d" % (i + 1), "UTIL", T.t_contador(p))

for i in range(n_of(12)):
    p = dict(name="SENHA%02d" % (i + 1), title="Senha %d" % (i + 1),
             base=10 + (i % 7), freq=700 + i * 30, **pal(i + 120))
    add("SENHA%02d" % (i + 1), "UTIL", T.t_senha(p))

for i in range(n_of(12)):
    p = dict(name="METRO%02d" % (i + 1), title="Metronomo %d" % (i + 1),
             bpm=60 + i * 12, step=2 + i % 4, freq=440 + i * 15, **pal(i + 150))
    add("METRO%02d" % (i + 1), "UTIL", T.t_metrono(p))

for i in range(n_of(12)):
    p = dict(name="BINR%02d" % (i + 1), title="Binario %d" % (i + 1), **pal(i + 180))
    add("BINR%02d" % (i + 1), "UTIL", T.t_binrel(p))

for i in range(n_of(12)):
    p = dict(name="UPTM%02d" % (i + 1), title="Uptime %d" % (i + 1), **pal(i + 210))
    add("UPTM%02d" % (i + 1), "UTIL", T.t_upmon(p))

for i in range(n_of(8)):
    rows = ["A  065  B  066  C  067  D  068", "E  069  F  070  G  071  H  072",
            "I  073  J  074  K  075  L  076", "M  077  N  078  O  079  P  080",
            "Q  081  R  082  S  083  T  084", "U  085  V  086  W  087  X  088",
            "Y  089  Z  090  [  091  \\  092", "a  097  b  098  c  099  d  100",
            "e  101  f  102  g  103  h  104", "0  048  1  049  2  050  3  051"]
    p = dict(name="ASCII%02d" % (i + 1), title="Ascii %d" % (i + 1),
             rows=rows[: 6 + (i % 5)], hlrow=i % 4, **pal(i + 240))
    add("ASCII%02d" % (i + 1), "UTIL", T.t_ascii(p))

# ============================================================== MATH ========
for i in range(n_of(16)):
    p = dict(name="PRIMO%02d" % (i + 1), title="Primos %d" % (i + 1),
             n=200 + i * 150, step=50, span=800 + i * 40, cols=360, **pal(i + 270))
    add("PRIMO%02d" % (i + 1), "MATH", T.t_primos(p))

for i in range(n_of(16)):
    p = dict(name="FIBO%02d" % (i + 1), title="Fibo %d" % (i + 1), **pal(i + 300))
    add("FIBO%02d" % (i + 1), "MATH", T.t_fibo(p))

for i in range(n_of(16)):
    p = dict(name="COLL%02d" % (i + 1), title="Collatz %d" % (i + 1),
             start=7 + i * 3, base=10 + i * 4, range=400 + i * 30, **pal(i + 330))
    add("COLL%02d" % (i + 1), "MATH", T.t_collatz(p))

for i in range(n_of(16)):
    p = dict(name="PASC%02d" % (i + 1), title="Pascal %d" % (i + 1),
             modn=2 + (i % 6), rows=24 + (i % 8),
             c0=0x1B2436, c1=col(i * 47, 0.7, 0.9), c2=col(i * 47 + 40, 0.7, 0.85),
             c3=col(i * 47 + 80, 0.7, 0.8), c4=col(i * 47 + 120, 0.7, 0.75),
             c5=col(i * 47 + 160, 0.7, 0.7), c6=col(i * 47 + 200, 0.7, 0.95),
             bg=0x10141F, fg=0xE8ECF4)
    add("PASC%02d" % (i + 1), "MATH", T.t_pascal(p))

for i in range(n_of(16)):
    p = dict(name="MDC%02d" % (i + 1), title="Mdc %d" % (i + 1),
             a0=120 + i * 7, b0=84 + i * 5, range=600 + i * 20,
             ca=col(i * 47, 0.6, 0.85), cb=col(i * 47 + 180, 0.6, 0.85),
             bg=0x10141F, fg=0xE8ECF4, fg2=0x8A93A5, dig=col(i * 47, 0.5, 0.95))
    add("MDC%02d" % (i + 1), "MATH", T.t_mdc(p))

BHASK = [
    (1, -3, 2, "x^2 - 3x + 2"), (1, -5, 6, "x^2 - 5x + 6"), (1, 2, -8, "x^2 + 2x - 8"),
    (2, -7, 3, "2x^2 - 7x + 3"), (1, -7, 12, "x^2 - 7x + 12"), (3, -12, 0, "3x^2 - 12x"),
    (1, -8, 15, "x^2 - 8x + 15"), (2, 4, -6, "2x^2 + 4x - 6"), (1, 1, -12, "x^2 + x - 12"),
    (4, -4, -3, "4x^2 - 4x - 3"), (1, -10, 24, "x^2 - 10x + 24"), (5, -13, 6, "5x^2 - 13x + 6"),
    (1, -6, 8, "x^2 - 6x + 8"), (2, -8, 6, "2x^2 - 8x + 6"), (7, -15, 2, "7x^2 - 15x + 2"),
    (1, 0, -16, "x^2 - 16"),
]
for i in range(n_of(16)):
    A, B, C, eq = BHASK[i % len(BHASK)]
    p = dict(name="BHAS%02d" % (i + 1), title="Bhaskara %d" % (i + 1),
             A=A, B=B, C=C, eq=eq, scale=max(2, abs(A) * 2 + 2),
             axis=0x39435A, curve=col(i * 47, 0.7, 0.95),
             bg=0x10141F, fg=0xE8ECF4, fg2=0x8A93A5, dig=col(i * 47, 0.5, 0.95))
    add("BHAS%02d" % (i + 1), "MATH", T.t_bhaskara(p))

for i in range(n_of(16)):
    p = dict(name="CONV%02d" % (i + 1), title="Converte %d" % (i + 1),
             start=i * 37, step=1 + i % 5, max=60000, **pal(i + 360))
    add("CONV%02d" % (i + 1), "MATH", T.t_converte(p))

for i in range(n_of(16)):
    p = dict(name="TABU%02d" % (i + 1), title="Tabuada %d" % (i + 1),
             n=i + 2, **pal(i + 390))
    add("TABU%02d" % (i + 1), "MATH", T.t_tabuada(p))

for i in range(n_of(16)):
    p = dict(name="JURO%02d" % (i + 1), title="Juros %d" % (i + 1),
             periodos=18, taxa=2 + i % 8, capital=100,
             bar=col(i * 47, 0.65, 0.9), axis=0x39435A,
             bg=0x10141F, fg=0xE8ECF4, dig=col(i * 47, 0.5, 0.95))
    add("JURO%02d" % (i + 1), "MATH", T.t_juros(p))

for i in range(n_of(16)):
    p = dict(name="TERMO%02d" % (i + 1), title="Termos %d" % (i + 1),
             mercury=col(i * 30, 0.75, 0.95), cold=0x6FC3FF, hot=0xFF7A59,
             bg=0x10141F, fg=0xE8ECF4, fg2=0x8A93A5, off=0x2A3143, dig=col(i * 47, 0.5, 0.95))
    add("TERMO%02d" % (i + 1), "MATH", T.t_termos(p))

for i in range(n_of(16)):
    p = dict(name="PITA%02d" % (i + 1), title="Pitagoras %d" % (i + 1),
             lim=12 + (i % 5) * 3,
             hyp=0xFF9F45, cat=0x4FA3E0, dot=0xE8ECF4,
             bg=0x10141F, fg=0xE8ECF4, dig=col(i * 47, 0.5, 0.95))
    add("PITA%02d" % (i + 1), "MATH", T.t_pitagoras(p))

# ============================================================== JOGOS =======
for i in range(n_of(20)):
    p = dict(name="ADIV%02d" % (i + 1), title="Adivinha %d" % (i + 1),
             max=100 * (1 + i % 9), freq=880,
             band=col(i * 47, 0.5, 0.35), needle=0xFFFFFF, win=0x6FE08A,
             bg=0x10141F, fg=0xE8ECF4, off=0x2A3143, dig=col(i * 47, 0.5, 0.95))
    add("ADIV%02d" % (i + 1), "JOGO", T.t_adivinha(p))

for i in range(n_of(20)):
    p = dict(name="DADO%02d" % (i + 1), title="Dados %d" % (i + 1),
             n=2 + i % 6, faces=6 + (i % 3) * 2,
             bg2=0xF5F7FA, bg=0x1A2030, fg=0xE8ECF4, fg2=0x8A93A5,
             pips=0x1A2030, dig=col(i * 47, 0.5, 0.95))
    add("DADO%02d" % (i + 1), "JOGO", T.t_dados(p))

for i in range(n_of(20)):
    p = dict(name="REFL%02d" % (i + 1), title="Reflexo %d" % (i + 1),
             espera=1500 + i * 150, janela=2500, freq=990,
             green=0x1E9E50, gfg=0xFFFFFF, red=0xB03040, rfg=0xFFFFFF,
             amber=0xC07820, afg=0xFFFFFF, blue=0x20344E, bfg=0xE8ECF4,
             bg=0x10141F, fg=0xE8ECF4, dig=0x6FE08A)
    add("REFL%02d" % (i + 1), "JOGO", T.t_reflexo(p))

for i in range(n_of(20)):
    p = dict(name="VELH%02d" % (i + 1), title="Velha %d" % (i + 1),
             freq=880, x1=0x6FD8FF, x2=0x2D9CDB, o1=0xFFB84D, o2=0xE08A20,
             grid=0x39435A, win=0x6FE08A, lose=0xFF7A59, tie=0x8A93A5,
             bg=0x10141F, fg=0xE8ECF4, dig=0xE8ECF4)
    add("VELH%02d" % (i + 1), "JOGO", T.t_velha(p))

for i in range(n_of(20)):
    p = dict(name="COBR%02d" % (i + 1), title="Cobra %d" % (i + 1),
             vel=2 + i % 4, freq=740, freqd=220,
             food=0xFF7A59, body=col(i * 47, 0.6, 0.8), head=0xFFFFFF,
             bg=0x10141F, fg=0xE8ECF4, fg2=0xFF7A59, dig=col(i * 47, 0.5, 0.95))
    add("COBR%02d" % (i + 1), "JOGO", T.t_cobra(p))

for i in range(n_of(20)):
    p = dict(name="PONG%02d" % (i + 1), title="Pong %d" % (i + 1),
             vx=3 + i % 4, vy=2 + i % 3, rp=14, vel=1, cpu=2 + i % 3,
             freq=600, net=0x39435A, p1=0x6FD8FF, p2=0xFFB84D, ball=0xFFFFFF,
             bg=0x10141F, fg=0xE8ECF4, dig=0xE8ECF4)
    add("PONG%02d" % (i + 1), "JOGO", T.t_pong(p))

for i in range(n_of(20)):
    p = dict(name="MEMO%02d" % (i + 1), title="Memoria %d" % (i + 1),
             freq=880, back=col(i * 47, 0.5, 0.3), back2=col(i * 47, 0.4, 0.4),
             open=0x222B3E, sym=col(i * 47 + 180, 0.7, 0.95), win=0x6FE08A,
             bg=0x10141F, fg=0xE8ECF4, dig=0xE8ECF4)
    add("MEMO%02d" % (i + 1), "JOGO", T.t_memoria(p))

for i in range(n_of(20)):
    p = dict(name="JOKE%02d" % (i + 1), title="Jokenpo %d" % (i + 1),
             freq=880, me=0x6FD8FF, cpu=0xFFB84D, tie=0x8A93A5,
             win=0x6FE08A, lose=0xFF7A59, btn=0x27304A,
             bg=0x10141F, fg=0xE8ECF4, dig=0xE8ECF4)
    add("JOKE%02d" % (i + 1), "JOGO", T.t_jokenpo(p))

PALAVRAS = ["ENZO", "SISTEMA", "KERNEL", "ASSEMBLY", "MEMORIA", "TELA",
            "MOUSE", "DADOS", "ARQUIVO", "REDE", "PIXEL", "SOM",
            "PORTA", "CODIGO", "LINUX", "FONTE"]
for i in range(n_of(20)):
    p = dict(name="FORC%02d" % (i + 1), title="Forca %d" % (i + 1),
             word=PALAVRAS[i % len(PALAVRAS)], freq=300,
             dash=0x8A93A5, gallow=0xC8D0E0, body=0xFF7A59, arm=0xE8ECF4,
             leg=0xE8ECF4, keyoff=0x222B3E, keyon=0x4FA3E0, lose=0xFF7A59,
             bg=0x10141F, fg=0xE8ECF4, dig=0xE8ECF4)
    add("FORC%02d" % (i + 1), "JOGO", T.t_forca(p))

for i in range(n_of(20)):
    p = dict(name="CAMP%02d" % (i + 1), title="Campo %d" % (i + 1),
             nminas=8 + (i % 5) * 2, freqb=200, freqw=990, freqc=700,
             closed=col(i * 47, 0.5, 0.35), closed2=col(i * 47, 0.4, 0.45),
             boomed=0xB03040, mine=0x1A2030, open=0x1A2233, cnt=0x6FD8FF,
             bg=0x10141F, fg=0xE8ECF4, fg2=0xFF7A59, dig=0xE8ECF4)
    add("CAMP%02d" % (i + 1), "JOGO", T.t_campo(p))

for i in range(n_of(20)):
    nn = 20 + (i % 5) * 6
    p = dict(name="BOLH%02d" % (i + 1), title="Bolha %d" % (i + 1),
             n=nn, bar=col(i * 47, 0.6, 0.8), hlbar=0xFFFFFF, axis=0x39435A,
             win=0x6FE08A, bg=0x10141F, fg=0xE8ECF4, dig=0xE8ECF4)
    add("BOLH%02d" % (i + 1), "JOGO", T.t_bolha(p))

for i in range(n_of(20)):
    p = dict(name="VIDA%02d" % (i + 1), title="Vida %d" % (i + 1),
             dens=18 + (i % 6) * 5, on=col(i * 47, 0.65, 0.95),
             bg=0x10141F, fg=0xE8ECF4, off=0x151A26, dig=0xE8ECF4)
    add("VIDA%02d" % (i + 1), "JOGO", T.t_vida(p))

for i in range(n_of(20)):
    p = dict(name="HANO%02d" % (i + 1), title="Hanoi %d" % (i + 1),
             n=3 + i % 5, delay=140 + (i % 4) * 60, freq=880,
             peg=0xC8D0E0, base=0x39435A, d1=col(i * 47, 0.6, 0.85),
             d2=col(i * 47 + 180, 0.6, 0.85), win=0x6FE08A,
             bg=0x10141F, fg=0xE8ECF4, dig=0xE8ECF4)
    add("HANO%02d" % (i + 1), "JOGO", T.t_hanoi(p))

# ============================================================ VISUAL ========
FORMULAS = ["radial", "xor", "soma", "ondas", "diag", "anel"]
for i in range(n_of(56)):
    f = FORMULAS[i % len(FORMULAS)]
    k1 = 40 + (i * 13) % 200
    k2 = 20 + (i * 7) % 160
    p = dict(name="PLAS%02d" % (i + 1), title="Plasma %d" % (i + 1),
             formula=f, k1=k1, k2=k2, vel=1 + i % 5,
             palname="harmonica %d" % (i + 1), g2=1 + i % 4, b2=1 + (i * 3) % 6,
             label="PLASMA %d" % (i + 1))
    add("PLAS%02d" % (i + 1), "VISUAL", V.t_plasma(p))

REGIOES = [
    (-2 << 12, 0, 3 << 12, "completo"), (-8170, -2100, 900, "elefantes"),
    (-7450, 1130, 500, "cavalos-marinhos"), (-1760, -550, 350, "espiral dupla"),
    (-1620, -55, 120, "espiral tripla"), (-1010, 955, 120, "zoom profundo"),
    (-405, 625, 80, "mini-brot"), (-1590, 160, 60, "satelite"),
    (-1180, 260, 40, "pontes"), (-1720, 820, 30, "corais"),
]
for i in range(n_of(44)):
    cr, ci, span, lbl = REGIOES[i % len(REGIOES)]
    # variacoes finas por instancia
    cr = cr + ((i // 10) * 37)
    ci = ci + ((i // 10) * 23)
    span = max(24, span - (i // 10) * 9)
    p = dict(name="MAND%02d" % (i + 1), title="Mandel %d" % (i + 1),
             cr=cr, ci=ci, span=span, iter=24 + (i % 4) * 8,
             r0=(i * 23) % 200, rs=1 + i % 5, g0=(i * 17) % 160, gs=2 + i % 4,
             b0=80 + (i * 11) % 140, bs=1 + (i * 2) % 6,
             label="MANDELBROT %d — %s" % (i + 1, lbl))
    add("MAND%02d" % (i + 1), "VISUAL", V.t_mandel(p))

for i in range(n_of(32)):
    p = dict(name="LISS%02d" % (i + 1), title="Lissajous %d" % (i + 1),
             wa=5 + (i % 7), wb=3 + (i % 5), wd=40 + (i % 4) * 10,
             vel=1 + i % 3, steps=90 + (i % 4) * 30,
             bg=0x0D1117, fg=col(i * 47, 0.7, 0.95),
             label="LISSAJOUS %d" % (i + 1))
    add("LISS%02d" % (i + 1), "VISUAL", V.t_lissajous(p))

for i in range(n_of(28)):
    p = dict(name="ESPI%02d" % (i + 1), title="Espiro %d" % (i + 1),
             wa=7 + (i % 5), wb=11 + (i % 7), wd=60 + (i % 3) * 15,
             vel=1 + i % 3, steps=140 + (i % 5) * 20, r2=20 + (i % 4) * 9,
             bg=0x0D1117, fg=col(i * 47 + 120, 0.7, 0.95),
             label="ESPIROGRAFO %d" % (i + 1))
    add("ESPI%02d" % (i + 1), "VISUAL", V.t_espiro(p))

for i in range(n_of(24)):
    p = dict(name="ESTR%02d" % (i + 1), title="Estrelas %d" % (i + 1),
             vel=30 + i * 9, star=0xE8ECF4, glow=0x9FB6D8,
             bg=(0x0D1117 + (i % 3)) & 0xFFFFFF, label="CAMPO ESTELAR %d" % (i + 1))
    add("ESTR%02d" % (i + 1), "VISUAL", V.t_estrela(p))

for i in range(n_of(24)):
    p = dict(name="MATX%02d" % (i + 1), title="Matrix %d" % (i + 1),
             vel=1 + i % 4, gly=1 + i % 4,
             bg=0x050A06, c0=0x6FE08A, c1=0x1E9E50, c2=0xB8FFD0,
             tcol=0x4FA35E, label="MATRIX %d" % (i + 1))
    add("MATX%02d" % (i + 1), "VISUAL", V.t_matrix(p))

for i in range(n_of(24)):
    p = dict(name="ONDA%02d" % (i + 1), title="Ondas %d" % (i + 1),
             vel=1 + i % 5, k1=300 + (i * 37) % 900, k2=250 + (i * 29) % 700,
             r0=(i * 13) % 120, g0=(i * 7) % 120, b0=60 + (i * 17) % 160,
             label="INTERFERENCIA %d" % (i + 1))
    add("ONDA%02d" % (i + 1), "VISUAL", V.t_ondas(p))

for i in range(n_of(20)):
    p = dict(name="ARVO%02d" % (i + 1), title="Arvore %d" % (i + 1),
             len0=56 + i * 2, prof=4 + i % 3, ang=18 + (i % 4) * 5,
             shrink=62 + (i % 3) * 5, trunk=0x8A5A2B, twig=col(90 + i * 9, 0.6, 0.8),
             bg=0x0D1117, label="ARVORE FRACTAL %d" % (i + 1))
    add("ARVO%02d" % (i + 1), "VISUAL", V.t_arvore(p))

for i in range(n_of(16)):
    p = dict(name="KALE%02d" % (i + 1), title="Caleido %d" % (i + 1),
             vel=1 + i % 5, k1=3 + i % 5, k2=5 + i % 7, k3=64 + (i * 17) % 200,
             g1=1 + i % 3, b1=2 + (i * 2) % 5, fatias=2 + i % 4,
             label="CALEIDOSCOPIO %d" % (i + 1))
    add("KALE%02d" % (i + 1), "VISUAL", V.t_kaleido(p))

for i in range(n_of(16)):
    p = dict(name="FOGO%02d" % (i + 1), title="Fogo %d" % (i + 1),
             feed=30 + (i % 5) * 8, decay=55 + (i % 3) * 10, cool=3 + i % 4,
             gm=150 + (i % 4) * 30, bm=(i * 7) % 60, bg=0x0A0603,
             label="FOGO %d" % (i + 1))
    add("FOGO%02d" % (i + 1), "VISUAL", V.t_fogo(p))

for i in range(n_of(16)):
    p = dict(name="TUNL%02d" % (i + 1), title="Tunel %d" % (i + 1),
             vel=1 + i % 6, k1=180 + (i * 23) % 400, k2=90 + (i * 31) % 300,
             r0=(i * 11) % 100, g0=40 + (i * 19) % 120, b0=80 + (i * 13) % 150,
             label="TUNEL %d" % (i + 1))
    add("TUNL%02d" % (i + 1), "VISUAL", V.t_tunel(p))

for i in range(n_of(16)):
    p = dict(name="MOIR%02d" % (i + 1), title="Moire %d" % (i + 1),
             vel=1 + i % 4, k1=140 + (i * 17) % 300, k2=120 + (i * 23) % 260,
             r0=(i * 7) % 80, g0=(i * 29) % 80, b0=100 + (i * 13) % 140,
             label="MOIRE %d" % (i + 1))
    add("MOIR%02d" % (i + 1), "VISUAL", V.t_moire(p))

for i in range(n_of(16)):
    p = dict(name="CAOS%02d" % (i + 1), title="Caos %d" % (i + 1),
             vel=0, r0=10000 + (i % 6) * 160, rstep=60 + (i % 4) * 12,
             bg=0x0D1117, fg=col(i * 47, 0.7, 0.95),
             label="MAPA LOGISTICO %d" % (i + 1))
    add("CAOS%02d" % (i + 1), "VISUAL", V.t_caos(p))

for i in range(n_of(16)):
    a = 1 + (i * 3) % 40
    b = 1 + (i * 5) % 40
    c = 1 + (i * 7) % 40
    d = 1 + (i * 11) % 40
    p = dict(name="ATRA%02d" % (i + 1), title="Atrator %d" % (i + 1),
             pts=1400 + (i % 4) * 300, a=a, b=b, c=c, d=d,
             sc=(70 + (i % 5) * 10),
             bg=0x0D1117, fg=col(i * 47 + 60, 0.75, 0.95), fg2=col(i * 47 + 60, 0.75, 0.55),
             label="ATRATOR DE JONG %d" % (i + 1))
    add("ATRA%02d" % (i + 1), "VISUAL", V.t_atrator(p))

for i in range(n_of(16)):
    p = dict(name="VITR%02d" % (i + 1), title="Vitral %d" % (i + 1),
             vel=1 + i % 6,
             c0=0xFF000000 | col(i * 47, 0.8, 0.5),
             c1=0xFF000000 | col(i * 47 + 120, 0.8, 0.5),
             c2=0xFF000000 | col(i * 47 + 240, 0.8, 0.5),
             label="VITRAL %d" % (i + 1))
    add("VITR%02d" % (i + 1), "VISUAL", V.t_vitral(p))

for i in range(n_of(16)):
    p = dict(name="ESPL%02d" % (i + 1), title="Espiral %d" % (i + 1),
             vel=1 + i % 4, wd=50 + (i % 5) * 12, rvel=1 + i % 3,
             steps=240 + (i % 4) * 60, sc=28 + (i % 5) * 6,
             bg=0x0D1117, fg=col(i * 47, 0.7, 0.95), hl=0xFFFFFF,
             label="ESPIRAL %d" % (i + 1))
    add("ESPL%02d" % (i + 1), "VISUAL", V.t_espiral(p))

for i in range(n_of(16)):
    p = dict(name="GRAD%02d" % (i + 1), title="Grade %d" % (i + 1),
             vel=1 + i % 5, k1=60 + (i * 13) % 120, k2=90 + (i * 17) % 140,
             tint=(i * 29) % 60, cell=8 + (i % 4) * 4,
             grid=0x39435A, label="GRADE %d" % (i + 1))
    add("GRAD%02d" % (i + 1), "VISUAL", V.t_grade(p))

for i in range(n_of(12)):
    p = dict(name="RANA%02d" % (i + 1), title="RelogioAnalogico %d" % (i + 1),
             bg=0x10141F, tick=col(i * 47, 0.3, 0.4), tick5=0xE8ECF4,
             hour=0xE8ECF4, min=0x9FB6D8, sec=0xFF7A59, hub=0xE8ECF4,
             fg=0x8A93A5, label="RELOGIO ANALOGICO %d" % (i + 1))
    add("RANA%02d" % (i + 1), "VISUAL", V.t_relanal(p))


# ============================================================== saida =======
def main():
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        if f.endswith(".enz"):
            os.remove(os.path.join(OUT, f))
    manifest = []
    for a in APPS:
        path = os.path.join(OUT, a["name"] + ".enz")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(a["src"])
        manifest.append(dict(name=a["name"], w=a["w"], h=a["h"],
                             icon=a["icon"], cat=a["cat"]))
    with open(os.path.join(OUT, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    cats = {}
    for a in APPS:
        cats[a["cat"]] = cats.get(a["cat"], 0) + 1
    print("genapps: %d apps em %s — %s" % (len(APPS), OUT, cats))
    names = [a["name"] for a in APPS]
    assert len(set(names)) == len(names), "nomes duplicados!"


if __name__ == "__main__":
    main()
