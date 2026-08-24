/*
 * theme.c — carregamento de temas `.novatheme` (NovaUI)
 */
#include "theme.h"
#include "common.h"

#include <ctype.h>
#include <strings.h>

/* --- utils de parsing -------------------------------------------------- */
static char *trim(char *s)
{
    while (isspace((unsigned char)*s)) s++;
    char *end = s + strlen(s);
    while (end > s && isspace((unsigned char)end[-1])) *--end = '\0';
    return s;
}

static char *unquote(const char *s)
{
    size_t n = strlen(s);
    if (n >= 2 && s[0] == '"' && s[n - 1] == '"') {
        char *o = strndup(s + 1, n - 2);
        return o;
    }
    return strdup(s);
}

/* NovaColor: converte "#7f2cbf" (hex) -> double r,g,b. */
NovaColor nova_theme_color(const char *hex, NovaColor fallback)
{
    if (!hex)
        return fallback;
    while (*hex == '#' || isspace((unsigned char)*hex)) hex++;
    unsigned long v = strtoul(hex, NULL, 16);
    /* suporta #rgb e #rrggbb e #rrggbbaa */
    size_t len = strlen(hex);
    int r, g, b, a = 255;
    if (len <= 3) {
        r = ((v >> 8) & 0xF) * 17;
        g = ((v >> 4) & 0xF) * 17;
        b = (v & 0xF) * 17;
    } else {
        r = (v >> 16) & 0xFF;
        g = (v >> 8) & 0xFF;
        b = v & 0xFF;
        if (len >= 8)
            a = (v >> 24) & 0xFF;
    }
    NovaColor c = { r / 255.0, g / 255.0, b / 255.0, a / 255.0 };
    return c;
}

const char *nova_theme_path_for_kind(NovaThemeKind kind)
{
    if (kind == NOVA_THEME_LIGHT)
        return NOVA_THEME_DIR "/nova-light.novatheme";
    return NOVA_THEME_DIR "/nova-dark.novatheme";
}

/* --- seção atual durante o parsing -------------------------------------- */
static void parse_line(NovaTheme *t, char *section, char *key, char *val)
{
    if (!section || !key || !val)
        return;

    /* [meta] */
    if (strcmp(section, "meta") == 0) {
        if (strcmp(key, "name") == 0)    { free(t->name);    t->name = unquote(val); }
        else if (strcmp(key, "author") == 0) { free(t->author); t->author = unquote(val); }
        else if (strcmp(key, "version") == 0) t->version = atoi(val);
        else if (strcmp(key, "kind") == 0) {
            if (strcasecmp(val, "light") == 0) t->kind = NOVA_THEME_LIGHT;
            else t->kind = NOVA_THEME_DARK;
        }
    } else if (strcmp(section, "colors") == 0) {
        if      (strcmp(key, "bg") == 0)          t->bg          = unquote(val);
        else if (strcmp(key, "bg_alt") == 0)      t->bg_alt      = unquote(val);
        else if (strcmp(key, "fg") == 0)          t->fg          = unquote(val);
        else if (strcmp(key, "fg_dim") == 0)      t->fg_dim      = unquote(val);
        else if (strcmp(key, "accent") == 0)      t->accent      = unquote(val);
        else if (strcmp(key, "accent_2") == 0)    t->accent_2    = unquote(val);
        else if (strcmp(key, "panel_bg") == 0)    t->panel_bg    = unquote(val);
        else if (strcmp(key, "panel_fg") == 0)    t->panel_fg    = unquote(val);
        else if (strcmp(key, "selection") == 0)   t->selection   = unquote(val);
        else if (strcmp(key, "border") == 0)      t->border      = unquote(val);
        else if (strcmp(key, "terminal_bg") == 0) t->terminal_bg = unquote(val);
        else if (strcmp(key, "terminal_fg") == 0) t->terminal_fg = unquote(val);

    } else if (strcmp(section, "fonts") == 0) {
        if      (strcmp(key, "ui") == 0)     t->font_ui    = unquote(val);
        else if (strcmp(key, "mono") == 0)   t->font_mono  = unquote(val);
        else if (strcmp(key, "title") == 0)  t->font_title = unquote(val);

    } else if (strcmp(section, "metrics") == 0) {
        if      (strcmp(key, "corner_radius") == 0) t->corner_radius = atof(val);
        else if (strcmp(key, "padding") == 0)      t->padding       = atof(val);
        else if (strcmp(key, "panel_height") == 0) t->panel_height  = atoi(val);
        else if (strcmp(key, "wallpaper") == 0)    t->wallpaper     = unquote(val);
    }
}

static void defaults(NovaTheme *t)
{
    t->name    = strdup("Nova Dark");
    t->author  = strdup("Nova Project");
    t->version = 1;
    t->kind    = NOVA_THEME_DARK;

    t->bg          = strdup("#1a1b3a");
    t->bg_alt      = strdup("#24264d");
    t->fg          = strdup("#eaeaf2");
    t->fg_dim      = strdup("#a9aac4");
    t->accent      = strdup("#3a0ca3");
    t->accent_2    = strdup("#7209b7");
    t->panel_bg    = strdup("#12132b");
    t->panel_fg    = strdup("#eaeaf2");
    t->selection   = strdup("#4361ee");
    t->border      = strdup("#3f3f70");
    t->terminal_bg = strdup("#101020");
    t->terminal_fg = strdup("#d8d8f0");

    t->font_ui   = strdup("DejaVu Sans 11");
    t->font_mono = strdup("DejaVu Sans Mono 11");
    t->font_title= strdup("DejaVu Sans Bold 12");

    t->corner_radius = 10.0;
    t->padding       = 8.0;
    t->panel_height  = NOVA_PANEL_HEIGHT;
    t->wallpaper     = strdup("/usr/share/novaui/themes/wallpaper.png");
}

NovaTheme *nova_theme_load(const char *path)
{
    FILE *fp = fopen(path, "r");
    if (!fp) {
        nova_log("tema '%s' não encontrado; usando padrão", path);
        NovaTheme *t = calloc(1, sizeof(NovaTheme));
        defaults(t);
        return t;
    }

    NovaTheme *t = calloc(1, sizeof(NovaTheme));
    defaults(t);

    char line[512];
    char *section = NULL;
    while (fgets(line, sizeof(line), fp)) {
        char *p = trim(line);
        if (*p == '\0' || *p == '#' || *p == ';')
            continue;
        if (*p == '[') {
            char *close = strchr(p, ']');
            if (close) {
                *close = '\0';
                free(section);
                section = strdup(trim(p + 1));
            }
            continue;
        }
        char *eq = strchr(p, '=');
        if (!eq)
            continue;
        *eq = '\0';
        char *key = trim(p);
        char *val = trim(eq + 1);
        parse_line(t, section, key, val);
    }
    free(section);
    fclose(fp);
    nova_log("tema carregado: %s (%s)", t->name,
             t->kind == NOVA_THEME_LIGHT ? "claro" : "escuro");
    return t;
}

void nova_theme_free(NovaTheme *t)
{
    if (!t) return;
    free(t->name); free(t->author);
    free(t->bg); free(t->bg_alt); free(t->fg); free(t->fg_dim);
    free(t->accent); free(t->accent_2);
    free(t->panel_bg); free(t->panel_fg); free(t->selection); free(t->border);
    free(t->terminal_bg); free(t->terminal_fg);
    free(t->font_ui); free(t->font_mono); free(t->font_title);
    free(t->wallpaper);
    free(t);
}
