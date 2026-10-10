"""Modo PRATICA: a IA aprende e dirige no ETS2 REAL.

Esta e a resposta para "fazer a IA praticar no ETS2": um loop que roda ao
lado do jogo lendo a telemetria REAL (plugin RenCloud scs-sdk-plugin) e,
dependendo do modo:

  record  — VOCE dirige; o loop aprende o mapa da estrada (linha central +
            curvaturas a frente, coisa que o SDK nao da) e grava
            estado->comando REAIS para finetune (formato ets2ai-rec,v1).
            Na 1a passada o mapa e construido; da 2a em diante as features
            ficam completas e tudo vira dado de treino.

  shadow  — VOCE dirige; a IA calcula o que faria e nao injeta NADA. Serve
            para (a) conferir que os sinais do mapa estao certos (veredicto
            "ESPELHADO?" no HUD) e (b) medir a divergencia antes de deixar
            a IA no volante.

  drive   — A IA DIRIGE (injeta as setas/Espaco via SendInput; ESC = kill).
            Se voce encostar no volante/teclado, o loop detecta a
            intervencao, solta as teclas e grava a correcao humana
            (DAgger) — e depois volta a dirigir.

Depois de uma sessao:  python -m ets2ai.finetune --recordings sessao.csv
A cada sessao o mapa melhora e o finetune adapta a rede — e literalmente
a IA "praticando" no jogo de verdade. Sem captura de tela, sem mexer no
jogo: so telemetria + teclas.

Uso (no Windows, com o ETS2 aberto):
    python -m ets2ai.practice record --map practice/mapa.json
    python -m ets2ai.practice shadow --map practice/mapa.json
    python -m ets2ai.practice drive --map practice/mapa.json \
        --inject --window "Euro Truck" --rec practice/sessao1.csv
"""
import argparse
import math
import os
import time
from pathlib import Path

import numpy as np

from . import sim, telemetry
from .contract import load_weights, clamp_action
from .keys import KeyInjector, Recorder, load_keymap
from .model import make_forward_fast
from .joy import JoystickMonitor
from . import memtelemetry
from .model import forward
from .roadmap import RoadMap, detect_frame, wrap

TICK = 0.05               # 20 Hz (a telemetria atualiza por frame do jogo)
COURSE_WIN_M = 6.0        # janela do curso por deslocamento
STALE_S = 1.0             # telemetria congelada por isso = solta as teclas
REC_MIN_COVERAGE = 3      # minimo de curvaturas a frente p/ gravar linha
UNKNOWN_CAP = 8.0         # teto de velocidade (m/s) em estrada sem mapa
OVERRIDE_RESUME_S = 1.5   # humano soltou os controles por isto = IA volta
FATIGUE_MIN = 660.0       # ~11 h de jogo ate fatigue=1 (como o sim)
BASE_WEIGHTS = Path(__file__).resolve().parent.parent / "artifacts" / "model-weights.json"


# ---------------------------------------------------------------------------
# Features do contrato a partir de telemetria + mapa
# ---------------------------------------------------------------------------
def features_from(sn, road_map, course, job_minutes):
    """Monta as 13 features do contrato (mesma ordem/escala do sim).

    Retorna (features, meta) — meta carrega o que o HUD e o governador
    precisam (offset, heading_error, curvaturas, cobertura do mapa).
    """
    speed = max(0.0, sn["speed"])
    fuel_cap = sn.get("fuel_capacity") or 600.0
    fuel = min(1.0, max(0.0, sn["fuel"] / fuel_cap)) if fuel_cap > 1.0 else 1.0
    limit = sn.get("speed_limit") or 0.0
    if limit < 0.5:
        limit = 25.0
    limit = min(limit, 25.0)
    meta = {"located": False, "coverage": 0, "offset": 0.0,
            "heading_error": 0.0, "curvs": [None] * 5}
    curv_feat = [0.0] * 5
    if course is not None:
        loc = road_map.locate(sn["world_x"], sn["world_z"], course)
        if loc is not None:
            idx, offset, tangent = loc
            he = wrap(course - tangent)
            curvs = road_map.curvatures_ahead(idx, course)
            meta.update(located=True, offset=offset, heading_error=he,
                        curvs=curvs, idx=idx,
                        coverage=sum(c is not None for c in curvs))
            curv_feat = [(c if c is not None else 0.0) / 0.05 for c in curvs]
    route_km = max(0.0, sn.get("route_distance", 0.0)) / 1000.0
    feat = [
        min(speed, 50.0) / 25.0,
        max(-2.0, min(2.0, meta["offset"] / 3.5)),
        max(-2.0, min(2.0, meta["heading_error"] / 0.6)),
        *[max(-2.0, min(2.0, c)) for c in curv_feat],
        limit / 25.0,
        fuel,
        min(1.0, max(0.0, job_minutes) / FATIGUE_MIN),
        min(route_km, 20.0) / 20.0,
        1.0,                      # radar: SDK nao expoe — "sem radar a frente"
    ]
    return feat, meta


# ---------------------------------------------------------------------------
# Governador (porta do sim.governor para o mundo real)
# ---------------------------------------------------------------------------
def governor_real(speed, meta, route_distance_m, cmd, limit_mps):
    """ESC por curvatura + teto de limite + aproximação do dock + anti-stall.

    route_distance_m: metros ate o destino (navigation). <=0 = sem rota.
    """
    # 1. curva a frente que exige menos velocidade do que da pra frear
    if meta["located"]:
        worst = None
        for d, k in zip(sim.LOOKAHEAD, meta["curvs"]):
            if k is None or abs(k) < 1e-6:
                continue
            v_curve = math.sqrt(sim.GOVERNOR_LIMIT / abs(k))
            v_allow = math.sqrt(v_curve ** 2 +
                                2.0 * sim.MAX_BRAKE * max(0.0, d - 8.0))
            worst = v_allow if worst is None else min(worst, v_allow)
        if worst is not None and speed > worst:
            return (cmd[0], 0.0, 1.0)
    # 2. respeito ao limite da via (o modelo ve o limite; o governador garante)
    if speed > limit_mps + 2.0:
        return (cmd[0], 0.0, 0.85)
    # 3. aproximacao do destino: nunca carregar velocidade ate a entrega
    #    (perfil sonoro igual sim.governor: mira 4 m antes, hold 2,0 m,
    #     freio total mesmo se cruzar a linha)
    # route_distance_m None = SEM ROTA/job: o velho 0.0 caia no elif
    # "cruzou: freia" e a IA segurava o freio PARA SEMPRE sem job ativo
    # (o anti-stall nunca rodava — retorno antecipado).
    if route_distance_m is not None and 0.0 < route_distance_m < 600.0:
        v_allow = math.sqrt(2.0 * sim.MAX_BRAKE * max(0.0, route_distance_m - 4.0))
        if speed > v_allow:
            return (cmd[0], 0.0, 1.0)
        if route_distance_m <= 1.5:
            return (cmd[0], 0.0, 1.0)                 # para na linha
        if speed < 2.0:
            return (cmd[0], max(cmd[1], 0.35), 0.0)   # creep final
    elif route_distance_m is not None and \
            -50.0 < route_distance_m <= 0.0:
        return (cmd[0], 0.0, 1.0)                     # cruzou: freia
    # 4. anti-stall + LAUNCH (nunca parar/engasgar no meio da estrada) —
    #    piso de acelerador ate 2.0 m/s: a rede tem um VALE de arranque
    #    entre ~0.5-1.5 m/s (throttle ~0.15, abaixo do gatilho da tecla)
    #    herdado do sim, onde o lancamento era papel do anti-stall — sem
    #    o piso o caminhao oscila preso a ~2 km/h para sempre (provado na
    #    PROVA DE DIRECAO do CI). Acima de 2.0 a rede assume (thr 0.32+).
    if speed < 2.0 and (route_distance_m is None or
                        route_distance_m <= 0.0 or route_distance_m > 30.0):
        return (cmd[0], max(cmd[1], 0.35), 0.0)
    # 5. estrada desconhecida: devagar ate o mapa cobrir
    if not meta["located"] and speed > UNKNOWN_CAP:
        return (cmd[0], 0.0, 1.0)
    if meta["located"] and meta["coverage"] < REC_MIN_COVERAGE and speed > UNKNOWN_CAP:
        return (cmd[0], 0.0, 1.0)
    return cmd


# ---------------------------------------------------------------------------
# O loop de pratica
# ---------------------------------------------------------------------------
class PracticeLoop:
    """Loop principal: telemetria -> mapa/features -> politica -> teclas/gravacao.

    `source`: funcao que devolve um snapshot (TelemetryReader.snapshot ou um
    simulado nos testes). `policy_fn`: (features) -> (steer, throttle, brake)
    — por padrao a rede neural; testes podem injetar um controlador.
    """

    def __init__(self, mode, road_map, source, layers=None, injector=None,
                 recorder=None, map_path=None, policy_fn=None, phone=None,
                 tick=TICK, clock=time.monotonic, sleep=time.sleep, log=print,
                 foreign_keys=None, stop_event=None, macros=None,
                 joystick=None):
        assert mode in ("record", "drive", "shadow")
        self.mode = mode
        self.road_map = road_map
        self.source = source
        self.injector = injector
        self.phone = phone
        self.recorder = recorder
        self.map_path = map_path
        self.layers = layers
        self._fast_fwd = make_forward_fast(layers) if layers else None
        self.policy_fn = policy_fn or self._nn_policy
        self.tick = tick
        self.clock = clock
        self.sleep = sleep
        self.log = log
        self.stop = False
        # estado
        self._trail = []            # [(wx, wz)] janela do curso
        self._trail_d = 0.0
        self._course = None
        self._pending = []          # gravacoes aguardando a calibracao do frame
        self._cal_pts, self._cal_steer = [], []
        self._last_ticks, self._ticks_t = None, 0.0
        self._job_start_min = None
        self._override_hold = 0.0   # ate quando o humano manda (drive)
        self.macros = macros or {}  # teclas ORIGINAIS do jogo (controls.sii)
        self.joystick = joystick    # volante/joystick: humano no controle
        self._signal = None         # None | "left" | "right" (seta acesa)
        self._last_signal_t = -1e9
        self._last_pit_t = -1e9     # aviso (combustivel/sono): 30 s
        self._last_ok_t = -1e9      # Enter de confirmacao: 10 s
        self._parked_at_dest = False
        self._cold_t0 = None        # arranque frio: quando parou (drive)
        self._last_macro_t = -1e9
        self._fk_ticks = 0          # teclas fisicas estranhas seguidas
        self._no_frame_needed = False   # telemetria sem input do jogo (mem)
        self.foreign_keys = foreign_keys or None
        self.stop_event = stop_event      # GUI: botao PARAR
        self._human_active = False
        self._exp_steer = 0.0       # input esperado (rampa do jogo)
        self._exp_thr = 0.0
        self._exp_brk = 0.0
        self._obs_steer = 0.0       # input observado (suavizado p/ PWM)
        self._obs_thr = 0.0
        self._obs_brk = 0.0
        self._sm_steer = 0.0        # esperado suavizado
        self._sm_thr = 0.0
        self._sm_brk = 0.0
        self._dev_ticks = 0
        self._last_human_t = 0.0
        self._shadow_n, self._shadow_dot = 0, 0.0
        self._shadow_ai, self._shadow_h = 0.0, 0.0
        self._last_hud = 0.0
        self._last_save = 0.0
        self.rows = 0
        self.n_steps = 0
        self.speed_max = 0.0

    # ------------------------------------------------------------------ #
    def _nn_policy(self, feat):
        # CAMINHO RAPIDO: buffers pre-alocados (zero alocacao por tick) —
        # <1% de CPU no N5030. Cai no forward() classico se nao houver.
        if self._fast_fwd is not None:
            o = self._fast_fwd(feat)
        else:
            o = forward(np.asarray(feat, dtype=np.float32),
                        self.layers)[0]
        return clamp_action(float(o[0]), float(o[1]), float(o[2]))

    def _phone_or_local(self, feat, sn, meta):
        """IA no CELULAR (GPU/TFLite do APK) via protocolo S; sem resposta
        a tempo cai na IA local do PC — e sem pesos, freia (seguro)."""
        ph = self.phone
        if ph is not None and getattr(ph, "connected", False):
            try:
                ph.send_fields(
                    speed=max(0.0, sn["speed"]),
                    offset=meta.get("offset", 0.0),
                    hdg=meta.get("heading_error", 0.0),
                    curvs=meta.get("curvs", [None] * 5),
                    limit=min(sn.get("speed_limit") or 25.0, 25.0),
                    fuel=min(1.0, max(0.0, (sn.get("fuel") or 0.0)
                                      / ((sn.get("fuel_capacity") or 600.0)
                                         or 600.0))),
                    fatigue=min(1.0, max(0.0, (self._job_min or 0.0)
                                         / FATIGUE_MIN)),
                    job_km=max(0.0, sn.get("route_distance", 0.0)) / 1000.0)
                cmd = ph.wait_cmd(0.30)
                if cmd is not None:
                    return clamp_action(*cmd), "celular"
            except Exception:
                pass
        # sem celular: politica local (IA numpy do PC — ou a politica de teste)
        if self.layers is not None or self.policy_fn is not self._nn_policy:
            return self.policy_fn(feat), "pc"
        return (0.0, 0.0, 0.8), "freio"      # sem IA disponivel: para

    def _update_course(self, sn):
        """Curso (direcao do deslocamento) numa janela de ~6 m."""
        wx, wz = sn["world_x"], sn["world_z"]
        if not self._trail:
            self._trail = [(wx, wz)]
            return None
        lx, lz = self._trail[-1]
        d = math.hypot(wx - lx, wz - lz)
        if d < 0.15:
            return self._course
        self._trail.append((wx, wz))
        self._trail_d += d
        while len(self._trail) > 2:
            dx = self._trail[1][0] - self._trail[0][0]
            dz = self._trail[1][1] - self._trail[0][1]
            if self._trail_d - math.hypot(dx, dz) >= COURSE_WIN_M:
                self._trail.pop(0)
                self._trail_d -= math.hypot(dx, dz)
            else:
                break
        ax, az = self._trail[0]
        if math.hypot(wx - ax, wz - az) >= 3.0:
            self._course = math.atan2(wz - az, wx - ax)
        return self._course

    def _calibrate(self, sn):
        """Coleta dirigida ate travar a reflexao do frame do jogo."""
        if self._no_frame_needed:
            return          # memoria nativa: nao existe espelho a calibrar
        if self.road_map.frame.locked or len(self.road_map.x) > 0:
            return
        if abs(sn["speed"]) < 1.0:
            return
        if self._cal_pts and math.hypot(sn["world_x"] - self._cal_pts[-1][0],
                                        sn["world_z"] - self._cal_pts[-1][1]) < 2.5:
            return
        self._cal_pts.append((sn["world_x"], sn["world_z"]))
        self._cal_steer.append(sn["user_steer"])
        if len(self._cal_pts) >= 40 and len(self._cal_pts) % 20 == 0:
            f, q = detect_frame(self._cal_pts, self._cal_steer)
            if f.locked:
                self.road_map.frame = f
                self.log(f"[calibra] frame travado (z_flip={f.z_flip}, "
                         f"confianca {q:.2f}) — despejando {len(self._pending)} "
                         f"pontos pendentes no mapa")
                for (wx, wz, hd, v) in self._pending:
                    self.road_map.record(wx, wz, hd, v)
                self._pending = []

    def _record_row(self, feat, cmd, override, src):
        if self.recorder is not None:
            self.recorder.write(feat, cmd, override, src)
            self.rows += 1

    # ------------------------------------------------------------------ #
    def step(self, sn, now):
        """Um tick do loop. Retorna dict de estado para o HUD/testes."""
        self.n_steps += 1
        out = {"telemetry": True, "stale": False, "cmd": None,
               "source": self.mode, "feat": None, "meta": None}
        # telemetria viva? (ticks do jogo congelando = menu/pausa)
        if sn["ticks"] != self._last_ticks:
            self._last_ticks = sn["ticks"]
            self._ticks_t = now
        elif now - self._ticks_t > STALE_S and not sn.get("paused"):
            out.update(telemetry=False, stale=True)
        if sn.get("paused"):
            out.update(telemetry=False, stale=False, paused=True)
        if not out["telemetry"]:
            if self.injector is not None:
                self.injector.release_all()
            return out
        self.speed_max = max(self.speed_max, sn["speed"])
        if sn.get("user_steer") is None:
            # leitor sem DLL (memoria): coordenadas NATIVAS do jogo — nao ha
            # reflexao de frame p/ calibrar; e os inputs do jogador nao vem
            # pela telemetria (deteccao de humano e por teclas fisicas).
            self._no_frame_needed = True
        course = self._update_course(sn)
        self._calibrate(sn)
        # minutos de trabalho (para fatigue)
        if sn.get("on_job") and self._job_start_min is None:
            self._job_start_min = sn["game_minutes"]
        if not sn.get("on_job"):
            self._job_start_min = None
        job_min = (sn["game_minutes"] - self._job_start_min) \
            if self._job_start_min is not None else 0.0
        self._job_min = job_min
        # mapa: em record/shadow o HUMANO refina a linha central (dado bom);
        # em drive a IA so ESTENDE o mapa onde ele nao existe — nunca deixa
        # a propria oscilacao virar "centro da pista" (espiral de erro).
        if course is not None and sn["speed"] > 0.5:
            loc_now = self.road_map.locate(sn["world_x"], sn["world_z"], course)
            if (self.road_map.frame.locked or len(self.road_map.x) > 0
                    or self._no_frame_needed):
                if self.mode == "drive":
                    if loc_now is None:
                        self.road_map.record(sn["world_x"], sn["world_z"],
                                             course, sn["speed"])
                else:
                    good = loc_now is None or abs(loc_now[1]) < 0.5
                    if good:
                        self.road_map.record(sn["world_x"], sn["world_z"],
                                             course, sn["speed"])
            else:
                self._pending.append((sn["world_x"], sn["world_z"], course,
                                      sn["speed"]))
                if len(self._pending) > 1200 and len(self._pending) % 400 == 0:
                    self.log("[pratica] AVISO: frame do jogo ainda nao "
                             "calibrado (dirija COM CURVAS por ~1 min); o "
                             "mapa comeca depois disso")
        feat, meta = features_from(sn, self.road_map, course, job_min)
        out["feat"], out["meta"] = feat, meta
        limit = sn.get("speed_limit") or 25.0
        if limit < 0.5:
            limit = 25.0
        # rota do GPS: valida COM job (destino) OU sem job quando o jogo
        # reporta um alvo real (caminhao proprio: buscar/acoplar o reboque;
        # sem alvo de verdade o jogo reporta ~0 -> None)
        route_m = sn.get("route_distance", 0.0)
        if route_m is not None and route_m <= 1.0 and not sn.get("on_job"):
            route_m = None
        # ---- por modo ----
        if self.mode == "record":
            self._maybe_record(feat, meta, sn, speed_min=0.5)
            out["source"] = "voce (gravando)"
        elif self.mode == "shadow":
            cmd, ai_src = self._phone_or_local(feat, sn, meta)
            self._shadow_update(cmd, sn)
            self._maybe_record(feat, meta, sn, speed_min=0.5)
            out["cmd"], out["source"] = cmd, "IA (sombra, sem injecao)"
        else:  # drive
            cmd, ai_src = self._phone_or_local(feat, sn, meta)
            self._human_detect(sn, cmd, now)
            if self._human_active or (now < self._override_hold):
                if self.injector is not None:
                    self.injector.release_all()
                self._maybe_record(feat, meta, sn, speed_min=0.5,
                                   override=True, src="H")
                out["source"] = "HUMANO no comando (DAgger)"
            else:
                self._job_flow(sn, now)
                self._cold_start(sn, now)
                self._maybe_signal(meta, sn, now)
                self._pit_crew(sn, now, job_min)
                # chegou ao destino: freia ate parar e PUXA O FREIAO DE MAO
                if route_m is not None and 0.0 < route_m <= 1.5 \
                        and sn["speed"] < 0.5:
                    if not self._parked_at_dest:
                        self._parked_at_dest = True
                        if self.injector is not None:
                            self.injector.tap(*self.macros.get(
                                "park_brake", (0x39, "freio de mao")))
                        self.log("[pratica] destino: parado — freio de mao "
                                 "PUXADO e setas apagadas")
                # mapa ainda vazio: assume MODERADO (11 m/s ~ 40 km/h) ate
                # se situar (40 pontos de estrada) — a tomada continua
                # IMEDIATA, so nao acelera tudo no escuro.
                if not (self.road_map.frame.locked
                        or len(self.road_map.x) >= 40):
                    limit = min(limit, 11.0)
                cmd = governor_real(sn["speed"], meta, route_m, cmd, limit)
                if self.injector is not None:
                    if sn.get("park_brake") and sn["speed"] < 0.5:
                        self.injector.release_all()
                    else:
                        self.injector.update(*cmd)
                out["cmd"], out["source"] = cmd, "IA"
        out["sn"] = sn
        return out

    def _maybe_record(self, feat, meta, sn, speed_min, override=False, src="M"):
        if self.recorder is None or sn["speed"] < speed_min:
            return
        if not meta["located"] or meta["coverage"] < REC_MIN_COVERAGE:
            return
        cmd = (sn.get("user_steer") or 0.0, sn.get("user_throttle") or 0.0,
               sn.get("user_brake") or 0.0)
        self._record_row(feat, cmd, 1 if (override or self.mode == "record")
                         else 0, src if override else "M")

    def _shadow_update(self, cmd, sn):
        if sn["speed"] > 2.0:
            self._shadow_n += 1
            h = sn.get("user_steer") or 0.0
            if abs(h) + abs(cmd[0]) > 0.05:      # ignora trechos "mortos"
                self._shadow_dot += cmd[0] * h
                self._shadow_ai += cmd[0] * cmd[0]
                self._shadow_h += h * h

    def shadow_verdict(self):
        if self._shadow_n < 60:
            return "aguardando dirigida (volte ao volante)"
        denom = math.sqrt(self._shadow_ai * self._shadow_h)
        if denom < 1e-6:
            return "pouca curva para julgar (dirija trechos com curvas)"
        agree = self._shadow_dot / denom          # cosseno -1..1
        if agree < -0.3:
            return ("ATENCAO: IA e voce discordam de direcao — frame possivelmente"
                    " ESPELHADO. Rode 'record' por 1-2 min e mande o mapa de novo.")
        return f"sinais OK (concordancia {agree*100:.0f}%)"

    def _maybe_signal(self, meta, sn, now):
        """DAR SETA antes de curvas (teclas ORIGINAIS do jogo). Acende ~60 m
        antes de curva forte (raio < ~300 m) e apaga quando a estrada
        endireita — respeitando o auto-cancel do proprio jogo."""
        curvs = [c for c in (meta.get("curvs") or []) if c is not None]
        want = None
        for c in curvs:
            if abs(c) > 0.0035:
                want = "right" if c > 0 else "left"
                break
        if want == self._signal or now - self._last_signal_t < 1.0:
            return
        prev, self._signal = self._signal, want
        self._last_signal_t = now
        if self.injector is None:
            return

        def ind(side):
            return self.macros.get(
                f"ind_{side}", (0x1A if side == "left" else 0x1B,
                                f"seta {side}"))

        if want is not None and prev is None:          # acende
            self.injector.tap(*ind(want))
            self.log(f"[pratica] SETA {want.upper()} (curva a frente)")
        elif want is not None and prev is not None:    # trocou o lado
            self.injector.tap(*ind(prev))              # apaga a antiga
        elif want is None and prev is not None:        # endireitou: apaga
            known = "blinker_left_on" in sn
            lit = bool(sn.get("blinker_left_on")) or \
                bool(sn.get("blinker_right_on"))
            if not known or lit:   # jogo NAO cancelou sozinho (ou nao sei)
                self.injector.tap(*ind(prev))

    def _pit_crew(self, sn, now, job_min):
        """ABASTECER e DORMIR (parado no lugar certo, tecla de confirmar).

        Combustivel: < 15% -> avisa; parado 1,5 s em posto (o jogo mostra o
        dialogo) -> confirma 'abastecer'. Sono: rest_stop=1 ou 9 h de
        trabalho -> avisa; parado em descanso -> confirma 'dormir'.
        Precisa de telemetria com fuel/rest_stop (DLL ou pack completo)."""
        fuel = sn.get("fuel")
        cap = sn.get("fuel_capacity") or 0.0
        frac = (fuel / cap) if (fuel is not None and cap > 1.0) else None
        if frac is not None and frac < 0.15 and now - self._last_pit_t > 30:
            self.log(f"[pratica] COMBUSTIVEL {frac*100:.0f}% — pare em um "
                     "posto; a IA confirma o abastecimento")
            self._last_pit_t = now
        tired = bool(sn.get("rest_stop")) or job_min > 9.0 * 60.0
        if tired and now - self._last_pit_t > 30:
            self.log("[pratica] SONO — pare em uma area de descanso; a IA "
                     "confirma o sono (Enter)")
            self._last_pit_t = now
        if self._parked_at_dest:
            return
        if sn["speed"] > 0.3 or now - self._last_ok_t < 10 \
                or self.injector is None:
            return
        # parado: confirma o dialogo do jogo (abastecer / dormir)
        if frac is not None and frac < 0.90:
            self.log("[pratica] parado com tanque baixo — confirmando "
                     "abastecimento (Enter)")
            self.injector.tap(*self.macros.get("ok", (0x1C, "Enter")))
            self._last_ok_t = now
        elif sn.get("rest_stop"):
            self.log("[pratica] parado em descanso — confirmando sono "
                     "(Enter)")
            self.injector.tap(*self.macros.get("ok", (0x1C, "Enter")))
            self._last_ok_t = now

    def _job_flow(self, sn, now):
        """CICLO DE TRABALHO por tecla REAL (guiado pela telemetria):

        - caminhao PROPRIo sem reboque (sem job) + chegou no alvo + parado:
          ACOPA o reboque (T) — o jogo real aceita o encaixe nesta hora;
        - rota com BALSA (job config ferry.*) + no porto + parado:
          confirma o embarque (Enter) — o jogo real abre o dialogo do porto.
        """
        if self.mode != "drive" or self.injector is None:
            return
        rm = sn.get("route_distance")
        if rm is None or rm >= 25.0 or sn["speed"] >= 0.5:
            return
        if now - self._last_macro_t < 3.0:
            return
        if not sn.get("on_job"):
            self._last_macro_t = now
            self.injector.tap(*self.macros.get(
                "dock", (0x14, "T (acoplar reboque)")))
            self.log("[trabalho] caminhao proprio: ACOPANDO o reboque (T)")
        elif sn.get("ferry"):
            self._last_macro_t = now
            self.injector.tap(*self.macros.get("ok", (0x1C, "Enter")))
            self.log("[trabalho] balsa na rota: EMBARCANDO (Enter)")

    def _cold_start(self, sn, now):
        """TOMADA IMEDIATA: caminhao parado? A IA liga o motor e solta o
        freio de mao SOZINHA (macros E e .) — nao espera o humano.
        Uma tentativa a cada 2.5 s; se apos 6 s parado nao andou, toca o
        motor de novo (cobrir telemetria sem engine_enabled)."""
        if sn["speed"] >= 0.5:
            self._cold_t0 = None
            return
        if self._cold_t0 is None:
            self._cold_t0 = now
            if self.mode == "drive":
                self.log("[pratica] caminhao parado: IA ligando o motor e "
                         "soltando o freio de mao sozinha (tomada imediata)")
        parado = now - self._cold_t0
        if parado < 0.8 or now - self._last_macro_t < 2.5:
            return
        if self.injector is None:
            return
        self._last_macro_t = now
        if not sn.get("engine_enabled", True) or parado > 6.0:
            self.injector.tap(*self.macros.get(
                "engine", (0x12, "E (ligar motor)")))
        if sn.get("park_brake"):
            self.injector.tap(*self.macros.get(
                "park_brake", (0x39, "freio de mao")))

    def _human_detect(self, sn, cmd, now):
        """Detecta intervencao humana comparando o input do jogo com o
        esperado — esperado = teclas da IA passadas PELA RAMPA do jogo
        (o volante do ETS2 nao salta: sobe ~2.5/s, solta ~3.5/s). Sem isso,
        uma tecla recem-pressionada parece "humano contrariando a IA".
        """
        if sn.get("user_steer") is None:
            # telemetria sem DLL: os inputs do jogador nao vem do jogo —
            # humano = tecla fisica de direcao que NAO fomos nos que
            # injetamos (SendInput tambem acorda o estado async; por isso
            # descontamos as nossas).
            fk = self.foreign_keys() if self.foreign_keys else set()
            joy = self.joystick.human_active() if self.joystick else False
            self._fk_ticks = self._fk_ticks + 1 if (fk or joy) else 0
            if self._fk_ticks >= 3:
                if not self._human_active:
                    self.log("[pratica] humano no volante — IA solta o "
                             "volante e grava a correcao (DAgger)")
                self._human_active = True
                self._last_human_t = now
            elif self._human_active and \
                    now - self._last_human_t > OVERRIDE_RESUME_S:
                self._human_active = False
                self._override_hold = now + 0.5
            return
        inj = self.injector
        t_steer = t_thr = t_brk = 0.0
        if inj is not None:
            if "left" in inj.down:
                t_steer = -1.0
            elif "right" in inj.down:
                t_steer = 1.0
            t_thr = 1.0 if "accel" in inj.down else 0.0
            t_brk = 1.0 if "brake" in inj.down else 0.0
        dt = self.tick

        def ramp(cur, tgt, up=2.5, dn=3.5):
            r = (up if abs(tgt) > abs(cur) or
                 (tgt != 0 and cur != 0 and (cur > 0) != (tgt > 0)) else dn)
            return cur + max(-r * dt, min(r * dt, tgt - cur))

        self._exp_steer = ramp(self._exp_steer, t_steer)
        self._exp_thr = ramp(self._exp_thr, t_thr, 2.0, 3.0)
        self._exp_brk = ramp(self._exp_brk, t_brk, 2.0, 3.0)
        # suaviza observado e esperado: o volante real pulsa (PWM das setas)
        a = 0.3
        self._obs_steer += a * (sn["user_steer"] - self._obs_steer)
        self._obs_thr += a * (sn["user_throttle"] - self._obs_thr)
        self._obs_brk += a * (sn["user_brake"] - self._obs_brk)
        self._sm_steer += a * (self._exp_steer - self._sm_steer)
        self._sm_thr += a * (self._exp_thr - self._sm_thr)
        self._sm_brk += a * (self._exp_brk - self._sm_brk)
        dev = (abs(self._obs_steer - self._sm_steer) > 0.5 or
               (self._sm_brk < 0.3 and self._obs_brk > 0.5) or
               (self._sm_thr < 0.3 and self._obs_thr > 0.55) or
               (self._sm_brk > 0.5 and self._obs_thr > 0.55))
        if dev:
            self._dev_ticks += 1
        else:
            self._dev_ticks = 0
        if self._dev_ticks >= 8:            # ~0.4 s seguidos = intervencao
            if not self._human_active:
                self.log("[pratica] humano no volante — IA solta o volante "
                         "e grava a correcao (DAgger)")
            self._human_active = True
            self._last_human_t = now
        elif self._human_active and now - self._last_human_t > OVERRIDE_RESUME_S:
            self._human_active = False
            self._override_hold = now + 0.5

    # ------------------------------------------------------------------ #
    def run(self, max_seconds=None, hud_every=2.0):
        self.log(f"[pratica] modo {self.mode.upper()} | mapa: "
                 f"{self.road_map.stats()}")
        if self.stop_event is not None:
            self.stop_event.clear()
        if self.mode == "record":
            self.log("[pratica] VOCE dirige: 1a passada aprende a estrada; "
                     "da 2a em diante grava dados de treino. Ctrl+C sai.")
        elif self.mode == "shadow":
            self.log("[pratica] VOCE dirige; a IA so observa (sem injecao).")
        else:
            self.log("[pratica] IA DIRIGINDO IMEDIATAMENTE: liga o motor e "
                     "solta o freio de mao sozinha. ESC = kill switch; "
                     "encoste no teclado para corrigir (vira dado DAgger).")
        t0 = self.clock()
        last = t0
        try:
            while not self.stop and not (self.stop_event is not None
                                         and self.stop_event.is_set()):
                now = self.clock()
                while now - last >= self.tick:
                    last += self.tick
                    sn = self.source()
                    if sn is None:
                        continue
                    try:
                        st = self.step(sn, now)
                    except RuntimeError as e:      # telemetria inativa
                        self.log(f"[pratica] {e}")
                        self.sleep(1.0)
                        continue
                    if now - self._last_hud > hud_every:
                        self._last_hud = now
                        self._hud(st, now)
                    if now - self._last_save > 60.0 and self.map_path:
                        self._last_save = now
                        self.road_map.save(self.map_path)
                if max_seconds and now - t0 > max_seconds:
                    break
                self.sleep(max(0.0, self.tick * 0.2))
        except KeyboardInterrupt:
            self.log("[pratica] Ctrl+C — encerrando e salvando...")
        finally:
            if self.injector is not None:
                self.injector.release_all()
            if self.map_path:
                self.road_map.save(self.map_path)
                self.log(f"[pratica] mapa salvo em {self.map_path}")
            if self.recorder is not None:
                n = self.recorder.close()
                self.log(f"[pratica] {n} linhas em {self.recorder.path} -> "
                         f"python -m ets2ai.finetune --recordings {self.recorder.path}")
        return {"rows": self.rows, "speed_max": self.speed_max,
                "map": self.road_map.stats(),
                "shadow": self.shadow_verdict() if self.mode == "shadow" else None}

    def _hud(self, st, now):
        sn = st.get("sn")
        if sn is None:
            return
        meta = st.get("meta") or {}
        line = (f"[{self.mode}] {sn['speed']*3.6:5.1f} km/h | "
                f"offset {meta.get('offset', 0.0):+5.2f} m | "
                f"hdg {math.degrees(meta.get('heading_error', 0.0)):+5.1f}° | "
                f"mapa {meta.get('coverage', 0)}/5 | {st['source']}")
        if self.mode == "drive" and not meta.get("located"):
            line += " | SEM MAPA AQUI — devagar (rode 'record' nesta estrada)"
        if self.mode == "shadow" and self._shadow_n >= 60:
            line += f" | {self.shadow_verdict()}"
        self.log(line)


def _try_install_plugin(game_dir=None, auto=True, log=print, exclude=()):
    """Telemetria 100% AUTOMATICA: instala a DLL embutida na pasta do jogo.

    Nada manual: a pasta vem do CACHE -> processo rodando -> Steam ->
    VARREDURA LITERAL do disco todo (a mesma descoberta dos controles).
    Delega para telemetry.ensure_plugin (idempotente, verifica a copia).
    exclude = {(repo, tag)} ja tentadas: instala a PROXIMA release
    (rotacao p/ QUALQUER ETS2). Retorna o dict do ensure_plugin ou None."""
    if os.name != "nt" or not auto:
        return None
    try:
        return telemetry.ensure_plugin(log=log, game_dir=game_dir,
                                       exclude=exclude)
    except Exception as e:
        log(f"[pratica] auto-install da telemetria falhou: {e}")
    return None


# ---------------------------------------------------------------------------
# Entrada (linha de comando e pelo bridge/exe)
# ---------------------------------------------------------------------------
def _acquire_source(mode, telemetry_mode, log, stop_event=None,
                    wait_game=45.0, game_dir=None, auto_install=True):
    """Telemetria com ESPERA pelo jogo (corrige o 'iniciando e parou').

    O usuario pode clicar COMEÇAR ANTES de abrir o ETS2: o loop fica vivo
    (PARAR funciona) e comeca quando a telemetria aparecer. Ordem: leitura
    de MEMORIA (sem DLL) -> DLL embutida (auto-install 1x). Desiste com
    SystemExit apos `wait_game` segundos sem telemetria.
    """
    # wait_game=None: ESPERA SEM PRAZO — a GUI usa isto (o usuario clica
    # COMEÇAR, abre o jogo quando quiser e a IA comeca sozinha; o botao
    # NUNCA desiste so porque o jogo ainda nao esta aberto)
    deadline = None if wait_game is None else \
        time.monotonic() + max(0.0, float(wait_game))
    last_install_try = 0.0        # re-tenta o auto-install a cada ~60 s
    last_rotate = 0.0             # rotacao de release: no max. 1 a cada 2 min
    tried = set()                 # {(repo, tag)} ja instaladas nesta sessao
    last_err = ""
    attempt = 0
    while True:
        attempt += 1
        if telemetry_mode in ("mem", "auto"):
            # 1a via: LEITURA DE MEMORIA — nao instala NADA no jogo.
            try:
                mreader = memtelemetry.MemTelemetry()
                log("[telemetria] SEM DLL — leitura de memoria do processo "
                    f"(pack '{mreader.version}')")
                try:
                    telemetry.note_state(telemetry=f"mem:{mreader.version}",
                                         mode=mode)
                except Exception:
                    pass
                return mreader.snapshot
            except RuntimeError as e:
                last_err = str(e)
                if telemetry_mode == "auto":
                    log("[telemetria] memoria nao validou — tentando a DLL "
                        "embutida")
        if telemetry_mode in ("dll", "auto"):
            # 2a via: DLL de telemetria (MIT, RenCloud) EMBUTIDA no .exe —
            # plug & play: instala sozinha na pasta do jogo (1x) se preciso.
            try:
                reader = telemetry.TelemetryReader()
                try:
                    telemetry.note_state(telemetry="dll", mode=mode)
                except Exception:
                    pass
                return reader.snapshot
            except RuntimeError as e:
                last_err = str(e)
                now = time.monotonic()
                if (telemetry_mode == "auto" and now - last_install_try > 60.0):
                    last_install_try = now
                    # ROTACAO (QUALQUER ETS2): jogo RODANDO mas a MMF nao
                    # apareceu -> a DLL escolhida nao foi aceita (SDK
                    # incompativel). Instala a PROXIMA release do banco e
                    # pede o restart (o plugin carrega na abertura).
                    exclude = set(tried)
                    run_ok = telemetry.game_process_running()
                    if run_ok and tried and now - last_rotate > 120.0:
                        exclude = set(tried)
                        log("[dll] jogo rodando sem telemetria — girando "
                            f"para a proxima release (ja tentadas: "
                            f"{', '.join(sorted(t for _r, t in tried))})")
                    r = _try_install_plugin(game_dir, auto_install, log=log,
                                            exclude=exclude)
                    if r:
                        tried.add((r.get("repo"), r.get("tag")))
                        if len(tried) > 1:
                            last_rotate = now
                            log(f"[dll] RELEASE TROCADA: {r.get('repo')} "
                                f"{r.get('tag')} instalada — REINICIE o "
                                "ETS2 para carregar a nova DLL")
                            for hint in telemetry.game_log_hints()[-4:]:
                                log(f"[game.log] {hint[:160]}")
                    try:
                        reader = telemetry.TelemetryReader()
                        try:
                            telemetry.note_state(telemetry="dll", mode=mode)
                        except Exception:
                            pass
                        return reader.snapshot
                    except RuntimeError as e2:
                        last_err = (f"{e2} (DLL instalada agora — se o jogo "
                                    "ja estava aberto, REINICIE o jogo)")
        if deadline is not None and time.monotonic() >= deadline:
            raise SystemExit(
                "[telemetria] sem telemetria apos "
                f"{max(0.0, float(wait_game)):.0f} s esperando o jogo. "
                f"Ultimo motivo: {last_err[:200]}\n"
                "[pratica] Abra o ETS2 (ou REINICIE se a DLL acabou de ser "
                "instalada — o plugin carrega na abertura do jogo) e clique "
                "COMEÇAR de novo. A instalacao e AUTOMATICA (varredura do "
                "disco); --game-dir so e excecao do CLI.")
        if stop_event is not None and stop_event.is_set():
            raise SystemExit("[pratica] PARAR clicado enquanto aguardava o jogo")
        if attempt == 1 or attempt % (20 if deadline is None else 5) == 0:
            prazo = ("SEM PRAZO — abra o jogo quando quiser (o botao PARAR "
                     "cancela)" if deadline is None else
                     f"{int(deadline - time.monotonic())} s restantes")
            log(f"[telemetria] aguardando o ETS2 abrir... ({prazo} | "
                f"{last_err[:90]})")
        time.sleep(3.0)


def run(mode, map_path="practice/mapa.json", rec_path=None, inject=False,
        window="Euro Truck", weights=BASE_WEIGHTS, max_seconds=None,
        game_dir=None, auto_install=True, phone=None, telemetry_mode="auto",
        log=print, stop_event=None, wait_game=45.0, on_source=None,
        _source=None, _policy=None, _clock=None, _sleep=None):
    """Monta e roda o loop de pratica (usado pelo CLI e pelo bridge --ets2).

    wait_game: segundos esperando o ETS2/telemetria aparecer antes de
    desistir; None = ESPERA SEM PRAZO (a GUI usa None — pode clicar
    COMEÇAR antes de abrir o jogo e a IA comeca sozinha quando ele abrir).
    on_source: callback 1x quando a telemetria conecta (GUI muda o botao).
    """
    map_path = Path(map_path)
    road_map = RoadMap.load(map_path) if map_path.exists() else RoadMap()
    layers = None
    if mode in ("drive", "shadow"):
        layers, meta = load_weights(weights)
        log(f"[pesos] {weights} (val_loss {meta['final_loss']:.5f})")
    source = _source
    if source is None:
        source = _acquire_source(mode, telemetry_mode, log,
                                 stop_event=stop_event, wait_game=wait_game,
                                 game_dir=game_dir, auto_install=auto_install)
    if on_source is not None:            # GUI: jogo ABRIU -> botao muda
        try:
            on_source()
        except Exception:
            pass
    joystick = JoystickMonitor()
    _devs = joystick.describe()
    if _devs:
        log(f"[joystick] controles vigiados: {_devs} — mexer neles "
            "entrega o volante ao humano")
    keymap, macros, ksrc = load_keymap()
    log(f"[teclas] mapeadas do jogo: {ksrc} | "
        f"WASD={sorted(hex(v) for v in keymap.values())}")
    injector = (KeyInjector(window, inject, keymap=keymap, log=log)
                if (mode == "drive" and inject) else None)
    if inject and mode == "drive":
        log(f"[inject] alvo: janela '{window}' | a IA so AGE com o jogo em "
            "TELA CHEIA (e em 1º plano) | ESC = kill switch")
    recorder = Recorder(rec_path) if rec_path else None
    loop = PracticeLoop(mode, road_map, source, layers=layers,
                        injector=injector, recorder=recorder,
                        map_path=map_path, policy_fn=_policy, phone=phone,
                        clock=_clock or time.monotonic,
                        sleep=_sleep or time.sleep, log=log, macros=macros,
                        joystick=joystick,
                        foreign_keys=(injector.foreign_keys_down
                                      if injector is not None else None),
                        stop_event=stop_event)
    try:
        return loop.run(max_seconds=max_seconds)
    finally:
        if source is not None and hasattr(source, "__self__") and \
                hasattr(source.__self__, "close"):
            source.__self__.close()


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="ETS2-AI pratica: aprendizado e direcao no ETS2 real",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("modo", choices=["record", "shadow", "drive"])
    ap.add_argument("--map", default="practice/mapa.json",
                    help="arquivo do mapa de pista aprendido")
    ap.add_argument("--rec", default=None,
                    help="CSV de gravacao p/ finetune (ets2ai-rec,v1)")
    ap.add_argument("--inject", action="store_true",
                    help="injetar teclas REAIS no jogo (so com 'drive')")
    ap.add_argument("--window", default="Euro Truck",
                    help="parte do titulo da janela do ETS2")
    ap.add_argument("--weights", default=str(BASE_WEIGHTS))
    ap.add_argument("--segundos", type=float, default=None,
                    help="encerrar apos N segundos (testes)")
    ap.add_argument("--game-dir", default=None,
                    help="pasta de instalacao do ETS2 (auto-detecta via Steam)")
    ap.add_argument("--no-auto-install", action="store_true",
                    help="nao auto-instalar a DLL de telemetria embutida")
    args = ap.parse_args(argv)
    if args.rec is None and args.modo in ("record", "shadow"):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        args.rec = f"practice/{args.modo}-{stamp}.csv"
        print(f"[pratica] gravando automaticamente em {args.rec}")
    return run(args.modo, map_path=args.map, rec_path=args.rec,
               inject=args.inject, window=args.window,
               weights=Path(args.weights), max_seconds=args.segundos,
               game_dir=args.game_dir, auto_install=not args.no_auto_install)


if __name__ == "__main__":
    main()
