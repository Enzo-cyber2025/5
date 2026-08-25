/*
 * theme.h — formato de tema NovaLinux `.novatheme`
 *
 * Um tema `.novatheme` é um arquivo de texto chave=valor que descreve as
 * cores, fontes e métricas da interface. É um formato original da NovaUI,
 * sem qualquer relação com Qt/GTK/EFL/etc.
 *
 * Estrutura do arquivo:
 *
 *   [meta]
 *   name = "Nova Dark"
 *   author = "Nova Project"
 *   version = 1
 *   kind = dark
 *
 *   [colors]
 *   bg = #f7f7fb
 *   bg_alt = #ececf4
 *   fg = #1c1c2e
 *   accent = #3a0ca3
 *   accent_2 = #7209b7
 *   panel_bg = #1a1b3a
 *   ...
 *
 *   [fonts]
 *   ui = "DejaVu Sans 11"
 *   mono = "DejaVu Sans Mono 11"
 *   title = "DejaVu Sans Bold 12"
 *
 *   [metrics]
 *   corner_radius = 10
 *   padding = 8
 *   panel_height = 30
 */
#ifndef NOVA_THEME_H
#define NOVA_THEME_H

#include "common.h"

typedef enum {
    NOVA_THEME_LIGHT = 0,
    NOVA_THEME_DARK  = 1
} NovaThemeKind;

typedef struct {
    char    *name;
    char    *author;
    int      version;
    NovaThemeKind kind;

    /* cores */
    char    *bg;
    char    *bg_alt;
    char    *fg;
    char    *fg_dim;
    char    *accent;
    char    *accent_2;
    char    *panel_bg;
    char    *panel_fg;
    char    *selection;
    char    *border;
    char    *terminal_bg;
    char    *terminal_fg;

    /* fontes */
    char    *font_ui;
    char    *font_mono;
    char    *font_title;

    /* métricas */
    double   corner_radius;
    double   padding;
    int      panel_height;
    char    *wallpaper;   /* caminho do papel de parede (opcional) */
} NovaTheme;

NovaTheme   *nova_theme_load(const char *path);
void         nova_theme_free(NovaTheme *t);
NovaColor    nova_theme_color(const char *hex, NovaColor fallback);
const char  *nova_theme_path_for_kind(NovaThemeKind kind);
void         nova_theme_wallpaper_default(const char *out_path);

#endif /* NOVA_THEME_H */
