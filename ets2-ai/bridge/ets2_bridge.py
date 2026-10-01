#!/usr/bin/env python3
"""ETS2-AI bridge para Windows (gera ETS2-AI-bridge.exe via PyInstaller no CI).

O que ele faz:
  1. Roda um cenario-demo com a MESMA fisica do app Android (ets2ai.sim).
  2. Escuta TCP :7777 — o celular conecta e passa a ser o 'cerebro':
     o bridge envia o estado do caminhao, o celular responde os comandos
     da rede neural (protocolo CSV, ver README).
  3. Sem celular (ou se o celular sumir por >0.5 s) usa a politica local
     (numpy, mesmos pesos) — failover automatico.
  4. Com --inject, traduz os comandos em teclas REAIS (SendInput / scan codes)
     enviadas a janela cujo titulo contem --window. ESC = mata tudo (kill switch).

Uso:
    python ets2_bridge.py                    # janela demo, IA local ou celular
    python ets2_bridge.py --inject --window "Euro Truck"   # injeta teclas reais

Nota ETS2 real: a injeção de teclas é a parte pronta. Para dirigir o jogo de
verdade falta a telemetria do jogo (plugin SCS SDK), que alimentaria o estado
no lugar do demo — ponto de integracao documentado no README.
"""
import argparse
import math
import socket
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ets2ai import sim                                    # noqa: E402
from ets2ai import mission as mission_mod                 # noqa: E402
from ets2ai.contract import load_weights, clamp_action    # noqa: E402
from ets2ai.model import forward                          # noqa: E402

DEFAULT_PORT = 7777
PHONE_TIMEOUT_S = 0.5      # sem resposta do celular por isso = failover local

# Teclas enviadas (scan codes). ETS2 vem com setas para dirigir por padrao.
KEYMAP = {"left": 0x4B, "right": 0x4D, "accel": 0x48, "brake": 0x50}
# Macros da missao (scan code, nome) — liga motor, carga, menus do jogo.
# Ajuste se seus binds forem diferentes (ver ets2-ai/README.md).
MACROS = {
    "engine":     (0x12, "E (ligar motor)"),
    "dock":       (0x14, "T (carregar/descarregar)"),
    "ok":         (0x1C, "Enter (confirmar)"),
    "down":       (0x50, "Baixo (navegar menu)"),
    "park_brake": (0x34, ". (freio de estacionamento)"),
}
# Setas/Enter etc. sao teclas EXTENDIDAS no Windows: sem a flag, viram
# teclado numerico (bug real de injecao — corrigido abaixo).
EXTENDED_KEYS = {0x48, 0x4B, 0x4D, 0x50, 0x52, 0x53, 0x1C, 0x34}


def load_policy():
    cands = []
    if hasattr(sys, "_MEIPASS"):
        cands.append(Path(sys._MEIPASS) / "artifacts" / "model-weights.json")
    here = Path(__file__).resolve().parent
    cands += [here.parent / "artifacts" / "model-weights.json",
              here / "model-weights.json"]
    for c in cands:
        if c.exists():
            layers, meta = load_weights(c)
            print(f"[pesos] {c} (val_loss {meta['final_loss']:.5f})")
            return layers
    raise SystemExit("model-weights.json nao encontrado: rode a partir de ets2-ai/ "
                     "ou use o .exe do CI (pesos embutidos).")


def policy_cmd(layers, road, truck, job_left_km):
    f = np.asarray(sim.features(road, truck, job_left_km), dtype=np.float32)
    o = forward(f, layers)[0]
    cmd = clamp_action(float(o[0]), float(o[1]), float(o[2]))
    return sim.governor(road, truck, cmd)


# ---------------------------------------------------------------------------
# TCP server: phone is the brain
# ---------------------------------------------------------------------------
class PhoneLink(threading.Thread):
    """Accepts one phone; feeds states; collects commands."""

    def __init__(self, port):
        super().__init__(daemon=True)
        self.port = port
        self.latest_cmd = None        # (steer, throttle, brake, t_sent)
        self.last_recv = 0.0
        self.rtt_ms = -1.0
        self.connected = False
        self.log = []

    def run(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", self.port))
        srv.listen(1)
        self.log.append(f"aguardando celular em tcp://{self.local_ip()}:{self.port}")
        while True:
            conn, addr = srv.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._conn = conn
            rfile = conn.makefile("rwb", buffering=0)
            self._rfile = rfile          # set BEFORE connected (avoid race)
            self.connected = True
            self.log.append(f"celular conectado: {addr[0]}")
            try:
                while True:
                    line = rfile.readline()
                    if not line:
                        break
                    parts = line.decode("utf-8", "replace").strip().split(",")
                    if len(parts) >= 5 and parts[0] == "C":
                        self.latest_cmd = (float(parts[1]), float(parts[2]),
                                           float(parts[3]), float(parts[4]))
                        self.last_recv = time.time()
                        now = time.time() * 1000.0
                        self.rtt_ms = now - float(parts[4])
            except Exception:
                pass
            finally:
                self.connected = False
                self.latest_cmd = None
                self.log.append("celular desconectado")
                try:
                    conn.close()
                except Exception:
                    pass

    def send_state(self, road, truck, job_left_km):
        if not self.connected or not hasattr(self, "_conn"):
            return
        try:
            curv = [road.curvature_at(truck.s + d) for d in sim.LOOKAHEAD]
            ts = time.time()
            msg = ("S," + ",".join([
                f"{truck.speed:.4f}", f"{truck.offset:.4f}",
                f"{sim.wrap_angle(truck.heading - truck.tangent):.4f}",
                ",".join(f"{c:.6f}" for c in curv),
                f"{sim.SPEED_LIMIT_MPS:.2f}", f"{truck.fuel:.4f}",
                f"{truck.fatigue:.4f}", f"{job_left_km:.4f}",
                f"{road.radar_dist_ahead(truck.s):.2f}",
                f"{int(ts*1000)}"]) + "\n")
            self._conn.sendall(msg.encode("utf-8"))
        except Exception:
            pass

    @staticmethod
    def local_ip():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
        finally:
            s.close()


# ---------------------------------------------------------------------------
# Windows keyboard injection (SendInput, scan codes)
# ---------------------------------------------------------------------------
def press_menu(injector, keys):
    """Presses a menu key sequence (['down', 'ok'] etc.) with small pauses."""
    for k in keys:
        scan, name = MACROS[k]
        injector.tap(scan, name)
        time.sleep(0.15)


class KeyInjector:
    def __init__(self, window_substring, enabled):
        self.enabled = enabled and sys.platform == "win32"
        self.window_substring = window_substring
        self.down = set()
        if self.enabled:
            import ctypes
            self.ct = ctypes
            self.user32 = ctypes.windll.user32
            self.kernel32 = ctypes.windll.kernel32
        self.kill = False

    def _keybd(self, scan, up):
        INPUT_KEYBOARD = 1
        KEYEVENTF_SCANCODE = 0x0008
        KEYEVENTF_KEYUP = 0x0002
        KEYEVENTF_EXTENDEDKEY = 0x0001
        class _KBD(ctypes.Structure):
            _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                        ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]
        class _INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("ki", _KBD)]
        extra = ctypes.c_ulong(0)
        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
        if scan in EXTENDED_KEYS:
            flags |= KEYEVENTF_EXTENDEDKEY
        ki = _KBD(0, scan, flags, 0, ctypes.pointer(extra))
        inp = _INPUT(INPUT_KEYBOARD, ki)
        n = self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        return n == 1

    def _target_is_foreground(self):
        fg = self.user32.GetForegroundWindow()
        length = 512
        buf = ctypes.create_unicode_buffer(length)
        self.user32.GetWindowTextW(fg, buf, length)
        title = buf.value
        if self.window_substring.lower() in title.lower():
            return True
        return False

    def update(self, steer, throttle, brake):
        """Map continuous commands to key presses (bang-bang with hysteresis)."""
        if not self.enabled:
            return
        # kill switch: ESC pressed at any time stops injection for good
        if self.user32.GetAsyncKeyState(0x1B) & 0x8000:
            self.kill = True
        if self.kill:
            self.release_all()
            return
        want = set()
        if steer < -0.25:
            want.add("left")
        if steer > 0.25:
            want.add("right")
        if throttle > 0.30:
            want.add("accel")
        if brake > 0.30:
            want.add("brake")
        if not self._target_is_foreground():
            want = set()          # nao injeta fora da janela alvo
        for k in self.down - want:
            self._keybd(KEYMAP[k], True)
            self.down.discard(k)
        for k in want - self.down:
            self._keybd(KEYMAP[k], False)
            self.down.add(k)

    def tap(self, scan, name=""):
        """One-shot keypress (down 60 ms, up) for mission macros."""
        if not self.enabled:
            print(f"[macro] {name or hex(scan)} (injecao desligada — apenas sim)")
            return
        self._keybd(scan, False)
        time.sleep(0.06)
        self._keybd(scan, True)
        if name:
            print(f"[macro] {name}")

    def release_all(self):
        if not self.enabled:
            return
        for k in list(self.down):
            self._keybd(KEYMAP[k], True)
            self.down.discard(k)


# ---------------------------------------------------------------------------
# Recorder (DAgger): state->command log consumable by ets2ai.finetune
# ---------------------------------------------------------------------------
class Recorder:
    """CSV writer: normalized 12 features + 3 commands + override flag + source.

    source: L=IA local | P=IA celular | H=correcao humana (override=1) | M=manual
    """
    def __init__(self, path):
        self.path = Path(path)
        self.f = open(self.path, "w", encoding="utf-8")
        self.f.write("ets2ai-rec,v1\n")
        self.n = 0
        self.overrides = 0

    def write(self, feat, cmd, override, src):
        vals = [f"{v:.6f}" for v in feat] + [f"{v:.6f}" for v in cmd]
        vals.append(str(int(override)))
        vals.append(src)
        self.f.write(",".join(vals) + "\n")
        self.n += 1
        if override:
            self.overrides += 1
        if self.n % 50 == 0:
            self.f.flush()

    def close(self):
        if not self.f.closed:
            self.f.close()
        return self.n


# ---------------------------------------------------------------------------
# Tkinter demo window (same physics as the phone)
# ---------------------------------------------------------------------------
def run_demo(layers, port, injector, record_path=None):
    import tkinter as tk

    road = sim.Road.random(20260930)
    truck = sim.Truck(road, s=5.0, offset=0.0, speed=15.0)
    link = PhoneLink(port)
    link.start()
    rec = Recorder(record_path) if record_path else None
    state = {"ai": True, "source": "local", "km": 0.0, "msg": ""}

    root = tk.Tk()
    root.title("ETS2-AI bridge — demo (ESC no modo --inject = kill switch)")
    root.configure(bg="#14141C")
    W, H = 960, 600
    SCALE = 6

    header = tk.Frame(root, bg="#14141C")
    header.pack(fill="x", padx=14, pady=(10, 2))
    tk.Label(header, text="ETS2-AI  BRIDGE", font=("Segoe UI", 15, "bold"),
             bg="#14141C", fg="#EDEDF7").pack(side="left")
    chip = tk.Label(header, text="IA LOCAL", font=("Segoe UI", 9, "bold"),
                    bg="#2F7BFF", fg="white", padx=10, pady=3)
    chip.pack(side="left", padx=12)
    tk.Label(header, text="offline · sem captura de tela · ESC mata a injecao",
             font=("Segoe UI", 9), bg="#14141C", fg="#8B8BA3").pack(side="right")

    cv = tk.Canvas(root, width=W, height=H, bg="#101B2D", highlightthickness=0)
    cv.pack(padx=14, pady=4)

    footer = tk.Frame(root, bg="#1B1B26")
    footer.pack(fill="x", padx=14, pady=(4, 6))
    info = tk.Label(footer, font=("Consolas", 10), justify="left", anchor="w",
                    bg="#1B1B26", fg="#B9F0D0", padx=10, pady=6)
    info.pack(side="left", fill="both", expand=True)

    def toggle_ai(_e=None):
        state["ai"] = not state["ai"]
    root.bind("a", toggle_ai)

    acc = {"t": 0.0}
    manual = {"keys": set()}

    def manual_from_keys():
        ks = manual["keys"]
        steer = (-1 if "left" in ks else 0) + (1 if "right" in ks else 0)
        thr = 0.65 if "accel" in ks else 0.0
        brk = 1.0 if "brake" in ks else 0.0
        return clamp_action(steer, thr, brk), len(ks) > 0

    root.bind("<Left>", lambda e: manual["keys"].add("left"))
    root.bind("<Right>", lambda e: manual["keys"].add("right"))
    root.bind("<Up>", lambda e: manual["keys"].add("accel"))
    root.bind("<Down>", lambda e: manual["keys"].add("brake"))
    root.bind("<KeyRelease-Left>", lambda e: manual["keys"].discard("left"))
    root.bind("<KeyRelease-Right>", lambda e: manual["keys"].discard("right"))
    root.bind("<KeyRelease-Up>", lambda e: manual["keys"].discard("accel"))
    root.bind("<KeyRelease-Down>", lambda e: manual["keys"].discard("brake"))

    def tick():
        t0 = time.time()
        acc["t"] += 0.033
        while acc["t"] >= sim.DT:
            acc["t"] -= sim.DT
            job_left = max(0.0, (road.length - truck.s) / 1000.0)

            feat = sim.features(road, truck, job_left)
            override = 0
            mcmd, human_active = manual_from_keys()
            if state["ai"]:
                link.send_state(road, truck, job_left)
                fresh = (time.time() - link.last_recv) < PHONE_TIMEOUT_S
                if link.latest_cmd and fresh:
                    c = link.latest_cmd
                    cmd = sim.governor(road, truck, clamp_action(c[0], c[1], c[2]))
                    src = "P"
                    state["source"] = f"CELULAR (RTT {link.rtt_ms:.0f} ms)"
                else:
                    o = forward(feat, layers)[0]
                    cmd = clamp_action(float(o[0]), float(o[1]), float(o[2]))
                    src = "L"
                    state["source"] = "local (numpy)"
                if human_active:      # DAgger: correcao humana enquanto a IA dirige
                    cmd = mcmd
                    src = "H"
                    override = 1
                    state["source"] = "CORRECAO HUMANA (gravando p/ finetune)"
            else:
                cmd = mcmd
                src = "M"
                state["source"] = "manual (setas; A liga/desliga IA)"

            if rec is not None:
                rec.write(feat, cmd, override, src)
            truck.step(road, cmd[0], cmd[1], cmd[2])
            injector.update(cmd[0], cmd[1], cmd[2])

            if truck.fuel < sim.REFUEL_BELOW:
                truck.fuel = 1.0
                state["msg"] = "Abastecendo 600 L (postos a cada rota)"
            if truck.fatigue > sim.SLEEP_ABOVE:
                truck.fatigue = 0.0
                state["msg"] = "Motorista dormiu 9 h"
            if abs(truck.offset) > sim.ROAD_HALF:
                state["msg"] = "BATER! Reinicie (R)"
            if truck.s >= road.length - 10:
                state["msg"] = "Entrega concluida! Nova rota (R)"

        draw()
        info.config(text=fmt())
        root.after(33, tick)

    def fmt():
        recmsg = f"  |  REC {rec.n} ({rec.overrides} correcoes)" if rec else ""
        chip.configure(text=state["source"].split(" (")[0].upper()[:24])
        return (f"{truck.speed*3.6:5.1f} km/h   offset {truck.offset:+.2f} m   "
                f"comb {truck.fuel*100:3.0f}%   sono {truck.fatigue*100:3.0f}%   "
                f"restam {road.length/1000 - truck.s/1000:.1f} km{recmsg}\n"
                f"{state['msg']}   |   {' | '.join(link.log[-2:])}")

    def draw():
        cv.delete("all")
        cx, cy = W / 2, H * 0.62
        # ceu e grama com gradiente
        for i in range(36):
            f = i / 35.0
            col = (int(16 + 30 * f), int(27 + 63 * f), int(45 + 25 * f))
            y1 = (i + 1) * H * 0.45 / 36 + 1
            cv.create_rectangle(0, i * H * 0.45 / 36, W, y1, outline="",
                                fill="#%02x%02x%02x" % col)
        for i in range(26):
            f = i / 25.0
            col = (int(46 - 18 * f), int(90 - 20 * f), int(70 - 28 * f))
            y0 = H * 0.45 + i * H * 0.55 / 26
            cv.create_rectangle(0, y0, W, y0 + H * 0.55 / 26 + 1, outline="",
                                fill="#%02x%02x%02x" % col)
        for hx, hw, hh in ((W * 0.15, 280, 55), (W * 0.55, 400, 88), (W * 0.93, 320, 46)):
            cv.create_oval(hx - hw / 2, H * 0.45 - hh, hx + hw / 2, H * 0.45 + 30,
                           fill="#24463A", outline="")

        ang = -math.pi / 2 - truck.heading
        cos, sin = math.cos(ang), math.sin(ang)

        def to_screen(x, y):
            dx, dy = x - truck.x, y - truck.y
            return cx + dx * cos - dy * sin, cy + dx * sin + dy * cos

        i0 = max(0, truck._hint - 40)
        i1 = min(len(road.samples) - 1, truck._hint + 110)

        def road_poly(lat):
            out = []
            for i in range(i0, i1 + 1, 2):
                a = road.samples[max(0, i - 1)]
                b = road.samples[min(len(road.samples) - 1, i + 1)]
                tx_, ty_ = b[0] - a[0], b[1] - a[1]
                tn = math.hypot(tx_, ty_) or 1.0
                out.append(to_screen(road.samples[i][0] + (-ty_ / tn) * lat,
                                     road.samples[i][1] + (tx_ / tn) * lat))
            return out

        pts = road_poly(0)
        flat = [c for p in pts for c in p]
        if len(flat) > 3:
            cv.create_line(*flat, width=9 * SCALE, fill="#2E2E38",
                           capstyle="round", smooth=True)
            cv.create_line(*flat, width=1, fill="#55555F", dash=(3, 12), smooth=True)
            for lat in (-4.5, 4.5):
                op = [c for p in road_poly(lat) for c in p]
                if len(op) > 3:
                    cv.create_line(*op, width=2, fill="#E8E8E8", smooth=True)
            cv.create_line(*flat, width=2, fill="#F2C14E", dash=(14, 14), smooth=True)

        # radares
        for rs in road.radars:
            if truck.s - 20 < rs < truck.s + 200:
                idx = min(len(road.samples) - 1, max(0, int(rs / 2)))
                rx, ry = to_screen(*road.samples[idx])
                cv.create_rectangle(rx - 5, ry - 5, rx + 5, ry + 5,
                                    fill="#F2C14E", outline="#3A3A44")
                cv.create_text(rx, ry - 14, text="RADAR", fill="#F2C14E",
                               font=("Segoe UI", 7, "bold"))
        # dock: faixa quadriculada no fim da rota
        dock_s = road.length - 6.0
        if dock_s < truck.s + 240:
            idx = min(len(road.samples) - 1, max(0, int(dock_s / 2)))
            a = road.samples[max(0, idx - 1)]
            b = road.samples[min(len(road.samples) - 1, idx + 1)]
            tx_, ty_ = b[0] - a[0], b[1] - a[1]
            tn = math.hypot(tx_, ty_) or 1.0
            nx, ny = -ty_ / tn, tx_ / tn
            c0 = road.samples[idx]
            e1 = to_screen(c0[0] + nx * 4.6, c0[1] + ny * 4.6)
            e2 = to_screen(c0[0] - nx * 4.6, c0[1] - ny * 4.6)
            cv.create_line(*e1, *e2, width=8, fill="#F5F5F5")
            cv.create_line(*e1, *e2, width=8, fill="#1A1A22", dash=(8, 8))
            cv.create_text((e1[0] + e2[0]) / 2, (e1[1] + e2[1]) / 2 - 16,
                           text="DOCK", fill="#FFFFFF", font=("Segoe UI", 8, "bold"))

        # caminhao: sombra, bau, cabine, para-brisa, rodas
        tx, ty = to_screen(truck.x, truck.y)
        cv.create_oval(tx - 14, ty + 56, tx + 14, ty + 68, fill="#00000040", outline="")
        cv.create_rectangle(tx - 8, ty - 24, tx + 8, ty + 62, fill="#C9D1DC",
                            outline="#8A93A3")
        cv.create_rectangle(tx - 8, ty - 44, tx + 8, ty - 22, fill="#2F7BFF",
                            outline="#1E5BBF")
        cv.create_rectangle(tx - 6, ty - 40, tx + 6, ty - 30, fill="#BFE3FF", outline="")
        for wy in (-38, 28, 50):
            cv.create_oval(tx - 11, ty + wy - 3, tx + 11, ty + wy + 3,
                           fill="#14141C", outline="")

        # HUD: velocimetro + barras + faixa de evento
        cv.create_rectangle(W - 150, 16, W - 20, 96, fill="#00000066", outline="#FFFFFF22")
        cv.create_text(W - 85, 44, text=f"{truck.speed*3.6:.0f}", fill="#FFFFFF",
                       font=("Segoe UI", 26, "bold"))
        cv.create_text(W - 85, 78, text="km/h", fill="#9FE8C1", font=("Segoe UI", 9))
        bars = (("COMB", truck.fuel, "#7ED957", truck.fuel < 0.22),
                ("SONO", truck.fatigue, "#FFC24B", truck.fatigue > 0.7))
        for (label, frac, col, warn), bx in zip(bars, (W - 140, W - 78)):
            cv.create_rectangle(bx, 112, bx + 54, 118, fill="#00000066", outline="")
            cv.create_rectangle(bx, 112, bx + 54 * frac, 118,
                                fill="#FF5252" if warn else col, outline="")
            cv.create_text(bx + 27, 128, text=label, fill="#B9B9C9",
                           font=("Segoe UI", 7, "bold"))
        if state["msg"]:
            cv.create_rectangle(W / 2 - 220, 18, W / 2 + 220, 50,
                                fill="#00000099", outline="#FFFFFF33")
            cv.create_text(W / 2, 34, text=state["msg"], fill="#FFD75E",
                           font=("Segoe UI", 10, "bold"))
        cv.create_text(12, H - 12, anchor="sw", fill="#8B8BA3",
                       text="A: IA on/off  ·  setas: manual/correcao  ·  R: nova rota  ·  celular: botao BRIDGE",
                       font=("Segoe UI", 8))

    def restart(_e=None):
        nonlocal road, truck
        road = sim.Road.random(int(time.time()))
        truck = sim.Truck(road, s=5.0, offset=0.0, speed=15.0)
        state["msg"] = ""
    root.bind("r", restart)

    btns = tk.Frame(root, bg="#14141C")
    btns.pack(fill="x", padx=14, pady=(0, 10))
    for label, color, cmd in (("IA ON/OFF (A)", "#2F7BFF", toggle_ai),
                              ("NOVA ROTA (R)", "#00A884", restart)):
        tk.Button(btns, text=label, command=cmd, bg=color, fg="white",
                  activebackground="#00000055", activeforeground="white",
                  relief="flat", padx=14, pady=6,
                  font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 8))

    tick()
    root.mainloop()
    injector.release_all()
    if rec is not None:
        n = rec.close()
        print(f"[rec] {n} linhas em {rec.path} -> "
              f"python -m ets2ai.finetune --recordings {rec.path}")


def run_headless(layers, port, injector, phone_only):
    """Modo leve para PC fraco (Pentium N5030/4 GB): sem janela, sem render,
    sem captura de tela (o projeto NUNCA captura tela — estado vem da
    telemetria/demo). Missao completa: liga motor -> dirige (IA) -> para no
    dock com precisao -> carrega/descarrega -> dispatcher escolhe o proximo
    trabalho -> repete."""
    import numpy as np
    from ets2ai import dispatch as dispatch_mod
    rng = np.random.default_rng(int(time.time()))
    best, _offers = dispatch_mod.pick_best(rng, sim.Road, 3)
    road = sim.Road.random(best.road_seed)
    truck = sim.Truck(road, s=5.0, offset=0.0, speed=0.0)
    link = PhoneLink(port)
    link.start()
    money = 0.0
    jobs = 0
    phase = {"name": "engine", "t": 1.5}       # engine -> drive -> dock
    injector.tap(*MACROS["engine"])
    print(f"[leve] headless na porta {port} | celular: botao BRIDGE -> "
          f"{PhoneLink.local_ip()}:{port} | Ctrl+C sai")
    if phone_only:
        print("[leve] --somente-celular: sem o celular o caminhao FREIA (sem IA local)")
    print(f"[job] {best.label()} [melhor de 3]")
    last_print = 0.0
    acc = 0.0
    t_prev = time.time()
    src = "ligando"
    try:
        while True:
            now = time.time()
            acc += min(0.25, now - t_prev)
            t_prev = now
            while acc >= sim.DT:
                acc -= sim.DT
                if phase["name"] != "drive":
                    phase["t"] -= sim.DT
                    if phase["t"] <= 0:
                        if phase["name"] == "engine":         # motor ligado
                            phase = {"name": "drive", "t": 0.0}
                        elif phase["name"] == "dock":         # dialogo do jogo
                            idx = mission_mod.delivery_selection()
                            print("[menu] " + " | ".join(mission_mod.DELIVERY_DIALOG))
                            print(f"[menu] selecionando: "
                                  f"'{mission_mod.DELIVERY_DIALOG[idx]}'")
                            press_menu(injector, mission_mod.menu_key_sequence(idx))
                            phase = {"name": "menu", "t": 1.5}
                        elif phase["name"] == "menu":         # estacionar
                            injector.tap(*MACROS["park_brake"])
                            money += best.pay_eur
                            jobs += 1
                            print(f"[park] estacionado — entrega #{jobs}: "
                                  f"+{best.pay_eur:.0f} EUR (total {money:.0f} EUR)")
                            if jobs % mission_mod.SKILL_EVERY_N_JOBS == 0:
                                sk = mission_mod.pick_random_skill(rng)
                                print("[skill] " + " | ".join(mission_mod.SKILLS))
                                print(f"[skill] escolhida (aleatoria): "
                                      f"{mission_mod.SKILLS[sk]}")
                                press_menu(injector, mission_mod.menu_key_sequence(sk))
                                phase = {"name": "skill", "t": 1.5}
                            else:
                                best, _ = dispatch_mod.pick_best(rng, sim.Road, 3)
                                road = sim.Road.random(best.road_seed)
                                truck = sim.Truck(road, s=5.0, offset=0.0, speed=0.0)
                                phase = {"name": "engine", "t": 1.5}
                                injector.tap(*MACROS["engine"])
                                print(f"[job] proximo: {best.label()} [melhor de 3]")
                        elif phase["name"] == "skill":        # nova habilidade
                            best, _ = dispatch_mod.pick_best(rng, sim.Road, 3)
                            road = sim.Road.random(best.road_seed)
                            truck = sim.Truck(road, s=5.0, offset=0.0, speed=0.0)
                            phase = {"name": "engine", "t": 1.5}
                            injector.tap(*MACROS["engine"])
                            print(f"[job] proximo: {best.label()} [melhor de 3]")
                    continue
                job_left = max(0.0, (road.length - truck.s) / 1000.0)
                link.send_state(road, truck, job_left)
                fresh = (now - link.last_recv) < PHONE_TIMEOUT_S
                if link.latest_cmd and fresh:
                    c = link.latest_cmd
                    cmd = sim.governor(road, truck, clamp_action(c[0], c[1], c[2]))
                    src = "celular"
                elif phone_only:
                    cmd = (0.0, 0.0, 0.8)              # freia ate o celular voltar
                    src = "FREIO (sem celular)"
                else:
                    cmd = policy_cmd(layers, road, truck, job_left)
                    src = "local"
                truck.step(road, cmd[0], cmd[1], cmd[2])
                injector.update(cmd[0], cmd[1], cmd[2])
                if truck.fuel < sim.REFUEL_BELOW:
                    truck.fuel = 1.0
                    money -= dispatch_mod.FUEL_STOP_EUR
                    print("[regra] abastecendo 600 L")
                if truck.fatigue > sim.SLEEP_ABOVE:
                    truck.fatigue = 0.0
                    money -= dispatch_mod.HOTEL_EUR
                    print("[regra] dormindo 9 h no hotel")
                if abs(truck.offset) > sim.ROAD_HALF:
                    print("[evento] fora da pista — novo trabalho")
                    best, _ = dispatch_mod.pick_best(rng, sim.Road, 3)
                    road = sim.Road.random(best.road_seed)
                    truck = sim.Truck(road, s=5.0, offset=0.0, speed=0.0)
                    phase = {"name": "engine", "t": 1.5}
                    injector.tap(*MACROS["engine"])
                d_dock = (road.length - 6.0) - truck.s
                if d_dock <= 4.0 and truck.speed < 0.6:
                    phase = {"name": "dock", "t": 2.0}
                    injector.tap(*MACROS["dock"])
                    print("[dock] parada precisa na area de entrega — abrindo dialogo...")
            if now - last_print > 2.0:
                last_print = now
                print(f"[leve] {src:16s} {truck.speed*3.6:5.1f} km/h "
                      f"offset {truck.offset:+.2f} m | jobs {jobs} | {money:+.0f} EUR | "
                      f"{link.log[-1] if link.log else ''}")
            time.sleep(0.03)
    except KeyboardInterrupt:
        print("\n[leve] encerrado")
    finally:
        injector.release_all()


def run_bench():
    """Prova o custo do bridge: 10 s do loop leve medindo CPU do processo."""
    import os
    layers = load_policy()
    injector = KeyInjector("", False)
    road = sim.Road.random(42)
    truck = sim.Truck(road, s=5.0, offset=0.0, speed=15.0)
    link = None
    t0 = time.time()
    c0 = os.times()
    steps = 0
    while time.time() - t0 < 10.0:
        for _ in range(10):                       # 100 Hz de loop interno
            cmd = policy_cmd(layers, road, truck, 1.0)
            truck.step(road, cmd[0], cmd[1], cmd[2])
            steps += 1
        time.sleep(0.01)
    c1 = os.times()
    wall = time.time() - t0
    cpu = (c1.user - c0.user) + (c1.system - c0.system)
    print(f"[bench] {steps} passos de fisica em {wall:.1f} s")
    print(f"[bench] CPU do processo: {cpu/wall*100:.1f}% de UM nucleo "
          f"(N5030 tem 4) — impacto no FPS do jogo: ~{cpu/wall*25:.1f}% de 1 nucleo")
    print("[bench] captura de tela: NENHUMA (estado por telemetria/demo)")


def main():
    ap = argparse.ArgumentParser(description="ETS2-AI bridge (Windows)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--inject", action="store_true",
                    help="injetar teclas REAIS na janela alvo (ESC mata)")
    ap.add_argument("--window", default="Euro Truck",
                    help="parte do titulo da janela alvo (ex.: 'Euro Truck')")
    ap.add_argument("--record", metavar="CSV",
                    help="gravar estados+comandos para finetune (DAgger)")
    ap.add_argument("--sem-janela", action="store_true",
                    help="modo leve: sem janela (PC fraco); Ctrl+C sai")
    ap.add_argument("--somente-celular", action="store_true",
                    help="a IA roda SO no celular; sem conexao o caminhao freia")
    ap.add_argument("--bench", action="store_true",
                    help="medir o custo de CPU do bridge (prova do impacto no FPS)")
    args = ap.parse_args()

    if args.inject and sys.platform != "win32":
        print("[aviso] --inject so funciona no Windows; rodando sem injecao.")

    if args.bench:
        run_bench()
        return
    layers = None if (args.sem_janela and args.somente_celular) else load_policy()
    injector = KeyInjector(args.window, args.inject)
    if args.inject:
        print(f"[inject] alvo: janela com '{args.window}' no titulo | ESC = kill switch")
    print("[info] este bridge NUNCA captura a tela do jogo — estado vem da "
          "telemetria/demo (0% de GPU/CPU do ETS2)")
    print(f"[rede] no celular: botao BRIDGE -> IP {PhoneLink.local_ip()} porta {args.port}")
    if args.sem_janela:
        run_headless(layers, args.port, injector, args.somente_celular)
        return
    if args.record:
        print(f"[rec] gravando em {args.record} — use as SETAS para corrigir a IA; "
              "as correcoes viram dados de treino (DAgger)")
    run_demo(layers, args.port, injector, record_path=args.record)


if __name__ == "__main__":
    main()
