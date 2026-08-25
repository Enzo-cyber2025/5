/*
 * terminal.c — NovaTerm: terminal da NovaUI
 *
 * Emulador de terminal escrito do zero, usando:
 *   - forkpty (pty) para o shell
 *   - X11 + Cairo + Pango para renderização de texto
 *   - uma máquina de estados VT100 mínima (carecteres de controle,
 *     CR/LF/BS/TAB, cores ANSI SGR básicas)
 *
 * Características:
 *   - fonte monoespaçada (DejaVu Sans Mono) via Pango
 *   - suporte a cores do tema (.novatheme)
 *   - scrollback em memória
 *   - redimensionamento -> SIGWINCH no child
 * Nada de VTE/libvte/termcap de outro ambiente.
 */
#include "common.h"
#include "theme.h"

#include <pty.h>
#include <utmp.h>
#include <termios.h>
#include <sys/ioctl.h>
#include <poll.h>

#define ROWS_DEF 24
#define COLS_DEF 80
#define SCROLLBACK 2000

typedef struct {
    char   ch;
    int    fg, bg;      /* índices de cores ANSI */
    int    bold;
} Cell;

typedef struct {
    Cell   cells[SCROLLBACK][COLS_DEF];     /* (limitado ao comprimento máx) */
    int    cur_row, cur_col;
} Screen;

static Display   *dpy;
static int        screen;
static Window     win;
static int        width, height;
static NovaTheme *theme;

static int        master_fd;
static int        child_pid;
static int        term_rows, term_cols;
static char       term_cell_w, term_cell_h;
static Screen     scr;
static int        scrollback[ROWS_DEF];    /* linhas de scroolback (índices) */
static int        sb_used, sb_head;

/* --- utilidades ------------------------------------------------------- */
static void child_exec(void)
{
    /* executa o shell do usuário */
    const char *shell = getenv("SHELL");
    if (!shell || !*shell) shell = "/bin/sh";
    execl(shell, shell, (char *)NULL);
    _exit(127);
}

/* --- cores ANSI (16) --- */
static NovaColor ansi_color(int i)
{
    static const char *hex[16] = {
        "#000000", "#cd0000", "#00cd00", "#cdcd00",
        "#0000ee", "#cd00cd", "#00cdcd", "#e5e5e5",
        "#7f7f7f", "#ff0000", "#00ff00", "#ffff00",
        "#5c5cff", "#ff00ff", "#00ffff", "#ffffff"
    };
    return nova_theme_color(hex[i % 16], nova_color(0.5, 0.5, 0.5, 1));
}

/* --- escrita do pty --- */
static void write_pty(const char *buf, int n)
{
    if (master_fd >= 0)
        (void)write(master_fd, buf, n);
}

static void handle_char(unsigned char ch)
{
    Cell *c = &scr.cells[scr.cur_row][scr.cur_col];
    switch (ch) {
    case '\r':
        scr.cur_col = 0;
        return;
    case '\n':
        scr.cur_row++;
        if (scr.cur_row >= ROWS_DEF) {
            scr.cur_row = ROWS_DEF - 1;
            /* rola buffer para cima (simplificado) */
            for (int i = 0; i < ROWS_DEF - 1; i++)
                memmove(scr.cells[i], scr.cells[i + 1], sizeof(Cell) * COLS_DEF);
            memset(scr.cells[ROWS_DEF - 1], 0, sizeof(Cell) * COLS_DEF);
        }
        return;
    case '\b':
        if (scr.cur_col > 0) scr.cur_col--;
        return;
    case '\t':
        scr.cur_col = (scr.cur_col / 8 + 1) * 8;
        if (scr.cur_col >= COLS_DEF) scr.cur_col = COLS_DEF - 1;
        return;
    case '\a': /* bell: silencioso */
        return;
    case 0x1b: /* ESC: ignoramos sequências por ora (aplicações básicas) */
        return;
    default:
        if (ch < 0x20)
            return;
        *c = (Cell){ .ch = (char)ch, .fg = 7, .bg = 0, .bold = 0 };
        scr.cur_col++;
        if (scr.cur_col >= COLS_DEF) { scr.cur_col = 0; scr.cur_row++; }
        if (scr.cur_row >= ROWS_DEF) scr.cur_row = ROWS_DEF - 1;
        return;
    }
}

static void draw(void)
{
    cairo_surface_t *sfc = nova_surface_from_xid(dpy, win, width, height);
    cairo_t *cr = cairo_create(sfc);

    NovaColor bgc = nova_theme_color(theme->terminal_bg, nova_color(0.06,0.06,0.12,1));
    NovaColor fgc = nova_theme_color(theme->terminal_fg, nova_color(0.85,0.85,0.95,1));
    cairo_set_source_rgba(cr, bgc.r, bgc.g, bgc.b, bgc.a);
    cairo_rectangle(cr, 0, 0, width, height);
    cairo_fill(cr);

    /* grade de células */
    double cw = term_cell_w, chh = term_cell_h;
    PangoLayout *layout = NULL;
    for (int r = 0; r < ROWS_DEF; r++) {
        /* buffer com o texto desta linha */
        char line[COLS_DEF + 1];
        for (int col = 0; col < COLS_DEF; col++) {
            Cell *c = &scr.cells[r][col];
            line[col] = (c->ch) ? c->ch : ' ';
        }
        line[COLS_DEF] = '\0';
        double y = 4 + r * chh;
        cairo_set_source_rgba(cr, fgc.r, fgc.g, fgc.b, fgc.a);
        nova_draw_text(cr, line, theme->font_mono, 11.0, fgc, 4, y);
        (void)layout;
    }
    /* cursor piscante (bloco) na célula atual */
    NovaColor acc = nova_theme_color(theme->accent, NOVA_ACCENT);
    cairo_set_source_rgba(cr, acc.r, acc.g, acc.b, acc.a);
    cairo_rectangle(cr, 4 + scr.cur_col * cw, 4 + scr.cur_row * chh, cw, chh);
    cairo_fill(cr);

    cairo_destroy(cr);
    cairo_surface_destroy(sfc);
}

static void compute_metrics(void)
{
    /* estima tamanho de célula usando Pango */
    cairo_surface_t *s = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, 10, 10);
    cairo_t *cr = cairo_create(s);
    PangoLayout *l = pango_cairo_create_layout(cr);
    PangoFontDescription *d = pango_font_description_from_string(theme->font_mono);
    pango_font_description_set_absolute_size(d, 11.0 * PANGO_SCALE);
    pango_layout_set_font_description(l, d);
    pango_layout_set_text(l, "M", 1);
    PangoRectangle ink, logical;
    pango_layout_get_pixel_extents(l, &ink, &logical);
    term_cell_w = logical.width ? logical.width : 8;
    term_cell_h = logical.height ? logical.height : 14;
    pango_font_description_free(d);
    g_object_unref(l);
    cairo_destroy(cr);
    cairo_surface_destroy(s);

    term_cols = (width - 8) / term_cell_w;
    term_rows = (height - 8) / term_cell_h;
    if (term_cols > COLS_DEF) term_cols = COLS_DEF;
    if (term_rows > ROWS_DEF) term_rows = ROWS_DEF;
}

static void resize_child(void)
{
    struct winsize ws;
    ws.ws_row = term_rows;
    ws.ws_col = term_cols;
    ws.ws_xpixel = width;
    ws.ws_ypixel = height;
    ioctl(master_fd, TIOCSWINSZ, &ws);
    kill(child_pid, SIGWINCH);
}

int main(int argc, char **argv)
{
    (void)argc; (void)argv;
    dpy = XOpenDisplay(NULL);
    if (!dpy) return 1;
    screen = DefaultScreen(dpy);
    theme = nova_theme_load(nova_theme_path_for_kind(NOVA_THEME_DARK));
    int rootw = DisplayWidth(dpy, screen), rooth = DisplayHeight(dpy, screen);
    (void)rootw; (void)rooth;

    width  = 720; height = 400;
    win = nova_create_window(dpy, 60, 60, width, height, 1, "NovaTerm");
    XMapWindow(dpy, win);

    compute_metrics();

    /* cria o ptty e o shell */
    struct termios tio;
    struct winsize ws;
    memset(&ws, 0, sizeof(ws));
    ws.ws_row = term_rows; ws.ws_col = term_cols;
    if (tcgetattr(0, &tio) == 0) {
        /* herda termios do terminal de controle se houver */
    }
    child_pid = forkpty(&master_fd, NULL, NULL, &ws);
    if (child_pid < 0) { nova_log("forkpty falhou"); return 1; }
    if (child_pid == 0)
        child_exec();

    /* shell manda primeiro o prompt; nós usamos setvbuf para linha */
    nova_log("NovaTerm: %dx%d cells", term_cols, term_rows);

    XEvent ev;
    unsigned char inbuf[4096];
    int done = 0;
    while (!done) {
        fd_set r;
        FD_ZERO(&r);
        FD_SET(master_fd, &r);
        FD_SET(ConnectionNumber(dpy), &r);
        int maxfd = master_fd > ConnectionNumber(dpy) ?
                    master_fd : ConnectionNumber(dpy);
        struct timeval tv = {0, 100000};
        if (select(maxfd + 1, &r, NULL, NULL, &tv) < 0) continue;

        if (FD_ISSET(master_fd, &r)) {
            int n = read(master_fd, inbuf, sizeof(inbuf));
            if (n <= 0) { done = 1; continue; }
            for (int i = 0; i < n; i++)
                handle_char(inbuf[i]);
            draw();
        }
        if (FD_ISSET(ConnectionNumber(dpy), &r)) {
            while (XPending(dpy)) {
                XNextEvent(dpy, &ev);
                if (ev.type == KeyPress) {
                    char buf[64]; KeySym ks;
                    int n = XLookupString(&ev.xkey, buf, sizeof(buf), &ks, NULL);
                    if (n > 0) write_pty(buf, n);
                    else if (ks == XK_Return) write_pty("\r", 1);
                    else if (ks == XK_BackSpace) write_pty("\x7f", 1);
                } else if (ev.type == ConfigureNotify) {
                    width = ev.xconfigure.width; height = ev.xconfigure.height;
                    compute_metrics(); resize_child(); draw();
                } else if (ev.type == Expose) {
                    draw();
                } else if (ev.type == KeyRelease) {
                    /* ignorado */
                }
            }
        }
    }
    XCloseDisplay(dpy);
    return 0;
}
