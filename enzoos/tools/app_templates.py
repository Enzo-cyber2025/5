#!/usr/bin/env python3
# =============================================================================
#  EnzoOS — tools/app_templates.py: templates ENZ para o gerador de apps
#
#  Cada função retorna o código-fonte ENZ de um app REAL (lógica própria),
#  parametrizado. A linguagem ENZ é C-like de inteiros 32 bits (tools/enzc.py):
#  sem ponto flutuante (ponto fixo), sem strings dinâmicas (literais), vetores
#  1-D, handlers init/paint/tick/key/mouse.
#
#  Números dinâmicos na tela usam um auxiliar de 7 segmentos (seg7).
#  Trigonometria usa tabelas de seno geradas aqui (inteiros 1/4096).
# =============================================================================
import math

# ---------------------------------------------------------------- helpers ----

def sin_table(n=32, esc=4096):
    """Tabela de seno como literais ENZ (1/esc)."""
    vals = [round(math.sin(2 * math.pi * i / n) * esc) for i in range(n)]
    return vals


def emit_fill(name, vals):
    """Linhas 'nome[i] = v;' para o init()."""
    out = []
    for i, v in enumerate(vals):
        out.append("        %s[%d] = %d;" % (name, i, v))
    return "\n".join(out)


def seg7_code():
    """Auxiliar compartilhado: dígitos 7 segmentos + desenha número."""
    return r"""
// ---- máscaras 7-seg: bit0 topo,1 sup-dir,2 inf-dir,3 base,4 inf-esq,
// ---- 5 sup-esq,6 meio (hexa completo)
void seg_init() {
    segm[0] = 0x3F;  segm[1] = 0x06;  segm[2] = 0x5B;  segm[3] = 0x4F;
    segm[4] = 0x66;  segm[5] = 0x6D;  segm[6] = 0x7D;  segm[7] = 0x07;
    segm[8] = 0x7F;  segm[9] = 0x6F;  segm[10] = 0x77; segm[11] = 0x7C;
    segm[12] = 0x39; segm[13] = 0x5E; segm[14] = 0x79; segm[15] = 0x71;
}

void seg1(int x, int y, int d, int cor) {
    int m = segm[d & 15];
    int W = 14;
    int H = 24;
    if ((m & 1) != 0) { rect(x + 2, y, W, 3, cor); }
    if ((m & 2) != 0) { rect(x + W, y + 2, 3, H / 2, cor); }
    if ((m & 4) != 0) { rect(x + W, y + H, 3, H / 2, cor); }
    if ((m & 8) != 0) { rect(x + 2, y + H + H, W, 3, cor); }
    if ((m & 16) != 0) { rect(x, y + H, 3, H / 2, cor); }
    if ((m & 32) != 0) { rect(x, y + 2, 3, H / 2, cor); }
    if ((m & 64) != 0) { rect(x + 2, y + H, W, 3, cor); }
}

// desenha v com nd dígitos (sem sinal; se v<0 mostra '-')
void segnum(int x, int y, int v, int nd, int cor, int apag) {
    int i = nd - 1;
    int neg = 0;
    if (v < 0) { neg = 1; v = -v; }
    while (i >= 0) {
        int d = v % 10;
        v = v / 10;
        seg1(x + i * 22, y, d, cor);
        i = i - 1;
    }
    if (neg == 1) { rect(x - 6, y + 20, 4, 4, cor); }
}
""".strip()


HDR = """// %s — gerado por tools/genapps.py (categoria %s)
"""

COMMON_GLOBALS = """
int segm[16];
int vals[6];
int linha[34];
"""


# ================================================================== UTIL ====

def t_relogio(p):
    w, h = 420, 240
    body = HDR % (p["name"], "UTIL") + COMMON_GLOBALS + """
void init() {
    seg_init();
    title("%s");
}

void tick() {
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    time(tbuf);
    // hh:mm:ss nas posições fixas (a string é literal do runtime)
    text(16, 14, "RELOGIO", %s);
    // barreira de segundos: pulse
    int u = uptime() / 1000;
    int s = u %% 60;
    // mostrador: 6 dígitos h m s
    segnum(40, 90, (u / 3600) %% 100, 2, %s, 0);
    seg1(96, 90, 10, %s);
    segnum(130, 90, (u / 60) %% 60, 2, %s, 0);
    seg1(186, 90, 10, %s);
    segnum(220, 90, s, 2, %s, 0);
    // pontos da segundos
    int i = 0;
    while (i < 60) {
        int a = i * 6;
        int on = 0;
        if (i <= s) { on = 1; }
        int cx = win_w / 2 + (coss[a & 31] * 150) / 4096;
        int cy = 70 + (sins[a & 31] * 150) / 4096 / 2;
        if (on == 1) { rect(cx, cy, 4, 4, %s); }
        else { rect(cx, cy, 3, 3, %s); }
        i = i + 1;
    }
}
""" % (p["title"], p["bg"], p["fg"], p["dig"], p["dig"], p["dig"], p["dig"], p["dig"], p["on"], p["off"])
    body += "int tbuf[20];\nint sins[32];\nint coss[32];\n"
    body += "void fillsin() {\n" + emit_fill("sins", sin_table()) + "\n" + emit_fill("coss", [round(math.cos(2*math.pi*i/32)*4096) for i in range(32)]) + "\n}\n"
    body = body.replace("void init() {\n    seg_init();", "void init() {\n    seg_init();\n    fillsin();")
    return body, w, h


def t_crono(p):
    w, h = 380, 240
    return HDR % (p["name"], "UTIL") + COMMON_GLOBALS + """
int run;
int t0;
int best;

void init() {
    seg_init();
    title("%s");
}

void mouse(int x, int y, int b, int pr) {
    if (pr != 1) { return; }
    if (run == 0) {
        run = 1;
        t0 = uptime();
    } else {
        run = 0;
        int d = uptime() - t0;
        if (d < best || best == 0) { best = d; }
    }
    invalidate();
}

void key(int k) {
    if (k == 114) { run = 0; t0 = uptime(); best = 0; invalidate(); }
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(16, 12, "CRONOMETRO — clique liga/para, R zera", %s);
    int d = 0;
    if (run == 1) { d = uptime() - t0; }
    int cs = (d / 10) %% 100;
    int s = (d / 1000) %% 60;
    int m = (d / 60000) %% 60;
    segnum(30, 70, m, 2, %s, 0);
    seg1(86, 70, 10, %s);
    segnum(120, 70, s, 2, %s, 0);
    seg1(176, 70, 10, %s);
    segnum(210, 70, cs, 2, %s, 0);
    text(16, 170, "melhor volta:", %s);
    segnum(200, 160, best / 10, 4, %s, 0);
    if (run == 1) {
        rect(16, 200, 60, 8, %s);
    }
}

void tick() {
    if (run == 1) { invalidate(); }
}
""" % (p["title"], p["bg"], p["fg"], p["dig"], p["dig"], p["dig"], p["dig"], p["dig"], p["fg"], p["dig"], p["on"]), w, h


def t_timer(p):
    w, h = 380, 260
    return HDR % (p["name"], "UTIL") + COMMON_GLOBALS + """
int restante;
int t0;
int tocando;

void init() {
    seg_init();
    title("%s");
    restante = %d;
    t0 = uptime();
}

void mouse(int x, int y, int b, int pr) {
    if (pr != 1) { return; }
    restante = restante + %d;
    invalidate();
}

void tick() {
    int agora = uptime();
    while (t0 + 1000 <= agora) {
        t0 = t0 + 1000;
        if (restante > 0) { restante = restante - 1; }
        if (restante == 0) { tocando = 1; }
        invalidate();
    }
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(16, 12, "TIMER — clique soma tempo", %s);
    segnum(60, 80, restante / 60, 2, %s, 0);
    seg1(116, 80, 10, %s);
    segnum(150, 80, restante %% 60, 2, %s, 0);
    int i = 0;
    while (i < 30) {
        int on = 0;
        if (i < restante) { on = 1; }
        if (on == 1) { rect(20 + i * 11, 190, 8, 14, %s); }
        else { rect(20 + i * 11, 190, 8, 14, %s); }
        i = i + 1;
    }
    if (tocando == 1) {
        text(16, 150, "TEMPO! (T para silenciar)", %s);
        if ((uptime() / 400) %% 2 == 0) { beep(%d, 30); }
    }
}

void key(int k) {
    if (k == 116) { tocando = 0; invalidate(); }
}
""" % (p["title"], p["start"], p["add"], p["bg"], p["fg"], p["dig"], p["dig"], p["dig"], p["on"], p["off"], p["fg"], p["freq"]), w, h


def t_contador(p):
    w, h = 360, 260
    return HDR % (p["name"], "UTIL") + COMMON_GLOBALS + """
int n;
int t0;

void init() {
    seg_init();
    title("%s");
}

void mouse(int x, int y, int b, int pr) {
    if (pr != 1) { return; }
    if (y > win_h - 70) {
        if (x > win_w / 2) { n = n + %d; }
        else { n = n - %d; }
        t0 = uptime();
        invalidate();
    }
}

void key(int k) {
    if (k == 43) { n = n + 1; invalidate(); }
    if (k == 45) { n = n - 1; invalidate(); }
    if (k == 114) { n = 0; invalidate(); }
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(16, 12, "CONTADOR — clique nos botoes ou + -", %s);
    segnum(90, 80, n, 5, %s, 0);
    rect(20, win_h - 60, 140, 44, %s);
    text(60, win_h - 46, "MENOS", %s);
    rect(win_w - 160, win_h - 60, 140, 44, %s);
    text(win_w - 118, win_h - 46, "MAIS", %s);
    // tanque visual
    int lvl = n;
    if (lvl < 0) { lvl = 0; }
    if (lvl > 100) { lvl = 100; }
    rect(30, 40, lvl * (win_w - 60) / 100, 18, %s);
    if (t0 != 0) {
        int d = uptime() - t0;
        if (d < 400) { rect(0, 0, win_w, 4, %s); }
    }
}
""" % (p["title"], p["step"], p["step"], p["bg"], p["fg"], p["dig"], p["btn"], p["fg"], p["btn"], p["fg"], p["on"], p["on"]), w, h


def t_senha(p):
    w, h = 420, 240
    return HDR % (p["name"], "UTIL") + COMMON_GLOBALS + """
int d0; int d1; int d2; int d3; int d4; int d5;
int semente;

void init() {
    seg_init();
    title("%s");
    semente = uptime() | 1;
    d0 = 0; d1 = 0; d2 = 0; d3 = 0; d4 = 0; d5 = 0;
}

int rnd(int m) {
    semente = semente * 1664525 + 1013904223;
    if (semente < 0) { semente = 0 - semente; }
    return (semente / 65536) %% m;
}

void nova() {
    d0 = rnd(%d); d1 = rnd(%d); d2 = rnd(%d);
    d3 = rnd(%d); d4 = rnd(%d); d5 = rnd(%d);
}

void mouse(int x, int y, int b, int pr) {
    if (pr != 1) { return; }
    nova();
    beep(%d, 20);
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(16, 12, "GERADOR DE SENHA — clique gera", %s);
    seg1(30, 90, d0, %s);
    seg1(90, 90, d1, %s);
    seg1(150, 90, d2, %s);
    seg1(230, 90, d3, %s);
    seg1(290, 90, d4, %s);
    seg1(350, 90, d5, %s);
    int i = 0;
    while (i < 6) {
        rect(24 + i * 60, 160, 52, 6, %s);
        i = i + 1;
    }
    text(16, 185, "anote os 6 digitos antes de gerar de novo", %s);
}
""" % (p["title"], p["base"], p["base"], p["base"], p["base"], p["base"], p["base"], p["freq"], p["bg"], p["fg"], p["dig"], p["dig"], p["dig"], p["dig"], p["dig"], p["dig"], p["on"], p["fg2"]), w, h


def t_metrono(p):
    w, h = 380, 260
    body = HDR % (p["name"], "UTIL") + COMMON_GLOBALS + """
int bpm;
int t0;
int ligado;
int batida;

void init() {
    seg_init();
    title("%s");
    bpm = %d;
    t0 = uptime();
}

void mouse(int x, int y, int b, int pr) {
    if (pr != 1) { return; }
    if (y > win_h - 70) {
        if (x > win_w - 90) { ligado = 1 - ligado; }
        else if (x > win_w / 2) { bpm = bpm + %d; }
        else { bpm = bpm - %d; }
        if (bpm < 30) { bpm = 30; }
        if (bpm > 300) { bpm = 300; }
        invalidate();
    }
}

void tick() {
    if (ligado == 0) { return; }
    int intervalo = 60000 / bpm;
    int agora = uptime();
    if (agora - t0 >= intervalo) {
        t0 = agora;
        batida = 1 - batida;
        beep(%d, 40);
        invalidate();
    }
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(16, 12, "METRONOMO", %s);
    segnum(120, 70, bpm, 3, %s, 0);
    text(200, 92, "BPM", %s);
    rect(20, win_h - 60, 120, 44, %s);
    text(48, win_h - 46, "MENOS", %s);
    rect(150, win_h - 60, 120, 44, %s);
    text(178, win_h - 46, "MAIS", %s);
    rect(win_w - 90, win_h - 60, 70, 44, %s);
    if (ligado == 1) { text(win_w - 82, win_h - 46, "PAUSA", %s); }
    else { text(win_w - 82, win_h - 46, "TOCA", %s); }
    // pendulo
    int a = 0;
    if (ligado == 1) { a = (batida * 2 - 1) * 10; }
    int px = win_w / 2 + coss[(a + 16) & 31] * 90 / 4096;
    int py = 60 - coss[(a + 16) & 31] * 10 / 4096;
    line(win_w / 2, 40, px, 150, %s);
    rect(px - 6, 150, 12, 12, %s);
}
"""
    body = body % (p["title"], p["bpm"], p["step"], p["step"], p["freq"], p["bg"], p["fg"], p["dig"], p["fg"], p["btn"], p["fg"], p["btn"], p["fg"], p["btn"], p["fg"], p["fg"], p["fg"], p["on"])
    body += "int sins[32];\nint coss[32];\n"
    body += "void fillsin() {\n" + emit_fill("sins", sin_table()) + "\n" + emit_fill("coss", [round(math.cos(2*math.pi*i/32)*4096) for i in range(32)]) + "\n}\n"
    body = body.replace("void init() {\n    seg_init();", "void init() {\n    seg_init();\n    fillsin();")
    return body, w, h


def t_binrel(p):
    w, h = 400, 240
    return HDR % (p["name"], "UTIL") + COMMON_GLOBALS + """
void init() {
    seg_init();
    title("%s");
}

void tick() {
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(16, 12, "RELOGIO BINARIO — hh:mm:ss", %s);
    int u = uptime() / 1000;
        vals[0] = (u / 3600) %% 10;
    vals[1] = (u / 3600 / 10) %% 10;
    vals[2] = (u / 60) %% 10;
    vals[3] = (u / 60 / 10) %% 10;
    vals[4] = u %% 10;
    vals[5] = (u / 10) %% 10;
    int c = 0;
    while (c < 6) {
        int b = 0;
        while (b < 4) {
            int on = (vals[c] >> b) & 1;
            int x = 40 + c * 54;
            int y = 150 - b * 26;
            if (on == 1) { rect(x, y, 34, 20, %s); }
            else { rect(x, y, 34, 20, %s); }
            b = b + 1;
        }
        c = c + 1;
    }
    text(40, 190, "8 4 2 1 por coluna (h h m m s s)", %s);
}
""" % (p["title"], p["bg"], p["fg"], p["on"], p["off"], p["fg2"]), w, h


def t_upmon(p):
    w, h = 400, 260
    return HDR % (p["name"], "UTIL") + COMMON_GLOBALS + """
void init() {
    seg_init();
    title("%s");
}

void tick() {
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(16, 12, "UPTIME DO SISTEMA", %s);
    int u = uptime();
    segnum(40, 70, u / 3600000, 2, %s, 0);
    text(100, 92, "h", %s);
    segnum(130, 70, (u / 60000) %% 60, 2, %s, 0);
    text(190, 92, "m", %s);
    segnum(220, 70, (u / 1000) %% 60, 2, %s, 0);
    text(280, 92, "s", %s);
    // barra de minuto
    int f = (u / 1000) %% 60;
    rect(30, 160, (win_w - 60) * f / 60, 22, %s);
    rect(30, 160, win_w - 60, 22, %s);
    // pulsos
    int i = 0;
    while (i < 20) {
        int on = ((u / 250) >> i) & 1;
        if (on == 1) { rect(30 + i * 17, 210, 12, 12, %s); }
        else { rect(30 + i * 17, 210, 12, 12, %s); }
        i = i + 1;
    }
}
""" % (p["title"], p["bg"], p["fg"], p["dig"], p["fg"], p["dig"], p["fg"], p["dig"], p["fg"], p["on"], p["off"], p["on"], p["off"]), w, h


def t_ascii(p):
    w, h = 460, 340
    rows = p["rows"]
    lines = []
    for r in rows:
        lines.append('    text(16, %d, "%s", %s);' % (30 + rows.index(r) * 16, r, "COL"))
    return HDR % (p["name"], "UTIL") + COMMON_GLOBALS + """
void init() {
    seg_init();
    title("%s");
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    int COL = %s;
    text(16, 10, "TABELA ASCII (parte)", %s);
%s
    // cursor piscando sobre a linha do meio
    if ((uptime() / 500) %% 2 == 0) {
        rect(16, 30 + %d * 16 - 2, win_w - 32, 14, %s);
    }
}
""" % (p["title"], p["bg"], p["hl"], p["fg"], "\n".join(lines), p["hlrow"], p["on"]), w, h


# ================================================================== MATH ====

def t_primos(p):
    w, h = 420, 300
    return HDR % (p["name"], "MATH") + COMMON_GLOBALS + """
int n;
int ultimo;
int cnt;

void init() {
    seg_init();
    title("%s");
    n = %d;
    calcula();
}

void calcula() {
    cnt = 0;
    ultimo = 2;
    int c = 2;
    while (c <= n) {
        int primo = 1;
        int d = 2;
        while (d * d <= c) {
            if (c %% d == 0) { primo = 0; break; }
            d = d + 1;
        }
        if (primo == 1) { cnt = cnt + 1; ultimo = c; }
        c = c + 1;
    }
}

void key(int k) {
    if (k == 97) { n = n + %d; calcula(); invalidate(); }
    if (k == 100) { n = n - %d; if (n < 2) { n = 2; } calcula(); invalidate(); }
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(16, 12, "PRIMOS ATE N — teclas A/D mudam N", %s);
    segnum(60, 60, n, 5, %s, 0);
    text(200, 82, "N", %s);
    text(16, 120, "quantos:", %s);
    segnum(130, 112, cnt, 5, %s, 0);
    text(16, 160, "maior:", %s);
    segnum(100, 152, ultimo, 5, %s, 0);
    // densidade: pontos
    int i = 0;
    while (i < cnt) {
        int x = (i * %d) / 4096;
        int y = 220 + ((i * 2654435761) %% 40) / 4;
        rect(20 + (x %%% d), y, 3, 3, %s);
        i = i + 1;
    }
    rect(16, 210, win_w - 32, 60, %s);
}
""" % (p["title"], p["n"], p["step"], p["step"], p["bg"], p["fg"], p["dig"], p["fg"], p["fg"], p["dig"], p["fg"], p["dig"], p["span"], p["cols"], p["on"], p["off"]), w, h


def t_fibo(p):
    w, h = 420, 280
    return HDR % (p["name"], "MATH") + COMMON_GLOBALS + """
int k;
int a; int b;

void init() {
    seg_init();
    title("%s");
    a = 0; b = 1; k = 1;
}

void mouse(int x, int y, int b, int pr) {
    if (pr != 1) { return; }
    avanca();
    invalidate();
}

void key(int kk) {
    if (kk == 97) { avanca(); invalidate(); }
    if (kk == 100) { a = 0; b = 1; k = 1; invalidate(); }
}

void avanca() {
    int t = a + b;
    a = b;
    b = t;
    k = k + 1;
    if (b < 0) { a = 0; b = 1; k = 1; }
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(16, 12, "FIBONACCI — clique/tecla A avanca, D reinicia", %s);
    text(16, 50, "termo:", %s);
    segnum(120, 42, k, 2, %s, 0);
    text(16, 100, "valor:", %s);
    segnum(110, 92, a, 8, %s, 0);
    // proporcao aurea aproximada em 1/1000
    int razao = 0;
    if (a != 0) { razao = (b * 1000) / a; }
    text(16, 160, "razao b/a (x1000):", %s);
    segnum(220, 152, razao, 4, %s, 0);
    text(16, 200, "1618 = numero de ouro", %s);
    // espiral de quadrados
    int x0 = 260;
    int y0 = 60;
    int lado = 4;
    int f0 = 0; int f1 = 1;
    int i = 0;
    while (i < 9) {
        rect(x0, y0, lado, lado, %s);
        int t = f0 + f1;
        f0 = f1; f1 = t;
        if (i %% 4 == 0) { x0 = x0 + lado; }
        if (i %% 4 == 1) { y0 = y0 + lado; lado = f0 / 2 + 1; }
        if (i %% 4 == 2) { x0 = x0 - lado; }
        if (i %% 4 == 3) { y0 = y0 - lado; lado = f0 / 2 + 1; }
        i = i + 1;
    }
}
""" % (p["title"], p["bg"], p["fg"], p["fg"], p["dig"], p["fg"], p["dig"], p["fg"], p["dig"], p["fg2"], p["on"]), w, h


def t_collatz(p):
    w, h = 420, 300
    return HDR % (p["name"], "MATH") + COMMON_GLOBALS + """
int v;
int passo;
int maxv;
int semente;

void init() {
    seg_init();
    title("%s");
    semente = uptime() | 1;
    v = %d;
    passo = 0;
    maxv = v;
}

int rnd(int m) {
    semente = semente * 1664525 + 1013904223;
    if (semente < 0) { semente = 0 - semente; }
    return (semente / 65536) %% m;
}

void mouse(int x, int y, int b, int pr) {
    if (pr != 1) { return; }
    v = %d + rnd(%d);
    passo = 0;
    maxv = v;
    invalidate();
}

void tick() {
    if (v == 1) { return; }
    if (v %% 2 == 0) { v = v / 2; }
    else { v = v * 3 + 1; }
    if (v > maxv) { maxv = v; }
    passo = passo + 1;
    if (v > 2000000000) { v = 1; }
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(16, 12, "COLLATZ — clique sorteia novo valor", %s);
    text(16, 44, "valor:", %s);
    segnum(110, 36, v, 8, %s, 0);
    text(16, 90, "passos:", %s);
    segnum(120, 82, passo, 3, %s, 0);
    text(16, 136, "pico:", %s);
    segnum(90, 128, maxv, 8, %s, 0);
    text(16, 180, "a sequencia sempre chega a 1", %s);
    // linha do valor (log-ish)
    int lv = v;
    if (lv < 1) { lv = 1; }
    int expo = 0;
    while (lv > 1 && expo < 9) { lv = lv / 4; expo = expo + 1; }
    rect(20, 270 - expo * 22, win_w - 40, 8, %s);
}
""" % (p["title"], p["start"], p["base"], p["range"], p["bg"], p["fg"], p["fg"], p["dig"], p["fg"], p["dig"], p["fg"], p["dig"], p["fg2"], p["on"]), w, h


def t_pascal(p):
    w, h = 400, 320
    return HDR % (p["name"], "MATH") + COMMON_GLOBALS + """
int modn;

void init() {
    seg_init();
    title("%s");
    modn = %d;
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(16, 10, "TRIANGULO DE PASCAL MOD N", %s);
    int n = 0;
    while (n < %d) {
        // constroi a linha de tras pra frente
        int i = n;
        linha[n] = 1;
        while (i > 0) {
            linha[i] = linha[i] + linha[i - 1];
            i = i - 1;
        }
        int c = 0;
        while (c <= n) {
            int v = linha[c] %% modn;
            int cor = %s;
            if (v == 0) { cor = %s; }
            else if (v == 1) { cor = %s; }
            else if (v == 2) { cor = %s; }
            else if (v == 3) { cor = %s; }
            else if (v == 4) { cor = %s; }
            else { cor = %s; }
            rect(20 + c * 10 + (32 - n) * 5, 34 + n * 8, 8, 6, cor);
            c = c + 1;
        }
        n = n + 1;
    }
}
""" % (p["title"], p["modn"], p["bg"], p["fg"], p["rows"], p["c0"], p["c1"], p["c2"], p["c3"], p["c4"], p["c5"], p["c6"]), w, h


def t_mdc(p):
    w, h = 400, 280
    return HDR % (p["name"], "MATH") + COMMON_GLOBALS + """
int a; int b;
int passos;
int semente;

void init() {
    seg_init();
    title("%s");
    semente = uptime() | 1;
    a = %d;
    b = %d;
}

int rnd(int m) {
    semente = semente * 1664525 + 1013904223;
    if (semente < 0) { semente = 0 - semente; }
    return (semente / 65536) %% m;
}

void mouse(int x, int y, int bb, int pr) {
    if (pr != 1) { return; }
    a = 100 + rnd(%d);
    b = 100 + rnd(%d);
    passos = 0;
    invalidate();
}

void tick() {
    if (a == b) { return; }
    if (a > b) { a = a - b; } else { b = b - a; }
    passos = passos + 1;
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(16, 12, "ALGORITMO DE EUCLIDES (MDC)", %s);
    text(16, 46, "a:", %s);
    segnum(50, 38, a, 5, %s, 0);
    text(180, 46, "b:", %s);
    segnum(214, 38, b, 5, %s, 0);
    text(16, 100, "subtracoes:", %s);
    segnum(140, 92, passos, 3, %s, 0);
    text(16, 150, "mdc quando a == b", %s);
    // barras proporcionais
    int total = a + b;
    if (total > 0) {
        rect(20, 200, (win_w - 40) * a / total, 20, %s);
        rect(20 + (win_w - 40) * a / total, 200, (win_w - 40) * b / total, 20, %s);
    }
}
""" % (p["title"], p["a0"], p["b0"], p["range"], p["range"], p["bg"], p["fg"], p["fg"], p["dig"], p["fg"], p["dig"], p["fg"], p["dig"], p["fg2"], p["ca"], p["cb"]), w, h


def t_bhaskara(p):
    w, h = 420, 300
    eq = p["eq"]
    return HDR % (p["name"], "MATH") + COMMON_GLOBALS + """
int A; int B; int C;
int x1e; int x1d; int x2e; int x2d;
int tem;

void init() {
    seg_init();
    title("%s");
    A = %d; B = %d; C = %d;
}

void calcula() {
    // raizes por busca direta em inteiros (parabola classica)
    tem = 0;
    int x = -300;
    while (x <= 300) {
        int y = A * x * x + B * x + C;
        if (y == 0) {
            if (tem == 0) { x1e = x; tem = 1; }
            x2e = x;
            tem = 2;
        }
        x = x + 1;
    }
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(16, 12, "BHASKARA — %s", %s);
    text(16, 40, "coeficientes A B C fixos deste app", %s);
    calcula();
    // eixo
    line(16, 150, win_w - 16, 150, %s);
    line(210, 40, 210, 260, %s);
    // parabola
    int px = -40;
    while (px <= 40) {
        int y = A * px * px + B * px + C;
        int sy = 150 - y / %d;
        if (sy > 30 && sy < 280) {
            rect(210 + px * 4, sy, 3, 3, %s);
        }
        px = px + 1;
    }
    if (tem == 2) {
        text(16, 265, "raizes inteiras:", %s);
        segnum(160, 256, x1e, 4, %s, 0);
        segnum(250, 256, x2e, 4, %s, 0);
    } else {
        text(16, 265, "sem raiz inteira na janela", %s);
    }
}
""" % (p["title"], p["A"], p["B"], p["C"], p["bg"], eq, p["fg"], p["fg2"], p["axis"], p["axis"], p["scale"], p["curve"], p["fg"], p["dig"], p["dig"], p["fg2"]), w, h


def t_converte(p):
    w, h = 420, 280
    return HDR % (p["name"], "MATH") + COMMON_GLOBALS + """
int v;

void init() {
    seg_init();
    title("%s");
    v = %d;
}

void tick() {
    v = v + %d;
    if (v > %d) { v = 0; }
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(16, 12, "CONVERSOR DEC / HEX / BIN", %s);
    text(16, 44, "dec:", %s);
    segnum(90, 36, v, 5, %s, 0);
    text(16, 100, "hex:", %s);
    // 4 digitos hexa
    int i = 3;
    while (i >= 0) {
        int d = (v >> (i * 4)) & 15;
        seg1(90 + (3 - i) * 22, 92, d, %s);
        i = i - 1;
    }
    text(16, 160, "bin:", %s);
    int j = 15;
    while (j >= 0) {
        int on = (v >> j) & 1;
        if (on == 1) { rect(90 + (15 - j) * 12, 168, 8, 14, %s); }
        else { rect(90 + (15 - j) * 12, 168, 8, 14, %s); }
        j = j - 1;
    }
    text(16, 220, "cada app desta serie conta numa velocidade", %s);
}
""" % (p["title"], p["start"], p["step"], p["max"], p["bg"], p["fg"], p["fg"], p["dig"], p["fg"], p["dig"], p["fg"], p["on"], p["off"], p["fg2"]), w, h


def t_tabuada(p):
    w, h = 400, 320
    n = p["n"]
    lines = []
    for i in range(1, 11):
        lines.append('    text(24, %d, "%2d x %2d = %4d", COL);' % (50 + (i - 1) * 22, i, n, i * n))
    return HDR % (p["name"], "MATH") + COMMON_GLOBALS + """
void init() {
    seg_init();
    title("%s");
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    int COL = %s;
    text(24, 16, "TABUADA DO %d", %s);
%s
    // grade colorida n x 10
    int r = 0;
    while (r < %d) {
        int c = 0;
        while (c < 10) {
            int on = (r * c) %% 2;
            if (on == 1) { rect(240 + c * 12, 52 + r * 12, 10, 10, %s); }
            else { rect(240 + c * 12, 52 + r * 12, 10, 10, %s); }
            c = c + 1;
        }
        r = r + 1;
    }
}
""" % (p["title"], p["bg"], p["fg"], n, p["hl"], "\n".join(lines), n, p["on"], p["off"]), w, h


def t_juros(p):
    w, h = 420, 300
    return HDR % (p["name"], "MATH") + COMMON_GLOBALS + """
int t;

void init() {
    seg_init();
    title("%s");
}

void tick() {
    t = t + 1;
    if (t > %d) { t = 0; }
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(16, 12, "JUROS COMPOSTOS — %d%% por periodo", %s);
    int capital = %d;
    int i = 0;
    int v = capital;
    int maxv = capital;
    while (i < %d) {
        maxv = maxv + maxv * %d / 100;
        i = i + 1;
    }
    i = 0;
    v = capital;
    while (i <= t) {
        int h1 = (v - capital) * 180 / (maxv - capital + 1);
        rect(30 + i * 16, 240 - h1, 12, h1 + 2, %s);
        v = v + v * %d / 100;
        i = i + 1;
    }
    text(16, 262, "periodo:", %s);
    segnum(110, 254, t, 2, %s, 0);
    text(170, 262, "valor (x100):", %s);
    segnum(290, 254, v / 100, 4, %s, 0);
    line(20, 242, win_w - 20, 242, %s);
}
""" % (p["title"], p["periodos"], p["bg"], p["taxa"], p["fg"], p["capital"], p["periodos"], p["taxa"], p["bar"], p["taxa"], p["fg"], p["dig"], p["fg"], p["dig"], p["axis"]), w, h


def t_termos(p):
    w, h = 400, 260
    return HDR % (p["name"], "MATH") + COMMON_GLOBALS + """
int t;

void init() {
    seg_init();
    title("%s");
}

void tick() {
    t = t + 1;
    if (t > 120) { t = -40; }
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(16, 12, "ESCALA DE TEMPERATURA", %s);
    // termometro: -40 C a 120 C
    int y0 = 40;
    int y1 = 220;
    rect(60, y0, 26, y1 - y0, %s);
    int nivel = y1 - (t + 40) * (y1 - y0) / 160;
    rect(56, nivel, 34, y1 - nivel, %s);
    rect(50, y1 - 8, 46, 16, %s);
    // marcas
    int m = -40;
    while (m <= 120) {
        int my = y1 - (m + 40) * (y1 - y0) / 160;
        line(88, my, 96, my, %s);
        m = m + 20;
    }
    text(120, 60, "Celsius:", %s);
    segnum(210, 52, t, 3, %s, 0);
    text(120, 100, "Fahrenheit:", %s);
    segnum(240, 92, t * 9 / 5 + 32, 3, %s, 0);
    text(120, 140, "Kelvin:", %s);
    segnum(210, 132, t + 273, 3, %s, 0);
    // estado
    if (t <= 0) { text(120, 180, "CONGELANDO", %s); }
    else if (t >= 100) { text(120, 180, "FERVENDO", %s); }
    else { text(120, 180, "liquido", %s); }
}
""" % (p["title"], p["bg"], p["fg"], p["off"], p["mercury"], p["mercury"], p["fg"], p["fg"], p["dig"], p["fg"], p["dig"], p["fg"], p["dig"], p["cold"], p["hot"], p["fg2"]), w, h


def t_pitagoras(p):
    w, h = 420, 300
    return HDR % (p["name"], "MATH") + COMMON_GLOBALS + """
int achados;
int ua; int ub; int uc;

void init() {
    seg_init();
    title("%s");
    calcula();
}

void calcula() {
    achados = 0;
    int a = 1;
    while (a < %d) {
        int b = a;
        while (b < %d) {
            int c2 = a * a + b * b;
            int c = b;
            while (c * c < c2) { c = c + 1; }
            if (c * c == c2) {
                achados = achados + 1;
                ua = a; ub = b; uc = c;
            }
            b = b + 1;
        }
        a = a + 1;
    }
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(16, 12, "TERNOS PITAGORICOS", %s);
    text(16, 44, "achados:", %s);
    segnum(120, 36, achados, 3, %s, 0);
    text(16, 92, "ultimo: a b c", %s);
    segnum(120, 84, ua, 2, %s, 0);
    segnum(180, 84, ub, 2, %s, 0);
    segnum(240, 84, uc, 2, %s, 0);
    // triangulo
    int ox = 80;
    int oy = 250;
    int s = 4;
    line(ox, oy, ox + ua * s, oy, %s);
    line(ox, oy, ox, oy - ub * s, %s);
    line(ox, oy - ub * s, ox + ua * s, oy, %s);
    rect(ox - 3, oy + 3, 6, 6, %s);
}
""" % (p["title"], p["lim"], p["lim"], p["bg"], p["fg"], p["fg"], p["dig"], p["fg"], p["dig"], p["dig"], p["dig"], p["hyp"], p["cat"], p["hyp"], p["dot"]), w, h


# ================================================================= JOGOS ====

def t_adivinha(p):
    w, h = 420, 280
    return HDR % (p["name"], "JOGO") + COMMON_GLOBALS + """
int segredo;
int lo; int hi;
int chute;
int tentativas;
int fase;   // 0 chutando, 1 acertou
int semente;

void init() {
    seg_init();
    title("%s");
    semente = uptime() | 1;
    nova();
}

int rnd(int m) {
    semente = semente * 1664525 + 1013904223;
    if (semente < 0) { semente = 0 - semente; }
    return (semente / 65536) %% m;
}

void nova() {
    segredo = 1 + rnd(%d);
    lo = 1;
    hi = %d;
    chute = (lo + hi) / 2;
    tentativas = 0;
    fase = 0;
}

void tick() {
    if (fase == 1) { return; }
    tentativas = tentativas + 1;
    if (chute == segredo) {
        fase = 1;
        beep(%d, 80);
    } else if (chute < segredo) {
        lo = chute + 1;
    } else {
        hi = chute - 1;
    }
    chute = (lo + hi) / 2;
    if (lo > hi) { fase = 1; }
    invalidate();
}

void mouse(int x, int y, int b, int pr) {
    if (pr != 1) { return; }
    nova();
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(16, 12, "ADVINHADOR — busca binaria animada", %s);
    text(16, 44, "intervalo:", %s);
    segnum(130, 36, lo, 3, %s, 0);
    segnum(210, 36, hi, 3, %s, 0);
    text(16, 92, "chute:", %s);
    segnum(110, 84, chute, 3, %s, 0);
    text(16, 140, "tentativas:", %s);
    segnum(140, 132, tentativas, 2, %s, 0);
    // barra do intervalo
    rect(30, 190, win_w - 60, 18, %s);
    int bw = (win_w - 60) / %d;
    rect(30 + (lo - 1) * bw, 186, (hi - lo + 1) * bw, 26, %s);
    // agulha do chute
    int cx = 30 + (chute - 1) * bw + bw / 2;
    rect(cx - 2, 180, 4, 38, %s);
    if (fase == 1) {
        text(16, 236, "ACHEI! clique para novo numero", %s);
    }
}
""" % (p["title"], p["max"] - 1, p["max"], p["freq"], p["bg"], p["fg"], p["fg"], p["dig"], p["dig"], p["fg"], p["dig"], p["fg"], p["dig"], p["off"], p["max"], p["band"], p["needle"], p["win"]), w, h


def t_dados(p):
    w, h = 400, 280
    return HDR % (p["name"], "JOGO") + COMMON_GLOBALS + """
int ndados;
int val[8];
int rolando;
int t0;
int semente;
int total;

void init() {
    seg_init();
    title("%s");
    ndados = %d;
    semente = uptime() | 1;
}

int rnd(int m) {
    semente = semente * 1664525 + 1013904223;
    if (semente < 0) { semente = 0 - semente; }
    return (semente / 65536) %% m;
}

void mouse(int x, int y, int b, int pr) {
    if (pr != 1) { return; }
    rolando = 12;
    t0 = uptime();
    invalidate();
}

void tick() {
    if (rolando <= 0) { return; }
    rolando = rolando - 1;
    total = 0;
    int i = 0;
    while (i < ndados) {
        val[i] = 1 + rnd(%d);
        total = total + val[i];
        i = i + 1;
    }
    invalidate();
}

void pino(int x, int y, int c) {
    rect(x - 5, y - 5, 10, 10, c);
}

void face(int x, int y, int v) {
    rect(x, y, 56, 56, %s);
    rect(x + 2, y + 2, 52, 52, %s);
    int c = %s;
    if (v >= 1) { pino(x + 14, y + 14, c); }
    if (v >= 3) { pino(x + 28, y + 28, c); }
    if (v >= 5) { pino(x + 42, y + 14, c); pino(x + 14, y + 42, c); }
    if (v >= 2) { pino(x + 42, y + 42, c); }
    if (v >= 4) { pino(x + 28, y + 14, c); pino(x + 28, y + 42, c); }
    if (v >= 6) { pino(x + 14, y + 28, c); pino(x + 42, y + 28, c); }
    if (v >= 7) { pino(x + 28, y + 20, c); }
    if (v >= 8) { pino(x + 28, y + 36, c); }
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(16, 10, "DADOS — clique para rolar", %s);
    int i = 0;
    while (i < ndados) {
        int x = 20 + (i %% 4) * 90;
        int y = 40 + (i / 4) * 70;
        face(x, y, val[i]);
        i = i + 1;
    }
    text(16, 200, "total:", %s);
    segnum(110, 192, total, 2, %s, 0);
    if (rolando > 0) {
        text(200, 200, "rolando...", %s);
    }
}
""" % (p["title"], p["n"], p["faces"], p["bg2"], p["fg"], p["pips"], p["bg"], p["fg"], p["fg"], p["dig"], p["fg2"]), w, h


def t_reflexo(p):
    w, h = 400, 280
    return HDR % (p["name"], "JOGO") + COMMON_GLOBALS + """
int estado;   // 0 espera, 1 verde, 2 resultado, 3 apertado
int t0;
int melhor;
int semente;

void init() {
    seg_init();
    title("%s");
    semente = uptime() | 1;
}

int rnd(int m) {
    semente = semente * 1664525 + 1013904223;
    if (semente < 0) { semente = 0 - semente; }
    return (semente / 65536) %% m;
}

void mouse(int x, int y, int b, int pr) {
    if (pr != 1) { return; }
    if (estado == 0) {
        // apertou cedo demais
        estado = 3;
        invalidate();
    } else if (estado == 1) {
        int d = uptime() - t0;
        estado = 2;
        if (melhor == 0 || d < melhor) { melhor = d; }
        beep(%d, 40);
        invalidate();
    } else {
        estado = 0;
        invalidate();
    }
}

void tick() {
    if (estado == 0) {
        t0 = uptime() + %d + rnd(%d);
        estado = 1;
        invalidate();
    } else if (estado == 1) {
        if (uptime() >= t0) {
            // ficou verde agora
        }
    }
}

void paint() {
    if (estado == 1 && uptime() >= t0) {
        rect(0, 0, win_w, win_h, %s);
        text(90, 120, "CLIQUE!", %s);
    } else if (estado == 0) {
        rect(0, 0, win_w, win_h, %s);
        text(70, 120, "espere o verde...", %s);
    } else if (estado == 3) {
        rect(0, 0, win_w, win_h, %s);
        text(60, 120, "CEDO DEMAIS! clique p/ tentar", %s);
    } else {
        rect(0, 0, win_w, win_h, %s);
        text(60, 60, "seu tempo (ms):", %s);
        segnum(200, 100, uptime() - t0, 3, %s, 0);
        text(60, 170, "melhor:", %s);
        segnum(180, 210, melhor, 3, %s, 0);
        text(60, 250, "clique para reiniciar", %s);
    }
}
""" % (p["title"], p["freq"], p["espera"], p["janela"], p["green"], p["gfg"], p["red"], p["rfg"], p["amber"], p["afg"], p["blue"], p["bfg"], p["dig"], p["bfg"], p["dig"], p["bfg"]), w, h


def t_velha(p):
    w, h = 360, 400
    return HDR % (p["name"], "JOGO") + COMMON_GLOBALS + """
int tab[9];
int vez;      // 1 humano, 2 cpu
int pl; int cp;
int fim;
int semente;

void init() {
    seg_init();
    title("%s");
    semente = uptime() | 1;
}

int rnd(int m) {
    semente = semente * 1664525 + 1013904223;
    if (semente < 0) { semente = 0 - semente; }
    return (semente / 65536) %% m;
}

void zera() {
    int i = 0;
    while (i < 9) { tab[i] = 0; i = i + 1; }
    vez = 1;
    fim = 0;
}

int vence(int q) {
    if (tab[0] == q && tab[1] == q && tab[2] == q) { return 1; }
    if (tab[3] == q && tab[4] == q && tab[5] == q) { return 1; }
    if (tab[6] == q && tab[7] == q && tab[8] == q) { return 1; }
    if (tab[0] == q && tab[3] == q && tab[6] == q) { return 1; }
    if (tab[1] == q && tab[4] == q && tab[7] == q) { return 1; }
    if (tab[2] == q && tab[5] == q && tab[8] == q) { return 1; }
    if (tab[0] == q && tab[4] == q && tab[8] == q) { return 1; }
    if (tab[2] == q && tab[4] == q && tab[6] == q) { return 1; }
    return 0;
}

void cpu_joga() {
    if (fim != 0) { return; }
    int i = 0;
    int livres = 0;
    while (i < 9) { if (tab[i] == 0) { livres = livres + 1; } i = i + 1; }
    if (livres == 0) { fim = 3; return; }
    int alvo = rnd(livres);
    i = 0;
    int n = 0;
    while (i < 9) {
        if (tab[i] == 0) {
            if (n == alvo) {
                tab[i] = 2;
                if (vence(2) == 1) { fim = 2; cp = cp + 1; }
                else { vez = 1; }
                return;
            }
            n = n + 1;
        }
        i = i + 1;
    }
}

void mouse(int x, int y, int b, int pr) {
    if (pr != 1) { return; }
    if (fim != 0) { zera(); invalidate(); return; }
    if (vez != 1) { return; }
    int c = (x - 30) / 100;
    int l = (y - 40) / 100;
    if (c < 0 || c > 2 || l < 0 || l > 2) { return; }
    int idx = l * 3 + c;
    if (tab[idx] != 0) { return; }
    tab[idx] = 1;
    if (vence(1) == 1) { fim = 1; pl = pl + 1; beep(%d, 60); }
    else { vez = 2; cpu_joga(); if (fim == 0 && vence(2) == 0) { } }
    invalidate();
}

void marca(int x, int y, int q) {
    if (q == 1) {
        line(x + 22, y + 22, x + 78, y + 78, %s);
        line(x + 78, y + 22, x + 22, y + 78, %s);
    } else if (q == 2) {
        rect(x + 50 - 28, y + 50 - 28, 56, 56, %s);
        rect(x + 50 - 16, y + 50 - 16, 32, 32, %s);
    }
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(16, 10, "JOGO DA VELHA — voce e o X", %s);
    // grade
    line(30, 140, 330, 140, %s);
    line(30, 240, 330, 240, %s);
    line(130, 40, 130, 340, %s);
    line(230, 40, 230, 340, %s);
    int i = 0;
    while (i < 9) {
        marca(30 + (i %% 3) * 100, 40 + (i / 3) * 100, tab[i]);
        i = i + 1;
    }
    text(16, 356, "voce:", %s);
    segnum(70, 348, pl, 2, %s, 0);
    text(130, 356, "cpu:", %s);
    segnum(180, 348, cp, 2, %s, 0);
    if (fim == 1) { text(220, 356, "VOCE GANHOU!", %s); }
    if (fim == 2) { text(220, 356, "CPU GANHOU", %s); }
    if (fim == 3) { text(220, 356, "EMPATE — clique reinicia", %s); }
}
""" % (p["title"], p["freq"], p["x1"], p["x2"], p["o1"], p["o2"], p["bg"], p["fg"], p["grid"], p["grid"], p["grid"], p["grid"], p["fg"], p["dig"], p["fg"], p["dig"], p["win"], p["lose"], p["tie"]), w, h


def t_cobra(p):
    w, h = 400, 360
    return HDR % (p["name"], "JOGO") + COMMON_GLOBALS + """
int cx[200];
int cy[200];
int tam;
int dx; int dy;
int fx; int fy;
int pontos;
int vivo;
int t0;
int semente;
int passo;

void init() {
    seg_init();
    title("%s");
    semente = uptime() | 1;
    reinicia();
}

void reinicia() {
    tam = 4;
    int i = 0;
    while (i < 200) {
        cx[i] = 10 - i;
        cy[i] = 8;
        i = i + 1;
    }
    dx = 1; dy = 0;
    fx = 25; fy = 8;
    pontos = 0;
    vivo = 1;
    passo = 0;
    t0 = uptime();
}

int rnd(int m) {
    semente = semente * 1664525 + 1013904223;
    if (semente < 0) { semente = 0 - semente; }
    return (semente / 65536) %% m;
}

void key(int k) {
    if (k == 119 || k == 87) { if (dy == 0) { dx = 0; dy = -1; } }
    if (k == 115 || k == 83) { if (dy == 0) { dx = 0; dy = 1; } }
    if (k == 97 || k == 65) { if (dx == 0) { dx = -1; dy = 0; } }
    if (k == 100 || k == 68) { if (dx == 0) { dx = 1; dy = 0; } }
    if (k == 114) { reinicia(); invalidate(); }
}

void tick() {
    if (vivo == 0) { return; }
    passo = passo + 1;
    if (passo < %d) { return; }
    passo = 0;
    // anda
    int i = tam - 1;
    while (i > 0) {
        cx[i] = cx[i - 1];
        cy[i] = cy[i - 1];
        i = i - 1;
    }
    cx[0] = cx[0] + dx;
    cy[0] = cy[0] + dy;
    // colisoes
    if (cx[0] < 0 || cy[0] < 0 || cx[0] >= 40 || cy[0] >= 27) { vivo = 0; beep(%d, 120); }
    i = 1;
    while (i < tam) {
        if (cx[i] == cx[0] && cy[i] == cy[0]) { vivo = 0; }
        i = i + 1;
    }
    // comida
    if (cx[0] == fx && cy[0] == fy) {
        if (tam < 199) { tam = tam + 1; }
        pontos = pontos + 1;
        beep(%d, 30);
        fx = 1 + rnd(38);
        fy = 1 + rnd(25);
    }
    invalidate();
}

void mouse(int x, int y, int b, int pr) {
    if (pr == 1 && vivo == 0) { reinicia(); invalidate(); }
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(10, 8, "COBRA — WASD move, R reinicia", %s);
    // comida
    rect(20 + fx * 9, 34 + fy * 9, 8, 8, %s);
    // cobra
    int i = 0;
    while (i < tam) {
        int c = %s;
        if (i == 0) { c = %s; }
        rect(20 + cx[i] * 9, 34 + cy[i] * 9, 8, 8, c);
        i = i + 1;
    }
    text(10, 300, "pontos:", %s);
    segnum(80, 292, pontos, 3, %s, 0);
    if (vivo == 0) {
        text(150, 300, "MORREU — clique reinicia", %s);
    }
}
""" % (p["title"], p["vel"], p["freqd"], p["freq"], p["bg"], p["fg"], p["food"], p["body"], p["head"], p["fg"], p["dig"], p["fg2"]), w, h


def t_pong(p):
    w, h = 420, 320
    return HDR % (p["name"], "JOGO") + COMMON_GLOBALS + """
int py1; int py2;
int bx; int by;
int vx; int vy;
int s1; int s2;
int t0;
int passo;

void init() {
    seg_init();
    title("%s");
    py1 = 120; py2 = 120;
    bx = 200; by = 150;
    vx = %d; vy = %d;
    s1 = 0; s2 = 0;
    t0 = uptime();
}

void key(int k) {
    if (k == 119 || k == 87) { py1 = py1 - %d; }
    if (k == 115 || k == 83) { py1 = py1 + %d; }
    if (py1 < 30) { py1 = 30; }
    if (py1 > 250) { py1 = 250; }
    invalidate();
}

void tick() {
    passo = passo + 1;
    if (passo < %d) { return; }
    passo = 0;
    bx = bx + vx;
    by = by + vy;
    if (by < 34) { by = 34; vy = -vy; }
    if (by > 290) { by = 290; vy = -vy; }
    if (bx < 30 && by > py1 && by < py1 + 60) { bx = 30; vx = -vx; beep(%d, 15); }
    if (bx > 380 && by > py2 && by < py2 + 60) { bx = 380; vx = -vx; }
    if (bx < 10) { s2 = s2 + 1; bx = 200; by = 150; vx = %d; }
    if (bx > 400) { s1 = s1 + 1; bx = 200; by = 150; vx = -%d; beep(%d, 40); }
    // cpu segue
    if (py2 + 30 > by) { py2 = py2 - %d; }
    if (py2 + 30 < by) { py2 = py2 + %d; }
    if (py2 < 30) { py2 = 30; }
    if (py2 > 250) { py2 = 250; }
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(10, 8, "PONG — W/S move a raquete esquerda", %s);
    line(210, 30, 210, 300, %s);
    rect(20, py1, 8, 60, %s);
    rect(392, py2, 8, 60, %s);
    rect(bx - 5, by - 5, 10, 10, %s);
    segnum(150, 12, s1, 2, %s, 0);
    segnum(250, 12, s2, 2, %s, 0);
}
""" % (p["title"], p["vx"], p["vy"], p["rp"], p["rp"], p["vel"], p["freq"], p["vx"], p["vx"], p["freq"], p["cpu"], p["cpu"], p["bg"], p["fg"], p["net"], p["p1"], p["p2"], p["ball"], p["dig"], p["dig"]), w, h


def t_memoria(p):
    w, h = 400, 380
    return HDR % (p["name"], "JOGO") + COMMON_GLOBALS + """
int cartas[16];
int estado[16];  // 0 fechada, 1 aberta, 2 feita
int sel1; int sel2;
int achadas;
int cliques;
int semente;
int t0;

void init() {
    seg_init();
    title("%s");
    semente = uptime() | 1;
    distribui();
}

void distribui() {
    int i = 0;
    while (i < 16) { cartas[i] = 0; estado[i] = 0; i = i + 1; }
    int par = 0;
    while (par < 8) {
        int colocados = 0;
        while (colocados < 2) {
            int pos = rnd(16);
            if (cartas[pos] == 0) {
                cartas[pos] = par + 1;
                colocados = colocados + 1;
            }
        }
        par = par + 1;
    }
    sel1 = -1; sel2 = -1;
    achadas = 0;
    cliques = 0;
}

int rnd(int m) {
    semente = semente * 1664525 + 1013904223;
    if (semente < 0) { semente = 0 - semente; }
    return (semente / 65536) %% m;
}

void mouse(int x, int y, int b, int pr) {
    if (pr != 1) { return; }
    if (achadas >= 8) { distribui(); invalidate(); return; }
    if (sel2 >= 0) { return; }
    int c = (x - 20) / 90;
    int l = (y - 40) / 90;
    if (c < 0 || c > 3 || l < 0 || l > 3) { return; }
    int idx = l * 4 + c;
    if (estado[idx] != 0) { return; }
    cliques = cliques + 1;
    if (sel1 < 0) { sel1 = idx; estado[idx] = 1; }
    else { sel2 = idx; estado[idx] = 1; t0 = uptime(); }
    invalidate();
}

void tick() {
    if (sel2 >= 0) {
        if (uptime() - t0 > 700) {
            if (cartas[sel1] == cartas[sel2]) {
                estado[sel1] = 2;
                estado[sel2] = 2;
                achadas = achadas + 1;
                if (achadas >= 8) { beep(%d, 90); }
            } else {
                estado[sel1] = 0;
                estado[sel2] = 0;
            }
            sel1 = -1;
            sel2 = -1;
            invalidate();
        }
    }
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(12, 10, "MEMORIA — ache os 8 pares", %s);
    int i = 0;
    while (i < 16) {
        int x = 20 + (i %% 4) * 90;
        int y = 40 + (i / 4) * 80;
        if (estado[i] == 0) {
            rect(x, y, 80, 70, %s);
            rect(x + 8, y + 8, 64, 54, %s);
        } else {
            rect(x, y, 80, 70, %s);
            // simbolo do par: pilulas coloridas
            int v = cartas[i];
            int j = 0;
            while (j < v) {
                rect(x + 12 + j * 9, y + 30, 7, 12, %s);
                j = j + 1;
            }
        }
        i = i + 1;
    }
    text(12, 356, "cliques:", %s);
    segnum(90, 348, cliques, 3, %s, 0);
    text(170, 356, "pares:", %s);
    segnum(240, 348, achadas, 2, %s, 0);
    if (achadas >= 8) { text(290, 356, "FIM!", %s); }
}
""" % (p["title"], p["freq"], p["bg"], p["fg"], p["back"], p["back2"], p["open"], p["sym"], p["fg"], p["dig"], p["fg"], p["dig"], p["win"]), w, h


def t_jokenpo(p):
    w, h = 400, 300
    return HDR % (p["name"], "JOGO") + COMMON_GLOBALS + """
int meu;   // 1 pedra 2 papel 3 tesoura
int dele;
int res;   // 0 nada, 1 empate, 2 ganhei, 3 perdi
int v; int e; int d;
int semente;

void init() {
    seg_init();
    title("%s");
    semente = uptime() | 1;
}

int rnd(int m) {
    semente = semente * 1664525 + 1013904223;
    if (semente < 0) { semente = 0 - semente; }
    return (semente / 65536) %% m;
}

void joga(int m) {
    meu = m;
    dele = 1 + rnd(3);
    res = 1;
    if (meu == dele) { res = 1; e = e + 1; }
    else if (meu == 1 && dele == 3) { res = 2; v = v + 1; }
    else if (meu == 2 && dele == 1) { res = 2; v = v + 1; }
    else if (meu == 3 && dele == 2) { res = 2; v = v + 1; }
    else { res = 3; d = d + 1; }
    if (res == 2) { beep(%d, 50); }
    invalidate();
}

void mouse(int x, int y, int b, int pr) {
    if (pr != 1) { return; }
    if (y > 210) {
        if (x > 20 && x < 120) { joga(1); }
        if (x > 150 && x < 250) { joga(2); }
        if (x > 280 && x < 380) { joga(3); }
    }
}

void simbolo(int x, int y, int q, int cor) {
    if (q == 1) {
        rect(x, y, 60, 50, cor);
        rect(x + 8, y + 8, 44, 34, cor);
    } else if (q == 2) {
        rect(x, y, 55, 45, cor);
        rect(x + 12, y + 40, 31, 14, cor);
    } else {
        line(x + 10, y + 40, x + 30, y + 5, cor);
        line(x + 30, y + 5, x + 50, y + 40, cor);
        line(x + 18, y + 45, x + 42, y + 45, cor);
    }
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(12, 10, "PEDRA PAPEL TESOURA", %s);
    simbolo(30, 60, meu, %s);
    simbolo(280, 60, dele, %s);
    text(160, 80, "VS", %s);
    if (res == 1) { text(120, 140, "EMPATE", %s); }
    if (res == 2) { text(100, 140, "VOCE GANHOU", %s); }
    if (res == 3) { text(110, 140, "VOCE PERDEU", %s); }
    // botoes
    rect(20, 210, 100, 60, %s);
    text(30, 232, "PEDRA", %s);
    rect(150, 210, 100, 60, %s);
    text(160, 232, "PAPEL", %s);
    rect(280, 210, 100, 60, %s);
    text(280, 232, "TESOURA", %s);
    // placar
    segnum(40, 160, v, 2, %s, 0);
    text(90, 170, "v", %s);
    segnum(170, 160, e, 2, %s, 0);
    text(220, 170, "e", %s);
    segnum(300, 160, d, 2, %s, 0);
    text(350, 170, "d", %s);
}
""" % (p["title"], p["freq"], p["bg"], p["fg"], p["me"], p["cpu"], p["fg"], p["tie"], p["win"], p["lose"], p["btn"], p["fg"], p["btn"], p["fg"], p["btn"], p["fg"], p["dig"], p["fg"], p["dig"], p["fg"], p["dig"], p["fg"]), w, h


def t_forca(p):
    w, h = 420, 340
    word = p["word"].upper()
    hints = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8}
    # underline boxes
    dashes = []
    for i, ch in enumerate(word):
        if ch == " ":
            dashes.append("        rect(%d, 250, 40, 4, DASHC);" % (20 + i * 44))
        else:
            dashes.append("        rect(%d, 250, 40, 4, DASHC);" % (20 + i * 44))
    return HDR % (p["name"], "JOGO") + COMMON_GLOBALS + """
int letras[26];
int erradas;
int fim;

void init() {
    seg_init();
    title("%s");
}

void key(int k) {
    if (fim != 0) { return; }
    int c = k;
    if (c >= 65 && c <= 90) { c = c + 32; }
    if (c < 97 || c > 122) { return; }
    int idx = c - 97;
    if (letras[idx] != 0) { return; }
    letras[idx] = 1;
    int achou = 0;
%s
    if (achou == 0) {
        erradas = erradas + 1;
        beep(%d, 25);
        if (erradas >= 6) { fim = 2; }
    }
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    int DASHC = %s;
    text(12, 10, "FORCA — digite letras", %s);
    // forca
    line(40, 200, 40, 40, %s);
    line(40, 40, 140, 40, %s);
    line(140, 40, 140, 60, %s);
    if (erradas >= 1) { rect(128, 60, 24, 24, %s); }
    if (erradas >= 2) { line(140, 84, 140, 140, %s); }
    if (erradas >= 3) { line(140, 100, 110, 120, %s); }
    if (erradas >= 4) { line(140, 100, 170, 120, %s); }
    if (erradas >= 5) { line(140, 140, 115, 170, %s); }
    if (erradas >= 6) { line(140, 140, 165, 170, %s); }
    // palavra: "%s"
%s
    // teclado
    int i = 0;
    while (i < 26) {
        int usada = letras[i];
        int col = %s;
        if (usada != 0) { col = %s; }
        rect(20 + i * 14, 290, 12, 16, col);
        i = i + 1;
    }
    if (fim == 2) { text(160, 70, "PERDEU!", %s); }
}
""" % (p["title"],
       "\n".join("    if (k == %d || k == %d) { achou = 1; }" % (ord(ch) + 32, ord(ch)) if ch != " " else "" for ch in word),
       p["freq"], p["bg"], p["dash"], p["fg"], p["gallow"], p["gallow"], p["gallow"], p["body"], p["body"], p["arm"], p["arm"], p["leg"], p["leg"],
       word, "\n".join(dashes), p["keyoff"], p["keyon"], p["lose"]), w, h


def t_campo(p):
    w, h = 400, 400
    return HDR % (p["name"], "JOGO") + COMMON_GLOBALS + """
int minas[81];
int abertas[81];
int vivas;
int abriu;
int semente;
int bandeiras;

void init() {
    seg_init();
    title("%s");
    semente = uptime() | 1;
    gera();
}

int rnd(int m) {
    semente = semente * 1664525 + 1013904223;
    if (semente < 0) { semente = 0 - semente; }
    return (semente / 65536) %% m;
}

void gera() {
    int i = 0;
    while (i < 81) { minas[i] = 0; abertas[i] = 0; i = i + 1; }
    int m = 0;
    while (m < %d) {
        int pos = rnd(81);
        if (minas[pos] == 0) { minas[pos] = 1; m = m + 1; }
    }
    vivas = 1;
    abriu = 0;
    bandeiras = %d;
}

int vizinhas(int idx) {
    int l = idx / 9;
    int c = idx %% 9;
    int n = 0;
    int dl = -1;
    while (dl <= 1) {
        int dc = -1;
        while (dc <= 1) {
            int nl = l + dl;
            int nc = c + dc;
            if (nl >= 0 && nl < 9 && nc >= 0 && nc < 9) {
                if (minas[nl * 9 + nc] == 1) { n = n + 1; }
            }
            dc = dc + 1;
        }
        dl = dl + 1;
    }
    return n;
}

void mouse(int x, int y, int b, int pr) {
    if (pr != 1) { return; }
    if (vivas == 0) { gera(); invalidate(); return; }
    int c = (x - 20) / 40;
    int l = (y - 40) / 40;
    if (c < 0 || c > 8 || l < 0 || l > 8) { return; }
    int idx = l * 9 + c;
    if (abertas[idx] != 0) { return; }
    abertas[idx] = 1;
    abriu = abriu + 1;
    if (minas[idx] == 1) {
        vivas = 0;
        beep(%d, 150);
    } else if (abriu >= 81 - %d) {
        vivas = 0;
        beep(%d, 80);
    } else {
        beep(%d, 12);
    }
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(12, 10, "CAMPO MINADO — clique abre", %s);
    int i = 0;
    while (i < 81) {
        int x = 20 + (i %% 9) * 40;
        int y = 40 + (i / 9) * 40;
        if (abertas[i] == 0) {
            rect(x, y, 38, 38, %s);
            rect(x + 3, y + 3, 32, 32, %s);
        } else if (minas[i] == 1) {
            rect(x, y, 38, 38, %s);
            rect(x + 14, y + 14, 10, 10, %s);
        } else {
            int n = vizinhas(i);
            rect(x, y, 38, 38, %s);
            if (n > 0) {
                // n pontos
                int j = 0;
                while (j < n) {
                    rect(x + 6 + j * 6, y + 16, 4, 4, %s);
                    j = j + 1;
                }
            }
        }
        i = i + 1;
    }
    text(12, 375, "abertas:", %s);
    segnum(90, 367, abriu, 2, %s, 0);
    if (vivas == 0) { text(160, 375, "FIM — clique reinicia", %s); }
}
""" % (p["title"], p["nminas"], p["nminas"], p["freqb"], p["nminas"], p["freqw"], p["freqc"], p["bg"], p["fg"], p["closed"], p["closed2"], p["boomed"], p["mine"], p["open"], p["cnt"], p["fg"], p["dig"], p["fg2"]), w, h


def t_bolha(p):
    w, h = 420, 300
    return HDR % (p["name"], "JOGO") + COMMON_GLOBALS + """
int v[%d];
int i;
int j;
int trocas;
int semente;
int ordenado;

void init() {
    seg_init();
    title("%s");
    semente = uptime() | 1;
    embaralha();
}

void embaralha() {
    int k = 0;
    while (k < %d) {
        v[k] = 10 + rnd(160);
        k = k + 1;
    }
    i = 0;
    j = 0;
    trocas = 0;
    ordenado = 0;
}

int rnd(int m) {
    semente = semente * 1664525 + 1013904223;
    if (semente < 0) { semente = 0 - semente; }
    return (semente / 65536) %% m;
}

void mouse(int x, int y, int b, int pr) {
    if (pr == 1) { embaralha(); invalidate(); }
}

void tick() {
    if (ordenado == 1) { return; }
    if (j >= %d - 1 - i) {
        j = 0;
        i = i + 1;
        if (i >= %d - 1) { ordenado = 1; return; }
    }
    if (v[j] > v[j + 1]) {
        int t = v[j];
        v[j] = v[j + 1];
        v[j + 1] = t;
        trocas = trocas + 1;
    }
    j = j + 1;
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(12, 10, "BUBBLE SORT ANIMADO — clique embaralha", %s);
    int k = 0;
    while (k < %d) {
        int cor = %s;
        if (k == j && ordenado == 0) { cor = %s; }
        int bh = v[k];
        rect(16 + k * %d, 250 - bh, %d - 2, bh, cor);
        k = k + 1;
    }
    line(12, 252, win_w - 12, 252, %s);
    text(12, 262, "trocas:", %s);
    segnum(80, 270, trocas, 4, %s, 0);
    if (ordenado == 1) { text(160, 262, "ORDENADO!", %s); }
}
""" % (p["n"], p["title"], p["n"], p["n"], p["n"], p["bg"], p["fg"], p["n"], p["bar"], p["hlbar"], p["n"], 420 // p["n"], p["axis"], p["fg"], p["dig"], p["win"]), w, h


def t_vida(p):
    w, h = 400, 360
    return HDR % (p["name"], "JOGO") + COMMON_GLOBALS + """
int g[48];
int g2[48];
int ger;
int semente;
int dens;

void init() {
    seg_init();
    title("%s");
    semente = uptime() | 1;
    dens = %d;
    semeia();
}

int rnd(int m) {
    semente = semente * 1664525 + 1013904223;
    if (semente < 0) { semente = 0 - semente; }
    return (semente / 65536) %% m;
}

void semeia() {
    int y = 0;
    while (y < 36) {
        g[y] = 0;
        int x = 0;
        while (x < 32) {
            if (rnd(100) < dens) { g[y] = g[y] | (1 << x); }
            x = x + 1;
        }
        y = y + 1;
    }
    ger = 0;
}

int bit(int lin, int x) {
    if (lin < 0) { lin = lin + 36; }
    if (lin >= 36) { lin = lin - 36; }
    if (x < 0) { x = x + 32; }
    if (x >= 32) { x = x - 32; }
    return (g[lin] >> x) & 1;
}

void mouse(int x, int y, int b, int pr) {
    if (pr == 1) { semeia(); invalidate(); }
}

void tick() {
    int y = 0;
    while (y < 36) {
        g2[y] = 0;
        int x = 0;
        while (x < 32) {
            int n = bit(y - 1, x - 1) + bit(y - 1, x) + bit(y - 1, x + 1)
                  + bit(y, x - 1) + bit(y, x + 1)
                  + bit(y + 1, x - 1) + bit(y + 1, x) + bit(y + 1, x + 1);
            int viva = bit(y, x);
            int nova = 0;
            if (viva == 1 && (n == 2 || n == 3)) { nova = 1; }
            if (viva == 0 && n == 3) { nova = 1; }
            if (nova == 1) { g2[y] = g2[y] | (1 << x); }
            x = x + 1;
        }
        y = y + 1;
    }
    int y2 = 0;
    while (y2 < 36) { g[y2] = g2[y2]; y2 = y2 + 1; }
    ger = ger + 1;
    invalidate();
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(12, 8, "JOGO DA VIDA — clique semeia de novo", %s);
    int y = 0;
    while (y < 36) {
        int x = 0;
        while (x < 32) {
            if ((g[y] >> x) & 1 == 1) {
                rect(24 + x * 11, 30 + y * 9, 9, 7, %s);
            } else {
                rect(24 + x * 11, 30 + y * 9, 9, 7, %s);
            }
            x = x + 1;
        }
        y = y + 1;
    }
    text(12, 356, "geracao:", %s);
    segnum(100, 348, ger, 4, %s, 0);
}
""" % (p["title"], p["dens"], p["bg"], p["fg"], p["on"], p["off"], p["fg"], p["dig"]), w, h


def t_hanoi(p):
    w, h = 420, 340
    return HDR % (p["name"], "JOGO") + COMMON_GLOBALS + """
// torres: pino -> disco -> tamanho (0 = vazio)
int torre[24];
int ndiscos;
int movimentos;
int total;
int de; int para;
int fase;
int t0;

void init() {
    seg_init();
    title("%s");
    ndiscos = %d;
    total = 1;
    int i = 0;
    while (i < ndiscos) {
        torre[i] = ndiscos - i;
        torre[8 + i] = 0;
        torre[16 + i] = 0;
        i = i + 1;
    }
    movimentos = 0;
    fase = 0;
    t0 = uptime();
}

int topo(int p) {
    int i = 0;
    while (i < 8) {
        if (torre[p * 8 + i] == 0) { return i; }
        i = i + 1;
    }
    return 8;
}

void move(int d, int p) {
    // tira de d
    int td = topo(d) - 1;
    int disco = torre[d * 8 + td];
    torre[d * 8 + td] = 0;
    // poe em p
    int tp = topo(p);
    torre[p * 8 + tp] = disco;
    movimentos = movimentos + 1;
}

void tick() {
    if (fase == 1) { return; }
    if (uptime() - t0 < %d) { return; }
    t0 = uptime();
    // solucao iterativa padrao (torre de 3 pinos)
    int jogada = movimentos %% 3;
    if (ndiscos %% 2 == 0) {
        if (jogada == 0) { de = 0; para = 1; }
        if (jogada == 1) { de = 0; para = 2; }
        if (jogada == 2) { de = 1; para = 2; }
    } else {
        if (jogada == 0) { de = 0; para = 2; }
        if (jogada == 1) { de = 0; para = 1; }
        if (jogada == 2) { de = 1; para = 2; }
    }
    // valida e executa (troca se preciso)
    int vd = topo(de);
    int vp = topo(para);
    if (vd == 0) { return; }
    if (vp != 0 && torre[de * 8 + vd - 1] > torre[para * 8 + vp - 1]) {
        int t = de; de = para; para = t;
    }
    move(de, para);
    if (topo(2) == ndiscos) { fase = 1; beep(%d, 120); }
    invalidate();
}

void mouse(int x, int y, int b, int pr) {
    if (pr == 1 && fase == 1) { init(); invalidate(); }
}

void paint() {
    rect(0, 0, win_w, win_h, %s);
    text(12, 10, "TORRE DE HANOI — solucao automatica", %s);
    int p = 0;
    while (p < 3) {
        int bx = 60 + p * 130;
        line(bx, 40, bx, 280, %s);
        rect(bx - 55, 280, 110, 8, %s);
        int i = 0;
        while (i < 8) {
            int d = torre[p * 8 + i];
            if (d != 0) {
                int larg = 14 + d * 12;
                rect(bx - larg / 2, 272 - i * 18, larg, 14, %s);
                rect(bx - larg / 2 + 3, 272 - i * 18 + 3, larg - 6, 8, %s);
            }
            i = i + 1;
        }
        p = p + 1;
    }
    text(12, 306, "movimentos:", %s);
    segnum(120, 298, movimentos, 3, %s, 0);
    if (fase == 1) { text(200, 306, "RESOLVIDO! clique reinicia", %s); }
}
""" % (p["title"], p["n"], p["delay"], p["freq"], p["bg"], p["fg"], p["peg"], p["base"], p["d1"], p["d2"], p["fg"], p["dig"], p["win"]), w, h
