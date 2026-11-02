#!/usr/bin/env python3
# =============================================================================
#  EnzoOS — tools/app_templates2.py: templates ENZ VISUAIS (gerador de apps)
#  Efeitos com ponto fixo 1/4096 e tabelas de seno emitidas como literais.
# =============================================================================
import math
from app_templates import HDR, COMMON_GLOBALS, sin_table, emit_fill


def _sinfill():
    return ("int sins[32];\nint coss[32];\n"
            "void fillsin() {\n"
            + emit_fill("sins", sin_table()) + "\n"
            + emit_fill("coss", [round(math.cos(2 * math.pi * i / 32) * 4096) for i in range(32)])
            + "\n}\n")


def _with_sin(body, w, h):
    """Injeta tabela de seno + chamada fillsin() no init do app."""
    body = body.replace("void init() {", "void init() {\n    fillsin();", 1)
    return body + "\n" + _sinfill(), w, h


# ---------------------------------------------------------------- PLASMA ----

def t_plasma(p):
    w, h = p.get("w", 400), p.get("h", 300)
    body = HDR % (p["name"], "VISUAL") + COMMON_GLOBALS + """
int t;

void init() {
    title("%s");
}

void tick() {
    t = t + %d;
    invalidate();
}

int pal(int v) {
    v = v & 255;
    // rampa %s
    int r = v;
    int g = (v * %d) & 255;
    int b = (v * %d) & 255;
    return 0xFF000000 | (r << 16) | (g << 8) | b;
}

void paint() {
    int y = 0;
    while (y < win_h) {
        int x = 0;
        while (x < win_w) {
            int v;
%s
            px(x, y, pal(v));
            x = x + 1;
        }
        y = y + 1;
    }
    text(8, 8, "%s", 0xFFFFFFFF);
}
"""
    formulas = {
        "radial":  "            v = ((x - win_w/2) * (x - win_w/2) + (y - win_h/2) * (y - win_h/2)) / %d + t;",
        "xor":     "            v = ((x ^ y) * %d) + t;",
        "soma":    "            v = (x * %d + y * %d + t);",
        "ondas":   "            v = ((x * x / %d + y * y / %d) + t);",
        "diag":    "            v = ((x + y) * %d + t);",
        "anel":    "            v = ((x - win_w/2) * (x - win_w/2) / %d) ^ ((y - win_h/2) * (y - win_h/2) / %d) ^ t;",
    }
    if p["formula"] == "soma":
        f = formulas["soma"] % (p["k1"], p["k2"])
    elif p["formula"] == "ondas":
        f = formulas["ondas"] % (p["k1"], p["k2"])
    elif p["formula"] == "anel":
        f = formulas["anel"] % (p["k1"], p["k2"])
    else:
        f = formulas[p["formula"]] % p["k1"]
    body = body % (p["title"], p["vel"], p["palname"], p["g2"], p["b2"], f, p["label"])
    return _with_sin(body, w, h)


def t_mandel(p):
    w, h = p.get("w", 400), p.get("h", 320)
    body = HDR % (p["name"], "VISUAL") + COMMON_GLOBALS + """
int pal[32];
int cr0; int ci0; int span;

void init() {
    title("%s");
    cr0 = %d;
    ci0 = %d;
    span = %d;
    int i = 0;
    while (i < 32) {
        int r = %d + i * %d;
        int g = %d + i * %d;
        int b = %d + i * %d;
        if (r > 255) { r = 255; }
        if (g > 255) { g = 255; }
        if (b > 255) { b = 255; }
        pal[i] = 0xFF000000 | (r << 16) | (g << 8) | b;
        i = i + 1;
    }
}

void paint() {
    int esc = 4096;
    int y = 0;
    while (y < win_h) {
        int x = 0;
        while (x < win_w) {
            int cr = cr0 + ((x - win_w / 2) * span) / win_w;
            int ci = ci0 + ((y - win_h / 2) * span) / win_h;
            int zr = 0;
            int zi = 0;
            int i = 0;
            int cor = 0xFF05070D;
            while (i < %d) {
                int zr2 = (zr * zr) / esc;
                int zi2 = (zi * zi) / esc;
                if (zr2 + zi2 > 4 * esc) { cor = pal[i & 31]; break; }
                int tt = (((zr * zi) / esc) * 2) + ci;
                zr = zr2 - zi2 + cr;
                zi = tt;
                i = i + 1;
            }
            px(x, y, cor);
            x = x + 1;
        }
        y = y + 1;
    }
    text(8, 8, "%s", 0xFFFFFFFF);
}
"""
    body = body % (p["title"], p["cr"], p["ci"], p["span"],
                   p["r0"], p["rs"], p["g0"], p["gs"], p["b0"], p["bs"],
                   p["iter"], p["label"])
    return body, w, h


def t_lissajous(p):
    w, h = p.get("w", 400), p.get("h", 340)
    body = HDR % (p["name"], "VISUAL") + COMMON_GLOBALS + """
int ax; int ay;
int bx; int by;
int t;
int trilho[512];

void init() {
    title("%s");
    ax = 4096; ay = 0;
    bx = 0; by = 4096;
    t = 0;
}

void tick() {
    int i = 0;
    while (i < %d) {
        // fasores girando com frequencias diferentes (ponto fixo)
        int nax = ax - (ay * %d) / 4096 / %d;
        int nay = ay + (ax * %d) / 4096 / %d;
        ax = nax; ay = nay;
        int nbx = bx - (by * %d) / 4096 / %d;
        int nby = by + (bx * %d) / 4096 / %d;
        bx = nbx; by = nby;
        t = t + 1;
        i = i + 1;
    }
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    int i = 0;
    int px0 = 0; int py0 = 0;
    while (i < %d) {
        int X = win_w / 2 + (ax * (win_w / 2 - 20)) / 4096;
        int Y = win_h / 2 + (by * (win_h / 2 - 20)) / 4096;
        if (i > 0) {
            line(px0, py0, X, Y, %s);
        }
        px0 = X; py0 = Y;
        // avanca um passo para desenhar o rastro
        int nax = ax - (ay * %d) / 4096 / %d;
        int nay = ay + (ax * %d) / 4096 / %d;
        ax = nax; ay = nay;
        int nbx = bx - (by * %d) / 4096 / %d;
        int nby = by + (bx * %d) / 4096 / %d;
        bx = nbx; by = nby;
        i = i + 1;
    }
    text(8, 8, "%s", 0xFFFFFFFF);
}
"""
    body = body % (p["title"], p["vel"],
                   p["wa"], p["wd"], p["wa"], p["wd"],
                   p["wb"], p["wd"], p["wb"], p["wd"],
                   p["bg"], p["steps"],
                   p["fg"], p["wa"], p["wd"], p["wa"], p["wd"],
                   p["wb"], p["wd"], p["wb"], p["wd"],
                   p["label"])
    return _with_sin(body, w, h)


def t_espiro(p):
    w, h = p.get("w", 400), p.get("h", 340)
    body = HDR % (p["name"], "VISUAL") + COMMON_GLOBALS + """
int a1x; int a1y;
int a2x; int a2y;
int t;

void init() {
    title("%s");
    a1x = 4096; a1y = 0;
    a2x = 4096; a2y = 0;
}

void tick() {
    int i = 0;
    while (i < %d) {
        int nx = a1x - (a1y * %d) / 4096 / %d;
        int ny = a1y + (a1x * %d) / 4096 / %d;
        a1x = nx; a1y = ny;
        int mx = a2x - (a2y * %d) / 4096 / %d;
        int my = a2y + (a2x * %d) / 4096 / %d;
        a2x = mx; a2y = my;
        t = t + 1;
        i = i + 1;
    }
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    int i = 0;
    int px0 = 0; int py0 = 0;
    while (i < %d) {
        int X = win_w / 2 + (a1x * (win_w / 2 - 15)) / 4096 + (a2x * %d) / 4096;
        int Y = win_h / 2 + (a1y * (win_h / 2 - 15)) / 4096 + (a2y * %d) / 4096;
        if (i > 0) { line(px0, py0, X, Y, %s); }
        px0 = X; py0 = Y;
        int nx = a1x - (a1y * %d) / 4096 / %d;
        int ny = a1y + (a1x * %d) / 4096 / %d;
        a1x = nx; a1y = ny;
        int mx = a2x - (a2y * %d) / 4096 / %d;
        int my = a2y + (a2x * %d) / 4096 / %d;
        a2x = mx; a2y = my;
        i = i + 1;
    }
    text(8, 8, "%s", 0xFFFFFFFF);
}
"""
    body = body % (p["title"], p["vel"],
                   p["wa"], p["wd"], p["wa"], p["wd"],
                   p["wb"], p["wd"], p["wb"], p["wd"],
                   p["bg"], p["steps"], p["r2"], p["r2"], p["fg"],
                   p["wa"], p["wd"], p["wa"], p["wd"],
                   p["wb"], p["wd"], p["wb"], p["wd"],
                   p["label"])
    return _with_sin(body, w, h)


def t_estrela(p):
    w, h = p.get("w", 400), p.get("h", 300)
    return HDR % (p["name"], "VISUAL") + COMMON_GLOBALS + """
int sx[90];
int sy[90];
int sz[90];
int semente;

void init() {
    title("%s");
    semente = uptime() | 1;
    int i = 0;
    while (i < 90) {
        sx[i] = rnd(4096) - 2048;
        sy[i] = rnd(4096) - 2048;
        sz[i] = 64 + rnd(3840);
        i = i + 1;
    }
}

int rnd(int m) {
    semente = semente * 1664525 + 1013904223;
    if (semente < 0) { semente = -semente; }
    return (semente / 65536) %% m;
}

void tick() {
    int i = 0;
    while (i < 90) {
        sz[i] = sz[i] - %d;
        if (sz[i] < 32) {
            sz[i] = 3904;
            sx[i] = rnd(4096) - 2048;
            sy[i] = rnd(4096) - 2048;
        }
        i = i + 1;
    }
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    int i = 0;
    while (i < 90) {
        int z = sz[i];
        int X = win_w / 2 + (sx[i] * 300) / z;
        int Y = win_h / 2 + (sy[i] * 300) / z;
        if (X > 0 && X < win_w && Y > 0 && Y < win_h) {
            int t = 4 - z / 1000;
            if (t < 1) { t = 1; }
            if (t > 4) { t = 4; }
            rect(X, Y, t, t, %s);
            if (t >= 3) { rect(X + t, Y, 1, 1, %s); rect(X - 1, Y, 1, 1, %s); }
        }
        i = i + 1;
    }
    text(8, 8, "%s", 0xFFFFFFFF);
}
""" % (p["title"], p["vel"], p["bg"], p["star"], p["glow"], p["glow"], p["label"]), w, h


def t_matrix(p):
    w, h = p.get("w", 420), p.get("h", 300)
    return HDR % (p["name"], "VISUAL") + COMMON_GLOBALS + """
int colu[53];
int brilho[848];
int semente;

void init() {
    title("%s");
    semente = uptime() | 1;
    int i = 0;
    while (i < 53) {
        colu[i] = rnd(16);
        int j = 0;
        while (j < 16) {
            brilho[i*16+j] = rnd(3);
            j = j + 1;
        }
        i = i + 1;
    }
}

int rnd(int m) {
    semente = semente * 1664525 + 1013904223;
    if (semente < 0) { semente = -semente; }
    return (semente / 65536) %% m;
}

void tick() {
    int i = 0;
    while (i < 53) {
        colu[i] = colu[i] + %d;
        if (colu[i] >= 24) { colu[i] = 0; }
        int j = 0;
        while (j < 16) {
            if (rnd(6) == 0) { brilho[i*16+j] = 1 + rnd(%d); }
            j = j + 1;
        }
        i = i + 1;
    }
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    int i = 0;
    while (i < 53) {
        int j = 0;
        while (j < 16) {
            int pos = colu[i] - j;
            if (pos < 0) { pos = pos + 24; }
            if (pos < 19) {
                int br = 8 - j;
                if (br < 1) { br = 1; }
                int c = %s;
                if (j == 0) { c = %s; }
                else if (br > 6) { c = %s; }
                // glifo: pontos do brilho
                int g = brilho[i*16+j];
                int y = 10 + pos * 15;
                int x = 6 + i * 8;
                if ((g & 1) != 0) { rect(x, y, 4, 4, c); }
                if ((g & 2) != 0) { rect(x + 4, y + 4, 3, 3, c); }
                if (br > 4 && (g & 1) != 0) { rect(x, y + 8, 4, 3, c); }
            }
            j = j + 1;
        }
        i = i + 1;
    }
    text(8, win_h - 14, "%s", %s);
}
""" % (p["title"], p["vel"], p["gly"], p["bg"], p["c1"], p["c0"], p["c2"], p["label"], p["tcol"]), w, h


def t_ondas(p):
    w, h = p.get("w", 400), p.get("h", 300)
    return HDR % (p["name"], "VISUAL") + COMMON_GLOBALS + """
int t;

void init() {
    title("%s");
}

void tick() {
    t = t + %d;
    invalidate();
}

void paint() {
    int y = 0;
    while (y < win_h) {
        int x = 0;
        while (x < win_w) {
            int d1 = (x - win_w / 4) * (x - win_w / 4) + (y - win_h / 2) * (y - win_h / 2);
            int d2 = (x - 3 * win_w / 4) * (x - 3 * win_w / 4) + (y - win_h / 2) * (y - win_h / 2);
            int v = (d1 / %d + t) ^ (d2 / %d - t);
            v = v & 255;
            int r = %d + v / 2;
            int g = %d + v;
            int b = %d + (v * 3) / 2;
            if (r > 255) { r = 255; }
            if (g > 255) { g = 255; }
            if (b > 255) { b = 255; }
            px(x, y, 0xFF000000 | (r << 16) | (g << 8) | b);
            x = x + 1;
        }
        y = y + 1;
    }
    text(8, 8, "%s", 0xFFFFFFFF);
}
""" % (p["title"], p["vel"], p["k1"], p["k2"], p["r0"], p["g0"], p["b0"], p["label"]), w, h


def t_arvore(p):
    w, h = p.get("w", 380), p.get("h", 320)
    # arvore fractal iterativa: filas de segmentos (x, y, ang_idx, len)
    body = HDR % (p["name"], "VISUAL") + COMMON_GLOBALS + """
int fx[128];
int fy[128];
int fa[128];
int fl[128];
int n;
int t;

void init() {
    title("%s");
}

void tick() {
    t = t + 1;
    invalidate();
}

// angulo em unidades de 1/4096 rad aproximado por tabela
int cossi(int a) {
    a = a & 255;
    return coss[(a * 32 / 256) & 31];
}

int sini(int a) {
    a = a & 255;
    return sins[(a * 32 / 256) & 31];
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    // semente
    n = 1;
    fx[0] = win_w / 2;
    fy[0] = win_h - 20;
    fa[0] = 192;       // apontando pra cima (3/4 de volta)
    fl[0] = %d;
    int passo = 0;
    while (passo < %d) {
        int i = 0;
        int base = n;
        while (i < base) {
            int x = fx[i];
            int y = fy[i];
            int a = fa[i];
            int l = fl[i];
            int x2 = x + (sini(a) * l) / 4096;
            int y2 = y - (cossi(a) * l) / 4096;
            int cor = %s;
            if (passo < 2) { cor = %s; }
            line(x, y, x2, y2, cor);
            // dois filhos
            if (n < 126) {
                fx[n] = x2; fy[n] = y2; fa[n] = a - %d; fl[n] = l * %d / 100;
                n = n + 1;
            }
            if (n < 126) {
                fx[n] = x2; fy[n] = y2; fa[n] = a + %d; fl[n] = l * %d / 100;
                n = n + 1;
            }
            i = i + 1;
        }
        passo = passo + 1;
    }
    // vento: deslocamento pelo tempo
    text(8, 8, "%s", 0xFFFFFFFF);
}
"""
    body = body % (p["title"], p["bg"], p["len0"], p["prof"], p["twig"], p["trunk"], p["ang"], p["shrink"], p["ang"], p["shrink"], p["label"])
    return _with_sin(body, w, h)


def t_kaleido(p):
    w, h = p.get("w", 360), p.get("h", 300)
    return HDR % (p["name"], "VISUAL") + COMMON_GLOBALS + """
int t;

void init() {
    title("%s");
}

void tick() {
    t = t + %d;
    invalidate();
}

int pal(int v) {
    v = v & 255;
    return 0xFF000000 | (v << 16) | ((v * %d) & 255 << 8) | ((v * %d) & 255);
}

void paint() {
    int y = 0;
    while (y < win_h) {
        int x = 0;
        while (x < win_w) {
            int dx = x - win_w / 2;
            if (dx < 0) { dx = -dx; }
            int dy = y - win_h / 2;
            if (dy < 0) { dy = -dy; }
            int v = ((dx * %d + dy * %d) ^ (dx * dy / %d)) + t;
            // espelha em %d fatias
            if ((v / 16) %% 2 == 0) { v = 255 - v; }
            px(x, y, pal(v));
            x = x + 1;
        }
        y = y + 1;
    }
    text(8, 8, "%s", 0xFFFFFFFF);
}
""" % (p["title"], p["vel"], p["g1"], p["b1"], p["k1"], p["k2"], p["k3"], p["fatias"], p["label"]), w, h


def t_fogo(p):
    w, h = p.get("w", 380), p.get("h", 280)
    return HDR % (p["name"], "VISUAL") + COMMON_GLOBALS + """
int f[960];
int semente;

void init() {
    title("%s");
    semente = uptime() | 1;
}

int rnd(int m) {
    semente = semente * 1664525 + 1013904223;
    if (semente < 0) { semente = -semente; }
    return (semente / 65536) %% m;
}

void tick() {
    // base alimenta
    int x = 0;
    while (x < 40) {
        if (rnd(100) < %d) { f[x*24+23] = 255; }
        else { f[x*24+23] = f[x*24+23] * %d / 100; }
        x = x + 1;
    }
    // sobe esfriando
    int y = 0;
    while (y < 23) {
        x = 0;
        while (x < 40) {
            int soma = f[x*24+y+1];
            if (x > 0) { soma = soma + f[(x-1)*24+y+1]; }
            if (x < 39) { soma = soma + f[(x+1)*24+y+1]; }
            int v = soma / 3 - %d;
            if (v < 0) { v = 0; }
            f[x*24+y] = v;
            x = x + 1;
        }
        y = y + 1;
    }
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    int y = 0;
    while (y < 24) {
        int x = 0;
        while (x < 40) {
            int v = f[x*24+23-y];
            if (v > 0) {
                int r = v;
                int g = (v * %d) / 255;
                int b = (v * %d) / 255;
                rect(10 + x * 9, 10 + y * 11, 8, 10, 0xFF000000 | (r << 16) | (g << 8) | b);
            }
            x = x + 1;
        }
        y = y + 1;
    }
    text(8, win_h - 14, "%s", 0xFFFFFFFF);
}
""" % (p["title"], p["feed"], p["decay"], p["cool"], p["bg"], p["gm"], p["bm"], p["label"]), w, h


def t_tunel(p):
    w, h = p.get("w", 380), p.get("h", 300)
    return HDR % (p["name"], "VISUAL") + COMMON_GLOBALS + """
int t;

void init() {
    title("%s");
}

void tick() {
    t = t + %d;
    invalidate();
}

void paint() {
    int y = 0;
    while (y < win_h) {
        int x = 0;
        while (x < win_w) {
            int dx = x - win_w / 2;
            int dy = y - win_h / 2;
            int d2 = (dx * dx + dy * dy) / %d;
            int tw = (dx * dy) / %d;
            int v = (d2 + tw + t) & 127;
            v = v * 2;
            int r = %d + v / 3;
            int g = %d + v / 2;
            int b = %d + v;
            if (r > 255) { r = 255; }
            if (g > 255) { g = 255; }
            if (b > 255) { b = 255; }
            px(x, y, 0xFF000000 | (r << 16) | (g << 8) | b);
            x = x + 1;
        }
        y = y + 1;
    }
    text(8, 8, "%s", 0xFFFFFFFF);
}
""" % (p["title"], p["vel"], p["k1"], p["k2"], p["r0"], p["g0"], p["b0"], p["label"]), w, h


def t_moire(p):
    w, h = p.get("w", 380), p.get("h", 300)
    return HDR % (p["name"], "VISUAL") + COMMON_GLOBALS + """
int t;

void init() {
    title("%s");
}

void tick() {
    t = t + %d;
    invalidate();
}

void paint() {
    int y = 0;
    while (y < win_h) {
        int x = 0;
        while (x < win_w) {
            int d1 = ((x - win_w / 3 - t) * (x - win_w / 3 - t) + (y - win_h / 3) * (y - win_h / 3)) / %d;
            int d2 = ((x - 2 * win_w / 3 + t) * (x - 2 * win_w / 3 + t) + (y - 2 * win_h / 3) * (y - 2 * win_h / 3)) / %d;
            int v = (d1 ^ d2) & 63;
            v = v * 4;
            px(x, y, 0xFF000000 | (%d + v << 16) | (%d + v << 8) | (%d + v));
            x = x + 1;
        }
        y = y + 1;
    }
    text(8, 8, "%s", 0xFFFFFFFF);
}
""" % (p["title"], p["vel"], p["k1"], p["k2"], p["r0"], p["g0"], p["b0"], p["label"]), w, h


def t_caos(p):
    w, h = p.get("w", 400), p.get("h", 300)
    return HDR % (p["name"], "VISUAL") + COMMON_GLOBALS + """
int t;
int xp;

void init() {
    title("%s");
    t = 0;
    xp = 0;
}

void tick() {
    t = t + %d;
    if (t > 4000) { t = 0; }
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    // mapa logistico: x' = r x (1 - x), ponto fixo 1/4096
    int coluna = 0;
    int r = %d;
    while (coluna < win_w) {
        int x = 2048;
        int i = 0;
        while (i < 60) {
            x = (r * x * (4096 - x)) / 4096 / 4096;
            if (x < 0) { x = 0; }
            if (x > 4095) { x = 4095; }
            i = i + 1;
        }
        // plota alguns pontos da orbita
        i = 0;
        while (i < 20) {
            x = (r * x * (4096 - x)) / 4096 / 4096;
            if (x < 0) { x = 0; }
            if (x > 4095) { x = 4095; }
            int Y = win_h - 10 - (x * (win_h - 20)) / 4096;
            px(10 + coluna, Y, %s);
            i = i + 1;
        }
        r = r + %d;
        coluna = coluna + 1;
    }
    text(8, 8, "%s", 0xFFFFFFFF);
}
""" % (p["title"], p["vel"], p["bg"], p["r0"], p["rstep"], p["fg"], p["label"]), w, h


def t_atrator(p):
    w, h = p.get("w", 380), p.get("h", 320)
    body = HDR % (p["name"], "VISUAL") + COMMON_GLOBALS + """
int x; int y;
int n;

void init() {
    title("%s");
    x = 0;
    y = 0;
    n = 0;
}

int seno(int v) {
    // indexa a tabela por v (0..4095 = volta completa)
    int i = (v / 128) & 31;
    return sins[i];
}

int cosseno(int v) {
    int i = (v / 128) & 31;
    return coss[i];
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    int i = 0;
    while (i < %d) {
        int nx = seno(%d * y / 4096) - cosseno(%d * x / 4096);
        int ny = seno(%d * x / 4096) - cosseno(%d * y / 4096);
        x = nx;
        y = ny;
        int X = win_w / 2 + x * %d / 4096;
        int Y = win_h / 2 + y * %d / 4096;
        if (X > 1 && X < win_w - 1 && Y > 1 && Y < win_h - 1) {
            px(X, Y, %s);
            px(X + 1, Y, %s);
        }
        i = i + 1;
    }
    text(8, 8, "%s", 0xFFFFFFFF);
}
"""
    body = body % (p["title"], p["bg"], p["pts"], p["a"], p["b"], p["c"], p["d"], p["sc"], p["sc"], p["fg"], p["fg2"], p["label"])
    return _with_sin(body, w, h)


def t_vitral(p):
    w, h = p.get("w", 380), p.get("h", 300)
    body = HDR % (p["name"], "VISUAL") + COMMON_GLOBALS + """
int pxs[9];
int pys[9];
int t;

void init() {
    title("%s");
}

void tick() {
    t = t + %d;
    invalidate();
}

void paint() {
    int y = 0;
    while (y < win_h) {
        int x = 0;
        while (x < win_w) {
            // 9 focos orbitando
            int melhor = 0;
            int md = 2147483647;
            int k = 0;
            while (k < 9) {
                int fx = win_w / 2 + (coss[(k * 3 + t / 64) & 31] * (win_w / 2 - 10)) / 4096;
                int fy = win_h / 2 + (sins[(k * 5 + t / 64) & 31] * (win_h / 2 - 10)) / 4096;
                int dx = x - fx;
                int dy = y - fy;
                int d = dx * dx + dy * dy;
                if (d < md) { md = d; melhor = k; }
                k = k + 1;
            }
            int v = (md / 512 + t / 32) & 63;
            int cor = %s;
            if (melhor %% 3 == 0) { cor = %s; }
            if (melhor %% 3 == 1) { cor = %s; }
            px(x, y, cor + v);
            x = x + 1;
        }
        y = y + 1;
    }
    text(8, 8, "%s", 0xFFFFFFFF);
}
"""
    body = body % (p["title"], p["vel"], p["c0"], p["c1"], p["c2"], p["label"])
    return _with_sin(body, w, h)


def t_espiral(p):
    w, h = p.get("w", 380), p.get("h", 320)
    body = HDR % (p["name"], "VISUAL") + COMMON_GLOBALS + """
int ax; int ay;
int r;
int t;

void init() {
    title("%s");
    ax = 4096;
    ay = 0;
    r = 0;
}

void tick() {
    int i = 0;
    while (i < %d) {
        int nx = ax - (ay * 4096) / 4096 / %d;
        int ny = ay + (ax * 4096) / 4096 / %d;
        ax = nx; ay = ny;
        r = r + %d;
        t = t + 1;
        i = i + 1;
    }
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    int i = 0;
    int rr = 0;
    int lx = 4096; int ly = 0;
    while (i < %d) {
        int nx = lx - (ly * 4096) / 4096 / %d;
        int ny = ly + (lx * 4096) / 4096 / %d;
        lx = nx; ly = ny;
        rr = rr + %d;
        int X = win_w / 2 + (lx * rr) / 4096 / %d;
        int Y = win_h / 2 + (ly * rr) / 4096 / %d;
        rect(X, Y, 3, 3, %s);
        if ((i %% 8) == 0) { rect(X, Y, 6, 6, %s); }
        i = i + 1;
    }
    text(8, 8, "%s", 0xFFFFFFFF);
}
"""
    body = body % (p["title"], p["vel"], p["wd"], p["wd"], p["rvel"],
                   p["bg"], p["steps"], p["wd"], p["wd"], p["rvel"], p["sc"], p["sc"],
                   p["fg"], p["hl"], p["label"])
    return _with_sin(body, w, h)


def t_grade(p):
    w, h = p.get("w", 400), p.get("h", 300)
    return HDR % (p["name"], "VISUAL") + COMMON_GLOBALS + """
int t;

void init() {
    title("%s");
}

void tick() {
    t = t + %d;
    invalidate();
}

void paint() {
    int y = 0;
    while (y < win_h) {
        int x = 0;
        while (x < win_w) {
            int dx = x - win_w / 2;
            int dy = y - win_h / 2;
            int v = (dx * dx / %d + dy * dy / %d + t) & 127;
            int l = 24 + v / 2;
            px(x, y, 0xFF000000 | (l << 16) | (l << 8) | (l + %d));
            x = x + 1;
        }
        y = y + 1;
    }
    // linhas de grade
    int gx = 0;
    while (gx < win_w) {
        int gy = 0;
        while (gy < win_h) {
            px(gx, gy, %s);
            gy = gy + %d;
        }
        gx = gx + %d;
    }
    text(8, 8, "%s", 0xFFFFFFFF);
}
""" % (p["title"], p["vel"], p["k1"], p["k2"], p["tint"], p["grid"], p["cell"], p["cell"], p["label"]), w, h


def t_relanal(p):
    w, h = p.get("w", 340), p.get("h", 340)
    body = HDR % (p["name"], "VISUAL") + COMMON_GLOBALS + """
int t;

void init() {
    title("%s");
}

void tick() {
    t = t + 1;
    invalidate();
}

void pintar(int adeg, int raio, int cor) {
    int a = adeg * 32 / 360;
    int X = win_w / 2 + (coss[a & 31] * raio) / 4096;
    int Y = win_h / 2 + (sins[a & 31] * raio) / 4096;
    line(win_w / 2, win_h / 2, X, Y, cor);
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    int R = win_w / 2 - 16;
    int i = 0;
    while (i < 60) {
        int a = i * 6;
        int X = win_w / 2 + (coss[a & 31] * R) / 4096;
        int Y = win_h / 2 + (sins[a & 31] * R) / 4096;
        int c = %s;
        if (i %% 5 == 0) { c = %s; }
        line(win_w / 2, win_h / 2, X, Y, c);
        i = i + 1;
    }
    int u = uptime() / 1000;
    // ponteiros
    pintar((u / 3600 %% 12) * 30 + (u / 60 %% 60) / 2, R - 40, %s);
    pintar((u / 60 %% 60) * 6, R - 16, %s);
    pintar((u %% 60) * 6, R - 8, %s);
    rect(win_w / 2 - 5, win_h / 2 - 5, 10, 10, %s);
    text(10, win_h - 18, "%s", %s);
}
"""
    body = body % (p["title"], p["bg"], p["tick"], p["tick5"], p["hour"], p["min"], p["sec"], p["hub"], p["label"], p["fg"])
    return _with_sin(body, w, h)
