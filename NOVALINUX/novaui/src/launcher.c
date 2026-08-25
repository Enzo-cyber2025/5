/*
 * launcher.c — NovaLauncher: lançador rápido (Alt+Espaço)
 *
 * Uma janela override-redirect centrada no topo da tela, com um campo de
 * busca. Digite para filtrar os aplicativos (lista de .desktop própria em
 * /usr/share/novastation/apps/), Enter para abrir, Esc para fechar.
 *
 * Totalmente original; sem bibliotecas de "desktop search" de outros
 * ambientes.
 */
#include "common.h"
#include "theme.h"

#include <dirent.h>

#define LAUNCH_W  520
#define LAUNCH_H  360
#define ENTRY_H   34

typedef struct {
    char   name[128];
    char   exec[256];
    char   category[64];
} App;

static Display   *dpy;
static int        screen;
static Window     root;
static Window     win;
static NovaTheme *theme;
static App       *apps;
static int        napps;
static int        sel;
static char       query[128];
static int        width, height;

/* --------------------------------------------------------------------- */
static void load_apps(void)
{
    napps = 0;
    int cap = 64;
    apps = calloc(cap, sizeof(App));
    const char *dirs[] = {
        "/usr/share/novastation/apps/",
        "/usr/local/share/novastation/apps/",
        "/usr/share/applications/",
        NULL
    };
    for (int d = 0; dirs[d]; d++) {
        DIR *dp = opendir(dirs[d]);
        if (!dp) continue;
        struct dirent *de;
        while ((de = readdir(dp)) != NULL) {
            char *ext = strrchr(de->d_name, '.');
            if (!ext || strcmp(ext, ".nova") != 0) continue;
            char path[512];
            snprintf(path, sizeof(path), "%s%s", dirs[d], de->d_name);
            FILE *f = fopen(path, "r");
            if (!f) continue;
            App a; memset(&a, 0, sizeof(a));
            char line[256];
            while (fgets(line, sizeof(line), f)) {
                char k[64], v[192];
                if (sscanf(line, "%63[^=]=%191[^\n]", k, v) == 2) {
                    if (strcmp(k, "Name") == 0) snprintf(a.name, 128, "%s", v);
                    else if (strcmp(k, "Exec") == 0) snprintf(a.exec, 256, "%s", v);
                    else if (strcmp(k, "Categories") == 0) snprintf(a.category, 64, "%s", v);
                }
            }
            fclose(f);
            if (a.name[0] && a.exec[0])
                apps[napps++] = a;
            if (napps >= cap) { cap *= 2; apps = realloc(apps, cap * sizeof(App)); }
        }
        closedir(dp);
    }
}

static int matches(const App *a, const char *q)
{
    if (q[0] == '\0') return 1;
    /* case-insensitive substring search */
    char needle[128], hay[256];
    for (int i = 0; q[i]; i++) needle[i] = tolower((unsigned char)q[i]);
    needle[strlen(q)] = '\0';
    snprintf(hay, sizeof(hay), "%s %s", a->name, a->category);
    for (int i = 0; hay[i]; i++) hay[i] = tolower((unsigned char)hay[i]);
    return strstr(hay, needle) != NULL;
}

static void launch(void)
{
    int shown = 0;
    for (int i = 0; i < napps; i++) {
        if (!matches(&apps[i], query)) continue;
        if (shown == sel) {
            if (apps[i].exec[0]) {
                if (fork() == 0) {
                    execl("/bin/sh", "sh", "-c", apps[i].exec, (char *)NULL);
                    _exit(127);
                }
            }
            break;
        }
        shown++;
    }
}

/* --------------------------------------------------------------------- */
static void draw(void)
{
    cairo_surface_t *sfc = nova_surface_from_xid(dpy, win, width, height);
    cairo_t *cr = cairo_create(sfc);

    /* fundo translúcido de vidro */
    NovaColor bgc = nova_theme_color(theme->bg, nova_color(0.08,0.08,0.15,1));
    cairo_set_source_rgba(cr, bgc.r, bgc.g, bgc.b, 0.96);
    nova_fill_round(cr, 0, 0, width, height, 12);

    /* campo de busca */
    cairo_set_source_rgba(cr, 0.12, 0.11, 0.28, 1.0);
    nova_fill_round(cr, 10, 10, width - 20, 44, 8);
    NovaColor fg = nova_theme_color(theme->fg, nova_color(0.9,0.9,0.96,1));
    nova_draw_text(cr, "Buscar aplicativos...", theme->font_ui, 12.0,
                   nova_theme_color(theme->fg_dim, fg), 22, 38);
    nova_draw_text(cr, query, theme->font_ui, 12.0, fg, 22, 38);

    /* lista de resultados */
    int y = 66;
    int shown = 0;
    NovaColor acc = nova_theme_color(theme->accent, NOVA_ACCENT);
    for (int i = 0; i < napps; i++) {
        if (!matches(&apps[i], query)) continue;
        int ry = y + shown * ENTRY_H;
        if (shown == sel) {
            cairo_set_source_rgba(cr, acc.r, acc.g, acc.b, 0.9);
            nova_fill_round(cr, 10, ry, width - 20, ENTRY_H - 2, 6);
            nova_draw_text(cr, apps[i].name, theme->font_ui, 12.0,
                           nova_color(1,1,1,1), 22, ry + 20);
        } else {
            nova_draw_text(cr, apps[i].name, theme->font_ui, 12.0, fg,
                           22, ry + 20);
        }
        shown++;
        if (y + shown * ENTRY_H > height - 10) break;
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
    root = RootWindow(dpy, screen);
    theme = nova_theme_load(nova_theme_path_for_kind(NOVA_THEME_DARK));
    load_apps();

    int rw = DisplayWidth(dpy, screen);
    width = LAUNCH_W; height = LAUNCH_H;
    int x = (rw - width) / 2;
    int y = 60;

    XSetWindowAttributes swa;
    swa.override_redirect = True;
    swa.event_mask = ExposureMask | KeyPressMask | KeyReleaseMask |
                     StructureNotifyMask;
    swa.background_pixel = 0x000000;
    win = XCreateWindow(dpy, root, x, y, width, height, 0, CopyFromParent,
                        InputOutput, CopyFromParent,
                        CWOverrideRedirect | CWEventMask | CWBackPixel, &swa);
    XStoreName(dpy, win, "NovaLauncher");
    XMapWindow(dpy, win);
    XRaiseWindow(dpy, win);
    XSetInputFocus(dpy, win, RevertToPointerRoot, CurrentTime);

    int done = 0;
    XEvent ev;
    while (!done) {
        XNextEvent(dpy, &ev);
        if (ev.type == Expose) {
            draw();
        } else if (ev.type == KeyPress) {
            KeySym ks = XLookupKeysym(&ev.xkey, 0);
            if (ks == XK_Escape) {
                done = 1;
            } else if (ks == XK_Return) {
                launch();
                done = 1;
            } else if (ks == XK_Down) {
                sel++;
                draw();
            } else if (ks == XK_Up) {
                if (sel > 0) sel--;
                draw();
            } else if (ks == XK_BackSpace) {
                size_t n = strlen(query);
                if (n) { query[n-1] = '\0'; sel = 0; draw(); }
            } else {
                char buf[16]; KeySym k2;
                int n = XLookupString(&ev.xkey, buf, sizeof(buf), &k2, NULL);
                if (n == 1 && buf[0] >= 0x20 && buf[0] < 0x7f) {
                    size_t l = strlen(query);
                    if (l < sizeof(query) - 1) {
                        query[l] = buf[0]; query[l+1] = '\0';
                        sel = 0; draw();
                    }
                }
            }
        }
    }
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}
