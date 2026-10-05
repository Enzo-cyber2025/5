"""Detecção de input de JOYSTICK / VOLANTE / GAMEPAD (qualquer controle).

A IA injeta TECLAS — ela nunca toca no joystick. Então qualquer movimento
de eixo ou botão de um controle é o HUMANO intervindo: este módulo vigia
todos os dispositivos (winmm/DirectInput para volantes e joysticks,
XInput para controles Xbox) e alimenta a detecção de intervenção do loop
de prática. Nada é instalado; só leitura via API do Windows.
"""
import ctypes
import sys


def _setup_winmm():
    """[(nome, id)] dos joysticks/volantes DirectInput (winmm)."""
    try:
        winmm = ctypes.windll.winmm
        n = winmm.joyGetNumDevs()
        if not n:
            return None
        caps = ctypes.create_string_buffer(1024)
        found = []
        for jid in range(min(n, 16)):
            # JOYCAPSW: wMid, wPid (2 WORD), szPname[32] WCHAR...
            if winmm.joyGetDevCapsW(jid, caps, ctypes.sizeof(caps)) != 0:
                continue
            raw = caps.raw[4:4 + 64]                 # szPname (UTF-16)
            name = raw.decode("utf-16-le", errors="ignore").split("\x00")[0]
            if name:
                found.append((name, jid))
        return (winmm, found) if found else None
    except Exception:
        return None


def _setup_xinput():
    try:
        for dll in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                return (ctypes.windll[dll], dll)
            except OSError:
                continue
    except Exception:
        pass
    return None


class _XState(ctypes.Structure):
    _fields_ = [("packet", ctypes.c_ulong),
                ("buttons", ctypes.c_ushort),
                ("ltrig", ctypes.c_ubyte), ("rtrig", ctypes.c_ubyte),
                ("lx", ctypes.c_short), ("ly", ctypes.c_short),
                ("rx", ctypes.c_short), ("ry", ctypes.c_short)]


class JoystickMonitor:
    """Vigia controles: human_active() = alguém mexeu desde a última chamada."""

    AXIS_DELTA = 2500      # de 65536 (~4%): filtro de ruído/drift do volante
    THUMB_DELTA = 10000    # de 32768 (XInput)
    TRIG_DELTA = 30        # de 255

    def __init__(self):
        self.enabled = sys.platform == "win32"
        self._winmm = self._winmm_devs = None
        self._xinput = None
        self._last_axes = {}          # id -> tuple de eixos
        self._last_buttons = {}       # id -> int
        if not self.enabled:
            return
        got = _setup_winmm()
        if got:
            self._winmm, self._winmm_devs = got
        self._xinput = _setup_xinput()

    # ------------------------------------------------------------------ #
    def describe(self):
        """Nomes dos controles encontrados (para o log)."""
        if not self.enabled:
            return ""
        names = [n for n, _ in (self._winmm_devs or [])]
        if self._xinput:
            names.append("gamepad XInput")
        return " | ".join(names)

    def _poll_winmm(self):
        """True se qualquer eixo/botão de joystick mudou (ou botão apertado)."""
        if not self._winmm:
            return False

        class _JOYINFOEX(ctypes.Structure):
            _fields_ = [("size", ctypes.c_ulong), ("flags", ctypes.c_ulong),
                        ("x", ctypes.c_ulong), ("y", ctypes.c_ulong),
                        ("z", ctypes.c_ulong), ("r", ctypes.c_ulong),
                        ("u", ctypes.c_ulong), ("v", ctypes.c_ulong),
                        ("buttons", ctypes.c_ulong),
                        ("nbuttons", ctypes.c_ulong), ("pov", ctypes.c_ulong),
                        ("res1", ctypes.c_ulong), ("res2", ctypes.c_ulong)]
        moved = False
        for name, jid in self._winmm_devs:
            info = _JOYINFOEX()
            info.size, info.flags = ctypes.sizeof(_JOYINFOEX), 0x1FF
            if self._winmm.joyGetPosEx(jid, ctypes.byref(info)) != 0:
                continue
            axes = (info.x, info.y, info.z, info.r, info.u, info.v)
            prev = self._last_axes.get(jid)
            if prev is not None and any(
                    abs(a - p) > self.AXIS_DELTA for a, p in zip(axes, prev)):
                moved = True
            if info.buttons:
                moved = True
            self._last_axes[jid] = axes
            self._last_buttons[jid] = info.buttons
        return moved

    def _poll_xinput(self):
        if not self._xinput:
            return False
        dll, _ = self._xinput
        moved = False
        for pad in range(4):
            st = _XState()
            if dll.XInputGetState(pad, ctypes.byref(st)) != 0:
                continue
            axes = (st.lx, st.ly, st.rx, st.ry, st.ltrig, st.rtrig)
            prev = self._last_axes.get(("xi", pad))
            if prev is not None and any(
                    abs(a - p) > self.THUMB_DELTA for a, p in zip(axes, prev)):
                moved = True
            if st.buttons:
                moved = True
            self._last_axes[("xi", pad)] = axes
        return moved

    def human_active(self):
        """Alguém mexeu em um controle desde a última chamada."""
        if not self.enabled:
            return False
        try:
            return self._poll_winmm() or self._poll_xinput()
        except Exception:
            return False
