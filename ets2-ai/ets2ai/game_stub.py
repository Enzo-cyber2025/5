"""game_stub.py — o "JOGO SUBSTITUTO" da PROVA DE DIRECAO (CI Windows).

Por que existe: o ETS2 real e pago/quebrado por DRM e nao roda em CI —
mas TODOS os mecanismos que a IA usa sao testaveis com um hospedeiro
fiel. Este programa e um "ETS2 minimo" que:

1. roda como processo ``eurotrucks2.exe`` (o CI empacota com PyInstaller
   com esse nome) numa pasta estilo repack OptiJuegos;
2. CARREGA a DLL universal do projeto (bin/win_x64/plugins) pela ABI
   REAL do SDK (scs_telemetry_init 1.00 + register_for_channel/event) —
   a MESMA chamada que o jogo da;
3. abre janela em TELA CHEIA com titulo "Euro Truck Simulator 2 Opti";
4. roda uma fisica minima de caminhao: as SETAS/WASD (via
   GetAsyncKeyState — as mesmas teclas que o bridge injeta com SendInput)
   aceleram/freiam/esterçam; a cada frame os valores alimentam os canais
   registrados e a DLL escreve a memoria compartilhada Local\\SCSTelemetry;
5. o BRIDGE (outro processo) le a MMF, decide e injeta as teclas — o loop
   fecha AQUI: se o caminhao ANDA, a IA assumiu o volante de verdade.

Sai sozinho apos ``--segundos`` e grava ``--saida`` (JSON): distancia,
velocidade maxima, teclas vistas e a PROVA da DLL (magic AUI1 na MMF +
valores batendo com a fisica).

Nao usa nada do ets2ai (autonomo; offsets identicos ao
universal_plugin.c / telemetry.py — o anti-drift do repo vigia).
"""
import argparse
import ctypes as ct
import json
import struct
import sys
import time
from pathlib import Path

# ---- SDK (espelha scssdk.h/scssdk_telemetry.h — ABI 1.00/1.01) ---------- #
SCS_TELEMETRY_VERSION_1_00 = 0x00010000
VALUE_BOOL, VALUE_S32, VALUE_U32 = 1, 2, 3
VALUE_FLOAT, VALUE_FVECTOR, VALUE_DPLACEMENT = 5, 7, 11
EVENT_FRAME_START, EVENT_PAUSED, EVENT_STARTED = 1, 3, 4
EVENT_CONFIGURATION, EVENT_GAMEPLAY = 5, 6
U32_NIL = 0xFFFFFFFF

# offsets no layout da MMF (TelemetryMap / universal_plugin.c)
OFF_PAUSED, OFF_TIME, OFF_VER_MAJ, OFF_VER_MIN, OFF_GAME = 4, 8, 44, 48, 52
OFF_SPEED, OFF_STEER, OFF_THR, OFF_BRK = 948, 956, 960, 964
OFF_FUEL, OFF_ROUTE, OFF_LIMIT, OFF_MAGIC = 1000, 1060, 1068, 1472
OFF_WORLD_X, OFF_WORLD_Z = 2200, 2216
UNIVERSAL_MAGIC = 0x31495541                      # "AUI1"


class SCSValue(ct.Structure):
    _fields_ = [("type", ct.c_uint32), ("pad", ct.c_uint32),
                ("data", ct.c_char * 40)]         # union (48 bytes no total)


def v_float(x):
    v = SCSValue(); v.type = VALUE_FLOAT
    v.data[:4] = struct.pack("<f", float(x)); return v


def v_bool(b):
    v = SCSValue(); v.type = VALUE_BOOL
    v.data[0] = 1 if b else 0; return v


def v_s32(n):
    v = SCSValue(); v.type = VALUE_S32
    v.data[:4] = struct.pack("<i", int(n)); return v


def v_u32(n):
    v = SCSValue(); v.type = VALUE_U32
    v.data[:4] = struct.pack("<I", int(n) & 0xFFFFFFFF); return v


def v_dplacement(x, y, z, heading, pitch, roll):
    v = SCSValue(); v.type = VALUE_DPLACEMENT
    v.data[:36] = struct.pack("<dddfff", x, y, z, heading, pitch, roll)
    return v


CHANNEL_CB = ct.CFUNCTYPE(None, ct.c_char_p, ct.c_uint32,
                          ct.POINTER(SCSValue), ct.c_void_p)
LOG_FN = ct.CFUNCTYPE(None, ct.c_uint32, ct.c_char_p)
REG_EVENT = ct.CFUNCTYPE(ct.c_int, ct.c_uint32, CHANNEL_CB, ct.c_void_p)
REG_CHANNEL = ct.CFUNCTYPE(ct.c_int, ct.c_char_p, ct.c_uint32, ct.c_uint32,
                           ct.c_uint32, CHANNEL_CB, ct.c_void_p)
UNREG_EVENT = ct.CFUNCTYPE(ct.c_int, ct.c_uint32)
UNREG_CHANNEL = ct.CFUNCTYPE(ct.c_int, ct.c_char_p, ct.c_uint32, ct.c_uint32)


class InitParams(ct.Structure):
    """scs_telemetry_init_params_v100_t (x64): 5 ponteiros de funcao NA
    ORDEM do header — common / reg_event / unreg_event / reg_channel /
    unreg_channel (omitir os unregister = bug de ABI real)."""
    _fields_ = [
        ("game_name", ct.c_char_p), ("game_id", ct.c_char_p),
        ("game_version", ct.c_uint32), ("_pad", ct.c_uint32),
        ("log", LOG_FN),
        ("register_for_event", REG_EVENT),
        ("unregister_from_event", UNREG_EVENT),
        ("register_for_channel", REG_CHANNEL),
        ("unregister_from_channel", UNREG_CHANNEL),
    ]


class SDKHost:
    """Lado "jogo" do contrato: registra o que a DLL pedir e alimenta."""

    def __init__(self, dll_path, log):
        self.canais = {}                       # nome -> (cb, ctx)
        self.eventos = {}                      # id -> (cb, ctx)
        self.log = log
        self._log_c = LOG_FN(self._on_log)
        self._re_c = REG_EVENT(self._reg_event)
        self._ue_c = UNREG_EVENT(lambda e: 0)
        self._rc_c = REG_CHANNEL(self._reg_channel)
        self._uc_c = UNREG_CHANNEL(self._unreg_channel)
        dll = ct.CDLL(str(dll_path))           # exports __cdecl
        dll.scs_telemetry_init.argtypes = [
            ct.c_uint32, ct.POINTER(InitParams)]
        dll.scs_telemetry_init.restype = ct.c_int
        params = InitParams(
            b"Euro Truck Simulator 2", b"eurotrucks2", (1 << 16) | 45,
            self._log_c, self._re_c, self._ue_c, self._rc_c, self._uc_c)
        rc = dll.scs_telemetry_init(SCS_TELEMETRY_VERSION_1_00,
                                    ct.byref(params))
        if rc != 0:
            raise RuntimeError(f"scs_telemetry_init devolveu {rc}")
        log(f"[stub] DLL carregada e init OK (rc=0)")

    def _on_log(self, _tipo, msg):
        try:
            self.log("[sdk] " + (msg or b"?").decode("utf-8", "replace"))
        except Exception:
            pass

    def _reg_event(self, event, cb, _ctx):
        self.eventos[event] = (cb, _ctx)
        return 0

    def _reg_channel(self, name, _index, _type, _flags, cb, ctx):
        self.canais[(name or b"?").decode("utf-8", "replace")] = (cb, ctx)
        return 0

    def _unreg_channel(self, name, _index, _type):
        self.canais.pop((name or b"?").decode("utf-8", "replace"), None)
        return 0

    def feed(self, name, value):
        cb = self.canais.get(name)
        if cb:
            cb(name.encode(), U32_NIL, ct.byref(value), cb[1])

    def frame_start(self, sim_ms):
        ev = self.eventos.get(EVENT_FRAME_START)
        if ev:
            info = struct.pack("<IIQQ", 0, 0, sim_ms, sim_ms)
            buf = ct.create_string_buffer(info, len(info))
            ev[0](EVENT_FRAME_START, buf, ev[1])


def mmf_probe():
    """Le a MMF crua (offsets do layout) — a PROVA de que a DLL escreveu."""
    k32 = ct.WinDLL("kernel32", use_last_error=True)
    k32.OpenFileMappingW.restype = ct.c_void_p
    h = k32.OpenFileMappingW(0x0004, False, "Local\\SCSTelemetry")
    if not h:
        return {"erro": f"OpenFileMappingW falhou (err={ct.get_last_error()})"}
    k32.MapViewOfFile.restype = ct.c_void_p
    p = k32.MapViewOfFile(h, 0x0004, 0, 0, 32768)
    if not p:
        err = ct.get_last_error()
        k32.CloseHandle(h)
        return {"erro": f"MapViewOfFile falhou (err={err})"}
    raw = (ct.c_char * 32768).from_address(p)[:]
    k32.UnmapViewOfFile(ct.c_void_p(p))
    k32.CloseHandle(ct.c_void_p(h))
    return {
        "magic": struct.unpack_from("<I", raw, OFF_MAGIC)[0],
        "speed": struct.unpack_from("<f", raw, OFF_SPEED)[0],
        "fuel": struct.unpack_from("<f", raw, OFF_FUEL)[0],
        "paused": raw[OFF_PAUSED] != 0,
    }


class _Sink:
    """PyInstaller --noconsole: stdout/stderr podem ser None — print em
    None = AttributeError = morte instantânea. Este sink engole tudo."""

    def write(self, *_a, **_k):
        return 0

    def flush(self):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--segundos", type=float, default=90.0)
    ap.add_argument("--saida", required=True)
    ap.add_argument("--headless", action="store_true",
                    help="sem janela (smoke da DLL/ABI; a prova usa janela)")
    args = ap.parse_args()

    if sys.stdout is None:
        sys.stdout = _Sink()
    if sys.stderr is None:
        sys.stderr = _Sink()

    linhas = []

    def log(m):
        linhas.append(str(m))
        try:
            print(m, file=sys.stderr, flush=True)
        except Exception:
            pass

    def escrever(**extra):
        Path(args.saida).write_text(
            json.dumps(extra, indent=1, ensure_ascii=False), encoding="utf-8")

    try:
        _run(args, log, escrever)
    except Exception:
        import traceback
        tb = traceback.format_exc()
        log("[stub] ERRO FATAL:\n" + tb)
        escrever(dist_m=0.0, max_speed_mps=0.0, teclas_tracao=0,
                 teclas_volante=0, canais_dll=0, mmf_magic_ok=False,
                 mmf_valores_ok=False, erro=tb, log=linhas[-60:])
        return 1
    return 0


def _achar_plugin(game_root):
    """Acha a DLL universal: empacotado, o exe fica DENTRO de
    bin\\win_x64 (plugin ao lado, em .\\plugins); no modo dev, o script
    esta na raiz do jogo (bin\\win_x64\\plugins abaixo)."""
    base = (Path(sys.executable) if getattr(sys, "frozen", False)
            else Path(__file__).resolve()).parent
    candidatos = [
        base / "plugins" / "scs-telemetry.dll",                   # empacotado
        base / "bin" / "win_x64" / "plugins" / "scs-telemetry.dll",  # dev
    ]
    for cima in range(1, 5):                    # repack: sobe ate achar
        try:
            raiz = base.parents[cima]
        except IndexError:
            break
        candidatos.append(raiz / "bin" / "win_x64" / "plugins"
                          / "scs-telemetry.dll")
    for c in candidatos:
        if c.exists():
            return c
    raise RuntimeError("DLL nao encontrada; tentei: "
                       + " ; ".join(str(c) for c in candidatos))


def _run(args, log, escrever):
    # PyInstaller onefile: __file__ aponta p/ o dir TEMPORARIO de extracao
    # (_MEIPASS) — o lugar do jogo (e da DLL) e o dir do .exe.
    if getattr(sys, "frozen", False):
        game_root = Path(sys.executable).resolve().parent
    else:
        game_root = Path(__file__).resolve().parent
    plugin = _achar_plugin(game_root)
    log(f"[stub] jogo em {game_root}")
    log(f"[stub] DLL: {plugin}")
    sdk = SDKHost(plugin, log)

    # ---- janela TELA CHEIA (titulo com "Euro Truck" p/ o injetor) ----- #
    root = None
    if not args.headless:
        try:
            import tkinter as tk
            root = tk.Tk()
            root.title("Euro Truck Simulator 2 Opti (prova ETS2-AI)")
            root.attributes("-fullscreen", True)
            cv = tk.Canvas(root, bg="#1d3b2a", highlightthickness=0)
            cv.pack(fill="both", expand=True)
            root.update_idletasks()
            root.focus_force()
            log("[stub] janela TELA CHEIA aberta (gate do injetor pode passar)")
        except Exception as e:                 # sem display? smoke headless
            log(f"[stub] sem janela ({e}) — rodando HEADLESS")
            root = None
    else:
        log("[stub] modo headless (sem janela)")

    user32 = ct.windll.user32
    VK = {"left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
          "a": 0x41, "d": 0x44, "s": 0x53, "w": 0x57, "e": 0x45}

    def key(vk):
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    # ---- fisica minima do caminhao ------------------------------------ #
    st = {"speed": 0.0, "heading": 0.0, "x": 0.0, "z": 0.0,
          "fuel": 1167.0, "dist": 0.0, "vmax": 0.0, "thr": 0, "str": 0,
          "route": 25000.0}
    t0 = time.monotonic()
    dt = 1.0 / 30.0
    probe = {"ok": False, "match": False, "fail": None, "last": -10.0}

    def tick():
        el = time.monotonic() - t0
        # input do "motorista" (a IA do bridge injeta exatamente estas)
        acel = key(VK["up"]) or key(VK["w"])
        freio = key(VK["down"]) or key(VK["s"])
        esq = key(VK["left"]) or key(VK["a"])
        dir_ = key(VK["right"]) or key(VK["d"])
        steer = (-1.0 if esq else 0.0) + (1.0 if dir_ else 0.0)
        if acel:
            st["thr"] += 1
        if esq or dir_:
            st["str"] += 1
        # integracao simples
        if acel:
            st["speed"] += 2.2 * dt
        if freio:
            st["speed"] -= 4.0 * dt
        st["speed"] = max(0.0, min(st["speed"] - 0.25 * dt, 25.0))
        if st["speed"] > 0.05:
            st["heading"] += steer * 0.55 * dt * min(1.0, st["speed"] / 6)
            dx = st["speed"] * dt
            st["x"] += dx
            st["dist"] += dx
            st["route"] = max(0.0, st["route"] - dx)
            st["fuel"] = max(0.0, st["fuel"] - (0.02 * dx))
        st["vmax"] = max(st["vmax"], st["speed"])
        # alimenta os CANAIS registrados pela DLL (loop real do jogo)
        sdk.frame_start(int(el * 1000))
        sdk.feed("game.time", v_u32(int(el * 60000)))
        sdk.feed("truck.speed", v_float(st["speed"]))
        sdk.feed("truck.fuel.amount", v_float(st["fuel"]))
        sdk.feed("truck.input.steering", v_float(steer))
        sdk.feed("truck.input.throttle", v_float(1.0 if acel else 0.0))
        sdk.feed("truck.input.brake", v_float(1.0 if freio else 0.0))
        sdk.feed("truck.engine.enabled", v_bool(True))
        sdk.feed("truck.brake.parking", v_bool(False))
        sdk.feed("truck.world.placement",
                 v_dplacement(st["x"], 0.0, st["z"], st["heading"] / 360.0
                              % 1.0, 0.0, 0.0))
        sdk.feed("truck.navigation.distance", v_float(st["route"]))
        sdk.feed("truck.navigation.speed.limit", v_float(22.22))
        # PROVA da DLL (magic AUI1 + valores batendo) — a partir de 6 s,
        # no maximo 1x a cada 2 s (dict evita closure/UnboundLocalError)
        if el > 6.0 and not probe["ok"] and el - probe["last"] >= 2.0:
            probe["last"] = el
            m = mmf_probe()
            if m and "erro" in m:
                probe["fail"] = m["erro"]
                log(f"[stub] MMF probe FALHOU: {m['erro']}")
            elif m:
                probe["ok"] = (m["magic"] == UNIVERSAL_MAGIC)
                probe["match"] = (abs(m["speed"] - st["speed"]) < 0.5
                                  and abs(m["fuel"] - st["fuel"]) < 5.0)
                probe["fail"] = None
                log(f"[stub] MMF probe: magic=0x{m['magic']:08X} "
                    f"speed={m['speed']:.2f} fuel={m['fuel']:.1f} "
                    f"(fisica: {st['speed']:.2f} / {st['fuel']:.1f}) "
                    f"→ dll_ok={probe['ok']} match={probe['match']}")
            else:
                probe["fail"] = "probe devolveu None"
                log("[stub] MMF probe devolveu None")
        # painel (so com janela)
        if root is not None:
            cv.delete("all")
            cv.create_text(60, 40, anchor="w", fill="white",
                           font=("Consolas", 16, "bold"),
                           text=f"JOGO SUBSTITUTO (ABI real do SDK)  "
                                f"{el:5.1f}s  dist {st['dist']:.0f} m  "
                                f"{st['speed']*3.6:5.1f} km/h")
            cv.create_text(60, 80, anchor="w", fill="#9FE8C9",
                           font=("Consolas", 12),
                           text=f"canais registrados pela DLL: "
                                f"{len(sdk.canais)} | eventos: "
                                f"{len(sdk.eventos)}")
            cv.create_rectangle(60, 140, 60 + st["speed"] * 24, 170,
                                fill="#00C48C", width=0)
        if el >= args.segundos:
            escrever(dist_m=round(st["dist"], 1),
                     max_speed_mps=round(st["vmax"], 2),
                     teclas_tracao=st["thr"], teclas_volante=st["str"],
                     canais_dll=len(sdk.canais),
                     mmf_magic_ok=bool(probe["ok"]),
                     mmf_valores_ok=bool(probe["match"]),
                     mmf_erro=probe["fail"],
                     log=linhas[-60:])
            log("[stub] fim — resultado gravado")
            return True
        return False

    def loop_tk():
        if tick():
            root.destroy()
            return
        root.after(int(dt * 1000), loop_tk)

    if root is not None:
        loop_tk()
        root.mainloop()
    else:
        while not tick():
            time.sleep(dt)
    try:
        print("fim do jogo-substituto", file=sys.stderr)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
