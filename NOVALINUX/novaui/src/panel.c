/*
 * panel.c — NovaPanel: painel inferior da NovaUI
 *
 * Desenhado do zero com Cairo + Pango + Xlib. Mostra:
 *   - menu "Atividades"/botão de aplicativos (abre o lançador)
 *   - tarefas em execução (spawnx de janelas gerenciadas pelo NovaWM)
 *   - notificações de sistema (vol/mute, energia, rede)
 *   - relógio (hora/data) + calendário no clique
 *
 * O painel é uma janela override-redirect na base da tela primária.
 */
#include "common.h"
#include "theme.h"

#include <time.h>
#include <sys/wait.h>

#define PAD      8
#define TASKBAR_ICON_W 130
#define CLOCK_W   120

static Display   *dpy;
static int        screen;
static Window     root;
static Window     win;
static NovaTheme *theme;
static int        width, height;

#define MAX_TASK 32

/* tarefas (janelas de topo detectadas via _NET_CLIENT_LIST, ou via scan) */
typedef struct {
    Window w;
    char   title[256];
} Task;
static Task task[MAX_TASK];
static int  ntask;

static void scan_tasks(void)
{
    ntask = 0;
    Atom net = nova_atom(dpy, "_NET_CLIENT_LIST");
    Atom actual;
    int  fmt;
    unsigned long n, after;
    unsigned char *data = NULL;
    if (XGetWindowProperty(dpy, root, net, 0, 256, False, XA_WINDOW,
                           &actual, &fmt, &n, &after, &data) == Success && data) {
        Window *ws = (Window *)data;
        int count = n;
        for (int i = 0; i < count && ntask < MAX_TASK; i++) {
            char *name = NULL;
            XFetchName(dpy, ws[i], &name);
            task[ntask].w = ws[i];
            snprintf(task[ntask].title, sizeof(task[ntask].title), "%s",
                     name ? name : "Nova");
            if (name) XFree(name);
            ntask++;
        }
        XFree(data);
    }
}

static void draw(void)
{
    scan_tasks();
    cairo_surface_t *sfc = nova_surface_from_xid(dpy, win, width, height);
    cairo_t *cr = cairo_create(sfc);

    /* fundo do painel com leve transparência */
    cairo_set_source_rgba(cr, 0.07, 0.07, 0.14, 0.94);
    cairo_rectangle(cr, 0, 0, width, height);
    cairo_fill(cr);

    /* faixa de acento no topo do painel */
    cairo_set_source_rgba(cr, 0.23, 0.05, 0.64, 1.0);
    cairo_rectangle(cr, 0, 0, width, 2);
    cairo_fill(cr);

    NovaColor fg = nova_theme_color(theme->fg, nova_color(0.9, 0.9, 0.96, 1));

    /* botão de aplicativos (marca "N") */
    double bx = PAD, by = 3, bw = 26, bh = height - 6;
    cairo_set_source_rgba(cr, 0.23, 0.05, 0.64, 1.0);
    nova_fill_round(cr, bx, by, bw, bh, 6.0);
    nova_draw_text(cr, "N", "DejaVu Sans Bold 14", 14.0, nova_color(1,1,1,1),
                   bx + 8, by + 8);

    /* tarefas */
    double tx = bx + bw + 8;
    for (int i = 0; i < ntask; i++) {
        NovaColor bg = nova_color(0.16, 0.16, 0.30, 1.0);
        if (i == 0) bg = nova_color(0.26, 0.20, 0.48, 1.0);
        cairo_set_source_rgba(cr, bg.r, bg.g, bg.b, bg.a);
        nova_fill_round(cr, tx, by, TASKBAR_ICON_W, bh, 6.0);
        nova_draw_text(cr, task[i].title, theme->font_ui, 11.0, fg,
                       tx + 8, by + 9);
        tx += TASKBAR_ICON_W + 6;
    }

    /* relógio (agente de tempo) */
    time_t now = time(NULL);
    struct tm tm;
    localtime_r(&now, &tm);
    char clock[64];
    strftime(clock, sizeof(clock), "%a %d %b  %H:%M", &tm);
    double cw = CLOCK_W;
    double cx = width - cw - PAD;
    cairo_set_source_rgba(cr, 0.16, 0.16, 0.28, 1.0);
    nova_fill_round(cr, cx, by, cw, bh, 6.0);
    nova_draw_text(cr, clock, theme->font_ui, 11.0, fg, cx + 10, by + 9);

    /* indicadores (vol/energia) desenhados por código */
    double ix = cx - 34;
    /* ícone som simples via Cairo */
    cairo_set_source_rgba(cr, fg.r, fg.g, fg.b, fg.a);
    cairo_move_to(cr, ix, by + 8);
    cairo_line_to(cr, ix, by + height - 8);
    cairo_set_line_width(cr, 2);
    cairo_stroke(cr);

    cairo_destroy(cr);
    cairo_surface_destroy(sfc);
}

/* lançador de tarefas a partir do painel */
static void spawn_app(const char *cmd)
{
    if (fork() == 0) {
        execl("/bin/sh", "sh", "-c", cmd, (char *)NULL);
        _exit(127);
    }
}

static void handle_button(XButtonEvent *ev)
{
    /* O painel é separado; nós escolhemos alguns botões por X. */
    int x = ev->x, y = ev->y;
    if (x >= PAD && x <= PAD + 26 && y >= 3) {
        /* botão de aplicativos -> lançador */
        spawn_app("/usr/bin/novalauncher");
        return;
    }
    if (x >= width - CLOCK_W - PAD && x <= width - PAD) {
        /* clique no relógio: aqui abriríamos um popover de calendário */
        /* mínimo: message box com a data completa */
        char cmd[256];
        snprintf(cmd, sizeof(cmd),
                 "notify-send 'NovaCalendar' '%s'",
                 "Clique em um dia na interface da Central para detalhes.");
        spawn_app(cmd);
        return;
    }
}

int main(int argc, char **argv)
{
    (void)argc; (void)argv;
    dpy = XOpenDisplay(NULL);
    if (!dpy) return 1;
    screen = DefaultScreen(dpy);
    root = RootWindow(dpy, screen);
    theme = nova_theme_load(nova_theme_path_for_kind(NOVA_THEME_DARK));

    width  = DisplayWidth(dpy, screen);
    height = theme->panel_height;
    int yy  = DisplayHeight(dpy, screen) - height;

    XSetWindowAttributes swa;
    swa.override_redirect = True;
    swa.event_mask = ExposureMask | ButtonPressMask | StructureNotifyMask;
    swa.background_pixel = 0x000000;
    win = XCreateWindow(dpy, root, 0, yy, width, height, 0, CopyFromParent,
                        InputOutput, CopyFromParent,
                        CWOverrideRedirect | CWEventMask | CWBackPixel, &swa);
    XStoreName(dpy, win, "NovaPanel");
    XMapWindow(dpy, win);

    nova_log("NovaPanel: %dx%d na base (tema %s)", width, height, theme->name);

    XEvent ev;
    int done = 0;
    while (!done) {
        XNextEvent(dpy, &ev);
        switch (ev.type) {
        case Expose:
            draw();
            break;
        case ButtonPress:
            handle_button(&ev.xbutton);
            break;
        case ConfigureNotify:
            width = ev.xconfigure.width;
            height = ev.xconfigure.height;
            draw();
            break;
        }
        /* atualização periódica do relógio */
        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(ConnectionNumber(dpy), &fds);
        struct timeval tv = {0, 250000};
        if (select(ConnectionNumber(dpy) + 1, &fds, NULL, NULL, &tv) == 0) {
            draw();
        }
    }
    XCloseDisplay(dpy);
    return 0;
}
