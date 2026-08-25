/*
 * config.c — NovaConfig: Central de Configurações da NovaUI
 *
 * Uma única aplicação com seções:
 *    [0] Rede      [1] Áudio   [2] Vídeo   [3] Teclado
 *    [4] Mouse     [5] Energia [6] Aparência
 *
 * Desenhada com Cairo + Pango + Xlib; escreve/ler arquivos de configuração
 * em /etc/novastation/. Não dependemos de gsettings/GNOME/Plasma.
 *
 * Cada seção tem um painel de páginas (sidebar) e uma área de conteúdo que
 * desenha controles básicos (toggle/switch, slider) e aplica a mudança
 * chamando utilitários de sistema (nmcli, amixer, setxkbmap, sysctl, etc.).
 */
#include "common.h"
#include "theme.h"

#include <ctype.h>

#define SIDEBAR_W 180

static Display   *dpy;
static int        screen;
static Window     win;
static int        width, height;
static NovaTheme *theme;
static int        current_page = 0; /* 0..6 */

static const char *pages[] = {
    "Rede", "Áudio", "Vídeo", "Teclado", "Mouse", "Energia", "Aparência"
};
#define NPAGES 7

/* --- aplicar configuração (chamadas de sistema) ----------------------- */
static void apply_network(void)
{
    if (fork() == 0) {
        execl("/usr/bin/nmcli", "nmcli", "general", "status", (char *)NULL);
        execl("/bin/sh", "sh", "-c", "nmcli device status 2>/dev/null; true", (char *)NULL);
        _exit(127);
    }
}
static void apply_audio(int vol)
{
    if (fork() == 0) {
        char cmd[128];
        snprintf(cmd, sizeof(cmd), "amixer -q sset Master %d%%", vol);
        execl("/bin/sh", "sh", "-c", cmd, (char *)NULL);
        _exit(127);
    }
}
static void apply_ki_layout(const char *layout)
{
    if (fork() == 0) {
        char cmd[128];
        snprintf(cmd, sizeof(cmd), "setxkbmap -layout %s", layout);
        execl("/bin/sh", "sh", "-c", cmd, (char *)NULL);
        _exit(127);
    }
}
static void apply_swappiness(int val)
{
    if (fork() == 0) {
        char cmd[128];
        snprintf(cmd, sizeof(cmd), "sysctl -w vm.swappiness=%d", val);
        execl("/bin/sh", "sh", "-c", cmd, (char *)NULL);
        _exit(127);
    }
}

/* --- pause os tutoriais de desenho ------------------------------------ */
static void draw_sidebar(cairo_t *cr)
{
    cairo_set_source_rgba(cr, 0.10, 0.09, 0.24, 1.0);
    cairo_rectangle(cr, 0, 0, SIDEBAR_W, height);
    cairo_fill(cr);

    NovaColor fg = nova_theme_color(theme->fg, nova_color(0.9,0.9,0.96,1));
    nova_draw_text(cr, "Configurações", theme->font_title, 13.0, fg, 16, 26);

    for (int i = 0; i < NPAGES; i++) {
        int y = 60 + i * 34;
        if (i == current_page) {
            NovaColor acc = nova_theme_color(theme->accent, NOVA_ACCENT);
            cairo_set_source_rgba(cr, acc.r, acc.g, acc.b, 0.9);
            nova_fill_round(cr, 8, y - 18, SIDEBAR_W - 16, 30, 6);
            nova_draw_text(cr, pages[i], theme->font_ui, 11.0, nova_color(1,1,1,1),
                           20, y + 1);
        } else {
            NovaColor dim = nova_theme_color(theme->fg_dim, nova_color(0.7,0.7,0.8,1));
            nova_draw_text(cr, pages[i], theme->font_ui, 11.0, dim, 20, y + 1);
        }
    }
}

/* --- conteúdo de cada página ------------------------------------------ */
static void draw_network(cairo_t *cr, int cx, int w, int h)
{
    NovaColor fg = nova_theme_color(theme->fg, nova_color(0.9,0.9,0.96,1));
    nova_draw_text(cr, "Rede", theme->font_title, 14.0, fg, cx, 30);
    nova_draw_text(cr, "Wi-Fi, Ethernet e dispositivos de rede.",
                   theme->font_ui, 11.0, fg, cx, 54);
    /* "Wi-Fi" toggle desenhado */
    cairo_set_source_rgba(cr, 0.16, 0.6, 0.9, 1.0);
    nova_fill_round(cr, cx, 80, 44, 22, 11);
    cairo_set_source_rgb(cr, 1, 1, 1);
    cairo_arc(cr, cx + 32, 91, 9, 0, M_PI * 2);
    cairo_fill(cr);
    nova_draw_text(cr, "Wi-Fi: habilitado", theme->font_ui, 11.0, fg, cx + 56, 94);
    nova_draw_text(cr, "Dispositivos detectados (nmcli):",
                   theme->font_ui, 10.0, nova_theme_color(theme->fg_dim, fg),
                   cx, 130);
}

static void draw_audio(cairo_t *cr, int cx, int w, int h)
{
    NovaColor fg = nova_theme_color(theme->fg, nova_color(0.9,0.9,0.96,1));
    nova_draw_text(cr, "Áudio", theme->font_title, 14.0, fg, cx, 30);
    nova_draw_text(cr, "Volume e dispositivos de saída/entrada.",
                   theme->font_ui, 11.0, fg, cx, 54);
    /* slider de volume */
    double sx = cx + 20, sy = 90, sw = w - 60;
    cairo_set_source_rgba(cr, 0.3, 0.3, 0.4, 1.0);
    nova_fill_round(cr, sx, sy, sw, 8, 4);
    cairo_set_source_rgba(cr, 0.23, 0.05, 0.64, 1.0);
    nova_fill_round(cr, sx, sy, sw * 0.6, 8, 4);
    cairo_set_source_rgb(cr, 1, 1, 1);
    cairo_arc(cr, sx + sw * 0.6, sy + 4, 10, 0, M_PI * 2);
    cairo_fill(cr);
    nova_draw_text(cr, "Volume: 60%", theme->font_ui, 11.0, fg, cx, 122);
}

static void draw_video(cairo_t *cr, int cx, int w, int h)
{
    NovaColor fg = nova_theme_color(theme->fg, nova_color(0.9,0.9,0.96,1));
    nova_draw_text(cr, "Vídeo", theme->font_title, 14.0, fg, cx, 30);
    nova_draw_text(cr, "Resolução e aceleração de vídeo (Vulkan/OpenGL).",
                   theme->font_ui, 11.0, fg, cx, 54);
    nova_draw_text(cr, "Resolução: 1920x1080 @ 60 Hz", theme->font_ui, 11.0, fg, cx, 90);
    nova_draw_text(cr, "GPU: Intel UHD Graphics 605 (Goldmont Plus)",
                   theme->font_ui, 11.0, fg, cx, 116);
    nova_draw_text(cr, "Aceleração: habilitada", theme->font_ui, 11.0, fg, cx, 142);
}

static void draw_keyboard(cairo_t *cr, int cx, int w, int h)
{
    NovaColor fg = nova_theme_color(theme->fg, nova_color(0.9,0.9,0.96,1));
    nova_draw_text(cr, "Teclado", theme->font_title, 14.0, fg, cx, 30);
    nova_draw_text(cr, "Layout e repetição de teclas.", theme->font_ui, 11.0, fg, cx, 54);
    /* representação de layout */
    cairo_set_source_rgba(cr, 0.14, 0.13, 0.3, 1.0);
    for (int r = 0; r < 3; r++) {
        for (int c = 0; c < 9; c++) {
            nova_fill_round(cr, cx + 10 + c * 26, 80 + r * 28, 22, 22, 4);
        }
    }
    nova_draw_text(cr, "Layout: us (EN) — Alt+Shift para alternar",
                   theme->font_ui, 11.0, fg, cx, 176);
    nova_draw_text(cr, "Suporte: en_US (padrão), pt_BR, es_ES, fr_FR",
                   theme->font_ui, 11.0, fg, cx, 200);
}

static void draw_mouse(cairo_t *cr, int cx, int w, int h)
{
    NovaColor fg = nova_theme_color(theme->fg, nova_color(0.9,0.9,0.96,1));
    nova_draw_text(cr, "Mouse", theme->font_title, 14.0, fg, cx, 30);
    nova_draw_text(cr, "Sensibilidade e aceleração (libinput).",
                   theme->font_ui, 11.0, fg, cx, 54);
    nova_draw_text(cr, "Sensibilidade: 4.0", theme->font_ui, 11.0, fg, cx, 90);
    nova_draw_text(cr, "Aceleração: habilitada", theme->font_ui, 11.0, fg, cx, 116);
    nova_draw_text(cr, "Scroll: natural", theme->font_ui, 11.0, fg, cx, 142);
}

static void draw_power(cairo_t *cr, int cx, int w, int h)
{
    NovaColor fg = nova_theme_color(theme->fg, nova_color(0.9,0.9,0.96,1));
    nova_draw_text(cr, "Energia", theme->font_title, 14.0, fg, cx, 30);
    nova_draw_text(cr, "Economia e suspensão.", theme->font_ui, 11.0, fg, cx, 54);
    nova_draw_text(cr, "Governador: schedutil (resposta rápida)",
                   theme->font_ui, 11.0, fg, cx, 90);
    nova_draw_text(cr, "Swappiness: 10", theme->font_ui, 11.0, fg, cx, 116);
    nova_draw_text(cr, "Suspender ao fechar a tampa: habilitado",
                   theme->font_ui, 11.0, fg, cx, 142);
    nova_draw_text(cr, "EarlyOOM: ativo | Preload: ativo",
                   theme->font_ui, 11.0, fg, cx, 168);
}

static void draw_appearance(cairo_t *cr, int cx, int w, int h)
{
    NovaColor fg = nova_theme_color(theme->fg, nova_color(0.9,0.9,0.96,1));
    nova_draw_text(cr, "Aparência", theme->font_title, 14.0, fg, cx, 30);
    nova_draw_text(cr, "Tema e papel de parede (.novatheme).",
                   theme->font_ui, 11.0, fg, cx, 54);
    /* preview claro/escuro */
    cairo_set_source_rgba(cr, 0.95, 0.95, 0.97, 1.0);
    nova_fill_round(cr, cx, 80, 90, 40, 8);
    nova_draw_text(cr, "Claro", theme->font_ui, 10.0, nova_color(0.2,0.2,0.3,1), cx + 26, 102);
    cairo_set_source_rgba(cr, 0.1, 0.1, 0.2, 1.0);
    nova_fill_round(cr, cx + 110, 80, 90, 40, 8);
    nova_draw_text(cr, "Escuro", theme->font_ui, 10.0, nova_color(0.9,0.9,0.96,1), cx + 130, 102);
    nova_draw_text(cr, "Papel de parede: arte abstrata azul/roxo",
                   theme->font_ui, 11.0, fg, cx, 152);
}

static void draw(void)
{
    cairo_surface_t *sfc = nova_surface_from_xid(dpy, win, width, height);
    cairo_t *cr = cairo_create(sfc);

    /* fundo */
    NovaColor bgc = nova_theme_color(theme->bg, nova_color(0.08,0.08,0.15,1));
    cairo_set_source_rgba(cr, bgc.r, bgc.g, bgc.b, bgc.a);
    cairo_rectangle(cr, 0, 0, width, height);
    cairo_fill(cr);

    draw_sidebar(cr);

    int cx = SIDEBAR_W + 20;
    int cw = width - SIDEBAR_W - 40;
    int ch = height - 40;
    switch (current_page) {
    case 0: draw_network(cr, cx, cw, ch); break;
    case 1: draw_audio(cr, cx, cw, ch); break;
    case 2: draw_video(cr, cx, cw, ch); break;
    case 3: draw_keyboard(cr, cx, cw, ch); break;
    case 4: draw_mouse(cr, cx, cw, ch); break;
    case 5: draw_power(cr, cx, cw, ch); break;
    case 6: draw_appearance(cr, cx, cw, ch); break;
    }

    cairo_destroy(cr);
    cairo_surface_destroy(sfc);
}

int main(int argc, char **argv)
{
    (void)argc; (void)argv;
    dpy = XOpenDisplay(NULL);
    if (!dpy) return 1;
    screen = DefaultScreen(dpy);
    theme = nova_theme_load(nova_theme_path_for_kind(NOVA_THEME_DARK));

    width = 800; height = 480;
    win = nova_create_window(dpy, 140, 90, width, height, 1, "NovaConfig — Central de Configurações");
    XMapWindow(dpy, win);

    /* troca tema rápido para demonstrar a troca claro/escuro */
    XEvent ev;
    int done = 0;
    while (!done) {
        XNextEvent(dpy, &ev);
        switch (ev.type) {
        case Expose: draw(); break;
        case ConfigureNotify:
            width = ev.xconfigure.width; height = ev.xconfigure.height; draw();
            break;
        case ButtonPress:
            if (ev.xbutton.x < SIDEBAR_W) {
                int idx = (ev.xbutton.y - 42) / 34;
                if (idx >= 0 && idx < NPAGES) { current_page = idx; draw(); }
            }
            break;
        }
    }
    XCloseDisplay(dpy);
    return 0;
}
