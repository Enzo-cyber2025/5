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

  5. Com --ets2 MODO, PRATICA no jogo REAL: le a telemetria do plugin
     RenCloud (scs-telemetry.dll), aprende o mapa da estrada dirigindo
     (record), avalia os sinais (shadow) e dirige com DAgger (drive).
     Passo a passo completo em ets2-ai/PRATICA.md.

Uso:
    python ets2_bridge.py                    # janela demo, IA local ou celular
    python ets2_bridge.py --inject --window "Euro Truck"   # injeta teclas reais
    python ets2_bridge.py --ets2 record      # pratica: VOCE dirige, IA aprende
    python ets2_bridge.py --ets2 drive --inject --window "Euro Truck"  # IA dirige
"""
import argparse
import math
import os
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
from ets2ai.model import forward, make_forward_fast      # noqa: E402
from ets2ai.keys import (KEYMAP, MACROS, EXTENDED_KEYS,   # noqa: E402,F401
                         press_menu, KeyInjector, Recorder)

DEFAULT_PORT = 7777
PHONE_TIMEOUT_S = 0.5      # sem resposta do celular por isso = failover local


# ---------------------------------------------------------------------------
# Plug & play USB: 'adb reverse' tunela o localhost do celular direto pro
# bridge — o app conecta em 127.0.0.1:7777 SEM digitar IP e sem Wi-Fi.
# (requer 'Depuracao USB' ligada no aparelho, uma unica vez)
# ---------------------------------------------------------------------------
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0   # CREATE_NO_WINDOW


def find_adb():
    cands = []
    if hasattr(sys, "_MEIPASS"):
        cands.append(Path(sys._MEIPASS) / "adb.exe")
    here = Path(__file__).resolve().parent
    cands += [here / "adb.exe", here.parent / "tools" / "adb.exe"]
    for c in cands:
        if c.exists():
            return str(c)
    return "adb"                      # ultima chance: PATH do sistema


def usb_plug_and_play(port, quiet=False):
    """Tunela todos os celulares conectados por cabo (adb reverse)."""
    import subprocess
    adb = find_adb()
    try:
        r = subprocess.run([adb, "devices"], capture_output=True, text=True,
                           timeout=10, creationflags=_NO_WINDOW)
    except Exception:
        if not quiet:
            print("[usb] adb indisponivel — plug&play por cabo desligado "
                  "(Wi-Fi/AUTO continua funcionando)")
        return False
    devs = [ln.split("\t")[0] for ln in (r.stdout or "").splitlines()
            if "\tdevice" in ln]
    if not devs:
        if not quiet:
            print("[usb] nenhum celular no cabo. Conecte o cabo USB (com "
                  "'Depuracao USB' ligada no aparelho) e toque BRIDGE > AUTO "
                  "no app — conecta sozinho, sem IP.")
        return False
    ok = 0
    for d in devs:
        try:
            subprocess.run([adb, "-s", d, "reverse", f"tcp:{port}", f"tcp:{port}"],
                           capture_output=True, text=True, timeout=10,
                           creationflags=_NO_WINDOW)
            ok += 1
        except Exception:
            pass
    if ok and not quiet:
        print(f"[usb] plug&play ATIVO: {ok} aparelho(s) no cabo — no app, "
              f"toque BRIDGE > AUTO (conecta via 127.0.0.1 automaticamente)")
    return ok > 0


class UsbKeeper(threading.Thread):
    """Re-aplica o tunel a cada 15 s: plugar o cabo DEPOIS tambem funciona."""

    def __init__(self, port, host="127.0.0.1"):
        super().__init__(daemon=True)
        self.port = port
        self.host = host          # 127.0.0.1 = so cabo USB (tunel adb)

    def run(self):
        while True:
            usb_plug_and_play(self.port, quiet=True)
            time.sleep(15.0)


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


def load_nano():
    """Rede DESTILADA (nano) p/ PC fraco — opcional (embutida no .exe).

    Retorna (layers, meta, path) ou None se o build nao trouxer (gate da
    destilacao reprovado ou pesos oficiais novos sem nano redestilada).
    """
    cands = []
    if hasattr(sys, "_MEIPASS"):
        cands.append(Path(sys._MEIPASS) / "artifacts" / "model-nano.json")
    here = Path(__file__).resolve().parent
    cands += [here.parent / "artifacts" / "model-nano.json"]
    for c in cands:
        if c.exists():
            try:
                layers, meta = load_weights(c)
            except Exception:
                return None
            if not meta.get("nano"):
                return None
            return layers, meta, c
    return None


_FF_CACHE = {}


def _fast_for(layers):
    """Forward rapido (buffers pre-alocados) reutilizado entre ticks."""
    ff = _FF_CACHE.get(id(layers))
    if ff is None:
        ff = make_forward_fast(layers)
        _FF_CACHE[id(layers)] = ff
    return ff


def policy_cmd(layers, road, truck, job_left_km):
    f = np.asarray(sim.features(road, truck, job_left_km), dtype=np.float32)
    o = _fast_for(layers)(f)
    cmd = clamp_action(float(o[0]), float(o[1]), float(o[2]))
    return sim.governor(road, truck, cmd)


# ---------------------------------------------------------------------------
# TCP server: phone is the brain
# ---------------------------------------------------------------------------
class MtpPhoneLink:
    """Ponte PC->APK por ARQUIVOS no celular (MTP): a IA roda no APK.

    Mesma interface do PhoneLink (connected/start/send_fields/wait_cmd) —
    o loop de pratica nem sabe que embaixo nao ha socket: so arquivos no
    cabo USB. SEM porta TCP, SEM Depuracao USB, SEM internet."""

    def __init__(self):
        self.connected = False
        self.rtt_ms = -1.0
        self._ch = None

    def start(self):                      # mesma API do PhoneLink
        from ets2ai.mtp import MtpChannel, MtpError
        try:
            ch = MtpChannel()
            ch.open()
            self._ch = ch
            self.connected = True
            print("[usb] ponte por ARQUIVOS ativa: cabo simples, IA no APK "
                  "(sem porta TCP, sem Depuracao USB)")
        except (MtpError, Exception) as e:
            self.connected = False
            print(f"[usb] ponte por arquivos indisponivel: {e}")

    def send_fields(self, speed=0.0, offset=0.0, hdg=0.0, curvs=None,
                    limit=25.0, fuel=0.0, fatigue=0.0, job_km=0.0, **_kw):
        if not self.connected:
            return
        curvs = [0.0 if c is None else float(c) for c in (curvs or [0.0] * 5)]
        self._ch.send_state((float(speed), float(offset), float(hdg),
                             curvs, float(limit), float(fuel),
                             float(fatigue), float(job_km), 150.0))

    def wait_cmd(self, timeout=0.30):
        if not self.connected:
            return None
        try:
            self._ch.poll_cmd()
            return self._ch.fresh_cmd()
        except Exception:
            return None


class PhoneLink(threading.Thread):
    """Accepts one phone; feeds states; collects commands."""

    def __init__(self, port, host="127.0.0.1"):
        super().__init__(daemon=True)
        self.port = port
        self.host = host          # 127.0.0.1 = so cabo USB (tunel adb)
        self.latest_cmd = None        # (steer, throttle, brake, t_sent)
        self.last_recv = 0.0
        self.rtt_ms = -1.0
        self.connected = False
        self.log = []

    def run(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(1)
        onde = (f"tcp://{self.local_ip()}:{self.port}" if self.host == "0.0.0.0"
                else f"cabo USB (tunel adb) -> tcp://127.0.0.1:{self.port}")
        self.log.append(f"aguardando celular em {onde}")
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

    def send_fields(self, speed, offset, hdg, curvs, limit, fuel,
                    fatigue, job_km, radar=150.0):
        """Estado da PRATICA (ETS2 real) no mesmo protocolo S do APK:
        o celular roda a IA (GPU/TFLite) e devolve C,steer,throttle,brake."""
        if not self.connected or not hasattr(self, "_conn"):
            return
        try:
            ts = time.time()
            msg = ("S," + ",".join([
                f"{speed:.4f}", f"{offset:.4f}", f"{hdg:.4f}",
                ",".join(f"{float(c or 0.0):.6f}" for c in curvs),
                f"{limit:.2f}", f"{fuel:.4f}", f"{fatigue:.4f}",
                f"{job_km:.4f}", f"{float(radar):.2f}",
                f"{int(ts*1000)}"]) + "\n")
            self._conn.sendall(msg.encode("utf-8"))
        except Exception:
            pass

    def wait_cmd(self, timeout=0.30):
        """Espera um comando fresco do celular; None se nao vier a tempo."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            cmd = self.latest_cmd
            if cmd is not None and time.time() - self.last_recv < 0.5:
                self.latest_cmd = None        # consome
                return cmd[0], cmd[1], cmd[2]
            time.sleep(0.002)
        return None

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
# Tkinter demo window (same physics as the phone)
# ---------------------------------------------------------------------------
def run_demo(layers, port, injector, record_path=None, host="127.0.0.1"):
    import tkinter as tk

    road = sim.Road.random(20260930)
    truck = sim.Truck(road, s=5.0, offset=0.0, speed=15.0)
    link = PhoneLink(port, host)
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

    # painel de configuracao (plug and play: tudo clicavel, zero terminal)
    cfg = tk.Frame(root, bg="#14141C")
    cfg.pack(fill="x", padx=14, pady=(2, 2))
    tk.Label(cfg, text="No celular:", font=("Segoe UI", 9), bg="#14141C",
             fg="#8B8BA3").pack(side="left")
    ip_lbl = tk.Label(cfg, text=f"{PhoneLink.local_ip()}:7777",
                      font=("Consolas", 12, "bold"), bg="#14141C", fg="#7ED957")
    ip_lbl.pack(side="left", padx=8)
    tk.Label(cfg, text="→ botão BRIDGE (ou USB: ative 'Ancoragem USB' no celular)",
             font=("Segoe UI", 8), bg="#14141C", fg="#8B8BA3").pack(side="left", padx=6)
    inject_var = tk.BooleanVar(value=injector.enabled)
    tk.Checkbutton(cfg, text="Injetar teclas no jogo", variable=inject_var,
                   command=lambda: setattr(injector, "enabled",
                                           inject_var.get() and sys.platform == "win32"),
                   bg="#14141C", fg="white", selectcolor="#2F7BFF",
                   activebackground="#14141C", activeforeground="white",
                   font=("Segoe UI", 9)).pack(side="right", padx=6)
    win_entry = tk.Entry(cfg, width=22, bg="#1B1B26", fg="white",
                         insertbackground="white", relief="flat")
    win_entry.insert(0, injector.window_substring)
    win_entry.pack(side="right", padx=6)
    win_entry.bind("<FocusOut>",
                   lambda e: setattr(injector, "window_substring", win_entry.get()))
    tk.Label(cfg, text="Janela alvo:", font=("Segoe UI", 9), bg="#14141C",
             fg="#8B8BA3").pack(side="right")

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


def _pick_brain(local_ok, phone_connected):
    """Quem dirige: PC primeiro (GPU 0%, ~0,1% CPU); celular (cabo/arquivos
    ou tunel adb) so se o PC nao der conta. '', 'local' ou 'phone'."""
    if local_ok:
        return "local"
    return "phone" if phone_connected else ""


def _local_ai_ok(cmd_s, need_hz=20.0, max_cpu_pct_of_core=8.0):
    """A IA local e 'barata o bastante' se, rodando a need_hz, usar menos de
    max_cpu_pct_of_core% de UM nucleo. N5030 tem 4 nucleos: 8% de 1 nucleo
    = 2% do chip inteiro (e 0% de GPU — numpy puro)."""
    return cmd_s >= need_hz * 100.0 / max_cpu_pct_of_core   # >= 250/s


def _bench_local_ai(layers, seconds=0.5):
    """Inferencias/segundo da REDE LOCAL no caminho real do loop de
    pratica: forward rapido (buffers pre-alocados) sobre as 13 features —
    exatamente o que roda a 20 Hz quando a IA dirige no PC."""
    ff = _fast_for(layers)
    f = np.zeros(13, dtype=np.float32)
    t0 = time.time()
    n = 0
    while time.time() - t0 < seconds:
        for _ in range(200):
            ff(f)
            n += 1
    return n / (time.time() - t0)


_NANO_MIN_INF_S = 2000.0   # 20 Hz / 2000 = 1% de 1 nucleo = 0,25% do N5030


def _choose_local_policy(log=print):
    """Escada honesta do 'IA no PC' (tudo medido NESTA maquina, no caminho
    real — nunca prometido no papel):
      1. rede OFICIAL (290x13) se couber no orcamento (>= 250 inf/s);
      2. rede DESTILADA (nano, ~28 mil params, imita a oficial) se couber
         com FOLGA (>= 2000 inf/s = <=1% de 1 nucleo a 20 Hz);
      3. senao, celular via cabo (arquivos MTP, sem depuracao).
    Retorna (layers, weights_path|None, kind|None, inf_s).
    """
    try:
        official = load_policy()
    except SystemExit:
        official = None
    if official is not None:
        s = _bench_local_ai(official, seconds=0.5)
        if _local_ai_ok(s):
            return official, None, "oficial", s
        log(f"[ia-pc] rede oficial: {s:,.0f} inf/s "
            f"(~{20.0 / s * 100:.1f}% de 1 nucleo a 20 Hz) — acima do "
            "orcamento de 1% do N5030")
    nano = load_nano()
    if nano is not None:
        nlayers, _nmeta, npath = nano
        s = _bench_local_ai(nlayers, seconds=0.5)
        if s >= _NANO_MIN_INF_S:
            return nlayers, str(npath), "nano", s
        log(f"[ia-pc] rede destilada: {s:,.0f} inf/s — tambem nao coube")
    return None, None, None, 0.0


def _start_button_state(phone_connected, running, local_ok=False):
    """Regra do botao COMEÇAR (UI): a IA roda no PC (GPU 0%, ~0,1% CPU) —
    botao liberado SEM celular. Sem IA local, exige celular (cabo MTP ou
    tunel adb). PARAR ao rodar."""
    if running:
        return ("normal", "PARAR", "#E85D75")
    if local_ok or phone_connected:
        txt = "COMEÇAR (IA no PC)" if (local_ok and not phone_connected) \
            else "COMEÇAR"
        return ("normal", txt, "#00C48C")
    return ("disabled", "COMEÇAR (conecte o celular)", "#3A4150")


def _keymap_summary():
    """Resumo das teclas que serao usadas (do controls.sii ou padrao)."""
    from ets2ai.keys import load_keymap, SII_TOKENS
    km, _macros, src = load_keymap()
    rev = {v: k for k, v in SII_TOKENS.items()}
    toks = {k: rev.get(v, "?").upper() for k, v in km.items()}
    origem = "controls.sii do jogo" if "controls" in src else "padrao WASD"
    return (f"{toks['left']}/{toks['right']} volante  ·  "
            f"{toks['accel']}/{toks['brake']} pedais  ({origem})", src)


def run_gui(port, window, inject, telemetry_mode, weights=None,
            map_path="practice/mapa.json", host="127.0.0.1"):
    """UI grafica do bridge — sem nenhum terminal por tras.

    Celular: CABO SIMPLES (MTP, sem Depuracao USB, SEM portas TCP — a IA
    roda no PC e o APK mostra CONECTADO) ou tunel adb (cerebro no celular,
    localhost) se a depuracao estiver ligada. Botao BUSCAR (sempre visivel,
    independente da conexao) localiza o jogo no disco (com cache: busca
    completa so 1x) e mostra as teclas mapeadas.
    """
    import threading
    import tkinter as tk
    from collections import deque
    from ets2ai import practice
    from ets2ai import telemetry as tele
    from ets2ai import mtp as mtp_mod

    BG, CARD, FG = "#0E1116", "#171C26", "#E8ECF3"
    MUT, ACC, OKC = "#8A93A6", "#2F7BFF", "#00C48C"

    root = tk.Tk()
    root.title("ETS2-AI")
    root.configure(bg=BG)
    root.geometry("620x600")
    root.minsize(560, 540)

    state = {"running": False, "thread": None, "mtp": None,
             "link": None, "mlink": None, "searching": False,
             "local_ok": False, "local_cmd_s": 0.0,
             "local_kind": None, "local_weights": None}
    stop_event = threading.Event()
    logs = deque(maxlen=400)

    def log(msg):
        logs.append(str(msg))

    def card():
        return tk.Frame(root, bg=CARD, padx=18, pady=14)

    # ---------- cartao: celular ----------
    ph = card()
    ph.pack(fill="x", padx=16, pady=(16, 8))
    dot = tk.Canvas(ph, width=22, height=22, bg=CARD, highlightthickness=0)
    dot_id = dot.create_oval(3, 3, 19, 19, fill="#4A5160", outline="")
    dot.pack(side="left", padx=(0, 12))
    phone_lbl = tk.Label(ph, text="Celular: procurando...",
                         font=("Segoe UI", 13, "bold"), fg=FG, bg=CARD,
                         anchor="w")
    phone_lbl.pack(fill="x")
    phone_sub = tk.Label(ph, text="espete o CABO USB (modo 'Transferir "
                                  "arquivos') — sem Depuracao USB, sem "
                                  "portas TCP",
                         font=("Segoe UI", 9), fg=MUT, bg=CARD, anchor="w",
                         justify="left", wraplength=480)
    phone_sub.pack(fill="x", pady=(2, 0))

    # ---------- cartao: jogo + BUSCAR ----------
    gm = card()
    gm.pack(fill="x", padx=16, pady=8)
    glbl = tk.Label(gm, text="Jogo (inputs)", font=("Segoe UI", 13, "bold"),
                    fg=FG, bg=CARD)
    glbl.pack(anchor="w")
    game_path = tk.Label(gm, text="ainda nao procurado — toque em BUSCAR",
                         font=("Consolas", 9), fg=MUT, bg=CARD, anchor="w",
                         justify="left", wraplength=500)
    game_path.pack(fill="x", pady=(6, 0))
    game_keys = tk.Label(gm, text="", font=("Segoe UI", 9), fg=MUT, bg=CARD,
                         anchor="w", justify="left", wraplength=500)
    game_keys.pack(fill="x")
    brow = tk.Frame(gm, bg=CARD)
    brow.pack(fill="x", pady=(10, 0))

    def do_search(force):
        if state["searching"]:
            return
        state["searching"] = True
        b1.config(state="disabled", text="PROCURANDO...")
        b2.config(state="disabled")

        def worker():
            gd = tele.resolve_game_dir(log=log, force=force)
            dll = None
            if gd is not None:
                # AUTO-INSTALL da telemetria junto com a busca: nada manual.
                try:
                    dll = tele.ensure_plugin(log=log, game_dir=gd)
                except Exception as e:
                    log(f"[dll] auto-install falhou: {e.__class__.__name__}")
            try:
                keys, _src = _keymap_summary()
            except Exception:
                keys = ""
            state["searching"] = False
            state["game"] = str(gd) if gd else None
            root.after(0, lambda: _show(gd, keys, dll))

        def _show(gd, keys, dll=None):
            if gd is not None:
                st = tele.load_game_state()
                game_path.config(text=str(gd), fg=FG)
                extra = (f"achado por: {st.get('found_by', '?')}  ·  "
                         f"usado {st.get('runs', 1)}x "
                         f"(busca completa so 1x)")
                if dll:
                    extra += ("\ntelemetria AUTO-INSTALADA no jogo"
                              if dll.get("agora_instalou")
                              else "\ntelemetria pronta (plugin no lugar)")
                game_keys.config(text=f"{keys}\n{extra}", fg=MUT)
                log(f"[jogo] {gd}")
            else:
                game_path.config(
                    text="ETS2 NAO encontrado — ABRA o jogo e toque BUSCAR "
                         "(instantâneo) ou BUSCAR DE NOVO (varredura "
                         "completa)", fg="#E85D75")
            b1.config(state="normal", text="BUSCAR")
            b2.config(state="normal")

        threading.Thread(target=worker, daemon=True).start()

    b1 = tk.Button(brow, text="BUSCAR", font=("Segoe UI", 10, "bold"),
                   fg="white", bg=ACC, activebackground="#4C8DFF",
                   activeforeground="white", relief="flat", cursor="hand2",
                   padx=18, pady=7, command=lambda: do_search(False))
    b1.pack(side="left")
    b2 = tk.Button(brow, text="BUSCAR DE NOVO (ignora o salvo)",
                   font=("Segoe UI", 9), fg=FG, bg="#232B3A",
                   activebackground="#2C3547", activeforeground="white",
                   relief="flat", cursor="hand2", padx=14, pady=7,
                   command=lambda: do_search(True))
    b2.pack(side="left", padx=(10, 0))

    # ---------- botao COMEÇAR ----------
    def on_start():
        if state["running"]:
            stop_event.set()
            return
        btn.config(state="disabled", text="INICIANDO...", bg=ACC)
        link = (state["link"] if (state["link"]
                                  and state["link"].connected) else None)
        if link is None:
            ml = state.get("mlink")
            if ml is not None and ml.connected:
                link = ml
        # PC PRIMEIRO: a IA local e numpy puro (GPU 0%, <1% CPU, ~85 MB) —
        # se a maquina da conta (sempre da), o celular fica opcional e a
        # resposta sai SEM atraso nenhum. Celular so se o PC nao der conta.
        brain = _pick_brain(state["local_ok"], link is not None)
        if brain == "local":
            link = None
        local_weights = state.get("local_weights") if brain == "local" else None
        modo = {"local": "IA no PC (GPU 0%, <1% CPU, zero atraso)",
                "phone": "IA no CELULAR (cabo)"}.get(
                    brain, "sem IA (pesos ausentes e sem celular)")
        if brain == "local" and state.get("local_kind") == "nano":
            modo = "IA no PC via rede DESTILADA (GPU 0%, <1% CPU, zero atraso)"
        log(f"[começar] {modo} | telemetria: {telemetry_mode}")

        def worker():
            try:
                practice.run("drive", map_path=map_path, inject=inject,
                             window=window, phone=link,
                             telemetry_mode=telemetry_mode,
                             log=log, stop_event=stop_event,
                             wait_game=900.0,      # pode clicar antes do jogo
                             weights=local_weights or weights
                             or practice.BASE_WEIGHTS)
            except SystemExit as e:
                log(str(e))
            except Exception as e:                       # noqa: BLE001
                log(f"ERRO: {type(e).__name__}: {e}")
            finally:
                state["running"] = False

        state["running"] = True
        stop_event.clear()
        state["thread"] = threading.Thread(target=worker, daemon=True)
        state["thread"].start()

    btn = tk.Button(root, text="COMEÇAR", font=("Segoe UI", 15, "bold"),
                    fg="white", bg=OKC, activebackground="#2BE0A8",
                    activeforeground="#0B3B2C", relief="flat", cursor="hand2",
                    padx=20, pady=11, command=on_start)
    btn.pack(fill="x", padx=16, pady=(10, 8))

    # ---------- log ----------
    logbox = tk.Text(root, height=10, bg="#0A0D12", fg="#9FE8C9",
                     insertbackground="white", font=("Consolas", 9),
                     relief="flat", state="disabled", wrap="word")
    logbox.pack(fill="both", expand=True, padx=16, pady=(0, 6))
    hint = tk.Label(root, text="IA só age com o jogo em TELA CHEIA  ·  ESC "
                               "= kill switch  ·  encostar no teclado = "
                               "correção (DAgger)",
                    font=("Segoe UI", 8), fg="#5A6478", bg=BG)
    hint.pack(pady=(0, 12))

    # ---------- deteccoes em fundo (MTP + adb) ----------
    def detect():
        """Celular via cabo: MTP (sem depuracao) ou tunel adb (com)."""
        try:
            state["mtp"] = mtp_mod.phone_name_via_mtp()
        except Exception:
            state["mtp"] = None
        try:
            if usb_plug_and_play(port, quiet=True) and state["link"] is None:
                link = PhoneLink(port, host)
                link.start()
                state["link"] = link
                log("[usb] Depuracao USB detectada: tunel adb ativo "
                    "(cerebro no celular disponivel)")
        except Exception:
            pass
        # cabo SIMPLES (sem Depuracao): IA no APK por ARQUIVOS (MTP) —
        # nenhuma porta TCP; so se ainda nao ha tunel adb
        try:
            if state["mlink"] is None and state["link"] is None and mtp:
                mlink = MtpPhoneLink()
                mlink.start()
                state["mlink"] = mlink
                if mlink.connected:
                    log("[usb] cabo simples: IA no APK por arquivos (MTP)")
        except Exception:
            pass
        root.after(2500, detect)

    def tick():
        mtp, link = state["mtp"], state["link"]
        conn = (link is not None and link.connected)
        if state["running"]:
            dot.itemconfig(dot_id, fill="#F2A93B")
            phone_lbl.config(text="Dirigindo  ·  " +
                             ("celular-cerebro" if conn else "IA no PC"),
                             fg="#F2A93B")
        elif conn:
            dot.itemconfig(dot_id, fill=OKC)
            phone_lbl.config(text="Celular CONECTADO (tunel adb — IA no "
                                  "celular)", fg=OKC)
            phone_sub.config(text=f"localhost:{port}  ·  "
                             + (f"RTT {link.rtt_ms:.0f} ms"
                                if link.rtt_ms > 0 else "tunel ativo"))
        elif mtp:
            dot.itemconfig(dot_id, fill=OKC)
            ml = state.get("mlink")
            via = ("APK conectado (painel + backup via arquivos)"
                   if state["local_ok"]
                   else "IA no APK por arquivos (cabo simples, sem porta TCP)"
                   if (ml is not None and ml.connected)
                   else "IA no APK por arquivos — abrindo ponte MTP...")
            phone_lbl.config(text=f"Celular CONECTADO — {mtp}", fg=OKC)
            phone_sub.config(text=via)
        elif state["local_ok"]:
            dot.itemconfig(dot_id, fill=OKC)
            tag = ("IA no PC pronta (rede destilada)"
                   if state.get("local_kind") == "nano"
                   else "IA no PC pronta")
            phone_lbl.config(text=f"{tag} — celular OPCIONAL "
                                  f"({state['local_cmd_s']:,.0f} inf/s, "
                                  "GPU 0%)", fg=OKC)
            phone_sub.config(text="a IA roda no .exe: 0% de GPU, <1% de "
                                  "CPU, ~85 MB, zero atraso — o celular "
                                  "(cabo) e so painel/backup")
        else:
            dot.itemconfig(dot_id, fill="#4A5160")
            phone_lbl.config(text="Celular: NÃO conectado — botão travado",
                             fg=MUT)
        mtp_ok = bool(state.get("mlink") and state["mlink"].connected)
        st_, txt_, bg_ = _start_button_state(
            conn or mtp or mtp_ok, state["running"],
            local_ok=state["local_ok"])
        btn.config(state=st_, text=txt_, bg=bg_,
                   disabledforeground="#C9D1E0")
        logbox.config(state="normal")
        logbox.delete("1.0", "end")
        logbox.insert("1.0", "\n".join(list(logs)[-11:]))
        logbox.config(state="disabled")
        root.after(400, tick)

    def bench_local():
        """IA no PC: numpy puro — GPU 0%. Mede NESTA maquina quem dirige:
        rede OFICIAL -> rede DESTILADA (nano) -> celular (cabo)."""
        try:
            layers, wpath, kind, cmd_s = _choose_local_policy(log)
            state["local_cmd_s"] = cmd_s
            state["local_weights"] = wpath
            state["local_kind"] = kind
            state["local_ok"] = kind is not None
            if kind == "oficial":
                pct = 20.0 / cmd_s * 100.0
                log(f"[ia-pc] IA roda no PC: {cmd_s:,.0f} inf/s — GPU 0%, "
                    f"~{pct:.1f}% de 1 nucleo (~{pct/4:.1f}% do N5030), "
                    "~85 MB (celular OPCIONAL, zero atraso)")
            elif kind == "nano":
                pct = 20.0 / cmd_s * 100.0
                d = (load_nano() or (None, {}, None))[1].get("distill", {})
                log(f"[ia-pc] IA no PC com a rede DESTILADA: {cmd_s:,.0f} "
                    f"inf/s (~{pct:.2f}% de 1 nucleo = ~{pct/4:.2f}% do "
                    "N5030), GPU 0% — a oficial (290x13) nao coube; a nano "
                    f"imita a oficial (erro medio {d.get('mse_stream', 0):.4f}, "
                    "malha fechada equivalente) — celular OPCIONAL, zero atraso")
            else:
                log("[ia-pc] maquina nao deu conta — IA no CELULAR via cabo "
                    "(sem depuracao)")
        except Exception as e:
            log(f"[ia-pc] pesos indisponiveis ({e.__class__.__name__}) — "
                "IA no CELULAR via cabo (sem depuracao)")
        # telemetria: instalacao AUTOMATICA na abertura (cache -> processo
        # -> Steam -> varredura LITERAL do disco; nada manual, nunca)
        try:
            if sys.platform == "win32":
                tele.ensure_plugin(log=log)
        except Exception:
            pass

    log("[info] BUSCAR localiza o jogo (busca completa 1x, depois usa o "
        "salvo)")
    log(f"[info] telemetria: {telemetry_mode} | ESC = kill switch")
    log("[info] fluxo: COMEÇAR pode ser clicado ANTES de abrir o jogo — a "
        "IA espera o ETS2 (ate 15 min) e so AGE com ele em TELA CHEIA")
    threading.Thread(target=bench_local, daemon=True).start()
    detect()
    tick()
    root.protocol("WM_DELETE_WINDOW", lambda: (stop_event.set(),
                                               root.destroy()))
    root.mainloop()


def run_headless(layers, port, injector, phone_only, host="127.0.0.1"):
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
    link = PhoneLink(port, host)
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
    # builds sem console (PyInstaller --noconsole): stdout/stderr sao None
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
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
    ap.add_argument("--demo", action="store_true",
                    help="abre a CENA DEMO antiga (so visualizacao offline)")
    ap.add_argument("--rede", action="store_true",
                    help="conexao por rede/Wi-Fi (excecao): o padrao e SO "
                         "cabo USB (tunel adb), sem internet")
    ap.add_argument("--somente-celular", action="store_true",
                    help="a IA roda SO no celular; sem conexao o caminhao freia")
    ap.add_argument("--bench", action="store_true",
                    help="medir o custo de CPU do bridge (prova do impacto no FPS)")
    ap.add_argument("--ets2", choices=["record", "shadow", "drive"],
                    metavar="MODO",
                    help="PRATICA no ETS2 REAL (telemetria RenCloud): "
                         "record=voce dirige e a IA aprende a estrada | "
                         "shadow=IA observa e da o veredicto de sinais | "
                         "drive=IA dirige (use --inject)")
    ap.add_argument("--map", default="practice/mapa.json",
                    help="mapa de pista aprendido (modo --ets2)")
    ap.add_argument("--telemetry", default="auto",
                    choices=["auto", "mem", "dll"],
                    help="telemetria: mem = SO leitura de memoria (sem DLL "
                         "nenhuma no jogo); dll = plugin embutido; auto = "
                         "mem primeiro, DLL embutida como reserva (padrao)")
    ap.add_argument("--no-dll", action="store_true",
                    help="atalho para --telemetry mem (nunca instala DLL)")
    args = ap.parse_args()

    if args.inject and sys.platform != "win32":
        print("[aviso] --inject so funciona no Windows; rodando sem injecao.")

    if args.bench:
        run_bench()
        return
    if args.ets2:
        from ets2ai import practice
        rec = args.record or None
        if rec is None and args.ets2 in ("record", "shadow"):
            import time as _t
            rec = f"practice/{args.ets2}-{_t.strftime('%Y%m%d-%H%M%S')}.csv"
            print(f"[pratica] gravando automaticamente em {rec}")
        # PLUG & PLAY tambem na pratica: cabo USB -> tunel adb reverse
        usb_plug_and_play(args.port)
        UsbKeeper(args.port).start()
        if args.ets2 in ("drive", "shadow"):
            # CELULAR COMO CEREBRO: a IA roda no APK (GPU/TFLite) e devolve
            # os comandos; o PC so le a telemetria e injeta as teclas.
            # Sem celular conectado, cai na IA local do PC (numpy).
            link = PhoneLink(args.port,
                             "0.0.0.0" if args.rede else "127.0.0.1")
            link.start()
            print(f"[pratica] IA no CELULAR: no APK toque CONECTAR com o "
                  f"CABO USB (Depuração USB) — porta {args.port}"
                  + (f"; rede: {PhoneLink.local_ip()}" if args.rede else "")
                  + " — sem celular, a IA local do PC assume")
            tmode = "mem" if args.no_dll else args.telemetry
            practice.run(args.ets2, map_path=args.map, rec_path=rec,
                         inject=args.inject, window=args.window,
                         phone=link, telemetry_mode=tmode)
        else:
            tmode = "mem" if args.no_dll else args.telemetry
            practice.run(args.ets2, map_path=args.map, rec_path=rec,
                         inject=args.inject, window=args.window,
                         telemetry_mode=tmode)
        return
    layers = None if (args.sem_janela and args.somente_celular) else load_policy()
    injector = KeyInjector(args.window, args.inject)
    if args.inject:
        print(f"[inject] alvo: janela com '{args.window}' no titulo | ESC = kill switch")
    print("[info] este bridge NUNCA captura a tela do jogo — estado vem da "
          "telemetria/demo (0% de GPU/CPU do ETS2)")
    print(f"[rede] no celular: botao BRIDGE -> AUTO (cabo USB conecta sozinho) "
          f"ou IP {PhoneLink.local_ip()} porta {args.port}")
    usb_plug_and_play(args.port)
    UsbKeeper(args.port).start()
    _host = "0.0.0.0" if args.rede else "127.0.0.1"
    if args.sem_janela:
        if layers is not None:
            # escada PC-primeiro: oficial -> destilada (nano) -> celular
            layers, _wpath, kind, s = _choose_local_policy()
            if kind == "nano":
                print(f"[ia-pc] modo leve usa a rede DESTILADA ({s:,.0f} "
                      "inf/s) — a oficial nao coube no orcamento")
        run_headless(layers, args.port, injector, args.somente_celular,
                     host=_host)
        return
    if args.demo:
        if args.record:
            print(f"[rec] gravando em {args.record} — use as SETAS para "
                  "corrigir a IA; as correcoes viram dados de treino (DAgger)")
        run_demo(layers, args.port, injector, record_path=args.record,
                 host=_host)
        return
    # padrao: UI de controle com botao COMEÇAR (cinza ate o celular conectar).
    # Injecao LIGADA: o clique no botao e o consentimento explicito (ESC no
    # jogo continua sendo o kill switch e so injeta com o ETS2 em 1o plano).
    tmode = "mem" if args.no_dll else args.telemetry
    _host = "0.0.0.0" if args.rede else "127.0.0.1"
    run_gui(args.port, args.window, True, tmode, host=_host)


if __name__ == "__main__":
    main()
