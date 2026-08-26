/* NovaUI shell — original compositor, panel, files, terminal, settings, launcher.
 * Allowed stack: raw KMS/fbdev + evdev + our own drawing. No foreign DE code.
 */
#define _GNU_SOURCE
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <linux/fb.h>
#include <linux/input.h>
#include <linux/kd.h>
#include <linux/vt.h>
#include <poll.h>
#include <pty.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>

#include "../include/nova.h"
#include "../include/novafont.h"

#define PANEL_H     48
#define TITLE_H     28
#define MAX_WIN     16
#define MAX_TERM_C  120
#define MAX_TERM_R  40
#define TERM_HIST   200
#define MAX_PATH    512
#define MAX_FILES   256

typedef enum {
	W_NONE = 0, W_FILES, W_TERM, W_SETTINGS, W_LAUNCH, W_ABOUT, W_TEXT
} WinKind;

typedef struct {
	int used, kind, x, y, w, h;
	int minx, maxed, focused;
	char title[64];
	/* files */
	char path[MAX_PATH];
	int fcount, fsel, foff;
	char fnames[MAX_FILES][128];
	int fisdir[MAX_FILES];
	/* term */
	int pty, pid;
	char tgrid[TERM_HIST][MAX_TERM_C];
	uint8_t tattr[TERM_HIST][MAX_TERM_C];
	int tcols, trows, tcx, tcy, tscroll, tesc, tescn, tesci[8];
	char tesbuf[32];
	/* settings */
	int spage, ssel;
	/* text viewer */
	char tbuf[8192];
	int toff;
} Win;

static uint32_t *fb, *back;
static int fbfd = -1, fbw, fbh, fbpitch, fb_bpp = 32;
static size_t fb_map_len;
static int evfds[16], nev;
static int mx, my, mbtn, shift, ctrl, alt, caps;
static int running = 1;
static Win wins[MAX_WIN];
static int nwin, focus = -1, drag = -1, dragox, dragoy;
static int menu_open, launch_open, launch_sel;
static char launch_q[128];
static NovaTheme theme;
static char themename[32] = "dark";
static int vol = 70, bright = 80, pointer_speed = 1;
static char kb_layout[16] = "us";
static int last_click_ms, last_click_x, last_click_y;
static volatile int resized;

static uint32_t col(NovaColor c)
{
	return ((uint32_t)c.a << 24) | ((uint32_t)c.r << 16) | ((uint32_t)c.g << 8) | c.b;
}

static NovaColor rgb(int r, int g, int b)
{
	NovaColor c = { (uint8_t)r, (uint8_t)g, (uint8_t)b, 255 };
	return c;
}

static void theme_dark(void)
{
	memset(&theme, 0, sizeof(theme));
	snprintf(theme.name, sizeof(theme.name), "Nova Dark");
	snprintf(theme.id, sizeof(theme.id), "dark");
	theme.bg = rgb(16, 18, 32);
	theme.fg = rgb(236, 236, 244);
	theme.accent = rgb(124, 92, 228);
	theme.panel = rgb(18, 20, 36);
	theme.window = rgb(28, 30, 48);
	theme.title = rgb(22, 24, 40);
	theme.border = rgb(96, 78, 186);
	theme.danger = rgb(228, 78, 90);
	theme.success = rgb(72, 196, 140);
	theme.muted = rgb(140, 144, 168);
	theme.input = rgb(20, 22, 38);
	theme.hover = rgb(48, 44, 80);
	theme.shadow = rgb(0, 0, 0);
	theme.radius = 8;
	theme.font_px = 16;
}

static void theme_light(void)
{
	memset(&theme, 0, sizeof(theme));
	snprintf(theme.name, sizeof(theme.name), "Nova Light");
	snprintf(theme.id, sizeof(theme.id), "light");
	theme.bg = rgb(232, 236, 248);
	theme.fg = rgb(28, 30, 46);
	theme.accent = rgb(98, 70, 196);
	theme.panel = rgb(246, 246, 252);
	theme.window = rgb(255, 255, 255);
	theme.title = rgb(240, 240, 248);
	theme.border = rgb(160, 150, 210);
	theme.danger = rgb(196, 48, 64);
	theme.success = rgb(32, 148, 96);
	theme.muted = rgb(96, 100, 120);
	theme.input = rgb(236, 236, 244);
	theme.hover = rgb(226, 222, 246);
	theme.shadow = rgb(180, 180, 196);
	theme.radius = 8;
	theme.font_px = 16;
}

static int load_theme_file(const char *path)
{
	FILE *f = fopen(path, "r");
	char line[256], key[64], val[160];
	if (!f)
		return -1;
	while (fgets(line, sizeof(line), f)) {
		if (line[0] == '#' || line[0] == '\n')
			continue;
		if (sscanf(line, "%63[^=]=%159[^\n]", key, val) != 2)
			continue;
		if (!strcmp(key, "name")) snprintf(theme.name, sizeof(theme.name), "%s", val);
		else if (!strcmp(key, "id")) snprintf(theme.id, sizeof(theme.id), "%s", val);
		else {
			int r, g, b, a = 255;
			if (sscanf(val, "%d,%d,%d,%d", &r, &g, &b, &a) >= 3) {
				NovaColor c = { (uint8_t)r, (uint8_t)g, (uint8_t)b, (uint8_t)a };
				if (!strcmp(key, "bg")) theme.bg = c;
				else if (!strcmp(key, "fg")) theme.fg = c;
				else if (!strcmp(key, "accent")) theme.accent = c;
				else if (!strcmp(key, "panel")) theme.panel = c;
				else if (!strcmp(key, "window")) theme.window = c;
				else if (!strcmp(key, "title")) theme.title = c;
				else if (!strcmp(key, "border")) theme.border = c;
				else if (!strcmp(key, "danger")) theme.danger = c;
				else if (!strcmp(key, "success")) theme.success = c;
				else if (!strcmp(key, "muted")) theme.muted = c;
				else if (!strcmp(key, "input")) theme.input = c;
				else if (!strcmp(key, "hover")) theme.hover = c;
			} else if (!strcmp(key, "radius")) theme.radius = atoi(val);
			else if (!strcmp(key, "font_size")) theme.font_px = atoi(val);
		}
	}
	fclose(f);
	return 0;
}

static uint32_t blend(uint32_t d, uint32_t s, int a)
{
	int r1 = (d >> 16) & 255, g1 = (d >> 8) & 255, b1 = d & 255;
	int r2 = (s >> 16) & 255, g2 = (s >> 8) & 255, b2 = s & 255;
	int r = (r2 * a + r1 * (255 - a)) / 255;
	int g = (g2 * a + g1 * (255 - a)) / 255;
	int b = (b2 * a + b1 * (255 - a)) / 255;
	return 0xff000000 | (r << 16) | (g << 8) | b;
}

static void pset(int x, int y, uint32_t c)
{
	if ((unsigned)x >= (unsigned)fbw || (unsigned)y >= (unsigned)fbh)
		return;
	back[y * fbw + x] = c;
}

static void pseta(int x, int y, uint32_t c, int a)
{
	if ((unsigned)x >= (unsigned)fbw || (unsigned)y >= (unsigned)fbh)
		return;
	back[y * fbw + x] = blend(back[y * fbw + x], c, a);
}

static void fill(int x, int y, int w, int h, uint32_t c)
{
	int xx, yy;
	if (x < 0) { w += x; x = 0; }
	if (y < 0) { h += y; y = 0; }
	if (x + w > fbw) w = fbw - x;
	if (y + h > fbh) h = fbh - y;
	if (w <= 0 || h <= 0) return;
	for (yy = 0; yy < h; yy++) {
		uint32_t *row = back + (y + yy) * fbw + x;
		for (xx = 0; xx < w; xx++)
			row[xx] = c;
	}
}

static void fillr(int x, int y, int w, int h, uint32_t c, int rad)
{
	int yy, xx, r = rad;
	if (r < 0) r = 0;
	if (r * 2 > h) r = h / 2;
	if (r * 2 > w) r = w / 2;
	for (yy = 0; yy < h; yy++) {
		int inset = 0;
		if (yy < r) {
			int dy = r - 1 - yy;
			inset = r - (int)(0.5 + sqrt((double)(r * r - dy * dy)));
		} else if (yy >= h - r) {
			int dy = yy - (h - r);
			inset = r - (int)(0.5 + sqrt((double)(r * r - dy * dy)));
		}
		for (xx = inset; xx < w - inset; xx++)
			pset(x + xx, y + yy, c);
	}
}

static void rect(int x, int y, int w, int h, uint32_t c)
{
	int i;
	for (i = 0; i < w; i++) {
		pset(x + i, y, c);
		pset(x + i, y + h - 1, c);
	}
	for (i = 0; i < h; i++) {
		pset(x, y + i, c);
		pset(x + w - 1, y + i, c);
	}
}

static void glyph(int x, int y, unsigned char ch, uint32_t c)
{
	int row, col;
	const uint8_t *g = nova_font8x16[ch];
	for (row = 0; row < 16; row++) {
		uint8_t bits = g[row];
		for (col = 0; col < 8; col++)
			if (bits & (0x80 >> col))
				pset(x + col, y + row, c);
	}
}

static void text(int x, int y, const char *s, uint32_t c)
{
	int ox = x;
	while (*s) {
		unsigned char ch = (unsigned char)*s++;
		if (ch == '\n') { y += 16; x = ox; continue; }
		glyph(x, y, ch, c);
		x += 8;
	}
}

static void textn(int x, int y, const char *s, int n, uint32_t c)
{
	int i;
	for (i = 0; i < n && s[i]; i++)
		glyph(x + i * 8, y, (unsigned char)s[i], c);
}

static int textw(const char *s)
{
	return (int)strlen(s) * 8;
}

static int hit(int x, int y, int bx, int by, int bw, int bh)
{
	return x >= bx && y >= by && x < bx + bw && y < by + bh;
}

static long now_ms(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec * 1000L + ts.tv_nsec / 1000000L;
}

static void glyph_scaled(int x, int y, unsigned char ch, uint32_t c, int s)
{
	int row, col, dy, dx;
	const uint8_t *g = nova_font8x16[ch];
	if (s < 1) s = 1;
	for (row = 0; row < 16; row++) {
		uint8_t bits = g[row];
		for (col = 0; col < 8; col++) {
			if (!(bits & (0x80 >> col)))
				continue;
			for (dy = 0; dy < s; dy++)
				for (dx = 0; dx < s; dx++)
					pset(x + col * s + dx, y + row * s + dy, c);
		}
	}
}

static void text_scaled(int x, int y, const char *s, uint32_t c, int sc)
{
	while (*s) {
		glyph_scaled(x, y, (unsigned char)*s++, c, sc);
		x += 8 * sc;
	}
}

static void draw_wallpaper(void)
{
	int x, y;
	/* Bright violet desktop — impossible to mistake for a black console. */
	for (y = 0; y < fbh; y++) {
		for (x = 0; x < fbw; x++) {
			float u = (float)x / (float)(fbw ? fbw : 1);
			float v = (float)y / (float)(fbh ? fbh : 1);
			int r = (int)(70 + 90 * u + 40 * (1.0f - v));
			int g = (int)(90 + 40 * u + 80 * (1.0f - v));
			int b = (int)(170 + 70 * u + 20 * v);
			if (r > 255) r = 255;
			if (g > 255) g = 255;
			if (b > 255) b = 255;
			back[y * fbw + x] = 0xff000000 | (r << 16) | (g << 8) | b;
		}
	}
	text_scaled(24, 18, "NOVALINUX", 0xffffffff, 4);
	text(28, 90, "NovaUI 1.0   user nova   Alt+Space launcher   type in the Terminal", 0xfff4f0ff);
}

static void present(void)
{
	if (fb_bpp == 32 && fbpitch == fbw * 4) {
		memcpy(fb, back, (size_t)fbw * fbh * 4);
	} else if (fb_bpp == 32) {
		int y;
		for (y = 0; y < fbh; y++)
			memcpy((uint8_t *)fb + y * fbpitch, back + y * fbw, (size_t)fbw * 4);
	} else if (fb_bpp == 24) {
		int x, y;
		for (y = 0; y < fbh; y++) {
			uint8_t *dst = (uint8_t *)fb + y * fbpitch;
			uint32_t *src = back + y * fbw;
			for (x = 0; x < fbw; x++) {
				uint32_t c = src[x];
				dst[x * 3 + 0] = (uint8_t)(c);
				dst[x * 3 + 1] = (uint8_t)(c >> 8);
				dst[x * 3 + 2] = (uint8_t)(c >> 16);
			}
		}
	} else if (fb_bpp == 16) {
		int x, y;
		for (y = 0; y < fbh; y++) {
			uint16_t *dst = (uint16_t *)((uint8_t *)fb + y * fbpitch);
			uint32_t *src = back + y * fbw;
			for (x = 0; x < fbw; x++) {
				uint32_t c = src[x];
				dst[x] = (uint16_t)(((c >> 8) & 0xf800) | ((c >> 5) & 0x07e0) | ((c >> 3) & 0x1f));
			}
		}
	}
}

static int fb_open(void)
{
	struct fb_var_screeninfo v;
	struct fb_fix_screeninfo f;
	const char *devs[] = { "/dev/fb0", "/dev/graphics/fb0", NULL };
	int i;
	for (i = 0; devs[i]; i++) {
		fbfd = open(devs[i], O_RDWR);
		if (fbfd >= 0)
			break;
	}
	if (fbfd < 0)
		return -1;
	if (ioctl(fbfd, FBIOGET_VSCREENINFO, &v) < 0 || ioctl(fbfd, FBIOGET_FSCREENINFO, &f) < 0) {
		close(fbfd);
		fbfd = -1;
		return -1;
	}
	fbw = v.xres;
	fbh = v.yres;
	fb_bpp = v.bits_per_pixel;
	fbpitch = f.line_length;
	if (fbw < 640) fbw = 640;
	if (fbh < 480) fbh = 480;
	fb_map_len = (size_t)f.smem_len;
	if (fb_map_len < (size_t)fbpitch * fbh)
		fb_map_len = (size_t)fbpitch * fbh;
	fb = mmap(NULL, fb_map_len, PROT_READ | PROT_WRITE, MAP_SHARED, fbfd, 0);
	if (fb == MAP_FAILED) {
		close(fbfd);
		fbfd = -1;
		fb = NULL;
		return -1;
	}
	back = mmap(NULL, (size_t)fbw * fbh * 4, PROT_READ | PROT_WRITE,
		    MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
	if (back == MAP_FAILED) {
		back = calloc((size_t)fbw * fbh, 4);
		if (!back)
			return -1;
	}
	mx = fbw / 2;
	my = fbh / 2;
	return 0;
}

static void evdev_open(void)
{
	int i;
	char path[64];
	nev = 0;
	for (i = 0; i < 32 && nev < 16; i++) {
		int fd;
		snprintf(path, sizeof(path), "/dev/input/event%d", i);
		fd = open(path, O_RDONLY | O_NONBLOCK);
		if (fd >= 0)
			evfds[nev++] = fd;
	}
}

static const char *us_plain = "????????\b\t`1234567890-=\b\0qwertyuiop[]\n\0asdfghjkl;'\0\\zxcvbnm,./";
/* fallback translator */
static int key_to_ch(int code, int sh)
{
	static const char *norm = "0123456789abcdefghijklmnopqrstuvwxyz";
	if (code >= KEY_1 && code <= KEY_0) {
		const char *n = "1234567890", *s = "!@#$%^&*()";
		int i = (code == KEY_0) ? 9 : code - KEY_1;
		return sh ? s[i] : n[i];
	}
	if (code >= KEY_Q && code <= KEY_P) {
		const char *n = "qwertyuiop", *s = "QWERTYUIOP";
		return sh ? s[code - KEY_Q] : n[code - KEY_Q];
	}
	if (code >= KEY_A && code <= KEY_L) {
		const char *n = "asdfghjkl", *s = "ASDFGHJKL";
		return sh ? s[code - KEY_A] : n[code - KEY_A];
	}
	if (code >= KEY_Z && code <= KEY_M) {
		const char *n = "zxcvbnm", *s = "ZXCVBNM";
		return sh ? s[code - KEY_Z] : n[code - KEY_Z];
	}
	switch (code) {
	case KEY_SPACE: return ' ';
	case KEY_ENTER: case KEY_KPENTER: return '\n';
	case KEY_BACKSPACE: return '\b';
	case KEY_TAB: return '\t';
	case KEY_MINUS: return sh ? '_' : '-';
	case KEY_EQUAL: return sh ? '+' : '=';
	case KEY_LEFTBRACE: return sh ? '{' : '[';
	case KEY_RIGHTBRACE: return sh ? '}' : ']';
	case KEY_SEMICOLON: return sh ? ':' : ';';
	case KEY_APOSTROPHE: return sh ? '"' : '\'';
	case KEY_GRAVE: return sh ? '~' : '`';
	case KEY_BACKSLASH: return sh ? '|' : '\\';
	case KEY_COMMA: return sh ? '<' : ',';
	case KEY_DOT: return sh ? '>' : '.';
	case KEY_SLASH: return sh ? '?' : '/';
	default: return 0;
	}
	(void)norm;
	(void)us_plain;
}

static int cmpstr(const void *a, const void *b)
{
	return strcasecmp((const char *)a, (const char *)b);
}

static void files_reload(Win *w)
{
	DIR *d;
	struct dirent *de;
	w->fcount = 0;
	w->fsel = 0;
	w->foff = 0;
	d = opendir(w->path[0] ? w->path : "/");
	if (!d)
		return;
	while ((de = readdir(d)) && w->fcount < MAX_FILES) {
		struct stat st;
		char full[MAX_PATH];
		if (!strcmp(de->d_name, "."))
			continue;
		snprintf(full, sizeof(full), "%s/%s", w->path, de->d_name);
		snprintf(w->fnames[w->fcount], 128, "%s", de->d_name);
		w->fisdir[w->fcount] = 0;
		if (stat(full, &st) == 0 && S_ISDIR(st.st_mode))
			w->fisdir[w->fcount] = 1;
		w->fcount++;
	}
	closedir(d);
}

static void term_putc(Win *w, unsigned char ch)
{
	int r, c;
	if (ch == '\r') { w->tcx = 0; return; }
	if (ch == '\n') {
		w->tcx = 0;
		w->tcy++;
		if (w->tcy >= w->trows) {
			w->tcy = w->trows - 1;
			memmove(w->tgrid[0], w->tgrid[1], (size_t)(w->trows - 1) * MAX_TERM_C);
			memset(w->tgrid[w->trows - 1], ' ', MAX_TERM_C);
		}
		return;
	}
	if (ch == '\b') {
		if (w->tcx > 0) w->tcx--;
		return;
	}
	if (ch == '\t') {
		w->tcx = (w->tcx + 8) & ~7;
		if (w->tcx >= w->tcols) { w->tcx = 0; term_putc(w, '\n'); }
		return;
	}
	if (ch < 32)
		return;
	if (w->tcx >= w->tcols) {
		w->tcx = 0;
		term_putc(w, '\n');
	}
	r = w->tcy;
	c = w->tcx;
	if (r >= 0 && r < w->trows && c >= 0 && c < w->tcols)
		w->tgrid[r][c] = (char)ch;
	w->tcx++;
}

static void term_write(Win *w, const char *s, int n)
{
	int i;
	for (i = 0; i < n; i++) {
		unsigned char ch = (unsigned char)s[i];
		if (w->tesc == 1) {
			if (ch == '[') { w->tesc = 2; w->tescn = 0; w->tesci[0] = 0; continue; }
			w->tesc = 0;
			continue;
		}
		if (w->tesc == 2) {
			if (isdigit(ch)) {
				w->tesci[w->tescn] = w->tesci[w->tescn] * 10 + (ch - '0');
				continue;
			}
			if (ch == ';') {
				if (w->tescn < 7) { w->tescn++; w->tesci[w->tescn] = 0; }
				continue;
			}
			if (ch == 'H' || ch == 'f') {
				int rr = w->tesci[0] ? w->tesci[0] - 1 : 0;
				int cc = (w->tescn >= 1 && w->tesci[1]) ? w->tesci[1] - 1 : 0;
				if (rr < 0) rr = 0;
				if (cc < 0) cc = 0;
				if (rr >= w->trows) rr = w->trows - 1;
				if (cc >= w->tcols) cc = w->tcols - 1;
				w->tcy = rr; w->tcx = cc;
			} else if (ch == 'J') {
				memset(w->tgrid, ' ', sizeof(w->tgrid));
				w->tcx = w->tcy = 0;
			} else if (ch == 'K') {
				if (w->tcy >= 0 && w->tcy < w->trows)
					memset(w->tgrid[w->tcy] + w->tcx, ' ', (size_t)(w->tcols - w->tcx));
			} else if (ch == 'C') {
				w->tcx += w->tesci[0] ? w->tesci[0] : 1;
				if (w->tcx >= w->tcols) w->tcx = w->tcols - 1;
			} else if (ch == 'D') {
				w->tcx -= w->tesci[0] ? w->tesci[0] : 1;
				if (w->tcx < 0) w->tcx = 0;
			} else if (ch == 'A') {
				w->tcy -= w->tesci[0] ? w->tesci[0] : 1;
				if (w->tcy < 0) w->tcy = 0;
			} else if (ch == 'B') {
				w->tcy += w->tesci[0] ? w->tesci[0] : 1;
				if (w->tcy >= w->trows) w->tcy = w->trows - 1;
			} else if (ch == 'm') {
				/* color CSI ignored — keep default */
			}
			w->tesc = 0;
			continue;
		}
		if (ch == 0x1b) { w->tesc = 1; continue; }
		term_putc(w, ch);
	}
}

static int spawn_pty(Win *w)
{
	int m;
	pid_t pid;
	w->tcols = (w->w - 16) / 8;
	w->trows = (w->h - TITLE_H - 12) / 16;
	if (w->tcols < 20) w->tcols = 20;
	if (w->tcols > MAX_TERM_C) w->tcols = MAX_TERM_C;
	if (w->trows < 8) w->trows = 8;
	if (w->trows > MAX_TERM_R) w->trows = MAX_TERM_R;
	memset(w->tgrid, ' ', sizeof(w->tgrid));
	w->tcx = w->tcy = w->tesc = 0;
	pid = forkpty(&m, NULL, NULL, NULL);
	if (pid < 0)
		return -1;
	if (pid == 0) {
		setenv("TERM", "linux", 1);
		setenv("HOME", "/home/nova", 1);
		setenv("USER", "nova", 1);
		setenv("PATH", "/usr/local/bin:/usr/bin:/bin:/sbin", 1);
		setenv("PS1", "nova@novastation:\\w$ ", 1);
		chdir("/home/nova");
		execl("/bin/sh", "sh", "-l", (char *)NULL);
		_exit(127);
	}
	fcntl(m, F_SETFL, O_NONBLOCK);
	w->pty = m;
	w->pid = pid;
	return 0;
}

static int alloc_win(WinKind k, const char *title, int x, int y, int w, int h)
{
	int i;
	for (i = 0; i < MAX_WIN; i++) {
		if (!wins[i].used) {
			memset(&wins[i], 0, sizeof(wins[i]));
			wins[i].used = 1;
			wins[i].kind = k;
			wins[i].x = x;
			wins[i].y = y;
			wins[i].w = w;
			wins[i].h = h;
			snprintf(wins[i].title, sizeof(wins[i].title), "%s", title);
			if (i >= nwin) nwin = i + 1;
			focus = i;
			if (k == W_FILES) {
				snprintf(wins[i].path, sizeof(wins[i].path), "/home/nova");
				if (access(wins[i].path, R_OK) != 0)
					snprintf(wins[i].path, sizeof(wins[i].path), "/");
				files_reload(&wins[i]);
			} else if (k == W_TERM) {
				spawn_pty(&wins[i]);
			}
			return i;
		}
	}
	return -1;
}

static void close_win(int i)
{
	if (i < 0 || !wins[i].used) return;
	if (wins[i].pty > 0) close(wins[i].pty);
	if (wins[i].pid > 0) kill(wins[i].pid, SIGHUP);
	wins[i].used = 0;
	if (focus == i) {
		int j;
		focus = -1;
		for (j = nwin - 1; j >= 0; j--)
			if (wins[j].used) { focus = j; break; }
	}
}

static void raise_win(int i)
{
	focus = i;
}

static void draw_btn(int x, int y, int w, int h, const char *lab, int hover, int acc)
{
	uint32_t bg = acc ? col(theme.accent) : (hover ? col(theme.hover) : col(theme.input));
	fillr(x, y, w, h, bg, 6);
	text(x + (w - textw(lab)) / 2, y + (h - 16) / 2, lab, col(theme.fg));
}

static void draw_win(Win *w, int idx)
{
	int x = w->x, y = w->y, ww = w->w, hh = w->h;
	int focused = (idx == focus);
	uint32_t wb = col(theme.window), tb = col(theme.title), fg = col(theme.fg);
	int i, vis, row;
	fillr(x + 3, y + 4, ww, hh, 0x40000000, 6);
	fillr(x, y, ww, hh, wb, 6);
	fillr(x, y, ww, TITLE_H, tb, 6);
	fill(x, y + 12, ww, TITLE_H - 12, tb);
	rect(x, y, ww, hh, focused ? col(theme.accent) : col(theme.border));
	text(x + 10, y + 6, w->title, fg);
	/* close */
	fillr(x + ww - 26, y + 6, 16, 16, col(theme.danger), 4);
	text(x + ww - 23, y + 6, "x", 0xffffffff);
	/* max */
	fillr(x + ww - 48, y + 6, 16, 16, col(theme.muted), 4);
	text(x + ww - 45, y + 6, "+", fg);

	if (w->kind == W_FILES) {
		int lh = 20, y0 = y + TITLE_H + 8;
		fill(x + 8, y + TITLE_H + 4, ww - 16, 22, col(theme.input));
		textn(x + 12, y + TITLE_H + 6, w->path, (ww - 28) / 8, col(theme.muted));
		vis = (hh - TITLE_H - 40) / lh;
		if (vis < 1) vis = 1;
		if (w->fsel < w->foff) w->foff = w->fsel;
		if (w->fsel >= w->foff + vis) w->foff = w->fsel - vis + 1;
		for (i = 0; i < vis && i + w->foff < w->fcount; i++) {
			int yy = y0 + 24 + i * lh;
			int sel = (i + w->foff == w->fsel);
			if (sel) fill(x + 8, yy, ww - 16, lh, col(theme.hover));
			text(x + 14, yy + 2, w->fisdir[i + w->foff] ? ">" : " ", col(theme.accent));
			textn(x + 28, yy + 2, w->fnames[i + w->foff], (ww - 44) / 8, fg);
		}
	} else if (w->kind == W_TERM) {
		int cx, cy;
		fill(x + 6, y + TITLE_H + 4, ww - 12, hh - TITLE_H - 10, 0xff101018);
		for (row = 0; row < w->trows; row++) {
			for (cx = 0; cx < w->tcols; cx++) {
				char ch = w->tgrid[row][cx] ? w->tgrid[row][cx] : ' ';
				glyph(x + 10 + cx * 8, y + TITLE_H + 8 + row * 16, (unsigned char)ch, 0xffd0d8e8);
			}
		}
		cx = x + 10 + w->tcx * 8;
		cy = y + TITLE_H + 8 + w->tcy * 16;
		if (((now_ms() / 400) & 1) == 0)
			fill(cx, cy, 8, 16, col(theme.accent));
	} else if (w->kind == W_SETTINGS) {
		static const char *pages[] = {
			"Network", "Audio", "Video", "Keyboard", "Mouse", "Power", "Appearance"
		};
		int p;
		fill(x + 8, y + TITLE_H + 8, 140, hh - TITLE_H - 16, col(theme.input));
		for (p = 0; p < 7; p++) {
			int yy = y + TITLE_H + 16 + p * 28;
			if (p == w->spage) fill(x + 10, yy - 4, 136, 24, col(theme.hover));
			text(x + 18, yy, pages[p], p == w->spage ? col(theme.accent) : fg);
		}
		{
			int px = x + 160, py = y + TITLE_H + 20;
			char buf[128];
			text(px, py, pages[w->spage], col(theme.accent));
			py += 28;
			if (w->spage == 0) {
				text(px, py, "Interface: eth0   (udhcpc)", fg); py += 20;
				text(px, py, "Status:    offline-ready", col(theme.muted)); py += 20;
				text(px, py, "Hostname:  novastation", fg); py += 28;
				draw_btn(px, py, 140, 28, "Renew DHCP", 0, 1);
			} else if (w->spage == 1) {
				snprintf(buf, sizeof(buf), "Output volume: %d%%", vol);
				text(px, py, buf, fg); py += 24;
				fill(px, py, 200, 10, col(theme.input));
				fill(px, py, vol * 2, 10, col(theme.accent));
				py += 28;
				text(px, py, "Backend: NovaMix (PipeWire-ready)", col(theme.muted));
			} else if (w->spage == 2) {
				snprintf(buf, sizeof(buf), "Framebuffer: %dx%d %dbpp", fbw, fbh, fb_bpp);
				text(px, py, buf, fg); py += 20;
				snprintf(buf, sizeof(buf), "Brightness: %d%%", bright);
				text(px, py, buf, fg); py += 24;
				fill(px, py, 200, 10, col(theme.input));
				fill(px, py, bright * 2, 10, col(theme.accent));
			} else if (w->spage == 3) {
				snprintf(buf, sizeof(buf), "Layout: %s  (en_US / pt_BR / es_ES / fr_FR)", kb_layout);
				text(px, py, buf, fg); py += 20;
				text(px, py, "Repeat: 25 Hz   Delay: 250 ms", col(theme.muted));
			} else if (w->spage == 4) {
				text(px, py, "Acceleration: low (N5030)", fg); py += 20;
				text(px, py, "Left-handed: no", fg);
			} else if (w->spage == 5) {
				text(px, py, "CPU governor: schedutil", fg); py += 20;
				text(px, py, "Idle: intel_idle max_cstate=4", fg); py += 20;
				text(px, py, "Swap: zram zstd   swappiness=10", fg); py += 28;
				draw_btn(px, py, 120, 28, "Suspend", 0, 0);
				draw_btn(px + 132, py, 120, 28, "Power off", 0, 1);
			} else if (w->spage == 6) {
				snprintf(buf, sizeof(buf), "Theme: %s", theme.name);
				text(px, py, buf, fg); py += 28;
				draw_btn(px, py, 120, 28, "Dark", !strcmp(theme.id, "dark"), 1);
				draw_btn(px + 132, py, 120, 28, "Light", !strcmp(theme.id, "light"), 0);
			}
		}
	} else if (w->kind == W_ABOUT) {
		text(x + 20, y + TITLE_H + 24, "NovaLinux 1.0  (Goldmont Plus)", fg);
		text(x + 20, y + TITLE_H + 48, "NovaUI  — original desktop", col(theme.muted));
		text(x + 20, y + TITLE_H + 68, "OpenRC init   NovaPKG packages", col(theme.muted));
		text(x + 20, y + TITLE_H + 88, "User nova   host novastation", col(theme.muted));
		text(x + 20, y + TITLE_H + 120, "Alt+Space  launcher", fg);
		text(x + 20, y + TITLE_H + 140, "Alt+F4     close window", fg);
		text(x + 20, y + TITLE_H + 160, "Alt+Tab    cycle windows", fg);
	} else if (w->kind == W_TEXT) {
		const char *s = w->tbuf + w->toff;
		int yy = y + TITLE_H + 10;
		while (*s && yy < y + hh - 20) {
			char line[128];
			int n = 0;
			while (s[n] && s[n] != '\n' && n < 120) n++;
			memcpy(line, s, n); line[n] = 0;
			text(x + 12, yy, line, fg);
			s += n + (s[n] == '\n' ? 1 : 0);
			yy += 16;
		}
	}
}

static void draw_panel(void)
{
	char clk[32], ram[32];
	time_t t = time(NULL);
	struct tm *tm = localtime(&t);
	int i, tx;
	FILE *f;
	unsigned long memt = 0, memf = 0;
	fill(0, fbh - PANEL_H, fbw, PANEL_H, col(theme.panel));
	fill(0, fbh - PANEL_H, fbw, 1, col(theme.border));
	draw_btn(10, fbh - PANEL_H + 8, 88, 32, " Nova ", menu_open, 1);
	tx = 110;
	for (i = 0; i < MAX_WIN; i++) {
		if (!wins[i].used) continue;
		int hover = hit(mx, my, tx, fbh - PANEL_H + 8, 120, 32);
		draw_btn(tx, fbh - PANEL_H + 8, 120, 32, wins[i].title, hover || i == focus, 0);
		tx += 128;
		if (tx > fbw - 280) break;
	}
	strftime(clk, sizeof(clk), "%a %d  %H:%M", tm);
	f = fopen("/proc/meminfo", "r");
	if (f) {
		char line[80];
		while (fgets(line, sizeof(line), f)) {
			if (!strncmp(line, "MemTotal:", 9)) memt = strtoul(line + 9, NULL, 10);
			if (!strncmp(line, "MemAvailable:", 13)) memf = strtoul(line + 13, NULL, 10);
		}
		fclose(f);
	}
	if (memt)
		snprintf(ram, sizeof(ram), "%luM", (memt - memf) / 1024);
	else
		snprintf(ram, sizeof(ram), "--");
	text(fbw - 210, fbh - 32, ram, col(theme.muted));
	text(fbw - 150, fbh - 32, clk, col(theme.fg));
}

static void draw_menu(void)
{
	static const char *items[] = {
		"Files", "Terminal", "Settings", "Launcher", "About", "Suspend", "Power off"
	};
	int i, x = 10, y = fbh - PANEL_H - 8 - 7 * 32, w = 180;
	if (y < 8) y = 8;
	fillr(x, y, w, 7 * 32 + 8, col(theme.window), 8);
	rect(x, y, w, 7 * 32 + 8, col(theme.border));
	for (i = 0; i < 7; i++) {
		int yy = y + 6 + i * 32;
		int hov = hit(mx, my, x, yy, w, 30);
		if (hov) fill(x + 4, yy, w - 8, 28, col(theme.hover));
		text(x + 16, yy + 6, items[i], col(theme.fg));
	}
}

static void collect_apps(char names[][64], char cmds[][128], int *n)
{
	static const char *bn[] = { "Files", "Terminal", "Settings", "About", "novafetch", "vi", "top", "NovaPKG" };
	static const char *bc[] = { "files", "term", "settings", "about", "fetch", "vi", "top", "pkg" };
	int i;
	*n = 0;
	for (i = 0; i < 8; i++) {
		if (launch_q[0] && !strcasestr(bn[i], launch_q))
			continue;
		snprintf(names[*n], 64, "%s", bn[i]);
		snprintf(cmds[*n], 128, "%s", bc[i]);
		(*n)++;
	}
}

static void draw_launcher(void)
{
	char names[16][64], cmds[16][128];
	int n = 0, i;
	int w = 420, h = 280;
	int x = (fbw - w) / 2, y = fbh / 5;
	collect_apps(names, cmds, &n);
	fillr(x + 4, y + 6, w, h, 0x66000000, 10);
	fillr(x, y, w, h, col(theme.window), 10);
	rect(x, y, w, h, col(theme.accent));
	text(x + 16, y + 14, "Nova Launch   Alt+Space", col(theme.muted));
	fillr(x + 16, y + 40, w - 32, 28, col(theme.input), 6);
	text(x + 24, y + 46, launch_q[0] ? launch_q : "Type to filter...", launch_q[0] ? col(theme.fg) : col(theme.muted));
	for (i = 0; i < n && i < 8; i++) {
		int yy = y + 80 + i * 24;
		if (i == launch_sel) fill(x + 16, yy - 2, w - 32, 22, col(theme.hover));
		text(x + 28, yy, names[i], col(theme.fg));
	}
	(void)cmds;
}

static void draw_cursor(void)
{
	int i;
	for (i = 0; i < 14; i++) {
		pset(mx, my + i, 0xffffffff);
		if (i < 10) pset(mx + i, my, 0xffffffff);
	}
	for (i = 0; i < 12; i++)
		pset(mx + 1 + i / 2, my + 1 + i, 0xff202028);
}

static void run_cmd(const char *cmd)
{
	if (!strcmp(cmd, "files"))
		alloc_win(W_FILES, "Files", 80, 60, 640, 420);
	else if (!strcmp(cmd, "term"))
		alloc_win(W_TERM, "Terminal", 120, 80, 720, 440);
	else if (!strcmp(cmd, "settings"))
		alloc_win(W_SETTINGS, "Settings", 100, 70, 700, 460);
	else if (!strcmp(cmd, "about"))
		alloc_win(W_ABOUT, "About NovaLinux", 200, 140, 460, 280);
	else if (!strcmp(cmd, "launch")) {
		launch_open = 1;
		launch_q[0] = 0;
		launch_sel = 0;
	} else if (!strcmp(cmd, "suspend")) {
		int fd = open("/sys/power/state", O_WRONLY);
		if (fd >= 0) { if (write(fd, "mem\n", 4) < 0) {} close(fd); }
	} else if (!strcmp(cmd, "poweroff")) {
		running = 0;
		sync();
		if (fork() == 0) { execl("/sbin/poweroff", "poweroff", (char *)NULL); _exit(0); }
	} else if (!strcmp(cmd, "fetch")) {
		int id = alloc_win(W_TEXT, "novafetch", 160, 100, 520, 320);
		if (id >= 0) {
			snprintf(wins[id].tbuf, sizeof(wins[id].tbuf),
				 "nova@novastation\n------------\nOS: NovaLinux 1.0\nHost: novastation\nKernel: Linux 6.6 LTS\nCPU: Intel Pentium N5030\nArch: x86_64 Goldmont Plus\nInit: OpenRC\nDE: NovaUI\nWM: novawm\nShell: ash\nPackages: NovaPKG\nTheme: %s\n",
				 theme.name);
		}
	} else if (!strcmp(cmd, "pkg")) {
		int id = alloc_win(W_TEXT, "NovaPKG", 140, 90, 560, 340);
		if (id >= 0)
			snprintf(wins[id].tbuf, sizeof(wins[id].tbuf),
				 "NovaPKG 1.0\n\nnovapkg install <name|.nvpkg>\nnovapkg remove  <name>\nnovapkg update\nnovapkg search  <query>\nnovapkg info    <name>\n\nPackages live in /var/lib/novapkg\nFormat: tar.xz + metadata.json\n");
	}
}

static void menu_click(void)
{
	static const char *cmds[] = { "files", "term", "settings", "launch", "about", "suspend", "poweroff" };
	int y = fbh - PANEL_H - 8 - 7 * 32, i;
	if (y < 8) y = 8;
	for (i = 0; i < 7; i++) {
		if (hit(mx, my, 10, y + 6 + i * 32, 180, 30)) {
			run_cmd(cmds[i]);
			menu_open = 0;
			return;
		}
	}
}

static int win_at(int x, int y)
{
	int i;
	for (i = nwin - 1; i >= 0; i--) {
		if (!wins[i].used) continue;
		if (hit(x, y, wins[i].x, wins[i].y, wins[i].w, wins[i].h))
			return i;
	}
	return -1;
}

static void files_activate(Win *w)
{
	char next[MAX_PATH], full[MAX_PATH];
	struct stat st;
	if (w->fsel < 0 || w->fsel >= w->fcount) return;
	if (!strcmp(w->fnames[w->fsel], "..")) {
		char *sl = strrchr(w->path, '/');
		if (sl && sl != w->path) *sl = 0;
		else snprintf(w->path, sizeof(w->path), "/");
		files_reload(w);
		return;
	}
	if (!strcmp(w->path, "/"))
		snprintf(next, sizeof(next), "/%s", w->fnames[w->fsel]);
	else
		snprintf(next, sizeof(next), "%s/%s", w->path, w->fnames[w->fsel]);
	if (stat(next, &st) == 0 && S_ISDIR(st.st_mode)) {
		snprintf(w->path, sizeof(w->path), "%s", next);
		files_reload(w);
		return;
	}
	{
		int id = alloc_win(W_TEXT, w->fnames[w->fsel], w->x + 30, w->y + 30, 520, 360);
		FILE *f;
		if (id < 0) return;
		f = fopen(next, "r");
		if (f) {
			size_t n = fread(wins[id].tbuf, 1, sizeof(wins[id].tbuf) - 1, f);
			wins[id].tbuf[n] = 0;
			fclose(f);
		} else {
			snprintf(wins[id].tbuf, sizeof(wins[id].tbuf), "Cannot open %s", next);
		}
		(void)full;
	}
}

static void apply_theme_id(const char *id)
{
	char path[256];
	snprintf(themename, sizeof(themename), "%s", id);
	if (!strcmp(id, "light")) theme_light();
	else theme_dark();
	snprintf(path, sizeof(path), "%s/%s.novatheme", NOVA_THEME_DIR, id);
	load_theme_file(path);
	mkdir("/home/nova/.config", 0755);
	mkdir(NOVA_USER_CONF, 0755);
	{
		FILE *f = fopen(NOVA_USER_CONF "/theme", "w");
		if (f) { fprintf(f, "%s\n", id); fclose(f); }
	}
}

static void handle_key(int code, int down)
{
	if (code == KEY_LEFTSHIFT || code == KEY_RIGHTSHIFT) { shift = down; return; }
	if (code == KEY_LEFTCTRL || code == KEY_RIGHTCTRL) { ctrl = down; return; }
	if (code == KEY_LEFTALT || code == KEY_RIGHTALT) { alt = down; return; }
	if (code == KEY_CAPSLOCK && down) { caps = !caps; return; }
	if (!down) return;

	if (alt && code == KEY_SPACE) {
		launch_open = !launch_open;
		launch_q[0] = 0;
		launch_sel = 0;
		menu_open = 0;
		return;
	}
	if (alt && code == KEY_F4) {
		if (focus >= 0) close_win(focus);
		return;
	}
	if (alt && code == KEY_TAB) {
		int i, start = focus < 0 ? 0 : focus + 1;
		for (i = 0; i < MAX_WIN; i++) {
			int j = (start + i) % MAX_WIN;
			if (wins[j].used) { focus = j; break; }
		}
		return;
	}
	if (alt && code == KEY_ENTER && focus >= 0) {
		Win *w = &wins[focus];
		if (!w->maxed) {
			w->minx = w->x; /* stash */
			w->x = 0; w->y = 0; w->w = fbw; w->h = fbh - PANEL_H;
			w->maxed = 1;
		} else {
			w->x = 80; w->y = 60; w->w = 640; w->h = 420;
			w->maxed = 0;
		}
		return;
	}

	if (launch_open) {
		char names[16][64], cmds[16][128];
		int n = 0;
		collect_apps(names, cmds, &n);
		if (code == KEY_ESC) { launch_open = 0; return; }
		if (code == KEY_UP && launch_sel > 0) launch_sel--;
		if (code == KEY_DOWN && launch_sel + 1 < n) launch_sel++;
		if (code == KEY_ENTER && n) {
			run_cmd(cmds[launch_sel]);
			launch_open = 0;
			return;
		}
		if (code == KEY_BACKSPACE) {
			size_t L = strlen(launch_q);
			if (L) launch_q[L - 1] = 0;
			return;
		}
		{
			int ch = key_to_ch(code, shift ^ caps);
			size_t L = strlen(launch_q);
			if (ch >= 32 && ch < 127 && L + 1 < sizeof(launch_q)) {
				launch_q[L] = (char)ch;
				launch_q[L + 1] = 0;
				launch_sel = 0;
			}
		}
		return;
	}

	if (focus < 0) return;
	{
		Win *w = &wins[focus];
		if (w->kind == W_FILES) {
			if (code == KEY_UP && w->fsel > 0) w->fsel--;
			if (code == KEY_DOWN && w->fsel + 1 < w->fcount) w->fsel++;
			if (code == KEY_ENTER || code == KEY_RIGHT) files_activate(w);
			if (code == KEY_BACKSPACE || code == KEY_LEFT) {
				char *sl = strrchr(w->path, '/');
				if (sl && sl != w->path) *sl = 0;
				else snprintf(w->path, sizeof(w->path), "/");
				files_reload(w);
			}
		} else if (w->kind == W_TERM && w->pty > 0) {
			char ch;
			if (code == KEY_UP) { write(w->pty, "\x1b[A", 3); return; }
			if (code == KEY_DOWN) { write(w->pty, "\x1b[B", 3); return; }
			if (code == KEY_RIGHT) { write(w->pty, "\x1b[C", 3); return; }
			if (code == KEY_LEFT) { write(w->pty, "\x1b[D", 3); return; }
			ch = (char)key_to_ch(code, shift ^ caps);
			if (ctrl && ch >= 'a' && ch <= 'z') ch = (char)(ch - 'a' + 1);
			if (ch) write(w->pty, &ch, 1);
		} else if (w->kind == W_SETTINGS) {
			if (code == KEY_UP && w->spage > 0) w->spage--;
			if (code == KEY_DOWN && w->spage < 6) w->spage++;
			if (code == KEY_LEFT) {
				if (w->spage == 1 && vol >= 5) vol -= 5;
				if (w->spage == 2 && bright >= 5) bright -= 5;
			}
			if (code == KEY_RIGHT) {
				if (w->spage == 1 && vol <= 95) vol += 5;
				if (w->spage == 2 && bright <= 95) bright += 5;
			}
			if (code == KEY_ENTER && w->spage == 6)
				apply_theme_id(strcmp(theme.id, "dark") ? "dark" : "light");
			if (code == KEY_ENTER && w->spage == 5)
				run_cmd("suspend");
		}
	}
}

static void handle_mouse(int down)
{
	long t;
	if (!down) { drag = -1; return; }
	t = now_ms();
	if (launch_open) {
		char names[16][64], cmds[16][128];
		int n = 0, w = 420, x = (fbw - w) / 2, y = fbh / 5, i;
		collect_apps(names, cmds, &n);
		for (i = 0; i < n && i < 8; i++) {
			if (hit(mx, my, x + 16, y + 78 + i * 24, w - 32, 22)) {
				run_cmd(cmds[i]);
				launch_open = 0;
				return;
			}
		}
		if (!hit(mx, my, x, y, w, 280))
			launch_open = 0;
		return;
	}
	if (menu_open) {
		if (hit(mx, my, 10, fbh - PANEL_H + 8, 88, 32)) { menu_open = 0; return; }
		menu_click();
		if (!hit(mx, my, 10, fbh - PANEL_H - 240, 200, 260))
			menu_open = 0;
		return;
	}
	if (hit(mx, my, 10, fbh - PANEL_H + 8, 88, 32)) {
		menu_open = 1;
		return;
	}
	if (my >= fbh - PANEL_H) {
		int tx = 110, i;
		for (i = 0; i < MAX_WIN; i++) {
			if (!wins[i].used) continue;
			if (hit(mx, my, tx, fbh - PANEL_H + 8, 120, 32)) {
				if (focus == i) close_win(i);
				else raise_win(i);
				return;
			}
			tx += 128;
		}
		return;
	}
	{
		int i = win_at(mx, my);
		if (i < 0) return;
		raise_win(i);
		/* close */
		if (hit(mx, my, wins[i].x + wins[i].w - 26, wins[i].y + 6, 16, 16)) {
			close_win(i);
			return;
		}
		if (hit(mx, my, wins[i].x + wins[i].w - 48, wins[i].y + 6, 16, 16)) {
			handle_key(KEY_ENTER, 1); /* reuse max via alt-enter logic */
			if (wins[i].maxed) {
				wins[i].x = 80; wins[i].y = 60; wins[i].w = 640; wins[i].h = 420; wins[i].maxed = 0;
			} else {
				wins[i].x = 0; wins[i].y = 0; wins[i].w = fbw; wins[i].h = fbh - PANEL_H; wins[i].maxed = 1;
			}
			return;
		}
		if (my < wins[i].y + TITLE_H) {
			drag = i;
			dragox = mx - wins[i].x;
			dragoy = my - wins[i].y;
			return;
		}
		if (wins[i].kind == W_FILES) {
			int y0 = wins[i].y + TITLE_H + 32;
			int row = (my - y0) / 20;
			if (row >= 0) {
				int idx = wins[i].foff + row;
				if (idx >= 0 && idx < wins[i].fcount) {
					int dbl = (t - last_click_ms < 400 && abs(mx - last_click_x) < 6);
					wins[i].fsel = idx;
					if (dbl) files_activate(&wins[i]);
				}
			}
		} else if (wins[i].kind == W_SETTINGS) {
			int p;
			for (p = 0; p < 7; p++) {
				int yy = wins[i].y + TITLE_H + 16 + p * 28;
				if (hit(mx, my, wins[i].x + 10, yy - 4, 136, 24))
					wins[i].spage = p;
			}
			if (wins[i].spage == 6) {
				int px = wins[i].x + 160, py = wins[i].y + TITLE_H + 76;
				if (hit(mx, my, px, py, 120, 28)) apply_theme_id("dark");
				if (hit(mx, my, px + 132, py, 120, 28)) apply_theme_id("light");
			}
			if (wins[i].spage == 5) {
				int px = wins[i].x + 160, py = wins[i].y + TITLE_H + 116;
				if (hit(mx, my, px, py, 120, 28)) run_cmd("suspend");
				if (hit(mx, my, px + 132, py, 120, 28)) run_cmd("poweroff");
			}
			if (wins[i].spage == 1 || wins[i].spage == 2) {
				int px = wins[i].x + 160, py = wins[i].y + TITLE_H + 72;
				if (hit(mx, my, px, py, 200, 14)) {
					int v = (mx - px) / 2;
					if (v < 0) v = 0;
					if (v > 100) v = 100;
					if (wins[i].spage == 1) vol = v;
					else bright = v;
				}
			}
		}
		last_click_ms = (int)t;
		last_click_x = mx;
		last_click_y = my;
	}
}

static void poll_inputs(void)
{
	struct input_event ev;
	int i;
	for (i = 0; i < nev; i++) {
		while (read(evfds[i], &ev, sizeof(ev)) == sizeof(ev)) {
			if (ev.type == EV_REL) {
				if (ev.code == REL_X) mx += ev.value * pointer_speed;
				if (ev.code == REL_Y) my += ev.value * pointer_speed;
				if (ev.code == REL_WHEEL && focus >= 0) {
					Win *w = &wins[focus];
					if (w->kind == W_FILES) {
						if (ev.value > 0 && w->fsel > 0) w->fsel--;
						if (ev.value < 0 && w->fsel + 1 < w->fcount) w->fsel++;
					}
				}
			} else if (ev.type == EV_ABS) {
				/* touchpads sometimes report abs */
			} else if (ev.type == EV_KEY) {
				if (ev.code == BTN_LEFT || ev.code == BTN_TOUCH) {
					mbtn = ev.value;
					handle_mouse(ev.value);
				} else if (ev.code == BTN_RIGHT) {
					if (ev.value) menu_open = !menu_open;
				} else {
					handle_key(ev.code, ev.value);
				}
			}
		}
	}
	if (mx < 0) mx = 0;
	if (my < 0) my = 0;
	if (mx >= fbw) mx = fbw - 1;
	if (my >= fbh) my = fbh - 1;
	if (drag >= 0 && wins[drag].used && mbtn) {
		wins[drag].x = mx - dragox;
		wins[drag].y = my - dragoy;
		if (wins[drag].x < -wins[drag].w + 40) wins[drag].x = -wins[drag].w + 40;
		if (wins[drag].y < 0) wins[drag].y = 0;
	}
}

static void poll_terms(void)
{
	int i;
	char buf[512];
	for (i = 0; i < MAX_WIN; i++) {
		int n;
		if (!wins[i].used || wins[i].kind != W_TERM || wins[i].pty <= 0)
			continue;
		while ((n = read(wins[i].pty, buf, sizeof(buf))) > 0)
			term_write(&wins[i], buf, n);
		if (wins[i].pid > 0 && waitpid(wins[i].pid, NULL, WNOHANG) == wins[i].pid) {
			close(wins[i].pty);
			wins[i].pty = -1;
			wins[i].pid = 0;
			term_write(&wins[i], "\r\n[process exited]\r\n", 20);
		}
	}
}

static void frame(void)
{
	int i;
	draw_wallpaper();
	for (i = 0; i < MAX_WIN; i++)
		if (wins[i].used && i != focus)
			draw_win(&wins[i], i);
	if (focus >= 0 && wins[focus].used)
		draw_win(&wins[focus], focus);
	draw_panel();
	if (menu_open) draw_menu();
	if (launch_open) draw_launcher();
	draw_cursor();
	present();
}

static void on_sig(int s)
{
	if (s == SIGINT || s == SIGTERM)
		running = 0;
}

static struct termios tty_saved;
static int tty_have;

static void tty_restore(void)
{
	if (tty_have)
		tcsetattr(0, TCSANOW, &tty_saved);
}

static void tty_raw(void)
{
	struct termios t;
	if (tcgetattr(0, &tty_saved) < 0)
		return;
	t = tty_saved;
	cfmakeraw(&t);
	t.c_cc[VMIN] = 0;
	t.c_cc[VTIME] = 0;
	if (tcsetattr(0, TCSANOW, &t) == 0) {
		tty_have = 1;
		atexit(tty_restore);
	}
	fcntl(0, F_SETFL, O_NONBLOCK);
}

static void inject_char(int ch)
{
	if (launch_open) {
		size_t L = strlen(launch_q);
		if (ch == 0x7f || ch == 8) {
			if (L) launch_q[L - 1] = 0;
			return;
		}
		if (ch >= 32 && ch < 127 && L + 1 < sizeof(launch_q)) {
			launch_q[L] = (char)ch;
			launch_q[L + 1] = 0;
			launch_sel = 0;
		}
		return;
	}
	if (focus >= 0 && wins[focus].used && wins[focus].kind == W_TERM && wins[focus].pty > 0) {
		char c = (char)ch;
		write(wins[focus].pty, &c, 1);
	}
}

static void poll_tty(void)
{
	unsigned char buf[32];
	int n, i;
	n = read(0, buf, sizeof(buf));
	if (n <= 0)
		return;
	for (i = 0; i < n; i++) {
		int ch = buf[i];
		if (ch == 0x1b && i + 2 < n && buf[i + 1] == '[') {
			int c = buf[i + 2];
			i += 2;
			if (c == 'A') handle_key(KEY_UP, 1);
			else if (c == 'B') handle_key(KEY_DOWN, 1);
			else if (c == 'C') handle_key(KEY_RIGHT, 1);
			else if (c == 'D') handle_key(KEY_LEFT, 1);
			continue;
		}
		if (ch == 0x1b) { handle_key(KEY_ESC, 1); continue; }
		if (ch == '\r' || ch == '\n') { handle_key(KEY_ENTER, 1); continue; }
		if (ch == '\t') { handle_key(KEY_TAB, 1); continue; }
		if (ch == 0x7f || ch == 8) { handle_key(KEY_BACKSPACE, 1); inject_char(ch); continue; }
		inject_char(ch);
	}
}

static int text_session(void)
{
	char line[256];
	int n;
	const char *banner =
		"\033[44;97m\033[2J\033[H"
		"\n"
		"  ############################################\n"
		"  #                                          #\n"
		"  #          N O V A L I N U X   1 . 0       #\n"
		"  #              NovaUI  (texto)             #\n"
		"  #                                          #\n"
		"  #   user: nova     password: nova123       #\n"
		"  #   framebuffer /dev/fb0 nao encontrado    #\n"
		"  #   VirtualBox: EFI + placa VMSVGA         #\n"
		"  #                                          #\n"
		"  #   shell abaixo.  poweroff para desligar  #\n"
		"  #                                          #\n"
		"  ############################################\n"
		"\033[0m\n";
	write(1, banner, strlen(banner));
	fcntl(0, F_SETFL, 0);
	execl("/bin/sh", "-sh", "-l", (char *)NULL);
	while ((n = read(0, line, sizeof(line))) > 0)
		write(1, line, (size_t)n);
	return 1;
}

int main(int argc, char **argv)
{
	int ttyfd;
	const char *mode = argc > 1 ? argv[1] : "session";
	theme_dark();
	{
		char tpath[128], tid[32] = {0};
		FILE *f = fopen(NOVA_USER_CONF "/theme", "r");
		if (f) { if (fgets(tid, sizeof(tid), f)) {} fclose(f); }
		if (tid[0]) {
			char *nl = strchr(tid, '\n');
			if (nl) *nl = 0;
			apply_theme_id(tid);
		}
		snprintf(tpath, sizeof(tpath), "%s/%s.novatheme", NOVA_THEME_DIR, theme.id);
		load_theme_file(tpath);
	}

	if (!strcmp(mode, "--files") || !strcmp(mode, "files")) mode = "files";
	if (!strcmp(mode, "--term") || !strcmp(mode, "term")) mode = "term";
	if (!strcmp(mode, "--settings") || !strcmp(mode, "settings")) mode = "settings";
	if (!strcmp(mode, "--launch") || !strcmp(mode, "launch")) mode = "launch";

	if (fb_open() < 0)
		return text_session();
	/* Keep the VT in text mode so a failed FB still shows the console. */
	ttyfd = -1;
	tty_raw();
	evdev_open();
	signal(SIGINT, on_sig);
	signal(SIGTERM, on_sig);
	signal(SIGCHLD, SIG_DFL);

	if (!strcmp(mode, "files")) run_cmd("files");
	else if (!strcmp(mode, "term")) run_cmd("term");
	else if (!strcmp(mode, "settings")) run_cmd("settings");
	else if (!strcmp(mode, "launch")) run_cmd("launch");
	else {
		run_cmd("about");
		if (focus >= 0) { wins[focus].x = 40; wins[focus].y = 130; }
		run_cmd("files");
		if (focus >= 0) { wins[focus].x = 40; wins[focus].y = 36; }
		run_cmd("term");
		if (focus >= 0) { wins[focus].x = 280; wins[focus].y = 160; }
	}

	frame();
	while (running) {
		poll_inputs();
		poll_tty();
		poll_terms();
		frame();
		usleep(30000);
	}
	if (ttyfd >= 0) {
		ioctl(ttyfd, KDSETMODE, KD_TEXT);
		close(ttyfd);
	}
	return 0;
}
