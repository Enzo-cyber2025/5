"""Injecao de teclas no Windows (SendInput/scan codes) + gravador DAgger.

Compartilhado pelo bridge (demo/APK) e pelo modo pratica (ets2ai.practice):
mesmo mapeamento de teclas, mesmos macros de missao, mesmo formato de
gravacao (ets2ai-rec,v1) consumido por ets2ai.finetune.
"""
import os
import sys
import time
from pathlib import Path

# Teclas enviadas (scan codes). PADRAO = WASD (pedido do usuario); em
# tempo de execucao load_keymap() le o controls.sii do JOGO e usa as teclas
# que o perfil do jogador realmente tem configuradas (mapeamento original).
KEYMAP = {"left": 0x1E, "right": 0x20, "accel": 0x11, "brake": 0x1F}

# tokens SCS (controls.sii) -> scan code
SII_TOKENS = {
    **{c: sc for c, sc in zip("abcdefghijklmnopqrstuvwxyz",
        [0x1E, 0x30, 0x2E, 0x20, 0x12, 0x21, 0x22, 0x23, 0x17, 0x24,
         0x25, 0x26, 0x32, 0x31, 0x18, 0x19, 0x10, 0x13, 0x1F, 0x14,
         0x16, 0x2F, 0x11, 0x2D, 0x15, 0x2C])},
    **{str(d): 0x02 + i for i, d in enumerate([1, 2, 3, 4, 5, 6, 7, 8, 9, 0])},
    "larrow": 0x4B, "rarrow": 0x4D, "uarrow": 0x48, "darrow": 0x50,
    "space": 0x39, "esc": 0x01, "enter": 0x1C, "return": 0x1C,
    "tab": 0x0F, "caps": 0x3A, "lctrl": 0x1D, "rctrl": 0x9D,
    "lshift": 0x2A, "rshift": 0x36, "lalt": 0x38, "ralt": 0xB8,
    "lbracket": 0x1A, "rbracket": 0x1B, "comma": 0x33, "period": 0x34,
    "slash": 0x35, "semicolon": 0x27, "apostrophe": 0x28, "grave": 0x29,
    "backslash": 0x2B, "minus": 0x0C, "equal": 0x0D, "backspace": 0x0E,
    "num0": 0x52, "num1": 0x4F, "num2": 0x50, "num3": 0x51, "num4": 0x4B,
    "num5": 0x4C, "num6": 0x4D, "num7": 0x47, "num8": 0x48, "num9": 0x49,
    "numplus": 0x4E, "numminus": 0x4A, "numenter": 0xE0, "numperiod": 0x53,
    "numslash": 0xB5, "numstar": 0x37,
}
_MODIFIERS = {"lctrl", "rctrl", "lshift", "rshift", "lalt", "ralt"}

# mix do controls.sii -> (nome logico, papel)
SII_MIXES = {
    "dsteerleft": "left", "dsteerright": "right",
    "dforward": "accel", "dbackward": "brake",
    "engine": "engine", "parkingbrake": "park_brake",
    "lblinker": "ind_left", "rblinker": "ind_right",
    "activate": "ok", "attach": "dock",
}


def _sii_profiles():
    """Pastas de perfil do ETS2 (Documents; OneDrive tambem)."""
    import os
    home = os.path.expanduser("~")
    for docs in (os.path.join(home, "Documents"),
                 os.path.join(home, "OneDrive", "Documents"),
                 os.path.join(home, "OneDrive", "Documentos"),
                 os.path.join(home, "Documentos")):
        base = os.path.join(docs, "Euro Truck Simulator 2")
        for sub in ("profiles", "steam_profiles"):
            d = os.path.join(base, sub)
            if os.path.isdir(d):
                for prof in os.listdir(d):
                    yield os.path.join(d, prof, "controls.sii")


def _parse_sii(text):
    """controls.sii -> {nome_logico: scan}.

    Entende tambem ALIASES (`input k_left \`keyboard.a?0\`"), usados por
    perfis antigos e versoes alternativas do jogo: o mix referencia o alias
    (`mix dsteerleft \`k_left?0\`") e o token real vive na linha do alias.
    Bind sem tecla de teclado (so joystick/wheel) NAO mapeia — a injecao
    continua com a tecla padrao daquela acao.
    """
    import re
    aliases = {}
    for m in re.finditer(r'input\s+(\w+)\s+`([^`]*)`', text):
        toks = re.findall(r'keyboard\.(\w+)\?\d', m.group(2))
        toks = [t.lower() for t in toks if t.lower() in SII_TOKENS
                and t.lower() not in _MODIFIERS]
        if toks:
            aliases[m.group(1)] = toks
    out = {}
    for m in re.finditer(r'mix\s+(\w+)\s+`([^`]*)`', text):
        name, expr = m.group(1), m.group(2)
        logical = SII_MIXES.get(name)
        if logical is None:
            continue
        keys = [k.lower() for k in re.findall(r'keyboard\.(\w+)\?\d', expr)
                if k.lower() in SII_TOKENS and k.lower() not in _MODIFIERS]
        for ref in re.findall(r'(\w+)\?\d', expr):      # alias?0
            keys += aliases.get(ref, [])
        if not keys:
            continue
        keys = list(dict.fromkeys(keys))                   # dedup, ordem
        keys.sort(key=lambda k: not (k.isalnum() and len(k) == 1))
        out[logical] = SII_TOKENS[keys[0]]
    return out


def load_keymap(docs_root=None):
    """Mapeia as configuracoes ORIGINAIS do jogo (controls.sii do perfil).

    Retorna (keymap, macros, origem). Sem controls.sii (ou bind faltando)
    usa o padrao WASD. keymap = {left,right,accel,brake}; macros = pares
    (scan, nome) para engine/park_brake/ind_left/ind_right/ok/dock.
    """
    keymap = dict(KEYMAP)
    found = {}
    src = "padrao WASD"
    if docs_root is not None:                     # teste injeta um .sii
        import re as _re
        best = None
        for f in Path(docs_root).rglob("controls.sii"):
            best = f                      # rglob: pega o ultimo
        if best is not None:
            found = _parse_sii(best.read_text(encoding="utf-8",
                                              errors="replace"))
            src = best.name
    else:
        best_t, best_f = -1.0, None
        for f in _sii_profiles():
            try:
                t = os.path.getmtime(f)
            except OSError:
                continue
            if t > best_t:
                best_t, best_f = t, f
        if best_f is not None:
            found = _parse_sii(best_f.read_text(encoding="utf-8",
                                                errors="replace"))
            src = str(best_f)
    for k in keymap:
        if found.get(k):
            keymap[k] = found[k]
    names = {"engine": "E (ligar motor)", "park_brake": "freio de mao",
             "ind_left": "seta ESQUERDA", "ind_right": "seta DIREITA",
             "ok": "Enter (confirmar)", "dock": "T (carregar/descarregar)"}
    default_scan = {"engine": 0x12, "park_brake": 0x39,
                    "ind_left": 0x1A, "ind_right": 0x1B,
                    "ok": 0x1C, "dock": 0x14}
    macros = {k: (found.get(k) or default_scan[k], v)
              for k, v in names.items()}
    return keymap, macros, src
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


def rect_is_fullscreen(win, mon, tol=16):
    """A janela cobre o monitor inteiro (tolerancia em px)?

    Consentimento para a IA agir: so com o jogo em TELA CHEIA (janela
    maximizada com barra de titulo nao engana — o rect fica menor que o
    monitor). Usado pelo KeyInjector antes de QUALQUER tecla.
    """
    return (win[0] <= mon[0] + tol and win[1] <= mon[1] + tol
            and win[2] >= mon[2] - tol and win[3] >= mon[3] - tol)


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
    So injeta com a janela alvo em 1o plano E em TELA CHEIA (cobrindo o
    monitor) — fora disso solta todas as teclas e espera (a IA "começa a
    atuar" quando o jogo entra em tela cheia).
    """

    def __init__(self, window_substring, enabled, keymap=None, log=None):
        self.enabled = enabled and sys.platform == "win32"
        self.window_substring = window_substring
        self.keymap = keymap or KEYMAP
        self.log = log or print
        self.down = set()
        self.kill = False
        self.phase = 0
        self._gate = None       # ultimo estado do consentimento (tela cheia)
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

    def _gate_ok(self, announce=True):
        """Consentimento para injetar: janela alvo em 1o PLANO e em TELA
        CHEIA (cobrindo o monitor inteiro). Fora disso a IA fica parada com
        as teclas soltas — e o usuario ve o motivo no log."""
        if not self.enabled:
            return False
        ct, user32 = self.ct, self.user32
        ok = False
        fg = user32.GetForegroundWindow()
        if fg:
            buf = ct.create_unicode_buffer(512)
            user32.GetWindowTextW(fg, buf, 512)
            if self.window_substring.lower() in buf.value.lower():

                class _RECT(ct.Structure):
                    _fields_ = [("l", ct.c_long), ("t", ct.c_long),
                                ("r", ct.c_long), ("b", ct.c_long)]

                wr = _RECT()
                if user32.GetWindowRect(fg, ct.byref(wr)):
                    mon = user32.MonitorFromWindow(fg, 2)  # NEAREST
                    if mon:

                        class _MI(ct.Structure):
                            _fields_ = [("cb", ct.c_ulong), ("mon", _RECT),
                                        ("work", _RECT), ("flags", ct.c_ulong)]

                        mi = _MI()
                        mi.cb = ct.sizeof(_MI)
                        if user32.GetMonitorInfoW(mon, ct.byref(mi)):
                            ok = rect_is_fullscreen(
                                (wr.l, wr.t, wr.r, wr.b),
                                (mi.mon.l, mi.mon.t, mi.mon.r, mi.mon.b))
        if announce and ok != self._gate:
            self._gate = ok
            if ok:
                self.log("[inject] jogo em TELA CHEIA — IA assumindo o volante")
            else:
                self.log("[inject] fora da TELA CHEIA — teclas soltas; a IA "
                         "só age com o jogo em tela cheia (e em 1º plano)")
        return ok

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
        if not self._gate_ok():
            want = set()          # fora da tela cheia: nenhuma tecla
        for k in self.down - want:
            self._keybd(self.keymap[k], True)
            self.down.discard(k)
        for k in want - self.down:
            self._keybd(self.keymap[k], False)
            self.down.add(k)

    def tap(self, scan, name=""):
        """Tecla unica (60 ms) para macros de missao."""
        if not self.enabled:
            print(f"[macro] {name or hex(scan)} (injecao desligada — apenas sim)")
            return
        if not self._gate_ok(announce=False):
            self.log(f"[inject] macro '{name or hex(scan)}' ignorada — "
                     "jogo nao esta em TELA CHEIA")
            return
        self._keybd(scan, False)
        time.sleep(0.06)
        self._keybd(scan, True)
        if name:
            print(f"[macro] {name}")

    def foreign_keys_down(self):
        """Teclas de direcao FISICAS pressionadas que NAO foram injetadas
        por nos. SendInput tambem altera o estado async — por isso
        descontamos as nossas. Usado para detectar o humano no volante
        quando a telemetria nao expoe os inputs do jogo (leitor de
        memoria sem DLL)."""
        if not self.enabled:
            return set()
        out = set()
        for name, scan in self.keymap.items():
            vk = self.user32.MapVirtualKeyW(scan, 1)   # VSC -> VK
            if self.user32.GetAsyncKeyState(vk) & 0x8000 and \
                    name not in self.down:
                out.add(name)
        return out

    def release_all(self):
        if not self.enabled:
            return
        for k in list(self.down):
            self._keybd(self.keymap[k], True)
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
