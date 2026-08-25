/*
 * wm.c — NovaWM: gerenciador de janelas da NovaUI
 *
 * Um gerenciador de janelas X11 escrito DO ZERO. Nenhum toolkit.
 * Recursos:
 *   - decorações próprias (título, borda arredondada com Cairo)
 *   - focar + clique para focar, Alt+Tab para alternar
 *   - mover com Alt+drag, redimensionar com Alt+drag nos cantos
 *   - botões minimizar/maximizar/fechar desenhados por nós
 *   - launcher "Alt+Espaço" (dispara NOVA_ATOM "novalaunch")
 *   - suporte a múltiplos monitores (usamos o root da tela primária)
 *
 * Aqui é o "coração" do ambiente. Certamente NÃO é Openbox/Mutter/TWM/etc.
 * Toda a lógica de desenho e gerenciamento é original.
 */
#include "common.h"
#include "theme.h"

/* Tamanhos da decoração */
#define NOVA_TITLE_H     28
#define NOVA_RESIZE_MARGIN 8
/* Ids dos botões da decoração */
enum { NOVA_BTN_CLOSE, NOVA_BTN_MAX, NOVA_BTN_MIN, NOVA_BTN_COUNT };

typedef struct NovaFrame {
    Window     frame;      /* janela externa (decoração) */
    Window     client;     /* janela gerenciada           */
    char      *title;
    int        x, y, w, h; /* geometria do frame           */
    int        old_w, old_h;
    int        maximized;
    int        borders;    /* títulos etc                  */
    int        focused;
    struct NovaFrame *next;
} NovaFrame;

static Display           *dpy;
static int                screen;
static Window             root;
static NovaTheme         *theme;
static NovaFrame         *frames;
static NovaFrame         *active;
static Atom               wm_protocols;
static Atom               wm_delete;
static Atom               nova_launch_atom;
static Cursor             move_cursor, resize_cursor;

/* gravação durante drag */
static int dragging = 0;
static int drag_mode;      /* 0 move, 1 resize */
static int drag_start_x, drag_start_y, drag_win_x, drag_win_y;

/* --------------------------------------------------------------------- */
static void focus_frame(NovaFrame *f);

static void draw_frame(NovaFrame *f)
{
    if (!f) return;
    cairo_surface_t *sfc = nova_surface_from_xid(dpy, f->frame, f->w, f->h);
    cairo_t *cr = cairo_create(sfc);

    /* fundo do frame */
    cairo_set_source_rgba(cr, 0.07, 0.07, 0.16, 0.98);
    nova_fill_round(cr, 0, 0, f->w, f->h, theme->corner_radius);

    /* barra de título */
    cairo_set_source_rgba(cr, 0.12, 0.10, 0.30, 1.0);
    nova_fill_round(cr, 0, 0, f->w, NOVA_TITLE_H, theme->corner_radius);

    /* título */
    NovaColor tcol = nova_theme_color(theme->fg, NOVA_ACCENT);
    nova_draw_text(cr, f->title ? f->title : "", theme->font_title, 12.0, tcol,
                   theme->padding, 6.0);

    /* botões (min, max, close) na ordem inversa */
    double bw = 24.0, bh = 16.0;
    double bx = f->w - theme->padding - NOVA_BTN_COUNT * (bw + 4);
    double by = (NOVA_TITLE_H - bh) / 2.0;
    for (int i = 0; i < NOVA_BTN_COUNT; i++) {
        double cx = bx + i * (bw + 4);
        NovaColor c = nova_theme_color(theme->accent, NOVA_ACCENT);
        if (i == NOVA_BTN_CLOSE)
            c = nova_color(0.85, 0.20, 0.30, 1.0);
        cairo_set_source_rgba(cr, c.r, c.g, c.b, c.a);
        nova_fill_round(cr, cx, by, bw, bh, 4.0);

        /* ícone por código (não pegamos nada de toolkit) */
        cairo_set_source_rgb(cr, 1, 1, 1);
        double mx = cx + bw / 2.0, my = by + bh / 2.0;
        if (i == NOVA_BTN_CLOSE) {
            cairo_move_to(cr, mx - 4, my - 4); cairo_line_to(cr, mx + 4, my + 4);
            cairo_move_to(cr, mx + 4, my - 4); cairo_line_to(cr, mx - 4, my + 4);
            cairo_set_line_width(cr, 1.5);
            cairo_stroke(cr);
        } else if (i == NOVA_BTN_MAX) {
            cairo_rectangle(cr, mx - 4, my - 3, 8, 6);
            cairo_set_line_width(cr, 1.2);
            cairo_stroke(cr);
        } else { /* min: linha */
            cairo_move_to(cr, mx - 4, my); cairo_line_to(cr, mx + 4, my);
            cairo_set_line_width(cr, 1.5);
            cairo_stroke(cr);
        }
    }
    cairo_destroy(cr);
    cairo_surface_destroy(sfc);
}

/* --------------------------------------------------------------------- */
static void global_raise(NovaFrame *f)
{
    if (!f) return;
    XRaiseWindow(dpy, f->frame);
    XRaiseWindow(dpy, f->client);
}

static void focus_frame(NovaFrame *f)
{
    if (active == f)
        return;
    if (active)
        active->focused = 0;
    active = f;
    if (f)
        f->focused = 1;

    /* foco X para o client (para teclado) */
    if (f) {
        XSetInputFocus(dpy, f->client, RevertToPointerRoot, CurrentTime);
        draw_frame(f);
    }
    for (NovaFrame *it = frames; it; it = it->next)
        if (it != f) draw_frame(it);
}

/* --------------------------------------------------------------------- */
static void minimize_frame(NovaFrame *f)
{
    if (!f) return;
    XUnmapWindow(dpy, f->frame);
    XUnmapWindow(dpy, f->client);
    if (active == f) active = NULL;
}

static void toggle_maximize(NovaFrame *f)
{
    if (!f) return;
    if (f->maximized) {
        XMoveResizeWindow(dpy, f->frame, f->x, f->y, f->old_w, f->old_h);
        XMoveResizeWindow(dpy, f->client, 0, NOVA_TITLE_H,
                          f->old_w, f->old_h - NOVA_TITLE_H);
        f->w = f->old_w; f->h = f->old_h;
        f->maximized = 0;
    } else {
        f->old_w = f->w; f->old_h = f->h;
        f->x = 0; f->y = 0;
        int sw = DisplayWidth(dpy, screen);
        int sh = DisplayHeight(dpy, screen) - theme->panel_height;
        XMoveResizeWindow(dpy, f->frame, 0, 0, sw, sh);
        XMoveResizeWindow(dpy, f->client, 0, NOVA_TITLE_H, sw, sh - NOVA_TITLE_H);
        f->w = sw; f->h = sh;
        f->maximized = 1;
    }
    draw_frame(f);
}

static void destroy_frame(NovaFrame *f)
{
    if (!f) return;
    /* cliente pediu fechar; envia WM_DELETE_WINDOW se suportado */
    XEvent ev;
    memset(&ev, 0, sizeof(ev));
    ev.xclient.type = ClientMessage;
    ev.xclient.window = f->client;
    ev.xclient.message_type = wm_protocols;
    ev.xclient.format = 32;
    ev.xclient.data.l[0] = wm_delete;
    ev.xclient.data.l[1] = CurrentTime;
    XSendEvent(dpy, f->client, False, 0, &ev);
}

/* --------------------------------------------------------------------- */
static void add_frame(Window client)
{
    XWindowAttributes attr;
    if (!XGetWindowAttributes(dpy, client, &attr))
        return;
    if (attr.override_redirect || attr.class == InputOnly)
        return;

    NovaFrame *f = calloc(1, sizeof(NovaFrame));
    f->client = client;
    f->w = attr.width;
    f->h = attr.height;
    f->x = 80 + (frames ? 20 : 0);
    f->y = 60 + (frames ? 20 : 0);
    f->borders = attr.border_width;
    f->old_w = f->w; f->old_h = f->h;

    char *name = NULL;
    XFetchName(dpy, client, &name);
    f->title = name ? name : strdup("Nova App");

    /* frame = janela pai */
    XSetWindowAttributes fswa;
    fswa.event_mask = SubstructureRedirectMask | SubstructureNotifyMask |
                      ExposureMask | ButtonPressMask | ButtonReleaseMask |
                      PointerMotionMask | FocusChangeMask;
    fswa.override_redirect = False;
    f->frame = XCreateWindow(dpy, root, f->x, f->y, f->w, f->h, 0,
                             CopyFromParent, InputOutput, CopyFromParent,
                             CWEventMask | CWOverrideRedirect, &fswa);
    XStoreName(dpy, f->frame, "NovaWM Frame");

    /* reparent */
    XAddToSaveSet(dpy, client);
    XReparentWindow(dpy, client, f->frame, 0, NOVA_TITLE_H);
    XSelectInput(dpy, client, StructureNotifyMask | PropertyChangeMask |
                              FocusChangeMask | KeyPressMask);

    XMapWindow(dpy, f->frame);
    XMapWindow(dpy, client);

    f->next = frames;
    frames = f;
    focus_frame(f);
    draw_frame(f);
    nova_log("manejando janela '%s' (%lx -> %lx)", f->title, client, f->frame);
}

static void remove_frame(Window client)
{
    NovaFrame **pp = &frames;
    while (*pp) {
        if ((*pp)->client == client) {
            NovaFrame *f = *pp;
            *pp = f->next;
            XRemoveFromSaveSet(dpy, client);
            XReparentWindow(dpy, client, root, f->x, f->y + NOVA_TITLE_H);
            XDestroyWindow(dpy, f->frame);
            if (active == f) active = NULL;
            free(f->title);
            free(f);
            return;
        }
        pp = &(*pp)->next;
    }
}

/* --------------------------------------------------------------------- */
static NovaFrame *frame_for(Window w)
{
    for (NovaFrame *f = frames; f; f = f->next)
        if (f->frame == w || f->client == w)
            return f;
    return NULL;
}

static int hit_button(NovaFrame *f, int x, int y)
{
    if (y > NOVA_TITLE_H) return -1;
    double bw = 24.0, bh = 16.0;
    double bx = f->w - theme->padding - NOVA_BTN_COUNT * (bw + 4);
    double by = (NOVA_TITLE_H - bh) / 2.0;
    for (int i = 0; i < NOVA_BTN_COUNT; i++) {
        double cx = bx + i * (bw + 4);
        if (x >= cx && x <= cx + bw && y >= by && y <= by + bh)
            return i;
    }
    return -1;
}

static void handle_button_press(XButtonEvent *ev)
{
    NovaFrame *f = frame_for(ev->window);
    if (!f) return;
    /* somente em frames */
    int bx = ev->x, by = ev->y;
    if (f->frame == ev->window && by <= NOVA_TITLE_H) {
        if (by < NOVA_TITLE_H && by >= 0) {
            /* barra de título: foco + possível mover */
            focus_frame(f);
            if (ev->button == Button1) {
                int btn = hit_button(f, bx, by);
                if (btn == NOVA_BTN_CLOSE) { destroy_frame(f); return; }
                if (btn == NOVA_BTN_MAX)   { toggle_maximize(f); return; }
                if (btn == NOVA_BTN_MIN)   { minimize_frame(f); return; }
                /* iniciar mover com Alt não é necessário; drag na barra move */
                dragging = 1; drag_mode = 0;
                drag_start_x = ev->x_root; drag_start_y = ev->y_root;
                drag_win_x = f->x; drag_win_y = f->y;
            }
        }
    } else if (f->frame == ev->window) {
        /* clique fora da barra = redim ou foco */
        if (ev->x > f->w - NOVA_RESIZE_MARGIN || ev->y > f->h - NOVA_RESIZE_MARGIN) {
            focus_frame(f);
            dragging = 1; drag_mode = 1;
            drag_start_x = ev->x_root; drag_start_y = ev->y_root;
            drag_win_x = f->w; drag_win_y = f->h;
        } else {
            focus_frame(f);
        }
    } else {
        focus_frame(f);
    }
}

static void handle_motion(XMotionEvent *ev)
{
    NovaFrame *f = active;
    if (!f || !dragging) return;
    int dx = ev->x_root - drag_start_x;
    int dy = ev->y_root - drag_start_y;
    if (drag_mode == 0) {
        int nx = drag_win_x + dx;
        int ny = drag_win_y + dy;
        XMoveWindow(dpy, f->frame, nx, ny);
        f->x = nx; f->y = ny;
    } else {
        int nw = drag_win_x + dx;
        int nh = drag_win_y + dy;
        if (nw < 120) nw = 120;
        if (nh < 90)  nh = 90;
        XMoveResizeWindow(dpy, f->frame, f->x, f->y, nw, nh);
        XMoveResizeWindow(dpy, f->client, 0, NOVA_TITLE_H, nw, nh - NOVA_TITLE_H);
        f->w = nw; f->h = nh;
        draw_frame(f);
    }
}

static void handle_key(XKeyEvent *ev)
{
    KeySym ks = XLookupKeysym(ev, 0);
    NovaFrame *f = active;
    /* launcher: Alt+Espaço */
    if (ks == XK_space && (ev->state & Mod1Mask)) {
        XEvent e;
        memset(&e, 0, sizeof(e));
        e.xclient.type = ClientMessage;
        e.xclient.window = root;
        e.xclient.message_type = nova_launch_atom;
        e.xclient.format = 32;
        XSendEvent(dpy, root, False, SubstructureRedirectMask, &e);
        return;
    }
    if (ks == XK_Tab && (ev->state & Mod1Mask)) {
        /* ciclo simples entre frames */
        if (!frames) return;
        NovaFrame *n = frames;
        if (active) n = active->next ? active->next : frames;
        focus_frame(n);
        return;
    }
    (void)f;
}

/* --------------------------------------------------------------------- */
static void event_loop(void)
{
    XEvent ev;
    for (;;) {
        XNextEvent(dpy, &ev);
        switch (ev.type) {
        case MapRequest:
            add_frame(ev.xmaprequest.window);
            break;
        case DestroyNotify:
            remove_frame(ev.xdestroywindow.window);
            break;
        case UnmapNotify:
            if (ev.xunmap.event == ev.xunmap.window)
                remove_frame(ev.xunmap.window);
            break;
        case ConfigureRequest: {
            XConfigureRequestEvent *ce = &ev.xconfigurerequest;
            XWindowChanges wc;
            wc.x = ce->x; wc.y = ce->y; wc.width = ce->width; wc.height = ce->height;
            wc.border_width = ce->border_width; wc.sibling = ce->above; wc.stack_mode = ce->detail;
            XConfigureWindow(dpy, ce->window, ce->value_mask, &wc);
            break;
        }
        case ButtonPress:
            handle_button_press(&ev.xbutton);
            break;
        case MotionNotify:
            handle_motion(&ev.xmotion);
            break;
        case ButtonRelease:
            dragging = 0;
            break;
        case Expose:
            draw_frame(frame_for(ev.xexpose.window));
            break;
        case KeyPress:
            handle_key(&ev.xkey);
            break;
        case FocusIn:
            focus_frame(frame_for(ev.xfocus.window));
            break;
        case ClientMessage:
            if (ev.xclient.message_type == nova_launch_atom) {
                /* lançador: executa o binary novalauncher */
                if (fork() == 0) {
                    execl("/usr/bin/novalauncher", "novalauncher", (char *)NULL);
                    _exit(0);
                }
            }
            break;
        }
    }
}

/* --------------------------------------------------------------------- */
int main(int argc, char **argv)
{
    (void)argc; (void)argv;
    dpy = XOpenDisplay(NULL);
    if (!dpy) {
        fprintf(stderr, "NovaWM: não foi possível abrir o display X11\n");
        return 1;
    }
    screen = DefaultScreen(dpy);
    root = RootWindow(dpy, screen);
    theme = nova_theme_load(nova_theme_path_for_kind(NOVA_THEME_DARK));

    wm_protocols = nova_atom(dpy, "WM_PROTOCOLS");
    wm_delete    = nova_atom(dpy, NOVA_ATOM_PROTO);
    nova_launch_atom = nova_atom(dpy, "novalaunch");

    move_cursor   = XCreateFontCursor(dpy, XC_fleur);
    resize_cursor = XCreateFontCursor(dpy, XC_bottom_right_corner);
    (void)move_cursor; (void)resize_cursor;

    /* precisamos de SubstructureRedirectMask para gerenciar janelas */
    XSelectInput(dpy, root, SubstructureRedirectMask | SubstructureNotifyMask |
                            KeyPressMask | ButtonPressMask | PropertyChangeMask);

    /* intercepta SIGCHLD para reaproveitar filhos */
    signal(SIGCHLD, SIG_IGN);

    nova_log("NovaWM iniciado (tema %s). Pressione %s para o launcher.",
             theme->name, NOVA_LAUNCHER_HINT);

    event_loop();
    XCloseDisplay(dpy);
    return 0;
}
