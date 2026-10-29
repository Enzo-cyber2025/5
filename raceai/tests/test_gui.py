"""Teste de fumaça da interface: monta o jogo e desenha tudo sem janela.

Usa o driver de vídeo "dummy" do SDL, então funciona em CI/headless.
"""
from __future__ import annotations

import os
import sys

import numpy as np


def run_gui_smoke() -> int:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
    pygame.display.init()
    try:
        probe = pygame.display.set_mode((320, 240))
        pygame.display.quit()
        if probe is None:
            raise RuntimeError("set_mode devolveu None")
    except Exception as exc:
        print(f"[interface] pulando teste: sem driver de vídeo ({exc})")
        return 0
    from raceai.app import App

    app = App(width=1024, height=700, start_mode="train")
    app.settings["max_seconds"] = 6.0
    app.trainer.set_sim_params(max_seconds=6.0)
    app.settings["speed"] = 5                    # 32x para o teste terminar rápido
    app.settings["population"] = 24
    app.apply_mode()

    # algumas gerações devem se completar
    gens_before = app.trainer.pop.generation
    for _ in range(600):
        app.update(1.0 / 60.0)
        if app.trainer.pop.generation >= gens_before + 2:
            break
        if _ % 60 == 0:
            app.render()
    assert app.trainer.pop.generation >= gens_before + 1, "nenhuma geração concluída"
    assert app.trainer.pop.history, "sem histórico de fitness"

    # todas as telas precisam desenhar sem erro
    for name in ("main", "corrida", "treino", "tracks", "cars", "models", "settings",
                 "mods", "help"):
        app.goto(name)
        app.render()

    # atalhos de teclado
    app.goto("none")
    app.screen_name = "none"
    for key in (pygame.K_g, pygame.K_f, pygame.K_h, pygame.K_TAB, pygame.K_c, pygame.K_r,
                pygame.K_PLUS, pygame.K_MINUS):
        app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key, mod=0, unicode=""))

    # modos manual e IA
    app.set_mode("manual")
    app.settings["speed"] = 0
    for _ in range(30):
        app.update(1.0 / 60.0)
    app.render()
    assert app.trainer.manual_control
    app.set_mode("ia")
    for _ in range(30):
        app.update(1.0 / 60.0)
    app.render()
    app.set_mode("train")
    app.render()

    # salvar/carregar pela interface
    app.save_best(os.path.join(app.trainer and "modelos", "teste_gui.npz"))
    app.settings["show_hud"] = False
    app.render()
    app.settings["show_hud"] = True
    app.settings["draw_rays"] = True
    app.render()

    # ---- modo corrida: vários carros e modelos correndo ao mesmo tempo
    app.screen_name = "none"
    app.screens = {}
    app.settings["race_laps"] = 1
    app.settings["speed"] = 5                     # 32x
    assert app.start_race(), "não conseguiu montar a corrida"
    assert app.race is not None and len(app.race.entries) >= 2, "grid vazio"
    kinds = sorted({e.kind for e in app.race.entries})
    print(f"  corrida: {len(app.race.entries)} competidores ({'/'.join(kinds)})")
    for frame in range(3000):
        app.update(1.0 / 60.0)
        if frame % 150 == 0:
            app.render()
        if app.race.state == "finished":
            break
    assert app.race.state == "finished", "a corrida não terminou"
    st = app.race.standings()
    assert len(st) == len(app.race.entries) and st[0]["pos"] == 1, "classificação quebrada"
    app.render()
    print(f"  corrida: {len(st)} classificados · líder {st[0]['nome']} "
          f"({st[0]['voltas']} volta(s))")

    # ---- treinamento por épocas, salvando .pt no fim
    modelo = os.path.join("modelos", "teste_treino.pt")
    app.settings["model"] = modelo
    app.settings["max_seconds"] = 6.0
    app.start_training(individuals=8, epochs=2)
    assert app.train_session and app.train_session["target"] == 2, "sessão não criada"
    for frame in range(4000):
        app.update(1.0 / 60.0)
        if frame % 150 == 0:
            app.render()
        if app.train_session["done"]:
            break
    assert app.train_session["done"], "o treino não terminou"
    resumo = app.train_summary or {}
    assert resumo.get("épocas", 0) >= 2, "épocas insuficientes"
    assert resumo.get("arquivo") and os.path.isfile(resumo["arquivo"]), "modelo não salvo"
    app.render()                                  # tela de resultado
    print(f"  treino: {resumo['épocas']} épocas · melhor {resumo['melhor']:.0f} · "
          f"{os.path.basename(resumo['arquivo'])}")
    try:
        os.remove(resumo["arquivo"])
    except OSError:
        pass

    # troca de pista/carro por índice
    for i in range(len(app.tracks)):
        app.track_index = i
        app.trainer.set_track(app.tracks[i].obj)
        app.render()
    for i in range(len(app.cars)):
        app.car_index = i
        app.trainer.set_car(app.cars[i].obj)
        app.render()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_gui_smoke())
