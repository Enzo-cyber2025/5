"""Aplicação principal: modos de jogo, menus, HUD e laço de simulação.

Modos
-----
manual : você dirige (WASD/setas).
ia     : um modelo carregado (ou o melhor da evolução) dirige sozinho.
treino : população inteira evolui — as gerações podem ser ligadas/desligadas
         com a tecla G (ou no menu), e os melhores passam os pesos adiante.
"""
from __future__ import annotations

import json
import os
import time

import numpy as np
import pygame

from . import mods
from .ai.backend import list_devices
from .ai.ga import GAConfig
from .ai.model_io import ModelError, describe, load_model, save_model
from .ai.policy import PolicySpec, flatten, unflatten
from .car import CarSpec
from .mods import ModItem
from .render import (ACCENT, BAD, GOOD, TEXT, TEXT_DIM, WARN, Camera, Renderer)
from .sim import SimConfig
from .trainer import Trainer
from .ui import (Button, Label, ListBox, OptionCycle, Screen, Slider, TextInput,
                 Toggle)

SETTINGS_FILE = "config.json"
DEFAULT_SETTINGS = {
    "track": "kartodromo",
    "car": "gt",
    "population": 120,
    "max_seconds": 45.0,
    "decision_interval": 4,
    "rays": 9,
    "hidden": "64,64",
    "mutation_rate": 0.08,
    "mutation_sigma": 0.25,
    "elitism": 0.10,
    "tournament": 3,
    "crossover": "blend",
    "fresh_blood": 0.04,
    "generations": True,
    "device": "auto",
    "seed": 0,
    "speed": 1,
    "draw_ghosts": True,
    "draw_rays": False,
    "show_hud": True,
    "max_draw": 60,
    "autosave_every": 0,
    "model": os.path.join("modelos", "modelo.pt"),
    "zoom_manual": 11.0,
    "zoom_train": 5.0,
}

SPEEDS = [1, 2, 4, 8, 16, 32]


class App:
    def __init__(self, width: int = 1280, height: int = 720, start_mode: str = "menu",
                 model_path: str = "", fullscreen: bool = False):
        pygame.init()
        pygame.display.set_caption("RaceAI 2D — treino de IA com gerações")
        flags = pygame.RESIZABLE | (pygame.FULLSCREEN if fullscreen else 0)
        self.screen = pygame.display.set_mode((width, height), flags)
        try:
            pygame.scrap.init()          # permite colar caminhos de arquivos
        except Exception:
            pass
        self.clock = pygame.time.Clock()
        self.renderer = Renderer(self.screen)
        self.camera = Camera(width, height, zoom=DEFAULT_SETTINGS["zoom_manual"])

        self.settings = dict(DEFAULT_SETTINGS)
        self.settings.update(self.load_settings())
        self.start_model = model_path
        self.mode = start_mode
        self.running = True
        self.paused = False
        self.step_accum = 0.0
        self.fps = 60.0
        self.messages: list[tuple[str, tuple, float]] = []
        self.screens: dict[str, Screen] = {}
        self.screen_name = "main"
        self.tracks: list[ModItem] = []
        self.cars: list[ModItem] = []
        self.model_flat: np.ndarray | None = None
        self.model_meta: dict = {}
        self.steer_input = 0.0
        self.focus_index = 0
        self.last_autosave_gen = -1
        self._needs_rebuild = False

        self.reload_mods()
        self.build_trainer()

    # ------------------------------------------------------------------ #
    # Configuração persistente
    # ------------------------------------------------------------------ #
    def settings_path(self) -> str:
        return os.path.join(mods.base_dir(), SETTINGS_FILE)

    def load_settings(self) -> dict:
        try:
            with open(self.settings_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            return {k: v for k, v in data.items() if k in DEFAULT_SETTINGS}
        except Exception:
            return {}

    def save_settings(self):
        try:
            with open(self.settings_path(), "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Mods / assets
    # ------------------------------------------------------------------ #
    def reload_mods(self):
        self.tracks = [t for t in mods.load_tracks()]
        self.cars = [c for c in mods.load_cars()]
        if not self.tracks:
            from .track import make_oval
            t = mods.ModItem(kind="tracks", name="Oval (emergência)", path="", builtin=True)
            t.obj = __import__("raceai.track", fromlist=["Track"]).Track.from_dict(make_oval())
            self.tracks = [t]
        if not self.cars:
            c = mods.ModItem(kind="cars", name="Carro padrão", path="", builtin=True)
            c.obj = CarSpec()
            self.cars = [c]
        self.track_index = self._index_of(self.tracks, self.settings.get("track"), 0)
        self.car_index = self._index_of(self.cars, self.settings.get("car"), 0)

    @staticmethod
    def _index_of(items: list, name: str, default: int = 0) -> int:
        for i, it in enumerate(items):
            if it.name == name:
                return i
        return min(default, max(0, len(items) - 1))

    @property
    def track(self):
        return self.tracks[self.track_index].obj

    @property
    def car(self):
        return self.cars[self.car_index].obj

    # ------------------------------------------------------------------ #
    # Trainer
    # ------------------------------------------------------------------ #
    def build_trainer(self):
        s = self.settings
        sim_cfg = SimConfig(max_seconds=float(s["max_seconds"]),
                            decision_interval=int(s["decision_interval"]),
                            n_rays=int(s["rays"]))
        ga_cfg = GAConfig(population=int(s["population"]),
                          mutation_rate=float(s["mutation_rate"]),
                          mutation_sigma=float(s["mutation_sigma"]),
                          elitism=float(s["elitism"]),
                          tournament=int(s["tournament"]),
                          crossover=str(s["crossover"]),
                          fresh_blood=float(s["fresh_blood"]))
        hidden = tuple(int(h) for h in str(s["hidden"]).split(",") if h.strip()) or (64, 64)
        policy = PolicySpec(obs_dim=int(s["rays"]) + 15, hidden=hidden)
        self.trainer = Trainer(self.track, self.car, sim_cfg, ga_cfg, policy,
                               device_id=str(s["device"]), seed=int(s["seed"]))
        self.trainer.generations_enabled = bool(s["generations"])
        self.screens = {}
        if self.start_model:
            self.load_model(self.start_model)
        self.apply_mode()

    def apply_mode(self, reset: bool = True):
        s = self.settings
        t = self.trainer
        if self.mode == "manual":
            t.set_population_size(1)
            t.generations_enabled = False
            t.manual_control = True
            t.excluded = np.ones(t.sim.n, dtype=bool)
            self.camera.set_zoom(float(s["zoom_manual"]))
        elif self.mode == "ia":
            t.set_population_size(1)
            t.generations_enabled = False
            t.manual_control = False
            t.excluded = np.zeros(t.sim.n, dtype=bool)
            flat = self.model_flat if self.model_flat is not None else t.pop.best_genome
            if flat is not None:
                t.pop.genomes[0] = np.asarray(flat, dtype=np.float32)
                t.backend.set_population(t.pop.as_layers())
            # sem modelo carregado: usa o piloto automático clássico
            t.enable_autopilot(self.model_flat is None)
            self.camera.set_zoom(float(s["zoom_manual"]))
        else:
            t.set_population_size(int(s["population"]))
            t.generations_enabled = bool(s["generations"])
            t.manual_control = False
            t.enable_autopilot(False)
            t.excluded = np.zeros(t.sim.n, dtype=bool)
            self.camera.set_zoom(float(s["zoom_train"]))
        if reset:
            t.restart()

    def set_mode(self, mode: str):
        if mode == self.mode:
            return
        self.mode = mode
        self.apply_mode()

    # ------------------------------------------------------------------ #
    # Modelos
    # ------------------------------------------------------------------ #
    def load_model(self, path: str, seed_population: bool = True) -> bool:
        try:
            meta = self.trainer.load_model(path, seed_population=seed_population)
        except ModelError as exc:
            self.notify(f"falha ao carregar: {exc}", BAD)
            return False
        except FileNotFoundError:
            self.notify(f"arquivo não encontrado: {path}", BAD)
            return False
        self.model_flat = np.asarray(self.trainer.loaded_genome, dtype=np.float32)
        self.model_meta = meta
        self.settings["model"] = path
        self.notify(f"modelo carregado ({describe(meta)})", GOOD)
        if self.mode == "ia":
            self.apply_mode()
        return True

    def save_best(self, path: str | None = None) -> bool:
        path = path or self.settings["model"]
        try:
            used = self.trainer.save_best(path)
        except Exception as exc:
            self.notify(f"falha ao salvar: {exc}", BAD)
            return False
        self.settings["model"] = used
        self.notify(f"salvo em {os.path.basename(used)}", GOOD)
        return True

    def notify(self, msg: str, color=TEXT):
        self.messages.append((msg, color, time.time() + 4.0))
        if len(self.messages) > 6:
            self.messages = self.messages[-6:]

    # ------------------------------------------------------------------ #
    # Laço principal
    # ------------------------------------------------------------------ #
    def run(self):
        while self.running:
            dt = min(self.clock.tick(120) / 1000.0, 0.1)
            for event in pygame.event.get():
                self.handle_event(event)
            if self.screen_name == "none" and not self.paused:
                self.update(dt)
            self.render()
            pygame.display.flip()
        pygame.quit()

    def update(self, dt: float):
        t = self.trainer
        sim_dt = t.sim.cfg.dt
        speed = SPEEDS[min(len(SPEEDS) - 1, int(self.settings["speed"]))]
        self.step_accum += dt * speed / sim_dt
        steps = int(self.step_accum)
        self.step_accum -= steps
        steps = min(steps, 600)
        if steps > 0:
            if self.mode == "manual":
                t.manual_action = self.read_manual_input()
            t.step(steps)
        if t.generation_done():
            self.on_generation_end()

    def on_generation_end(self):
        t = self.trainer
        if self.mode == "manual":
            t.sim.reset()
            t.state.steps = 0
            return
        if self.mode == "ia":
            t.sim.reset()
            t.state.steps = 0
            return
        stats = t.finish_generation(evolve=bool(self.settings["generations"]))
        every = int(self.settings["autosave_every"])
        if every and t.pop.generation % every == 0 and t.pop.generation != self.last_autosave_gen:
            self.last_autosave_gen = t.pop.generation
            self.save_best()

    def read_manual_input(self) -> np.ndarray:
        keys = pygame.key.get_pressed()
        left = keys[pygame.K_LEFT] or keys[pygame.K_a]
        right = keys[pygame.K_RIGHT] or keys[pygame.K_d]
        up = keys[pygame.K_UP] or keys[pygame.K_w]
        down = keys[pygame.K_DOWN] or keys[pygame.K_s]
        target = (1.0 if right else 0.0) - (1.0 if left else 0.0)
        # suaviza o esterço no teclado (o volante virtual tem taxa limitada)
        rate = 3.5 * (1.0 / 60.0)
        self.steer_input += max(-rate, min(rate, target - self.steer_input))
        drive = (1.0 if up else 0.0) - (1.0 if down else 0.0)
        return np.array([self.steer_input, drive], dtype=np.float32)

    # ------------------------------------------------------------------ #
    # Eventos
    # ------------------------------------------------------------------ #
    def handle_event(self, event):
        if event.type == pygame.QUIT:
            self.save_settings()
            self.running = False
            return
        if event.type == pygame.VIDEORESIZE:
            self.screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
            self.renderer.screen = self.screen
            self.camera.resize(event.w, event.h)
            self.screens = {}
            return
        if event.type == pygame.KEYDOWN and self.screen_name != "none":
            if not self.screens.get(self.screen_name, Screen("")).handle(event):
                self.handle_menu_key(event)
            return
        if event.type == pygame.KEYDOWN:
            self.handle_game_key(event)
            return
        if self.screen_name != "none":
            screen = self.screens.get(self.screen_name)
            if screen:
                screen.handle(event)

    def handle_menu_key(self, event):
        if event.key == pygame.K_ESCAPE:
            if self.screen_name == "main":
                self.save_settings()
                self.running = False
            else:
                self.screen_name = "main"
                self.screens = {}
        elif event.key == pygame.K_F1:
            self.screen_name = "help"
        elif event.key in (pygame.K_1, pygame.K_KP_1):
            self.start_mode("manual")
        elif event.key in (pygame.K_2, pygame.K_KP_2):
            self.start_mode("ia")
        elif event.key in (pygame.K_3, pygame.K_KP_3):
            self.start_mode("train")

    def handle_game_key(self, event):
        s = self.settings
        if event.key == pygame.K_ESCAPE:
            self.screen_name = "main"
            self.screens = {}
        elif event.key == pygame.K_p:
            self.paused = not self.paused
        elif event.key == pygame.K_r:
            self.trainer.restart()
            self.notify("reiniciado")
        elif event.key == pygame.K_g:
            s["generations"] = not s["generations"]
            self.trainer.generations_enabled = s["generations"]
            self.notify("gerações " + ("ATIVADAS" if s["generations"] else "DESATIVADAS"),
                        GOOD if s["generations"] else WARN)
        elif event.key == pygame.K_f:
            s["speed"] = (int(s["speed"]) + 1) % len(SPEEDS)
            self.notify(f"velocidade {SPEEDS[int(s['speed'])]}x")
        elif event.key == pygame.K_h:
            s["show_hud"] = not s["show_hud"]
        elif event.key == pygame.K_TAB:
            s["draw_rays"] = not s["draw_rays"]
        elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
            self.camera.set_zoom(self.camera.zoom * 1.25)
        elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self.camera.set_zoom(self.camera.zoom / 1.25)
        elif event.key == pygame.K_c:
            self.cycle_focus()
        elif event.key == pygame.K_s and pygame.key.get_mods() & pygame.K_CTRL:
            self.save_best()
        elif event.key == pygame.K_l:
            self.screen_name = "models"
        elif event.key == pygame.K_m:
            self.screen_name = "main"
        elif event.key == pygame.K_F1:
            self.screen_name = "help"
        elif event.key == pygame.K_1:
            self.set_mode("manual")
        elif event.key == pygame.K_2:
            self.set_mode("ia")
        elif event.key == pygame.K_3:
            self.set_mode("train")
        elif event.key == pygame.K_SPACE:
            self.paused = not self.paused

    def cycle_focus(self):
        t = self.trainer
        n = t.sim.n_active
        if n <= 1:
            return
        alive = np.flatnonzero(t.sim.fleet.alive[:n])
        if len(alive) == 0:
            return
        fit = t.sim.fleet.fitness[alive]
        order = alive[np.argsort(-fit)]
        pos = np.flatnonzero(order == self.focus_index)
        nxt = int(pos[0]) + 1 if len(pos) else 0
        self.focus_index = int(order[nxt % len(order)])
        self.notify(f"foco no carro #{self.focus_index}")

    # ------------------------------------------------------------------ #
    # Render
    # ------------------------------------------------------------------ #
    def render(self):
        r = self.renderer
        r.draw_background()
        t = self.trainer
        fleet = t.sim.fleet
        n = max(1, t.sim.n_active)
        # índice focado
        if self.mode in ("manual", "ia"):
            self.focus_index = 0
        else:
            alive = np.flatnonzero(fleet.alive[:n])
            if len(alive) == 0:
                self.focus_index = 0
            elif self.focus_index >= n or not fleet.alive[self.focus_index]:
                self.focus_index = int(alive[int(np.argmax(fleet.fitness[alive]))])
        fi = min(self.focus_index, fleet.n - 1)
        if not self.paused:
            self.camera.follow(fleet.x[fi], fleet.y[fi], smoothing=0.15)

        r.draw_track(t.track, self.camera)
        r.draw_cars(t.car, fleet, n, self.camera, focus=fi,
                    max_draw=int(self.settings["max_draw"]) if self.settings["draw_ghosts"]
                    else 12,
                    draw_rays=bool(self.settings["draw_rays"]), track=t.track,
                    ray_count=int(self.settings["rays"]),
                    ray_range=t.sim.cfg.ray_range)

        if self.settings["show_hud"]:
            self.draw_hud(fi)

        if self.screen_name != "none":
            screen = self.screens.get(self.screen_name)
            if screen is None:
                screen = self.build_screen(self.screen_name)
                self.screens[self.screen_name] = screen
            screen.draw(r)
            self.draw_extra()
        self.draw_messages()
        pygame.display.set_caption(
            f"RaceAI 2D — {t.track.name} · {t.car.name} · "
            f"{self.mode_label()} · {self.clock.get_fps():.0f} fps")

    def mode_label(self) -> str:
        return {"manual": "MANUAL", "ia": "IA", "train": "TREINO"}.get(self.mode, self.mode)

    def draw_hud(self, focus: int):
        r = self.renderer
        t = self.trainer
        f = t.sim.fleet
        w, h = self.screen.get_size()
        st = t.state

        # ---- painel superior esquerdo
        panel = pygame.Rect(10, 10, 330, 132 if self.mode == "train" else 112)
        r.panel(panel)
        mode = self.mode_label()
        r.text(self.screen, f"MODO {mode}", (panel.x + 10, panel.y + 8), 20, ACCENT, bold=True)
        r.text(self.screen, f"{t.track.name} · {t.car.name}", (panel.right - 10, panel.y + 12),
               14, TEXT_DIM, anchor="topright")
        y = panel.y + 34
        if self.mode == "train":
            r.text(self.screen, f"geração {t.pop.generation}", (panel.x + 10, y), 17)
            r.text(self.screen, f"vivos {int(f.alive[:t.sim.n_active].sum())}/{t.sim.n}",
                   (panel.x + 150, y), 17, TEXT)
            y += 20
            hist = t.pop.history
            best = t.pop.best_fitness
            mean = f.fitness.mean()
            r.text(self.screen, f"melhor {best:,.0f}", (panel.x + 10, y), 16, GOOD)
            r.text(self.screen, f"média {mean:,.0f}", (panel.x + 150, y), 16, TEXT)
            y += 18
            r.text(self.screen, f"sigma {t.pop.sigma:.3f}", (panel.x + 10, y), 15, TEXT_DIM)
            r.text(self.screen, f"ger.{'ON' if self.settings['generations'] else 'OFF'} (G)",
                   (panel.x + 150, y), 15, GOOD if self.settings["generations"] else WARN)
            y += 18
        else:
            r.text(self.screen, f"voltas {int(f.laps[focus])}", (panel.x + 10, y), 17)
            if np.isfinite(f.best_lap[focus]):
                r.text(self.screen, f"melhor volta {f.best_lap[focus]:.2f}s",
                       (panel.x + 150, y), 17, GOOD)
            y += 22
        r.text(self.screen, f"t {st.sim_seconds:5.1f}s  x{SPEEDS[int(self.settings['speed'])]}",
               (panel.x + 10, y), 15, TEXT_DIM)
        r.text(self.screen, f"{st.device_desc or st.device}", (panel.right - 10, y),
               14, TEXT_DIM, anchor="topright")
        y += 18
        r.text(self.screen, f"inferência {st.inference_ms:.2f} ms · {st.steps_per_second:.0f} passos/s",
               (panel.x + 10, y), 14, TEXT_DIM)

        # ---- telemetria do carro focado
        tp = pygame.Rect(w - 250, 10, 240, 168)
        r.panel(tp)
        r.text(self.screen, f"carro #{focus}", (tp.x + 10, tp.y + 8), 17, ACCENT)
        kmh = f.speed[focus] * 3.6
        r.text(self.screen, f"{kmh:5.0f} km/h", (tp.right - 10, tp.y + 8), 17, anchor="topright")
        y = tp.y + 34
        r.bar(pygame.Rect(tp.x + 10, y, tp.width - 20, 8),
              abs(f.speed[focus]) / max(t.car.max_speed, 1e-6), (90, 190, 240))
        y += 16
        r.text(self.screen, "acel", (tp.x + 10, y), 13, TEXT_DIM)
        r.bar(pygame.Rect(tp.x + 50, y + 1, 70, 8), f.throttle[focus], GOOD)
        r.text(self.screen, "freio", (tp.x + 130, y), 13, TEXT_DIM)
        r.bar(pygame.Rect(tp.x + 172, y + 1, 58, 8), f.brake[focus], BAD)
        y += 20
        r.text(self.screen, "esterço", (tp.x + 10, y), 13, TEXT_DIM)
        r.bar(pygame.Rect(tp.x + 70, y + 1, 160, 8),
              abs(f.steer[focus]) / max(t.car.max_steer, 1e-6), WARN)
        y += 20
        r.text(self.screen, "aderência", (tp.x + 10, y), 13, TEXT_DIM)
        r.bar(pygame.Rect(tp.x + 90, y + 1, 140, 8),
              min(1.0, f.grip_use[focus]), BAD if f.grip_use[focus] > 0.98 else GOOD)
        y += 20
        r.text(self.screen, f"derrapagem {np.degrees(f.slip_f[focus]):5.1f}° / "
                            f"{np.degrees(f.slip_r[focus]):5.1f}°", (tp.x + 10, y), 13, TEXT)
        y += 18
        lateral = f.lateral[focus]
        r.text(self.screen, f"fora do eixo {lateral:5.1f} m", (tp.x + 10, y), 13,
               WARN if abs(lateral) > t.track.half_widths[f.idx[focus]] else TEXT)
        y += 16
        r.text(self.screen, f"fitness {f.fitness[focus]:,.0f}", (tp.x + 10, y), 14, ACCENT)
        if f.death_reason[focus]:
            r.text(self.screen, f"fim: {f.death_reason[focus]}", (tp.right - 10, y), 13, BAD,
                   anchor="topright")

        # ---- minimapa
        mm = pygame.Rect(w - 250, h - 210, 240, 200)
        r.draw_minimap(t.track, f, t.sim.n_active, focus, mm)

        # ---- gráfico da evolução
        if self.mode == "train" and t.pop.history:
            r.draw_plot(t.pop.history, pygame.Rect(10, h - 190, 380, 180))

        # ---- dicas
        if self.paused:
            r.text(self.screen, "PAUSADO — P ou ESPAÇO para voltar", (w // 2, h - 26), 20,
                   WARN, anchor="center")
        elif self.mode == "manual":
            r.text(self.screen, "setas/WASD dirigem · R reinicia · G gerações · F velocidade "
                                "· C câmera · CTRL+S salva · ESC menu",
                   (w // 2, h - 26), 15, TEXT_DIM, anchor="center")

    def draw_messages(self):
        now = time.time()
        self.messages = [(m, c, t) for (m, c, t) in self.messages if t > now]
        for i, (msg, color, _) in enumerate(self.messages):
            self.renderer.text(self.screen, msg, (self.screen.get_width() // 2, 60 + i * 22),
                               17, color, anchor="center")

    # ------------------------------------------------------------------ #
    # Telas de menu
    # ------------------------------------------------------------------ #
    def build_screen(self, name: str) -> Screen:
        w, h = self.screen.get_size()
        cx = w // 2
        if name == "main":
            return self.build_main(cx, h)
        if name == "tracks":
            return self.build_tracks(cx, h)
        if name == "cars":
            return self.build_cars(cx, h)
        if name == "models":
            return self.build_models(cx, h)
        if name == "settings":
            return self.build_settings(cx, h)
        if name == "mods":
            return self.build_mods(cx, h)
        if name == "help":
            return self.build_help(cx, h)
        return Screen("")

    def build_main(self, cx, h) -> Screen:
        s = Screen("RaceAI 2D", "corrida 2D para treinar IA: pilote você mesmo, "
                                "carregue um .pt ou evolua por gerações")
        bw, bh = 300, 44
        y = 120
        s.add(Button(pygame.Rect(cx - bw // 2, y, bw, bh), "1 · Dirigir (manual)",
                     lambda: self.start_mode("manual"), "primary"))
        y += bh + 8
        s.add(Button(pygame.Rect(cx - bw // 2, y, bw, bh), "2 · Assistir IA",
                     lambda: self.start_mode("ia"), "primary"))
        y += bh + 8
        s.add(Button(pygame.Rect(cx - bw // 2, y, bw, bh), "3 · Treinar (gerações)",
                     lambda: self.start_mode("train"), "primary"))
        y += bh + 18
        half = (bw - 10) // 2
        s.add(Button(pygame.Rect(cx - bw // 2, y, half, 38), "Modelo .pt",
                     lambda: self.goto("models")))
        s.add(Button(pygame.Rect(cx + 5, y, half, 38), "Pistas",
                     lambda: self.goto("tracks")))
        y += 46
        s.add(Button(pygame.Rect(cx - bw // 2, y, half, 38), "Carros",
                     lambda: self.goto("cars")))
        s.add(Button(pygame.Rect(cx + 5, y, half, 38), "Mods",
                     lambda: self.goto("mods")))
        y += 46
        s.add(Button(pygame.Rect(cx - bw // 2, y, half, 38), "Configurações",
                     lambda: self.goto("settings")))
        s.add(Button(pygame.Rect(cx + 5, y, half, 38), "Ajuda (F1)",
                     lambda: self.goto("help")))
        y += 52
        s.add(Button(pygame.Rect(cx - bw // 2, y, bw, 38), "Sair",
                     self.quit_app, "danger"))
        info = (f"pista: {self.track.name} · carro: {self.car.name} · "
                f"device: {self.trainer.state.device_desc}")
        s.add(Label(pygame.Rect(cx, h - 60, 0, 0), info, 15, TEXT_DIM, "center"))
        return s

    def start_mode(self, mode: str):
        self.apply_pending_rebuild()
        self.set_mode(mode)
        self.screen_name = "none"
        self.screens = {}
        self.save_settings()

    def goto(self, name: str):
        self.apply_pending_rebuild()
        self.screen_name = name
        self.screens = {}

    def apply_pending_rebuild(self):
        if getattr(self, "_needs_rebuild", False):
            self._needs_rebuild = False
            self.build_trainer()
            self.notify("simulação reconstruída com as novas configurações", ACCENT)
            self.save_settings()

    def quit_app(self):
        self.save_settings()
        self.running = False

    # ------------------------------------------------------------------ #
    def build_tracks(self, cx, h) -> Screen:
        s = Screen("Pistas", "escolha uma pista (as de mods/ aparecem marcadas)")
        lst = [t for t in self.tracks]
        box = ListBox(pygame.Rect(cx - 380, 120, 340, min(420, h - 240)),
                      [t.name for t in lst], self.track_index,
                      render_item=self._render_track_item)
        s.add(box)

        def apply(_item, idx):
            it = lst[idx]
            if it.error:
                s.message(it.error, BAD)
                return
            self.track_index = idx
            self.settings["track"] = it.name
            self.trainer.set_track(it.obj)
            self.camera.follow(it.obj.center[it.obj.start_index][0],
                               it.obj.center[it.obj.start_index][1], snap=True)
            self.save_settings()

        box.on_activate = apply
        s.add(Button(pygame.Rect(cx - 380, h - 100, 160, 40), "Usar esta",
                     lambda: apply(None, box.selected), "primary"))
        s.add(Button(pygame.Rect(cx - 210, h - 100, 160, 40), "Voltar",
                     lambda: self.goto("main")))
        preview = pygame.Rect(cx + 20, 130, 360, 300)
        s.add(Label(preview, "", 15))
        self._track_preview_rect = preview
        return s

    def _render_track_item(self, r, row, item, selected):
        idx = [t.name for t in self.tracks].index(item)
        it = self.tracks[idx]
        color = TEXT if selected else TEXT_DIM
        name = it.name + ("  [mod]" if not it.builtin else "")
        r.text(r.screen, name, (row.x + 8, row.centery - 6), 16, color, anchor="midleft")
        if it.error:
            r.text(r.screen, "erro", (row.right - 8, row.centery - 6), 13, BAD,
                   anchor="midright")
        elif it.obj is not None:
            r.text(r.screen, f"{it.obj.length:.0f} m · {it.obj.half_widths.mean() * 2:.0f} m larg",
                   (row.right - 8, row.centery + 8), 12, TEXT_DIM, anchor="midright")

    def build_cars(self, cx, h) -> Screen:
        s = Screen("Carros", "cada carro tem física própria — a IA precisa reaprender")
        lst = [c for c in self.cars]
        box = ListBox(pygame.Rect(cx - 380, 120, 340, min(420, h - 240)),
                      [c.name for c in lst], self.car_index,
                      render_item=self._render_car_item)
        s.add(box)
        info = pygame.Rect(cx + 10, 120, 370, 300)
        self._car_info_rect = info

        def apply(_item, idx):
            it = lst[idx]
            if it.error:
                s.message(it.error, BAD)
                return
            self.car_index = idx
            self.settings["car"] = it.name
            self.trainer.set_car(it.obj)
            self.save_settings()

        box.on_activate = apply
        s.add(Button(pygame.Rect(cx - 380, h - 100, 160, 40), "Usar este",
                     lambda: apply(None, box.selected), "primary"))
        s.add(Button(pygame.Rect(cx - 210, h - 100, 160, 40), "Voltar",
                     lambda: self.goto("main")))
        return s

    def _render_car_item(self, r, row, item, selected):
        idx = [c.name for c in self.cars].index(item)
        it = self.cars[idx]
        color = TEXT if selected else TEXT_DIM
        r.text(r.screen, it.name + ("  [mod]" if not it.builtin else ""),
               (row.x + 8, row.centery - 6), 16, color, anchor="midleft")
        if it.obj is not None and not it.error:
            pygame.draw.rect(r.screen, pygame.Color(it.obj.body_color),
                             (row.right - 30, row.centery - 7, 22, 14), border_radius=3)
        elif it.error:
            r.text(r.screen, "erro", (row.right - 8, row.centery), 12, BAD, anchor="midright")

    def build_models(self, cx, h) -> Screen:
        s = Screen("Modelo (.pt)", "carregue um modelo para dirigir ou para semear a população")
        path = TextInput(pygame.Rect(cx - 300, 120, 600, 38), self.settings.get("model", ""),
                         "caminho do arquivo .pt / .npz", label="arquivo")
        s.add(path)
        files = self.list_model_files()
        box = ListBox(pygame.Rect(cx - 300, 180, 600, min(220, h - 400)), files, 0,
                      on_select=lambda item, i: setattr(path, "value", item[1]))
        s.add(box)
        y = 190 + min(220, max(120, h - 400)) + 12

        def do_load(seed=True):
            if not path.value:
                s.message("digite um caminho ou escolha um arquivo da lista", WARN)
                return
            if self.load_model(path.value, seed_population=seed):
                s.message("carregado com sucesso", GOOD)

        s.add(Button(pygame.Rect(cx - 300, y, 290, 38), "Carregar e semear população",
                     lambda: do_load(True), "primary"))
        s.add(Button(pygame.Rect(cx + 10, y, 290, 38), "Carregar e dirigir (modo IA)",
                     lambda: (do_load(False), self.start_mode("ia"))))
        y += 46
        s.add(Button(pygame.Rect(cx - 300, y, 190, 38), "Salvar melhor (.pt)",
                     lambda: (self.save_best(path.value or None),
                              s.message(f"salvo: {path.value}", GOOD))))
        s.add(Button(pygame.Rect(cx - 100, y, 190, 38), "Exportar ONNX",
                     lambda: self.export_onnx(s)))
        s.add(Button(pygame.Rect(cx + 100, y, 190, 38), "Abrir pasta",
                     lambda: mods.open_folder(mods.models_dir())))
        y += 46
        s.add(Button(pygame.Rect(cx - 300, y, 190, 38), "Voltar", lambda: self.goto("main")))
        info = describe(self.model_meta) if self.model_meta else "nenhum modelo carregado"
        s.add(Label(pygame.Rect(cx, y + 8, 0, 0), info, 15, TEXT_DIM, "center"))
        return s

    def export_onnx(self, screen: Screen):
        genome, meta = self.trainer.best_model_path_info()
        out = os.path.splitext(self.settings.get("model", "modelo.pt"))[0] + ".onnx"
        try:
            save_model(out, self.trainer.policy, unflatten(self.trainer.policy, genome), meta)
            screen.message(f"ONNX exportado: {os.path.basename(out)}", GOOD)
        except Exception as exc:
            screen.message(f"falha no ONNX: {exc}", BAD)

    def list_model_files(self):
        out = []
        folder = mods.models_dir()
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception:
            pass
        for root, _dirs, files in os.walk(folder):
            for f in sorted(files):
                if f.lower().endswith((".pt", ".npz", ".onnx")):
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, mods.base_dir())
                    out.append((f"{rel}  ({os.path.getsize(full) / 1024:.0f} KB)", full))
        if not out:
            out.append(("(nenhum modelo em modelos/)", ""))
        return out

    def build_settings(self, cx, h) -> Screen:
        st = self.settings
        s = Screen("Configurações", "mudanças de população/device/pistas reiniciam a simulação")
        left = pygame.Rect(cx - 400, 110, 380, h - 200)
        right = pygame.Rect(cx + 20, 110, 380, h - 200)
        y = 110

        def slider(rect, label, key, vmin, vmax, step, fmt="{:.0f}", cast=float,
                   restart=False, live=None):
            def on_change(v):
                value = cast(v)
                st[key] = value
                if live:
                    self.trainer.set_sim_params(**{live: value})
                if restart:
                    self.apply_settings_deferred()
            return s.add(Slider(rect, label, cast(st[key]), vmin, vmax, step, fmt, on_change))

        # --- evolução
        s.add(Label(pygame.Rect(left.x, y, 0, 0), "EVOLUÇÃO", 16, ACCENT))
        y += 24
        slider(pygame.Rect(left.x, y, 360, 24), "população", "population", 2, 400, 2,
               restart=True, cast=int)
        y += 46
        slider(pygame.Rect(left.x, y, 360, 24), "elitismo (fração)", "elitism", 0.0, 0.5, 0.01,
               "{:.2f}")
        y += 46
        slider(pygame.Rect(left.x, y, 360, 24), "chance de mutação", "mutation_rate", 0.0, 0.5,
               0.005, "{:.3f}")
        y += 46
        slider(pygame.Rect(left.x, y, 360, 24), "intensidade (sigma)", "mutation_sigma", 0.01,
               0.8, 0.01, "{:.2f}")
        y += 46
        slider(pygame.Rect(left.x, y, 360, 24), "sangue novo", "fresh_blood", 0.0, 0.3, 0.01,
               "{:.2f}")
        y += 46
        slider(pygame.Rect(left.x, y, 360, 24), "torneio", "tournament", 2, 10, 1, cast=int)
        y += 46
        s.add(Toggle(pygame.Rect(left.x, y, 360, 24), "gerações ativadas (G)",
                     bool(st["generations"]),
                     lambda v: (st.__setitem__("generations", v),
                                setattr(self.trainer, "generations_enabled", v))))
        y += 40
        s.add(OptionCycle(pygame.Rect(left.x, y, 170, 30), "cruzamento", ["blend", "uniform"],
                          0 if st["crossover"] == "blend" else 1,
                          on_change=lambda v, i: st.__setitem__("crossover", v)))
        s.add(OptionCycle(pygame.Rect(left.x + 190, y, 170, 30), "velocidade",
                          [f"{v}x" for v in SPEEDS], int(st["speed"]),
                          on_change=lambda v, i: st.__setitem__("speed", i)))

        # --- simulação / render
        y2 = 110
        s.add(Label(pygame.Rect(right.x, y2, 0, 0), "SIMULAÇÃO", 16, ACCENT))
        y2 += 24
        slider(pygame.Rect(right.x, y2, 360, 24), "duração da geração (s)", "max_seconds", 10,
               180, 5, live="max_seconds")
        y2 += 46
        slider(pygame.Rect(right.x, y2, 360, 24), "passos entre decisões", "decision_interval",
               1, 10, 1, cast=int, live="decision_interval")
        y2 += 46
        slider(pygame.Rect(right.x, y2, 360, 24), "raios do sensor", "rays", 3, 15, 1,
               cast=int, restart=True)
        y2 += 46
        devices = [d[0] for d in list_devices()]
        dev_idx = devices.index(st["device"]) if st["device"] in devices else 0
        s.add(OptionCycle(pygame.Rect(right.x, y2, 360, 30), "backend de inferência", devices,
                          dev_idx, on_change=lambda v, i: self.change_device(v)))
        y2 += 56
        s.add(Label(pygame.Rect(right.x, y2, 0, 0), "VISUAL", 16, ACCENT))
        y2 += 24
        s.add(Toggle(pygame.Rect(right.x, y2, 360, 24), "mostrar HUD (H)", bool(st["show_hud"]),
                     lambda v: st.__setitem__("show_hud", v)))
        y2 += 32
        s.add(Toggle(pygame.Rect(right.x, y2, 360, 24), "desenhar todos os carros",
                     bool(st["draw_ghosts"]), lambda v: st.__setitem__("draw_ghosts", v)))
        y2 += 32
        s.add(Toggle(pygame.Rect(right.x, y2, 360, 24), "raios do sensor (TAB)",
                     bool(st["draw_rays"]), lambda v: st.__setitem__("draw_rays", v)))
        y2 += 46
        slider(pygame.Rect(right.x, y2, 360, 24), "máx. carros desenhados", "max_draw", 5, 300,
               5, cast=int)
        y2 += 46
        slider(pygame.Rect(right.x, y2, 360, 24), "salvar automático (gerações)",
               "autosave_every", 0, 100, 5, cast=int)
        y2 += 46
        s.add(Button(pygame.Rect(right.x, y2, 175, 36), "Reiniciar treino",
                     lambda: (self.trainer.reset_training(), self.notify("treino reiniciado"))))
        s.add(Button(pygame.Rect(right.x + 185, y2, 175, 36), "Voltar",
                     lambda: self.goto("main")))
        return s

    def change_device(self, device_id: str):
        self.settings["device"] = device_id
        self.trainer.set_device(device_id)
        self.notify(f"backend: {self.trainer.state.device_desc}", GOOD)
        self.save_settings()

    def apply_settings_deferred(self):
        """Aplicado ao sair da tela (reconstrói o trainer)."""
        self._needs_rebuild = True

    def build_mods(self, cx, h) -> Screen:
        s = Screen("Mods", f"pasta de mods: {mods.mods_dir()}")
        items = []
        for t in self.tracks:
            items.append(("pista", t))
        for c in self.cars:
            items.append(("carro", c))
        self._mod_items = items
        box = ListBox(pygame.Rect(cx - 380, 120, 760, min(360, h - 260)),
                      [f"{kind}: {it.name}" for kind, it in items], 0,
                      render_item=lambda r, row, item, sel: self._render_mod_item(
                          r, row, item, sel, box))
        s.add(box)
        y = 130 + min(360, h - 260)

        def reload():
            self.reload_mods()
            self.screens = {}
            s.message("mods recarregados", GOOD)

        s.add(Button(pygame.Rect(cx - 380, y, 180, 38), "Recarregar", reload))
        s.add(Button(pygame.Rect(cx - 190, y, 180, 38), "Abrir pasta de mods",
                     lambda: mods.open_folder(mods.mods_dir())))
        s.add(Button(pygame.Rect(cx + 10, y, 180, 38), "Nova pista (modelo)",
                     lambda: s.message(f"criado: {mods.create_template('tracks', 'minha pista')}",
                                       GOOD)))
        s.add(Button(pygame.Rect(cx + 200, y, 180, 38), "Novo carro (modelo)",
                     lambda: s.message(f"criado: {mods.create_template('cars', 'meu carro')}",
                                       GOOD)))
        y += 46
        s.add(Button(pygame.Rect(cx - 380, y, 180, 38), "Voltar", lambda: self.goto("main")))
        return s

    def _render_mod_item(self, r, row, item, selected, box):
        idx = int(round((row.y - (box.rect.y + 6) + box.scroll) / box.item_h))
        items = getattr(self, "_mod_items", [])
        if not (0 <= idx < len(items)):
            return
        kind, it = items[idx]
        color = TEXT if selected else TEXT_DIM
        r.text(r.screen, f"{kind}: {it.name}{'  [mod]' if not it.builtin else ''}",
               (row.x + 8, row.centery - 6), 16, color, anchor="midleft")
        status = it.error or ("embutido" if it.builtin else "mod do usuário")
        r.text(r.screen, status, (row.right - 10, row.centery - 6), 12,
               BAD if it.error else TEXT_DIM, anchor="midright")
        r.text(r.screen, os.path.basename(it.path), (row.x + 8, row.centery + 9), 11, TEXT_DIM)

    def build_help(self, cx, h) -> Screen:
        s = Screen("Ajuda", "teclas e conceitos básicos")
        lines = [
            "MANUAL: setas ou WASD dirigem · espaço/p = pausa · R reinicia",
            "TREINO: G liga/desliga as gerações · F muda a velocidade (1x..32x)",
            "        C troca o carro focado · TAB mostra os raios do sensor",
            "        CTRL+S salva o melhor modelo · L abre a tela de modelos",
            "+/- aproxima/afasta a câmera · H esconde o HUD · ESC abre o menu",
            "1/2/3 alternam manual / IA / treino",
            "",
            "O modelo é uma MLP pequena (sensores -> tanh -> [esterço, acelerador]).",
            "A evolução mantém os melhores intactos (elitismo), cruza os pais por",
            "torneio e aplica mutação gaussiana com sigma adaptativo.",
            "",
            "Modelos: .pt (PyTorch, roda em GPU via DirectML) ou .npz (numpy).",
            "Mods: JSONs em mods/tracks e mods/cars — copie um de assets/ e edite.",
        ]
        for i, line in enumerate(lines):
            s.add(Label(pygame.Rect(cx - 420, 120 + i * 24, 0, 0), line, 17, TEXT))
        y = 120 + len(lines) * 24 + 20
        s.add(Button(pygame.Rect(cx - 90, y, 180, 38), "Voltar", lambda: self.goto("main"),
                     "primary"))
        return s

    # ------------------------------------------------------------------ #
    def draw_extra(self):
        """Desenha detalhes contextuais das telas (preview de pista/carro)."""
        if self.screen_name == "tracks" and hasattr(self, "_track_preview_rect"):
            self.draw_track_preview(self._track_preview_rect)
        if self.screen_name == "cars" and hasattr(self, "_car_info_rect"):
            self.draw_car_info(self._car_info_rect)

    def draw_track_preview(self, rect: pygame.Rect):
        r = self.renderer
        self.renderer.panel(rect)
        idx = getattr(self, "_preview_index", -1)
        item = self.tracks[self.track_index]
        if item.obj is None:
            r.text(self.screen, item.error or "pista inválida", rect.center, 16, BAD,
                   anchor="center")
            return
        trk = item.obj
        minx, miny, maxx, maxy = trk.bounds()
        w = maxx - minx
        h = maxy - miny
        pad = 20
        scale = min((rect.width - pad * 2) / max(w, 1e-6), (rect.height - pad * 2) / max(h, 1e-6))
        ox = rect.x + (rect.width - w * scale) * 0.5
        oy = rect.y + (rect.height - h * scale) * 0.5

        def mp(pts):
            return np.stack([ox + (pts[:, 0] - minx) * scale,
                             oy + (maxy - pts[:, 1]) * scale], axis=1).astype(int)

        pygame.draw.polygon(self.screen, (58, 60, 66),
                            np.vstack([mp(trk.edge_l), mp(trk.edge_r)[::-1]]))
        pygame.draw.lines(self.screen, (225, 228, 235), trk.closed, mp(trk.edge_l), 2)
        pygame.draw.lines(self.screen, (225, 228, 235), trk.closed, mp(trk.edge_r), 2)
        p = mp(trk.center[trk.start_index:trk.start_index + 1])[0]
        pygame.draw.circle(self.screen, GOOD, p, 4)
        r.text(self.screen, f"{trk.length:.0f} m · largura média "
                            f"{trk.half_widths.mean() * 2:.1f} m · "
                            f"{trk.n} pontos", (rect.x + 10, rect.bottom - 24), 14, TEXT_DIM)
        diff = trk.meta.get("difficulty", "")
        if diff:
            r.text(self.screen, f"dificuldade: {diff}", (rect.right - 10, rect.bottom - 24),
                   14, TEXT_DIM, anchor="topright")

    def draw_car_info(self, rect: pygame.Rect):
        r = self.renderer
        self.renderer.panel(rect)
        item = self.cars[self.car_index]
        if item.obj is None:
            r.text(self.screen, item.error or "carro inválido", rect.center, 16, BAD,
                   anchor="center")
            return
        car = item.obj
        r.text(self.screen, car.name, (rect.x + 14, rect.y + 12), 22, TEXT, bold=True)
        r.text(self.screen, car.summary(), (rect.x + 14, rect.y + 40), 14, TEXT_DIM)
        rows = [
            ("potência", car.max_power / 1000.0, 600, "{:.0f} kW"),
            ("relação peso/potência", car.power_to_weight, 500, "{:.0f} W/kg"),
            ("massa", car.mass, 3000, "{:.0f} kg"),
            ("aderência dianteira", car.grip_front, 2.5, "{:.2f}"),
            ("aderência traseira", car.grip_rear, 2.5, "{:.2f}"),
            ("frenagem", car.brake_force / 1000.0, 25, "{:.0f} kN"),
            ("velocidade máxima", car.max_speed * 3.6, 350, "{:.0f} km/h"),
            ("esterço máximo", np.degrees(car.max_steer), 60, "{:.0f}°"),
            ("downforce", car.downforce, 4, "{:.1f}"),
        ]
        y = rect.y + 70
        for label, value, vmax, fmt in rows:
            r.text(self.screen, label, (rect.x + 14, y), 14, TEXT_DIM)
            r.text(self.screen, fmt.format(value), (rect.right - 14, y - 14), 14, ACCENT,
                   anchor="topright")
            r.bar(pygame.Rect(rect.x + 14, y + 16, rect.width - 28, 6),
                  value / max(vmax, 1e-6), ACCENT)
            y += 38
        drive = ("dianteira" if car.drive_front > 0.8 else
                 "traseira" if car.drive_front < 0.2 else "integral")
        r.text(self.screen, f"tração {drive}", (rect.x + 14, rect.bottom - 24), 14, TEXT)
