"""Kit de interface (pygame): botões, sliders, listas, campos de texto e telas.

Interface própria para não depender de dependências extras no executável.
"""
from __future__ import annotations

import os

import pygame

from .render import ACCENT, BAD, GOOD, PANEL, TEXT, TEXT_DIM, WARN


class Widget:
    def __init__(self, rect: pygame.Rect, label: str = ""):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.hover = False
        self.enabled = True

    def draw(self, r):
        raise NotImplementedError

    def handle(self, event) -> bool:
        if event.type == pygame.MOUSEMOTION:
            self.hover = self.rect.collidepoint(event.pos)
        return False


class Button(Widget):
    def __init__(self, rect, label, on_click=None, kind: str = "normal", hint: str = ""):
        super().__init__(rect, label)
        self.on_click = on_click
        self.kind = kind
        self.hint = hint

    def draw(self, r):
        colors = {"normal": (44, 50, 62), "primary": (40, 96, 132), "danger": (120, 48, 52),
                  "ghost": (32, 36, 44)}
        base = colors.get(self.kind, (44, 50, 62))
        if not self.enabled:
            base = (34, 37, 43)
        if self.hover and self.enabled:
            base = tuple(min(255, c + 26) for c in base)
        pygame.draw.rect(r.screen, base, self.rect, border_radius=6)
        border = ACCENT if (self.hover and self.enabled) else (70, 78, 94)
        pygame.draw.rect(r.screen, border, self.rect, 1, border_radius=6)
        color = TEXT if self.enabled else TEXT_DIM
        r.text(r.screen, self.label, self.rect.center, 19, color, anchor="center")
        if self.hint:
            r.text(r.screen, self.hint, (self.rect.right + 8, self.rect.centery), 13,
                   TEXT_DIM, anchor="midleft")

    def handle(self, event) -> bool:
        super().handle(event)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.enabled:
            if self.rect.collidepoint(event.pos) and self.on_click:
                self.on_click()
                return True
        return False


class Toggle(Widget):
    def __init__(self, rect, label, value=False, on_change=None, hint: str = ""):
        super().__init__(rect, label)
        self.value = bool(value)
        self.on_change = on_change
        self.hint = hint
        self.box = pygame.Rect(rect.x, rect.y + rect.height // 2 - 9, 18, 18)

    def draw(self, r):
        r.text(r.screen, self.label, (self.box.right + 8, self.rect.centery), 17,
               TEXT if self.enabled else TEXT_DIM, anchor="midleft")
        color = GOOD if self.value else (70, 78, 94)
        pygame.draw.rect(r.screen, color, self.box, border_radius=4)
        pygame.draw.rect(r.screen, (18, 20, 26), self.box, 1, border_radius=4)
        if self.value:
            pygame.draw.line(r.screen, (12, 14, 18), (self.box.x + 4, self.box.centery),
                             (self.box.x + 8, self.box.bottom - 5), 2)
            pygame.draw.line(r.screen, (12, 14, 18), (self.box.x + 8, self.box.bottom - 5),
                             (self.box.right - 4, self.box.y + 4), 2)
        if self.hint:
            r.text(r.screen, self.hint, (self.rect.right + 8, self.rect.centery), 13,
                   TEXT_DIM, anchor="midleft")

    def handle(self, event) -> bool:
        super().handle(event)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.enabled:
            if self.rect.collidepoint(event.pos):
                self.value = not self.value
                if self.on_change:
                    self.on_change(self.value)
                return True
        return False


class Slider(Widget):
    def __init__(self, rect, label, value, vmin, vmax, step=1.0, fmt="{:.0f}",
                 on_change=None, hint: str = ""):
        super().__init__(rect, label)
        self.value = value
        self.vmin = vmin
        self.vmax = vmax
        self.step = step
        self.fmt = fmt
        self.on_change = on_change
        self.hint = hint

    def draw(self, r):
        r.text(r.screen, self.label, (self.rect.x, self.rect.y - 2), 15, TEXT_DIM)
        val = self.fmt.format(self.value)
        r.text(r.screen, val, (self.rect.right, self.rect.y - 2), 15, ACCENT, anchor="topright")
        track = pygame.Rect(self.rect.x, self.rect.centery - 3, self.rect.width, 6)
        pygame.draw.rect(r.screen, (48, 53, 64), track, border_radius=3)
        frac = (self.value - self.vmin) / max(self.vmax - self.vmin, 1e-9)
        knob = pygame.Rect(track.x + frac * (track.width - 10), track.y - 4, 10, 14)
        pygame.draw.rect(r.screen, (60, 68, 84), track, 1, border_radius=3)
        pygame.draw.rect(r.screen, ACCENT if self.hover else (120, 190, 220), knob,
                         border_radius=3)
        if self.hint:
            r.text(r.screen, self.hint, (self.rect.right + 8, self.rect.centery), 13,
                   TEXT_DIM, anchor="midleft")

    def handle(self, event) -> bool:
        super().handle(event)
        if not self.enabled:
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self._set_from_x(event.pos[0])
                return True
        if event.type == pygame.MOUSEMOTION and pygame.mouse.get_pressed()[0]:
            if self.rect.collidepoint(event.pos):
                self._set_from_x(event.pos[0])
                return True
        if event.type == pygame.MOUSEWHEEL and self.rect.collidepoint(pygame.mouse.get_pos()):
            self.value = min(self.vmax, max(self.vmin,
                                            self.value + event.y * self.step))
            if self.on_change:
                self.on_change(self.value)
            return True
        return False

    def _set_from_x(self, x):
        frac = (x - self.rect.x) / max(self.rect.width, 1)
        raw = self.vmin + frac * (self.vmax - self.vmin)
        raw = round(raw / self.step) * self.step
        self.value = min(self.vmax, max(self.vmin, raw))
        if self.on_change:
            self.on_change(self.value)


class OptionCycle(Widget):
    """Ciclo de opções (clique alterna; útil para enumerações)."""

    def __init__(self, rect, label, options, index=0, on_change=None, hint: str = ""):
        super().__init__(rect, label)
        self.options = list(options)
        self.index = index
        self.on_change = on_change
        self.hint = hint
        self.btn = Button(rect, "", self.next)

    @property
    def value(self):
        return self.options[self.index] if self.options else None

    def next(self):
        if not self.options:
            return
        self.index = (self.index + 1) % len(self.options)
        if self.on_change:
            self.on_change(self.value, self.index)

    def draw(self, r):
        r.text(r.screen, self.label, (self.rect.x, self.rect.y - 16), 15, TEXT_DIM)
        base = (44, 50, 62)
        if self.hover:
            base = (60, 68, 84)
        pygame.draw.rect(r.screen, base, self.rect, border_radius=6)
        pygame.draw.rect(r.screen, ACCENT if self.hover else (70, 78, 94), self.rect, 1,
                         border_radius=6)
        r.text(r.screen, str(self.value), self.rect.center, 17, TEXT, anchor="center")
        if self.hint:
            r.text(r.screen, self.hint, (self.rect.right + 8, self.rect.centery), 13,
                   TEXT_DIM, anchor="midleft")

    def handle(self, event) -> bool:
        super().handle(event)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.enabled:
            if self.rect.collidepoint(event.pos):
                self.next()
                return True
        return False


class TextInput(Widget):
    def __init__(self, rect, value="", placeholder="", on_enter=None, label: str = ""):
        super().__init__(rect, label)
        self.value = value
        self.placeholder = placeholder
        self.on_enter = on_enter
        self.focused = False

    def draw(self, r):
        if self.label:
            r.text(r.screen, self.label, (self.rect.x, self.rect.y - 16), 15, TEXT_DIM)
        pygame.draw.rect(r.screen, (28, 31, 38), self.rect, border_radius=5)
        border = ACCENT if self.focused else (70, 78, 94)
        pygame.draw.rect(r.screen, border, self.rect, 1, border_radius=5)
        shown = self.value if self.value else self.placeholder
        color = TEXT if self.value else TEXT_DIM
        clip = r.font(17).render(shown, True, color)
        area = pygame.Rect(self.rect.x + 6, self.rect.y + 2,
                           self.rect.width - 12, self.rect.height - 4)
        r.screen.set_clip(area)
        r.screen.blit(clip, (self.rect.x + 6, self.rect.centery - clip.get_height() // 2))
        r.screen.set_clip(None)
        if self.focused and (pygame.time.get_ticks() // 500) % 2 == 0:
            x = self.rect.x + 6 + min(clip.get_width(), area.width - 4)
            pygame.draw.line(r.screen, ACCENT, (x, self.rect.y + 5),
                             (x, self.rect.bottom - 5), 1)

    def handle(self, event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.focused = self.rect.collidepoint(event.pos)
        if event.type == pygame.KEYDOWN and self.focused:
            if event.key == pygame.K_BACKSPACE:
                self.value = self.value[:-1]
            elif event.key == pygame.K_RETURN or event.key == pygame.K_KP_ENTER:
                if self.on_enter:
                    self.on_enter(self.value)
            elif event.unicode and event.unicode.isprintable():
                self.value += event.unicode
            return True
        return False


class ListBox(Widget):
    def __init__(self, rect, items, selected=0, on_select=None, on_activate=None,
                 render_item=None):
        super().__init__(rect)
        self.items = list(items)
        self.selected = selected
        self.on_select = on_select
        self.on_activate = on_activate
        self.render_item = render_item
        self.scroll = 0
        self.item_h = 30

    def draw(self, r):
        pygame.draw.rect(r.screen, (26, 29, 36), self.rect, border_radius=6)
        pygame.draw.rect(r.screen, (70, 78, 94), self.rect, 1, border_radius=6)
        inner = self.rect.inflate(-6, -6)
        r.screen.set_clip(inner)
        for i, item in enumerate(self.items):
            y = inner.y + i * self.item_h - self.scroll
            if y + self.item_h < inner.y or y > inner.bottom:
                continue
            row = pygame.Rect(inner.x, y, inner.width, self.item_h - 2)
            if i == self.selected:
                pygame.draw.rect(r.screen, (44, 78, 104), row, border_radius=4)
            elif i % 2 == 0:
                pygame.draw.rect(r.screen, (31, 35, 43), row, border_radius=4)
            if self.render_item:
                self.render_item(r, row, item, i == self.selected)
            else:
                label = item if isinstance(item, str) else str(item)
                r.text(r.screen, label, (row.x + 8, row.centery), 17,
                       TEXT if i == self.selected else TEXT_DIM, anchor="midleft")
        r.screen.set_clip(None)
        if self.items:
            total = len(self.items) * self.item_h
            if total > inner.height:
                frac = inner.height / total
                bar_h = max(20, int(inner.height * frac))
                y = inner.y + (self.scroll / max(total - inner.height, 1)) * (inner.height - bar_h)
                pygame.draw.rect(r.screen, (80, 88, 104),
                                 (self.rect.right - 8, y, 4, bar_h), border_radius=2)

    def handle(self, event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                inner = self.rect.inflate(-6, -6)
                idx = int((event.pos[1] - inner.y + self.scroll) // self.item_h)
                if 0 <= idx < len(self.items):
                    self.selected = idx
                    if self.on_select:
                        self.on_select(self.items[idx], idx)
                return True
        if event.type == pygame.MOUSEWHEEL and self.rect.collidepoint(pygame.mouse.get_pos()):
            self.scroll = max(0, min(max(0, len(self.items) * self.item_h - self.rect.height + 12),
                                      self.scroll - event.y * 30))
            return True
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_DOWN, pygame.K_UP) and self.items:
                d = 1 if event.key == pygame.K_DOWN else -1
                self.selected = max(0, min(len(self.items) - 1, self.selected + d))
                self.scroll = max(self.selected * self.item_h - self.rect.height + 40,
                                  min(self.scroll, self.selected * self.item_h))
                if self.on_select:
                    self.on_select(self.items[self.selected], self.selected)
                return True
            if event.key == pygame.K_RETURN and self.items and self.on_activate:
                self.on_activate(self.items[self.selected], self.selected)
                return True
        return False


class Label(Widget):
    def __init__(self, rect, text, size=17, color=TEXT, align="topleft"):
        super().__init__(rect, text)
        self.size = size
        self.color = color
        self.align = align

    def draw(self, r):
        r.text(r.screen, self.label, getattr(self.rect, self.align), self.size, self.color,
               anchor=self.align)


class Screen:
    """Tela com título e widgets."""

    def __init__(self, title: str, subtitle: str = ""):
        self.title = title
        self.subtitle = subtitle
        self.widgets: list[Widget] = []
        self.messages: list[tuple[str, tuple]] = []

    def add(self, widget):
        self.widgets.append(widget)
        return widget

    def draw(self, r):
        overlay = pygame.Surface(r.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((8, 10, 14, 205))
        r.screen.blit(overlay, (0, 0))
        r.text(r.screen, self.title, (r.screen.get_width() // 2, 42), 34, TEXT,
               anchor="center", bold=True)
        if self.subtitle:
            r.text(r.screen, self.subtitle, (r.screen.get_width() // 2, 74), 17, TEXT_DIM,
                   anchor="center")
        for w in self.widgets:
            w.draw(r)
        for i, (msg, color) in enumerate(self.messages[-6:]):
            r.text(r.screen, msg, (r.screen.get_width() // 2,
                                   r.screen.get_height() - 120 + i * 20), 16, color,
                   anchor="center")

    def handle(self, event) -> bool:
        for w in self.widgets:
            if w.handle(event):
                return True
        return False

    def message(self, text, color=TEXT):
        self.messages.append((text, color))


def wrap_text(text, font, max_width):
    """Quebra de linha simples para textos longos na UI."""
    words = str(text).split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if font.size(test)[0] <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines
