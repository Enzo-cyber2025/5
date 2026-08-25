# =============================================================================
# Makefile — build da NovaUI (interface gráfica do NovaLinux)
#
# Dependências (dev) no builder:
#   libx11-dev libxext-dev libxrender-dev (Xlib)
#   libcairo2-dev libpangocairo-1.0-0 (Cairo + Pango)
#   libfreetype6-dev libfontconfig1-dev
#   libinput-dev (para mouse/teclado/toque)
#   libvulkan-dev / libgl1-mesa-dev (OpenGL/Vulkan opcional)
#
# Ajuste CFLAGS/Optimização para o alvo Goldmont Plus conforme config.sh.
# =============================================================================

CC      ?= gcc
TARGET  ?= x86_64-nova-linux-gnu-gcc
PREFIX  ?= /usr

# Otimizações para Intel Pentium N5030 (Goldmont Plus)
ARCHFLAGS = -march=goldmont-plus -mtune=goldmont-plus
OPTFLAGS  = -O3 -pipe -flto=auto -fno-semantic-interposition

PKG_CONFIG = pkg-config

CFLAGS  ?= -std=gnu11 -Wall -Wextra ${OPTFLAGS} ${ARCHFLAGS} -fPIC
CPPFLAGS += -I.
LDLIBS   += -lX11 -lcairo -lcairo-xlib -lpangocairo-1.0 -lfontconfig -lfreetype

# Detecção de libs disponíveis (fallback para libs necessárias)
HAVE_PKG := $(shell command -v $(PKG_CONFIG) 2>/dev/null)
ifeq ($(HAVE_PKG),)
$(warning pkg-config não encontrado; assumindo libs no caminho padrão)
else
CPPFLAGS += $(shell $(PKG_CONFIG) --cflags x11 cairo pangocairo fontconfig freetype2 2>/dev/null)
LDLIBS   += $(shell $(PKG_CONFIG) --libs x11 cairo pangocairo fontconfig freetype2 2>/dev/null)
endif

# ---- componentes (binários) ----
BINS = novawm nova-panel nova-launcher nova-terminal nova-files nova-config

all: $(BINS)

novawm: src/wm.c src/common.c src/theme.c
	$(CC) $(CFLAGS) $(CPPFLAGS) $^ -o $@ $(LDLIBS)

nova-panel: src/panel.c src/common.c src/theme.c
	$(CC) $(CFLAGS) $(CPPFLAGS) $^ -o $@ $(LDLIBS)

nova-launcher: src/launcher.c src/common.c src/theme.c
	$(CC) $(CFLAGS) $(CPPFLAGS) $^ -o $@ $(LDLIBS)

nova-terminal: src/terminal.c src/common.c src/theme.c
	$(CC) $(CFLAGS) $(CPPFLAGS) $^ -o $@ $(LDLIBS)

nova-files: src/files.c src/common.c src/theme.c
	$(CC) $(CFLAGS) $(CPPFLAGS) $^ -o $@ $(LDLIBS)

nova-config: src/config.c src/common.c src/theme.c
	$(CC) $(CFLAGS) $(CPPFLAGS) $^ -o $@ $(LDLIBS)

# ---- instalação ----
install: all
	install -d $(DESTDIR)$(PREFIX)/bin
	install -m 0755 novawm nova-panel nova-launcher nova-terminal nova-files nova-config \
		$(DESTDIR)$(PREFIX)/bin/
	install -d $(DESTDIR)/usr/share/novaui/themes
	install -m 0644 themes/*.novatheme themes/wallpaper.png $(DESTDIR)/usr/share/novaui/themes/
	install -d $(DESTDIR)/usr/bin
	install -m 0755 novasession $(DESTDIR)/usr/bin/novasession

clean:
	rm -f $(BINS)

.PHONY: all install clean
