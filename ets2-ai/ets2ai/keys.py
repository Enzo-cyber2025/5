"""Injecao de teclas no Windows (SendInput/scan codes) + gravador DAgger.

Compartilhado pelo bridge (demo/APK) e pelo modo pratica (ets2ai.practice):
mesmo mapeamento de teclas, mesmos macros de missao, mesmo formato de
gravacao (ets2ai-rec,v1) consumido por ets2ai.finetune.
"""
import sys
import time
from pathlib import Path

# Teclas enviadas (scan codes). ETS2 vem com setas para dirigir por padrao.
KEYMAP = {"left": 0x4B, "right": 0x4D, "accel": 0x48, "brake": 0x50}
# Macros da missao (scan code, nome) — liga motor, carga, menus do jogo.
MACROS = {
    "engine":     (0x12, "E (ligar motor)"),
    "dock":       (0x14, "T (carregar/descarregar)"),
    "ok":         (0x1C, "Enter (confirmar)"),
    "down":       (0x50, "Baixo (navegar menu)"),
    "park_brake": (0x34, ". (freio de estacionamento)"),
}
# Setas/Enter etc. sao teclas EXTENDIDAS no Windows: sem a flag, viram
# teclado numerico (bug real de injecao).
EXTENDED_KEYS = {0x48, 0x4B, 0x4D, 0x50, 0x52, 0x53, 0x1C, 0x34}

# Modulacao do volante por densidade de pulso: a tecla de seta e pressionada
# em `duty*PWM_PHASES` de cada PWM_PHASES chamadas (resolucao 1/8 a 20 Hz =
# ciclo de 2.5 Hz). Segurar a seta no ETS2 = esterco MAXIMO (~0.6 rad nas
# rodas): demais para curvas suaves. Com PWM, |steer| vira o tempo medio de
# tecla pressionada e o caminhao faz curvas proporcionais.
PWM_PHASES = 8
STEER_DEADBAND = 0.03


def key_decisions(steer, throttle, brake, phase):
    """Comandos continuos -> conjunto de teclas desta fase (0..PWM_PHASES-1).

    Pedais: bang-bang com histerese (limiar 0.30 — rampas de acelerador/freio
    do jogo sao tolerantes). Volante: PWM proporcional (ver acima).
    Usado pelo KeyInjector real (SendInput) e pelos testes (mesma matematica).
    """
    want = set()
    if throttle > 0.30:
        want.add("accel")
    if brake > 0.30:
        want.add("brake")
    side, duty = None, 0.0
    if steer < -STEER_DEADBAND:
        side, duty = "left", min(1.0, -steer)
    elif steer > STEER_DEADBAND:
        side, duty = "right", min(1.0, steer)
    if side is not None and (phase % PWM_PHASES) < int(round(duty * PWM_PHASES)):
        want.add(side)
    return want


class KeyInjector:
    """Envia comandos continuos como teclas (bang-bang com histerese).

    ESC = kill switch permanente (release tudo e para de injetar).
    So injeta se a janela alvo estiver em primeiro plano.
    """

    def __init__(self, window_substring, enabled):
        self.enabled = enabled and sys.platform == "win32"
        self.window_substring = window_substring
        self.down = set()
        self.kill = False
        self.phase = 0
        if self.enabled:
            import ctypes
            self.ct = ctypes
            self.user32 = ctypes.windll.user32
            self.kernel32 = ctypes.windll.kernel32

    def _keybd(self, scan, up):
        INPUT_KEYBOARD = 1
        KEYEVENTF_SCANCODE = 0x0008
        KEYEVENTF_KEYUP = 0x0002
        KEYEVENTF_EXTENDEDKEY = 0x0001

        class _KBD(self.ct.Structure):
            _fields_ = [("wVk", self.ct.c_ushort), ("wScan", self.ct.c_ushort),
                        ("dwFlags", self.ct.c_ulong), ("time", self.ct.c_ulong),
                        ("dwExtraInfo", self.ct.POINTER(self.ct.c_ulong))]

        class _INPUT(self.ct.Structure):
            _fields_ = [("type", self.ct.c_ulong), ("ki", _KBD)]
        extra = self.ct.c_ulong(0)
        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
        if scan in EXTENDED_KEYS:
            flags |= KEYEVENTF_EXTENDEDKEY
        ki = _KBD(0, scan, flags, 0, self.ct.pointer(extra))
        inp = _INPUT(INPUT_KEYBOARD, ki)
        n = self.user32.SendInput(1, self.ct.byref(inp), self.ct.sizeof(inp))
        return n == 1

    def _target_is_foreground(self):
        fg = self.user32.GetForegroundWindow()
        buf = self.ct.create_unicode_buffer(512)
        self.user32.GetWindowTextW(fg, buf, 512)
        return self.window_substring.lower() in buf.value.lower()

    def update(self, steer, throttle, brake):
        """Mapeia comandos continuos em teclas (volante PWM, pedais on/off)."""
        if not self.enabled:
            return
        if self.user32.GetAsyncKeyState(0x1B) & 0x8000:   # ESC
            self.kill = True
        if self.kill:
            self.release_all()
            return
        want = key_decisions(steer, throttle, brake, self.phase)
        self.phase = (self.phase + 1) % PWM_PHASES
        if not self._target_is_foreground():
            want = set()          # nao injeta fora da janela alvo
        for k in self.down - want:
            self._keybd(KEYMAP[k], True)
            self.down.discard(k)
        for k in want - self.down:
            self._keybd(KEYMAP[k], False)
            self.down.add(k)

    def tap(self, scan, name=""):
        """Tecla unica (60 ms) para macros de missao."""
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


def press_menu(injector, keys):
    """Sequencia de menu (['down','ok'] etc.) com pausas curtas."""
    for k in keys:
        scan, name = MACROS[k]
        injector.tap(scan, name)
        time.sleep(0.15)


class Recorder:
    """CSV: 13 features + 3 comandos + flag override + origem.

    origem: L=IA local | P=IA celular | H=correcao humana | M=manual (pratica)
    Consumido por ets2ai.finetune (linhas override=1 pesam mais).
    """
    HEADER = "ets2ai-rec,v1"

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, "w", encoding="utf-8")
        self.f.write(self.HEADER + "\n")
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
