"""Telemetria por LEITURA de memoria do processo — SEM DLL no jogo.

Nao escreve NADA na pasta do ETS2: abre o processo com direito de LEITURA
(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION) e resolve a cadeia de
ponteiros do pacote de offsets (ets2ai/mem_offsets.json embarcado, ou uma
copia `ets2-mem-offsets.json` ao lado do .exe — a externa tem prioridade e
pode ser editada para versoes novas do jogo sem recompilar).

Honestidade tecnica: o ETS2 nao expoe telemetria nativa; a via oficial e o
plugin SDK (DLL com auto-install, embutida no .exe). Este leitor e a
alternativa SEM DLL: funciona nas versoes cujos offsets estao no pacote e
validam (speed + posicao mundiais legiveis e sanos). Se a versao do jogo
nao bater, o bridge cai automaticamente para a via DLL (modo `auto`) ou
reporta o erro (modo `mem` / --no-dll).

Projeto: os offsets sao cadeia de ponteiros no estilo Cheat Engine:
  base = modulo + base_offset
  addr = [[base + off0] + off1] ... + offN   (campo em addr)
"""
import ctypes
import json
import math
import struct
import time
from pathlib import Path

PROC_NAME = "eurotrucks2.exe"
_PACK_EMBEDDED = Path(__file__).with_name("mem_offsets.json")
_PACK_EXTERNAL = Path("ets2-mem-offsets.json")

_TYPES = {"f32": (4, "f"), "f64": (8, "d"),
          "u8": (1, "B"), "u32": (4, "I")}

# campos minimos para DIRIGIR (sem eles o pack nao valida)
_REQUIRED = ("speed", "world_x", "world_z")

# padroes seguros para o que o pack nao cobre
_DEFAULTS = {
    "user_steer": None, "user_throttle": None, "user_brake": None,
    "fuel": 0.5, "speed_limit": 0.0, "on_job": False,
    "route_distance": 0.0, "park_brake": False, "engine_enabled": True,
    "paused": False, "game_minutes": 480, "odometer": 0.0,
}


def _to_mps(v, unit):
    if unit == "kmh":
        return v / 3.6
    if unit == "auto" and abs(v) > 47.0:      # 47 m/s = 169 km/h: improvavel
        return v / 3.6
    return v


class _CtypesBackend:
    """Windows de verdade: OpenProcess + ReadProcessMemory."""

    def __init__(self):
        if not hasattr(ctypes, "windll"):   # Linux/macOS: cai p/ via DLL
            raise RuntimeError("leitura de memoria exige Windows")
        self.k32 = ctypes.windll.kernel32
        self.proc = None
        self.bases = {}

    @staticmethod
    def _pid():
        TH32CS_SNAPPROCESS = 0x2
        class PE(ctypes.Structure):
            _fields_ = [("dwSize", ctypes.c_ulong), ("cntUsage", ctypes.c_ulong),
                        ("th32ProcessID", ctypes.c_ulong),
                        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                        ("th32ModuleID", ctypes.c_ulong), ("cntThreads", ctypes.c_ulong),
                        ("th32ParentProcessID", ctypes.c_ulong), ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", ctypes.c_ulong), ("szExeFile", ctypes.c_char * 260)]
        snap = ctypes.windll.kernel32.CreateToolhelp32Snapshot(
            TH32CS_SNAPPROCESS, 0)
        pe = PE(); pe.dwSize = ctypes.sizeof(PE)
        ok = ctypes.windll.kernel32.Process32First(snap, ctypes.byref(pe))
        while ok:
            if pe.szExeFile.decode(errors="ignore").lower() == PROC_NAME:
                ctypes.windll.kernel32.CloseHandle(snap)
                return pe.th32ProcessID
            ok = ctypes.windll.kernel32.Process32Next(snap, ctypes.byref(pe))
        ctypes.windll.kernel32.CloseHandle(snap)
        return None

    def open(self):
        pid = self._pid()
        if pid is None:
            raise RuntimeError(f"processo {PROC_NAME} nao encontrado "
                               "(o ETS2 esta rodando?)")
        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        self.proc = self.k32.OpenProcess(
            PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not self.proc:
            raise RuntimeError("sem permissao para ler a memoria do jogo "
                               "(rode o .exe como administrador)")
        # base do modulo principal (peb walk simplificado via EnumProcessModules)
        psapi = ctypes.windll.psapi
        hmods = (ctypes.c_void_p * 1024)()
        need = ctypes.c_ulong()
        if psapi.EnumProcessModules(self.proc, hmods,
                                    ctypes.sizeof(hmods), ctypes.byref(need)):
            name = ctypes.create_string_buffer(260)
            for h in hmods[: need.value // ctypes.sizeof(ctypes.c_void_p)]:
                if psapi.GetModuleFileNameExA(self.proc, h, name, 260):
                    if name.value.lower().endswith(PROC_NAME):
                        self.bases[PROC_NAME] = h
                        break

    def module_base(self, name):
        return self.bases.get(name)

    def read(self, addr, n):
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t()
        if not self.k32.ReadProcessMemory(self.proc, ctypes.c_void_p(addr),
                                          buf, n, ctypes.byref(got)):
            raise OSError("ReadProcessMemory falhou")
        return buf.raw[: got.value]

    def close(self):
        if self.proc:
            self.k32.CloseHandle(self.proc)
            self.proc = None


class MemTelemetry:
    """Fonte de telemetria sem DLL: le o processo do jogo por ponteiros.

    Backend injetavel para testes: objeto com .open() .module_base(nome)
    .read(addr, n) .close().
    """

    def __init__(self, pack_path=None, backend=None):
        self.backend = backend if backend is not None else _CtypesBackend()
        path = Path(pack_path) if pack_path else (
            _PACK_EXTERNAL if _PACK_EXTERNAL.exists() else _PACK_EMBEDDED)
        try:
            pack = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as e:
            raise RuntimeError(f"pacote de offsets invalido ({path}): {e}")
        self.packs = pack.get("versoes", {})
        if not self.packs:
            raise RuntimeError(f"pacote sem versoes ({path})")
        self.version = None
        self._fields = None
        self._base = None
        self._ticks = 0
        self._last_sig = None
        self._last_change = None
        self._open_and_pick()

    # ------------------------------------------------------------------ #
    def _open_and_pick(self):
        self.backend.open()
        errs = []
        for name, spec in self.packs.items():
            if not all(k in spec.get("campos", {}) for k in _REQUIRED):
                errs.append(f"{name}: pack incompleto (faltam "
                            f"{[k for k in _REQUIRED if k not in spec.get('campos', {})]})")
                continue
            try:
                base = self._resolve_base(spec)
                vals = self._read_fields(base, spec["campos"])
                self._validate(vals)
            except Exception as e:
                errs.append(f"{name}: {e}")
                continue
            self.version, self._fields, self._base = name, spec["campos"], base
            return
        raise RuntimeError("nenhum pack de offsets validou neste jogo | " +
                           " ; ".join(errs) +
                           " | adicione os offsets da SUA versao em "
                           "ets2-mem-offsets.json ao lado do .exe")

    def _resolve_base(self, spec):
        b = spec["base"]
        mod, _, off = b.partition("+")
        modbase = self.backend.module_base(mod.strip())
        if modbase is None:
            raise RuntimeError(f"modulo {mod} nao achado no processo")
        return modbase + int(off, 0)

    def _read_fields(self, base, campos):
        out = {}
        for fname, f in campos.items():
            size, fmt = _TYPES[f.get("tipo", "f32")]
            addr = base
            chain = f["offsets"]
            for o in chain[:-1]:
                (ptr,) = struct.unpack("<Q", self.backend.read(addr + o, 8))
                if not ptr:
                    raise OSError(f"{fname}: ponteiro nulo na cadeia")
                addr = ptr
            raw = self.backend.read(addr + chain[-1], size)
            (v,) = struct.unpack("<" + fmt, raw)
            out[fname] = v
        return out

    @staticmethod
    def _validate(vals):
        v = _to_mps(vals["speed"], "auto")
        if not math.isfinite(v) or not (0.0 <= v <= 47.0):
            raise ValueError(f"speed insana: {v}")
        for k in ("world_x", "world_z"):
            if not math.isfinite(vals[k]) or abs(vals[k]) > 2.0e6:
                raise ValueError(f"{k} insano: {vals[k]}")

    # ------------------------------------------------------------------ #
    def snapshot(self):
        """Mesmo formato do leitor de DLL (RenCloud) — ver telemetry.py."""
        vals = self._read_fields(self._base, self._fields)
        self._validate(vals)
        speed = _to_mps(vals["speed"],
                        self._fields["speed"].get("unidade", "auto"))
        wx, wz = vals["world_x"], vals["world_z"]
        # ticks: so andam quando o mundo muda (pausa/menu congela -> o loop
        # de pratica detecta stale e solta as teclas). Parado com motor
        # ligado continua vivo (arranque frio precisa disso).
        sig = (round(wx, 2), round(wz, 2), round(speed, 2))
        now = time.monotonic()
        if sig != self._last_sig:
            self._last_sig, self._last_change = sig, now
            self._ticks += 1
        elif now - (self._last_change or now) < 2.0 or speed < 0.3:
            self._ticks += 1        # vivo em marcha lenta/parado
        sn = dict(_DEFAULTS)
        sn.update({
            "speed": speed, "world_x": wx, "world_z": wz,
            "ticks": self._ticks, "fuel": vals.get("fuel", 0.5),
        })
        for k in ("user_steer", "user_throttle", "user_brake",
                  "speed_limit", "on_job", "route_distance", "park_brake",
                  "engine_enabled", "game_minutes"):
            if k in self._fields:
                sn[k] = vals[k]
        return sn

    def close(self):
        try:
            self.backend.close()
        except Exception:
            pass
