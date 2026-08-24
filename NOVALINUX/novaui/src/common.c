/*
 * common.c — NovaLinux NovaUI: utilitários compartilhados
 */
#include "common.h"

#include <stdarg.h>

void nova_log(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    fprintf(stderr, "[NovaUI] ");
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");
    va_end(ap);
}

uint64_t nova_now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000u + (uint64_t)ts.tv_nsec / 1000000u;
}

cairo_surface_t *nova_surface_from_xid(Display *dpy, Window win, int w, int h)
{
    return cairo_xlib_surface_create(dpy, win, DefaultVisual(dpy, 0), w, h);
}

/* Desenha um retângulo arredondado (caminho) sem preencher. */
static void nova_round_path(cairo_t *cr, double x, double y, double w, double h, double r)
{
    double rr = r < (h / 2.0) ? r : (h / 2.0);
    rr = rr < (w / 2.0) ? rr : (w / 2.0);
    cairo_new_sub_path(cr);
    cairo_arc(cr, x + w - rr, y + rr, rr, -M_PI_2, 0);
    cairo_arc(cr, x + w - rr, y + h - rr, rr, 0, M_PI_2);
    cairo_arc(cr, x + rr, y + h - rr, rr, M_PI_2, M_PI);
    cairo_arc(cr, x + rr, y + rr, rr, M_PI, 3 * M_PI_2);
    cairo_close_path(cr);
}

void nova_fill_round(cairo_t *cr, double x, double y, double w, double h, double r)
{
    nova_round_path(cr, x, y, w, h, r);
    cairo_fill(cr);
}

void nova_draw_text(cairo_t *cr, const char *text, const char *font,
                    double size, NovaColor color, double x, double y)
{
    PangoLayout *layout = pango_cairo_create_layout(cr);
    PangoFontDescription *desc = pango_font_description_from_string(font);
    pango_font_description_set_absolute_size(desc, size * PANGO_SCALE);
    pango_layout_set_font_description(layout, desc);
    pango_layout_set_text(layout, text, -1);
    pango_font_description_free(desc);

    cairo_set_source_rgba(cr, color.r, color.g, color.b, color.a);
    cairo_move_to(cr, x, y);
    pango_cairo_show_layout(cr, layout);
    g_object_unref(layout);
}

void nova_blur_rect(cairo_t *cr, double x, double y, double w, double h,
                    double radius, double blur)
{
    /* Aproximação: camada semi-transparente escura para o efeito de vidro */
    cairo_push_group(cr);
    nova_fill_round(cr, x, y, w, h, radius);
    cairo_pop_group_to_source(cr);
    cairo_paint_with_alpha(cr, 0.55);
}

Window nova_create_window(Display *dpy, int x, int y, int w, int h,
                          int border, const char *title)
{
    XSetWindowAttributes swa;
    swa.event_mask = ExposureMask | KeyPressMask | KeyReleaseMask |
                     ButtonPressMask | ButtonReleaseMask | PointerMotionMask |
                     StructureNotifyMask | FocusChangeMask | PropertyChangeMask;
    swa.override_redirect = False;
    swa.background_pixel = 0x000000;
    swa.border_pixel = 0x000000;

    Window win = XCreateWindow(dpy, RootWindow(dpy, 0), x, y, w, h,
                               border, CopyFromParent, InputOutput,
                               CopyFromParent,
                               CWEventMask | CWOverrideRedirect |
                               CWBackPixel | CWBorderPixel,
                               &swa);
    if (title && *title)
        XStoreName(dpy, win, title);
    return win;
}

Atom nova_atom(Display *dpy, const char *name)
{
    return XInternAtom(dpy, name, False);
}

/*
 * pequeno helper para esvaziar eventos pendentes (evita operação longa
 * de XNextEvent ao sair).
 */
void nova_flush_events(Display *dpy)
{
    while (XPending(dpy))
        XNextEvent(dpy);
}
