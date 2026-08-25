/*
 * common.h — NovaLinux NovaUI
 *
 * Cabeçalho comum a todos os componentes da NovaUI.
 *
 * A NovaUI é uma interface gráfica 100% original, desenvolvida do zero.
 * Não usa Qt, GTK, EFL, FLTK, wxWidgets nem qualquer toolkit pronto.
 * Únicas bibliotecas permitidas (conforme requisito):
 *   Xlib, OpenGL/Vulkan, Cairo, Pango, FreeType, libinput.
 *
 * SPDX-License-Identifier: BSD-3-Clause
 */
#ifndef NOVA_COMMON_H
#define NOVA_COMMON_H

#define _GNU_SOURCE
#define _POSIX_C_SOURCE 200809L

#include <math.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/keysym.h>
#include <X11/cursorfont.h>
#include <cairo/cairo-xlib.h>
#include <pango/pangocairo.h>
#include <pango/pango.h>
#include <fontconfig/fontconfig.h>

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <signal.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <time.h>

/* ----------------------------------------------------------------------
 * Configuração de tema / identidade da marca
 * -------------------------------------------------------------------- */
#define NOVA_APP_NAME      "NovaUI"
#define NOVA_APP_VERSION   "1.0"
#define NOVA_ICON_DIR      "/usr/share/novaui/icons"
#define NOVA_THEME_DIR     "/usr/share/novaui/themes"
#define NOVA_PANEL_HEIGHT  30
#define NOVA_LAUNCHER_HINT "Alt+Space"

/* Constantes X11 customizadas (definidas por nós — nada de toolkits) */
#define NOVA_WINDOW_TITLE  0x4E4F56  /* 'NOV' — marca interna das janelas   */
#define NOVA_ATOM_PROTO    "WM_DELETE_WINDOW"

/* ----------------------------------------------------------------------
 * Cores padrão do tema
 * -------------------------------------------------------------------- */
typedef struct {
    double r, g, b, a;
} NovaColor;

static inline NovaColor nova_color(double r, double g, double b, double a)
{
    NovaColor c = { r, g, b, a };
    return c;
}

#define NOVA_ACCENT       nova_color(0.23, 0.05, 0.64, 1.0)   /* roxo/indigo */
#define NOVA_ACCENT_2     nova_color(0.45, 0.04, 0.72, 1.0)   /* violeta     */

/* ----------------------------------------------------------------------
 * Registro de log (pequeno; sem dependências)
 * -------------------------------------------------------------------- */
void nova_log(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

/* ----------------------------------------------------------------------
 * Utilidades de desenho Cairo
 * -------------------------------------------------------------------- */
cairo_surface_t *nova_surface_from_xid(Display *dpy, Window win, int w, int h);
void nova_fill_round(cairo_t *cr, double x, double y, double w, double h, double r);
void nova_draw_text(cairo_t *cr, const char *text, const char *font,
                    double size, NovaColor color, double x, double y);
void nova_blur_rect(cairo_t *cr, double x, double y, double w, double h,
                    double radius, double blur);
uint64_t nova_now_ms(void);

/* ----------------------------------------------------------------------
 * gerenciamento de janelas X11 auxiliares
 * -------------------------------------------------------------------- */
Window nova_create_window(Display *dpy, int x, int y, int w, int h,
                          int border, const char *title);
Atom nova_atom(Display *dpy, const char *name);

/* ----------------------------------------------------------------------
 * Launcher / teclado tem aplicações guardadas em variáveis globais.
 * Cada processo da NovaUI (panel, wm, apps) tem um loop de eventos.
 * -------------------------------------------------------------------- */
typedef void (*NovaKeyFunc)(XKeyEvent *ev, void *user);

#endif /* NOVA_COMMON_H */
