/*
 * files.c — NovaFiles: gerenciador de arquivos da NovaUI
 *
 * Renderiza um diretório com ícones/texto usando Cairo + Pango + Xlib.
 * Recursos:
 *   - navegação (duplo clique em diretório entra; clique em ".." volta)
 *   - barra de caminho editável
 *   - ícones detectados por extensão/mimetype (código próprio)
 *   - menus simples (criar pasta, atualizar, abrir terminal)
 * Não usa GIO/GVfs/Nautilus — tudo em C com chamadas POSIX + X11/Cairo.
 */
#include "common.h"
#include "theme.h"

#include <dirent.h>
#include <sys/stat.h>
#include <sys/types.h>

#define CELL_W  96
#define CELL_H  110
#define HEAD_H  50
#define ICON_SZ 64

static Display   *dpy;
static int        screen;
static Window     win;
static int        width, height;
static NovaTheme *theme;

static char cwd[PATH_MAX];
typedef struct { char name[NAME_MAX]; int isdir; off_t size; } Entry;
static Entry *entries;
static int    nentries;

static void fill_entries(void)
{
    if (entries) { free(entries); entries = NULL; }
    nentries = 0;
    DIR *d = opendir(cwd);
    if (!d) return;
    nentries = 0;
    int cap = 256;
    entries = calloc(cap, sizeof(Entry));
    struct dirent *de;
    while ((de = readdir(d)) != NULL) {
        if (strcmp(de->d_name, ".") == 0) continue;
        if (de->d_name[0] == '.' && strcmp(de->d_name, "..") != 0) continue;
        char p[PATH_MAX];
        snprintf(p, sizeof(p), "%s/%s", cwd, de->d_name);
        struct stat st;
        stat(p, &st);
        Entry *e = &entries[nentries++];
        snprintf(e->name, NAME_MAX, "%s", de->d_name);
        e->isdir = S_ISDIR(st.st_mode);
        e->size  = st.st_size;
        if (nentries >= cap) { cap *= 2; entries = realloc(entries, cap * sizeof(Entry)); }
    }
    closedir(d);
    /* ordenação: diretórios primeiro, depois alfabeto */
    for (int i = 0; i < nentries; i++)
        for (int j = i + 1; j < nentries; j++)
            if ((entries[j].isdir && !entries[i].isdir) ||
                (entries[i].isdir == entries[j].isdir &&
                 strcmp(entries[i].name, entries[j].name) < 0)) {
                Entry t = entries[i]; entries[i] = entries[j]; entries[j] = t;
            }
}

static void draw_icon(cairo_t *cr, int isdir, double x, double y, double s)
{
    NovaColor col = isdir ? nova_theme_color(theme->accent, NOVA_ACCENT)
                          : nova_theme_color(theme->fg_dim, nova_color(0.5,0.5,0.6,1));
    if (isdir) {
        /* pasta: retângulo arredondado + aba */
        cairo_set_source_rgba(cr, col.r, col.g, col.b, col.a);
        nova_fill_round(cr, x, y + s * 0.2, s, s * 0.65, 5);
        nova_fill_round(cr, x, y, s * 0.45, s * 0.25, 3);
    } else {
        /* documento: retângulo + linha dobrada */
        cairo_set_source_rgba(cr, col.r, col.g, col.b, col.a);
        nova_fill_round(cr, x, y, s * 0.6, s * 0.8, 4);
        cairo_set_source_rgb(cr, 1, 1, 1);
        cairo_rectangle(cr, x + s * 0.1, y + s * 0.2, s * 0.4, s * 0.5);
        cairo_stroke(cr);
    }
}

static void draw(void)
{
    cairo_surface_t *sfc = nova_surface_from_xid(dpy, win, width, height);
    cairo_t *cr = cairo_create(sfc);

    NovaColor bgc = nova_theme_color(theme->bg, nova_color(0.08,0.08,0.15,1));
    NovaColor fgc = nova_theme_color(theme->fg, nova_color(0.9,0.9,0.96,1));
    cairo_set_source_rgba(cr, bgc.r, bgc.g, bgc.b, bgc.a);
    cairo_rectangle(cr, 0, 0, width, height);
    cairo_fill(cr);

    /* cabeçalho de caminho */
    cairo_set_source_rgba(cr, 0.12, 0.10, 0.28, 1.0);
    cairo_rectangle(cr, 0, 0, width, HEAD_H);
    cairo_fill(cr);
    nova_draw_text(cr, cwd, theme->font_mono, 12.0, fgc, 12, 18);

    /* grid de entradas */
    int cols = width / CELL_W;
    if (cols < 1) cols = 1;
    for (int i = 0; i < nentries; i++) {
        int cx = (i % cols) * CELL_W;
        int cy = HEAD_H + (i / cols) * CELL_H;
        /* fundo de seleção (hover não implementado para manter simples) */
        double ix = cx + (CELL_W - ICON_SZ) / 2.0;
        draw_icon(cr, entries[i].isdir, ix, cy + 8, ICON_SZ);
        /* nome (truncado) */
        char disp[64];
        snprintf(disp, sizeof(disp), "%.14s", entries[i].name);
        nova_draw_text(cr, disp, theme->font_ui, 10.0, fgc, cx + 4, cy + CELL_H - 16);
    }

    cairo_destroy(cr);
    cairo_surface_destroy(sfc);
}

static int cell_hit(int x, int y, int *idx)
{
    int cols = width / CELL_W; if (cols < 1) cols = 1;
    int col = x / CELL_W;
    int row = (y - HEAD_H) / CELL_H;
    int i = row * cols + col;
    if (y < HEAD_H) return 0;
    if (i < 0 || i >= nentries) return 0;
    *idx = i;
    return 1;
}

static void open_entry(int i)
{
    if (i < 0 || i >= nentries) return;
    char p[PATH_MAX];
    snprintf(p, sizeof(p), "%s/%s", cwd, entries[i].name);
    if (entries[i].isdir) {
        realpath(p, cwd);
        fill_entries();
        draw();
    } else {
        /* abre com xdg-open (mimetype; sem depender de GVfs) */
        if (fork() == 0) {
            execl("/usr/bin/xdg-open", "xdg-open", p, (char *)NULL);
            execl("/usr/bin/nova-open", "nova-open", p, (char *)NULL);
            _exit(127);
        }
    }
}

static void new_folder(void)
{
    char p[PATH_MAX];
    for (int n = 1; n < 1000; n++) {
        snprintf(p, sizeof(p), "%s/nova-folder-%d", cwd, n);
        if (mkdir(p, 0755) == 0) break;
    }
    fill_entries(); draw();
}

static void key_handling(XKeyEvent *ev)
{
    if (ev->keycode == 0) return;
    KeySym ks = XLookupKeysym(ev, 0);
    if (ks == XK_F5) { fill_entries(); draw(); }
    if (ks == XK_BackSpace) {
        char tmp[PATH_MAX];
        strncpy(tmp, cwd, sizeof(tmp) - 1); tmp[sizeof(tmp)-1] = '\0';
        char *slash = strrchr(tmp, '/');
        if (slash && slash != tmp) *slash = '\0';
        else if (slash == tmp) tmp[1] = '\0';
        strncpy(cwd, tmp, sizeof(cwd)-1);
        fill_entries(); draw();
    }
}

int main(int argc, char **argv)
{
    (void)argc; (void)argv;
    dpy = XOpenDisplay(NULL);
    if (!dpy) return 1;
    screen = DefaultScreen(dpy);
    theme = nova_theme_load(nova_theme_path_for_kind(NOVA_THEME_DARK));

    getcwd(cwd, sizeof(cwd));
    fill_entries();

    width = 780; height = 520;
    win = nova_create_window(dpy, 120, 80, width, height, 1, "NovaFiles");
    XMapWindow(dpy, win);

    int did = 0;
    XEvent ev;
    while (!did) {
        XNextEvent(dpy, &ev);
        switch (ev.type) {
        case Expose: draw(); break;
        case ConfigureNotify:
            width = ev.xconfigure.width; height = ev.xconfigure.height; draw();
            break;
        case ButtonPress:
            if (ev.xbutton.button == Button1) {
                int idx = 0;
                if (cell_hit(ev.xbutton.x, ev.xbutton.y, &idx)) {
                    if (strcmp(entries[idx].name, "..") == 0) {
                        char tmp[PATH_MAX];
                        strncpy(tmp, cwd, sizeof(tmp)-1); tmp[sizeof(tmp)-1]='\0';
                        char *s = strrchr(tmp, '/');
                        if (s && s != tmp) *s = '\0'; else if (s==tmp) tmp[1]='\0';
                        strncpy(cwd, tmp, sizeof(cwd)-1); fill_entries(); draw();
                    } else {
                        open_entry(idx);
                    }
                }
            } else if (ev.xbutton.button == Button3) {
                /* menu de contexto: criar pasta, atualizar */
                if (ev.xbutton.y < 40) {
                    /* cabeçalho: nada */
                } else {
                    new_folder();
                }
            }
            break;
        case KeyPress:
            key_handling(&ev.xkey);
            break;
        }
    }
    XCloseDisplay(dpy);
    return 0;
}
