/* NovaUI public types — original toolkit, no third-party widget stack. */
#ifndef NOVA_H
#define NOVA_H

#include <stdint.h>
#include <stddef.h>

#define NOVA_THEME_MAGIC "NOVATHEME"
#define NOVA_SOCK_PATH   "/tmp/.novawm"
#define NOVA_CONF_DIR    "/etc/novaui"
#define NOVA_USER_CONF   "/home/nova/.config/novaui"
#define NOVA_THEME_DIR   "/usr/share/novaui/themes"
#define NOVA_APP_DIR     "/usr/share/novaui/apps"
#define NOVA_WALL_DIR    "/usr/share/novaui/wallpapers"

typedef struct {
	uint8_t r, g, b, a;
} NovaColor;

typedef struct {
	int x, y, w, h;
} NovaRect;

typedef struct {
	char name[64];
	char id[32];
	NovaColor bg, fg, accent, panel, window, title, border;
	NovaColor danger, success, muted, input, hover, shadow;
	int radius;
	int font_px;
} NovaTheme;

enum {
	NOVA_EV_NONE = 0,
	NOVA_EV_KEY,
	NOVA_EV_MOUSE,
	NOVA_EV_CLOSE,
	NOVA_EV_RESIZE,
	NOVA_EV_FOCUS
};

typedef struct {
	int type;
	int key;       /* linux keycode or unicode */
	int ch;        /* translated ASCII */
	int mods;      /* bit0 shift bit1 ctrl bit2 alt */
	int mx, my, btn, down;
	int win;
} NovaEvent;

#endif
