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
from ets2ai.contract import load_weights, clamp_action    # noqa: E402
from ets2ai.model import forward                          # noqa: E402

DEFAULT_PORT = 7777
PHONE_TIMEOUT_S = 0.5      # sem resposta do celular por isso = failover local

# Teclas enviadas (scan codes). ETS2 vem com setas para dirigir por padrao.
KEYMAP = {"left": 0x4B, "right": 0x4D, "accel": 0x48, "brake": 0x50}


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
    return clamp_action(float(o[0]), float(o[1]), float(o[2]))


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
        class _KBD(ctypes.Structure):
            _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                        ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]
        class _INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("ki", _KBD)]
        extra = ctypes.c_ulong(0)
        ki = _KBD(0, scan, KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0),
                  0, ctypes.pointer(extra))
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
    cv = tk.Canvas(root, width=900, height=560, bg="#1C4E28")
    cv.pack()
    info = tk.Label(root, font=("Courier New", 10), justify="left", anchor="w",
                    bg="black", fg="white")
    info.pack(fill="x")
    SCALE = 6

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
                    cmd = clamp_action(c[0], c[1], c[2])
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
        recmsg = f"  |  REC {rec.n} linhas ({rec.overrides} correcoes)" if rec else ""
        return (f"[{state['source']}]  {truck.speed*3.6:5.1f} km/h   "
                f"offset {truck.offset:+.2f} m   combustivel {truck.fuel*100:3.0f}%   "
                f"sono {truck.fatigue*100:3.0f}%   rota {road.length/1000 - truck.s/1000:.1f} km restantes   "
                f"{state['msg']}{recmsg}   | {' | '.join(link.log[-2:])}")

    def draw():
        cv.delete("all")
        W, H = 900, 560
        cv.create_text(10, 10, anchor="nw", fill="white",
                       text="A: IA on/off  |  setas: manual  |  celular: conecte pelo app")
        cx, cy = W / 2, H * 0.62
        ang = -math.pi / 2 - truck.heading
        cos, sin = math.cos(ang), math.sin(ang)

        def to_screen(x, y):
            dx, dy = x - truck.x, y - truck.y
            return cx + dx * cos - dy * sin, cy + dx * sin + dy * cos

        i0 = max(0, truck._hint - 40)
        i1 = min(len(road.samples) - 1, truck._hint + 110)
        pts = [to_screen(*road.samples[i]) for i in range(i0, i1, 2)]
        if len(pts) > 1:
            cv.create_line(*[c for p in pts for c in p], width=9 * SCALE,
                           fill="#3A3A44", capstyle="round", smooth=True)
            cv.create_line(*[c for p in pts for c in p], width=2, fill="#F2C14E",
                           dash=(12, 12), smooth=True)
        tx, ty = to_screen(truck.x, truck.y)
        cv.create_rectangle(tx - 8, ty - 26, tx + 8, ty + 66, fill="#2F7BFF")

    def restart(_e=None):
        nonlocal road, truck
        road = sim.Road.random(int(time.time()))
        truck = sim.Truck(road, s=5.0, offset=0.0, speed=15.0)
        state["msg"] = ""
    root.bind("r", restart)

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
    telemetria/demo). Só o servidor TCP + injeção de teclas opcional."""
    import selectors
    road = sim.Road.random(int(time.time()))
    truck = sim.Truck(road, s=5.0, offset=0.0, speed=15.0)
    link = PhoneLink(port)
    link.start()
    print(f"[leve] headless na porta {port} | celular: botao BRIDGE -> "
          f"{PhoneLink.local_ip()}:{port} | Ctrl+C sai")
    if phone_only:
        print("[leve] --somente-celular: sem o celular o caminhao FREIA (sem IA local)")
    last_print = 0.0
    acc = 0.0
    t_prev = time.time()
    try:
        while True:
            now = time.time()
            acc += min(0.25, now - t_prev)
            t_prev = now
            while acc >= sim.DT:
                acc -= sim.DT
                job_left = max(0.0, (road.length - truck.s) / 1000.0)
                link.send_state(road, truck, job_left)
                fresh = (now - link.last_recv) < PHONE_TIMEOUT_S
                if link.latest_cmd and fresh:
                    c = link.latest_cmd
                    cmd = clamp_action(c[0], c[1], c[2])
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
                if truck.fatigue > sim.SLEEP_ABOVE:
                    truck.fatigue = 0.0
                if abs(truck.offset) > sim.ROAD_HALF:
                    road = sim.Road.random(int(time.time()))
                    truck = sim.Truck(road, s=5.0, offset=0.0, speed=15.0)
                if truck.s >= road.length - 10:
                    road = sim.Road.random(int(time.time()))
                    truck = sim.Truck(road, s=5.0, offset=0.0, speed=15.0)
            if now - last_print > 2.0:
                last_print = now
                print(f"[leve] {src:16s} {truck.speed*3.6:5.1f} km/h "
                      f"offset {truck.offset:+.2f} m | {link.log[-1] if link.log else ''}")
            time.sleep(0.03)
    except KeyboardInterrupt:
        print("\n[leve] encerrado")
    finally:
        injector.release_all()


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
    args = ap.parse_args()

    if args.inject and sys.platform != "win32":
        print("[aviso] --inject so funciona no Windows; rodando sem injecao.")

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
