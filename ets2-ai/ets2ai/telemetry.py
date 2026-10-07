"""Leitor da telemetria REAL do ETS2/ATS (plugin RenCloud scs-sdk-plugin).

Como funciona: a DLL do plugin (scs-telemetry.dll, V.1.12+) que voce coloca em
``Documentos/ETS2/bin/win_x64/plugins/`` publica o estado do jogo numa memoria
compartilhada de 32 KB chamada ``Local\\SCSTelemetry``. Este modulo le esses
bytes e devolve um snapshot com o que a IA precisa (velocidade, entradas do
motorista, combustivel, limite, GPS, rota, eventos).

Layout: scs-telemetry/inc/scs-telemetry-common.hpp do repo
github.com/RenCloud/scs-sdk-plugin (estrutura `scsTelemetryMap_t`, revisao 12).
O struct e dividido em zonas alinhadas por tipo (bool/u64, u32, i32, f32,
bool, fvetor, fplacement, dplacement, strings, u64, i64, bool de eventos,
substances, trailers[10]). Os offsets abaixo sao exatamente os do cabecalho e
estao TRAVADOS por asserts — se um plugin futuro mudar o layout, o parse
recusa em vez de devolver lixo.

Sem captura de tela, sem hook no jogo: so leitura de memoria compartilhada
publicada voluntariamente pelo plugin oficial da SCS.
"""
import ctypes
import json as _json
import os as _os
import shutil
import sys
from pathlib import Path

MMF_NAME = "Local\\SCSTelemetry"
MMF_SIZE = 32 * 1024
MMF_MIN_REVID = 12          # layout abaixo vale para telemetry_plugin_revision >= 12
STR = 64                    # stringsize


# ---------------------------------------------------------------------------
# Struct ctypes (espelho do scsTelemetryMap_t — so os campos que usamos; as
# zonas de pad garantem os offsets publicados no cabecalho).
# ---------------------------------------------------------------------------
class _S(c_types := ctypes.Structure):  # noqa: F841 - truque de legibilidade
    pass


class TelemetryMap(ctypes.Structure):
    _fields_ = [
        # ---- zona 1 (offset 0): bools + u64 de tempo ----
        ("sdk_active", ctypes.c_bool), ("_pad1", ctypes.c_char * 3),
        ("paused", ctypes.c_bool), ("_pad2", ctypes.c_char * 3),
        ("time", ctypes.c_uint64),
        ("simulated_time", ctypes.c_uint64),
        ("render_time", ctypes.c_uint64),
        ("mp_time_offset", ctypes.c_int64),
        # ---- zona 2 (offset 40): u32 ----
        ("plugin_revision", ctypes.c_uint32),
        ("version_major", ctypes.c_uint32),
        ("version_minor", ctypes.c_uint32),
        ("game_id", ctypes.c_uint32),          # 1=ets2 2=ats
        ("telemetry_version_major", ctypes.c_uint32),
        ("telemetry_version_minor", ctypes.c_uint32),
        ("time_abs_min", ctypes.c_uint32),     # tempo de jogo absoluto (min)
        ("gears", ctypes.c_uint32),
        ("gears_reverse", ctypes.c_uint32),
        ("retarder_steps", ctypes.c_uint32),
        ("truck_wheel_count", ctypes.c_uint32),
        ("selector_count", ctypes.c_uint32),
        ("time_abs_delivery", ctypes.c_uint32),
        ("max_trailer_count", ctypes.c_uint32),
        ("unit_count", ctypes.c_uint32),
        ("planned_distance_km", ctypes.c_uint32),
        ("shifter_slot", ctypes.c_uint32),
        ("retarder_brake", ctypes.c_uint32),
        ("lights_aux_front", ctypes.c_uint32),
        ("lights_aux_roof", ctypes.c_uint32),
        ("wheel_substance", ctypes.c_uint32 * 16),
        ("hshifter_position", ctypes.c_uint32 * 32),
        ("hshifter_bitmask", ctypes.c_uint32 * 32),
        ("job_delivered_time", ctypes.c_uint32),
        ("job_starting_time", ctypes.c_uint32),
        ("job_finished_time", ctypes.c_uint32),
        ("_pad_ui", ctypes.c_char * 48),
        # ---- zona 3 (offset 500): i32 ----
        ("rest_stop", ctypes.c_int32),
        ("gear", ctypes.c_int32),
        ("gear_dashboard", ctypes.c_int32),
        ("hshifter_resulting", ctypes.c_int32 * 32),
        ("job_delivered_xp", ctypes.c_int32),
        ("_pad_i", ctypes.c_char * 56),
        # ---- zona 4 (offset 700): f32 ----
        ("scale", ctypes.c_float),
        ("fuel_capacity", ctypes.c_float),
        ("fuel_warning_factor", ctypes.c_float),
        ("adblue_capacity", ctypes.c_float),
        ("adblue_warning_factor", ctypes.c_float),
        ("air_pressure_warning", ctypes.c_float),
        ("air_pressure_emergency", ctypes.c_float),
        ("oil_pressure_warning", ctypes.c_float),
        ("water_temperature_warning", ctypes.c_float),
        ("battery_voltage_warning", ctypes.c_float),
        ("engine_rpm_max", ctypes.c_float),
        ("gear_differential", ctypes.c_float),
        ("cargo_mass", ctypes.c_float),
        ("truck_wheel_radius", ctypes.c_float * 16),
        ("gear_ratios_forward", ctypes.c_float * 24),
        ("gear_ratios_reverse", ctypes.c_float * 8),
        ("unit_mass", ctypes.c_float),
        ("speed", ctypes.c_float),                # m/s
        ("engine_rpm", ctypes.c_float),
        ("user_steer", ctypes.c_float),           # -1..1 (SDK: + = direita)
        ("user_throttle", ctypes.c_float),        # 0..1
        ("user_brake", ctypes.c_float),           # 0..1
        ("user_clutch", ctypes.c_float),
        ("game_steer", ctypes.c_float),
        ("game_throttle", ctypes.c_float),
        ("game_brake", ctypes.c_float),
        ("game_clutch", ctypes.c_float),
        ("cruise_control_speed", ctypes.c_float),
        ("air_pressure", ctypes.c_float),
        ("brake_temperature", ctypes.c_float),
        ("fuel", ctypes.c_float),                 # litros absolutos
        ("fuel_avg_consumption", ctypes.c_float),
        ("fuel_range", ctypes.c_float),
        ("adblue", ctypes.c_float),
        ("oil_pressure", ctypes.c_float),
        ("oil_temperature", ctypes.c_float),
        ("water_temperature", ctypes.c_float),
        ("battery_voltage", ctypes.c_float),
        ("lights_dashboard", ctypes.c_float),
        ("wear_engine", ctypes.c_float),
        ("wear_transmission", ctypes.c_float),
        ("wear_cabin", ctypes.c_float),
        ("wear_chassis", ctypes.c_float),
        ("wear_wheels", ctypes.c_float),
        ("odometer", ctypes.c_float),
        ("route_distance", ctypes.c_float),       # metros ate o destino
        ("route_time", ctypes.c_float),
        ("speed_limit", ctypes.c_float),          # m/s (0/-1 = desconhecido)
        ("wheel_susp_deflection", ctypes.c_float * 16),
        ("wheel_velocity", ctypes.c_float * 16),
        ("wheel_steering", ctypes.c_float * 16),
        ("wheel_rotation", ctypes.c_float * 16),
        ("wheel_lift", ctypes.c_float * 16),
        ("wheel_lift_offset", ctypes.c_float * 16),
        ("job_delivered_cargo_damage", ctypes.c_float),
        ("job_delivered_distance_km", ctypes.c_float),
        ("refuel_amount", ctypes.c_float),
        ("job_cargo_damage", ctypes.c_float),
        ("_pad_f", ctypes.c_char * 28),
        # ---- zona 5 (offset 1500): bools ----
        ("wheel_steerable", ctypes.c_bool * 16),
        ("wheel_simulated", ctypes.c_bool * 16),
        ("wheel_powered", ctypes.c_bool * 16),
        ("wheel_liftable", ctypes.c_bool * 16),
        ("is_cargo_loaded", ctypes.c_bool),
        ("special_job", ctypes.c_bool),
        ("park_brake", ctypes.c_bool),
        ("motor_brake", ctypes.c_bool),
        ("air_pressure_warning_on", ctypes.c_bool),
        ("air_pressure_emergency_on", ctypes.c_bool),
        ("fuel_warning_on", ctypes.c_bool),
        ("adblue_warning_on", ctypes.c_bool),
        ("oil_pressure_warning_on", ctypes.c_bool),
        ("water_temperature_warning_on", ctypes.c_bool),
        ("battery_voltage_warning_on", ctypes.c_bool),
        ("electric_enabled", ctypes.c_bool),
        ("engine_enabled", ctypes.c_bool),
        ("wipers", ctypes.c_bool),
        ("blinker_left_active", ctypes.c_bool),
        ("blinker_right_active", ctypes.c_bool),
        ("blinker_left_on", ctypes.c_bool),
        ("blinker_right_on", ctypes.c_bool),
        ("lights_parking", ctypes.c_bool),
        ("lights_beam_low", ctypes.c_bool),
        ("lights_beam_high", ctypes.c_bool),
        ("lights_beacon", ctypes.c_bool),
        ("lights_brake", ctypes.c_bool),
        ("lights_reverse", ctypes.c_bool),
        ("lights_hazard", ctypes.c_bool),
        ("cruise_control", ctypes.c_bool),
        ("wheel_on_ground", ctypes.c_bool * 16),
        ("shifter_toggle", ctypes.c_bool * 2),
        ("differential_lock", ctypes.c_bool),
        ("lift_axle", ctypes.c_bool),
        ("lift_axle_indicator", ctypes.c_bool),
        ("trailer_lift_axle", ctypes.c_bool),
        ("trailer_lift_axle_indicator", ctypes.c_bool),
        ("job_delivered_autopark", ctypes.c_bool),
        ("job_delivered_autoload", ctypes.c_bool),
        ("_pad_b", ctypes.c_char * 25),
        # ---- zona 6 (offset 1640): fvetores ----
        ("cabin_position", ctypes.c_float * 3),
        ("head_position", ctypes.c_float * 3),
        ("hook_position", ctypes.c_float * 3),
        ("wheel_position_x", ctypes.c_float * 16),
        ("wheel_position_y", ctypes.c_float * 16),
        ("wheel_position_z", ctypes.c_float * 16),
        ("lv_acceleration", ctypes.c_float * 3),
        ("av_acceleration", ctypes.c_float * 3),
        ("acceleration", ctypes.c_float * 3),
        ("aa_acceleration", ctypes.c_float * 3),
        ("cabin_av", ctypes.c_float * 3),
        ("cabin_aa", ctypes.c_float * 3),
        ("_pad_fv", ctypes.c_char * 60),
        # ---- zona 7 (offset 2000): fplacements ----
        ("cabin_offset", ctypes.c_float * 6),
        ("head_offset", ctypes.c_float * 6),
        ("_pad_fp", ctypes.c_char * 152),
        # ---- zona 8 (offset 2200): dplacement do caminhao ----
        ("world_x", ctypes.c_double),
        ("world_y", ctypes.c_double),            # altura
        ("world_z", ctypes.c_double),
        ("rotation_x", ctypes.c_double),
        ("rotation_y", ctypes.c_double),
        ("rotation_z", ctypes.c_double),
        ("_pad_dp", ctypes.c_char * 52),
        # ---- zona 9 (offset 2300): strings ----
        ("truck_brand_id", ctypes.c_char * STR),
        ("truck_brand", ctypes.c_char * STR),
        ("truck_id", ctypes.c_char * STR),
        ("truck_name", ctypes.c_char * STR),
        ("cargo_id", ctypes.c_char * STR),
        ("cargo", ctypes.c_char * STR),
        ("city_dst_id", ctypes.c_char * STR),
        ("city_dst", ctypes.c_char * STR),
        ("comp_dst_id", ctypes.c_char * STR),
        ("comp_dst", ctypes.c_char * STR),
        ("city_src_id", ctypes.c_char * STR),
        ("city_src", ctypes.c_char * STR),
        ("comp_src_id", ctypes.c_char * STR),
        ("comp_src", ctypes.c_char * STR),
        ("shifter_type", ctypes.c_char * 16),
        ("truck_license_plate", ctypes.c_char * STR),
        ("truck_plate_country_id", ctypes.c_char * STR),
        ("truck_plate_country", ctypes.c_char * STR),
        ("job_market", ctypes.c_char * 32),
        ("fine_offence", ctypes.c_char * 32),
        ("ferry_source_name", ctypes.c_char * STR),
        ("ferry_target_name", ctypes.c_char * STR),
        ("ferry_source_id", ctypes.c_char * STR),
        ("ferry_target_id", ctypes.c_char * STR),
        ("train_source_name", ctypes.c_char * STR),
        ("train_target_name", ctypes.c_char * STR),
        ("train_source_id", ctypes.c_char * STR),
        ("train_target_id", ctypes.c_char * STR),
        ("_pad_s", ctypes.c_char * 20),
        # ---- zona 10 (offset 4000): u64 ----
        ("job_income", ctypes.c_uint64),
        ("_pad_ull", ctypes.c_char * 192),
        # ---- zona 11 (offset 4200): i64 ----
        ("job_cancelled_penalty", ctypes.c_int64),
        ("job_delivered_revenue", ctypes.c_int64),
        ("fine_amount", ctypes.c_int64),
        ("tollgate_pay_amount", ctypes.c_int64),
        ("ferry_pay_amount", ctypes.c_int64),
        ("train_pay_amount", ctypes.c_int64),
        ("_pad_ll", ctypes.c_char * 52),
        # ---- zona 12 (offset 4300): eventos ----
        ("on_job", ctypes.c_bool),
        ("job_finished", ctypes.c_bool),
        ("job_cancelled", ctypes.c_bool),
        ("job_delivered", ctypes.c_bool),
        ("fined", ctypes.c_bool),
        ("tollgate", ctypes.c_bool),
        ("ferry", ctypes.c_bool),
        ("train", ctypes.c_bool),
        ("refuel", ctypes.c_bool),
        ("refuel_payed", ctypes.c_bool),
        # (zonas 13-14: substances e trailers — nao usadas; o buffer e 32 KB)
    ]


# Offsets-chave do cabecalho (scs-telemetry-common.hpp): qualquer divergencia
# aqui = layout mudou = o parse recusa. Isto protege contra versoes futuras.
_EXPECTED_OFFSETS = {
    "sdk_active": 0, "paused": 4, "time": 8,
    "plugin_revision": 40, "game_id": 52, "time_abs_min": 64,
    "planned_distance_km": 100, "rest_stop": 500, "gear": 504,
    "scale": 700, "fuel_capacity": 704, "cargo_mass": 748,
    "speed": 948, "engine_rpm": 952,
    "user_steer": 956, "user_throttle": 960, "user_brake": 964,
    "game_steer": 972, "cruise_control_speed": 988,
    "fuel": 1000, "route_distance": 1060, "speed_limit": 1068,
    "park_brake": 1566, "engine_enabled": 1576, "cruise_control": 1589,
    "world_x": 2200, "rotation_z": 2240,
    "truck_name": 2492, "cargo": 2620, "city_dst": 2748, "city_src": 3004,
    "job_income": 4000, "on_job": 4300, "job_delivered": 4303, "fined": 4304,
}


def check_layout():
    """Levanta AssertionError se o struct nao bater com o cabecalho."""
    for name, off in _EXPECTED_OFFSETS.items():
        got = getattr(TelemetryMap, name).offset
        assert got == off, (
            f"offset de {name}: esperado {off}, obtido {got} — "
            f"layout do plugin mudou?")


check_layout()


def _s(raw):
    return raw.split(b"\x00", 1)[0].decode("utf-8", "replace")


def parse(buf):
    """Bytes da memoria compartilhada -> dict (snapshot da telemetria).

    Levanta ``RuntimeError`` se o plugin nao estiver ativo ou se a revisao do
    layout for anterior a 12 (offsets diferentes = dados corrompidos).
    """
    m = TelemetryMap.from_buffer_copy(buf, 0)
    if not m.sdk_active:
        raise RuntimeError("telemetria inativa: o jogo nao esta rodando com o "
                           "plugin (confira game.log.txt)")
    if m.plugin_revision < MMF_MIN_REVID:
        raise RuntimeError(
            f"plugin revisao {m.plugin_revision} < {MMF_MIN_REVID}: baixe a "
            "versao atual do scs-sdk-plugin (RenCloud)")
    return {
        "sdk_active": True,
        "paused": bool(m.paused),
        "ticks": int(m.time),
        "game": {1: "ets2", 2: "ats"}.get(int(m.game_id), "?"),
        "game_version": f"{m.version_major}.{m.version_minor}",
        "plugin_revision": int(m.plugin_revision),
        "game_minutes": int(m.time_abs_min),
        "planned_distance_km": int(m.planned_distance_km),
        "speed": float(m.speed),                 # m/s
        "engine_rpm": float(m.engine_rpm),
        "gear": int(m.gear),
        "user_steer": float(m.user_steer),       # -1..1, + = direita
        "user_throttle": float(m.user_throttle),
        "user_brake": float(m.user_brake),
        "game_steer": float(m.game_steer),
        "game_throttle": float(m.game_throttle),
        "game_brake": float(m.game_brake),
        "cruise_control": bool(m.cruise_control),
        "cruise_speed": float(m.cruise_control_speed),
        "fuel": float(m.fuel),                   # litros
        "fuel_capacity": float(m.fuel_capacity),
        "route_distance": float(m.route_distance),  # m ate o destino
        "route_time": float(m.route_time),
        "speed_limit": float(m.speed_limit),     # m/s
        "odometer": float(m.odometer),
        "park_brake": bool(m.park_brake),
        "engine_enabled": bool(m.engine_enabled),
        "electric_enabled": bool(m.electric_enabled),
        "lights_brake": bool(m.lights_brake),
        "blinker_left_on": bool(m.blinker_left_on),
        "blinker_right_on": bool(m.blinker_right_on),
        "world_x": float(m.world_x),
        "world_y": float(m.world_y),
        "world_z": float(m.world_z),
        "rotation_x": float(m.rotation_x),
        "rotation_y": float(m.rotation_y),
        "rotation_z": float(m.rotation_z),
        "accel_x": float(m.acceleration[0]),
        "accel_y": float(m.acceleration[1]),
        "accel_z": float(m.acceleration[2]),
        "cargo_mass": float(m.cargo_mass),
        "is_cargo_loaded": bool(m.is_cargo_loaded),
        "on_job": bool(m.on_job),
        "job_delivered": bool(m.job_delivered),
        "job_finished": bool(m.job_finished),
        "fined": bool(m.fined),
        "refuel": bool(m.refuel),
        "truck_name": _s(m.truck_name),
        "cargo": _s(m.cargo),
        "city_src": _s(m.city_src),
        "city_dst": _s(m.city_dst),
    }


class TelemetryReader:
    """Abre ``Local\\SCSTelemetry`` (Windows) e tira snapshots sob demanda."""

    def __init__(self, name=MMF_NAME):
        if _os.name != "nt":
            raise RuntimeError(
                "TelemetryReader precisa do Windows (memoria compartilhada "
                "do jogo). Para testes, injete snapshots falsos.")
        from ctypes import wintypes
        self._k32 = ctypes.windll.kernel32
        FILE_MAP_READ = 0x0004
        self._size = MMF_SIZE
        self._h = self._k32.OpenFileMappingW(FILE_MAP_READ, False, name)
        if not self._h:
            raise RuntimeError(
                f"memoria '{name}' nao encontrada — o plugin scs-telemetry.dll "
                "esta instalado em bin/win_x64/plugins? O jogo esta aberto?")
        self._k32.OpenFileMappingW.restype = wintypes.HANDLE
        ptr = self._k32.MapViewOfFile(self._h, FILE_MAP_READ, 0, 0, self._size)
        if not ptr:
            raise RuntimeError("MapViewOfFile falhou")
        self._view = (ctypes.c_char * self._size).from_address(ptr)

    def snapshot(self):
        return parse(bytes(self._view))

    def close(self):
        try:
            self._k32.UnmapViewOfFile(ctypes.cast(self._view, ctypes.c_void_p))
            self._k32.CloseHandle(self._h)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Auto-instalacao do plugin (plug & play: o .exe ja embute a DLL — MIT,
# github.com/RenCloud/scs-sdk-plugin — e copia pra pasta do jogo sozinho).
# ---------------------------------------------------------------------------
ETS2_APPID = "227300"          # Steam app id do Euro Truck Simulator 2
DLL_NAME = "scs-telemetry.dll"


def _steam_libraries(steam_path):
    """Pastas de biblioteca do Steam (libraryfolders.vdf)."""
    libs = [str(steam_path)]
    vdf = Path(steam_path) / "steamapps" / "libraryfolders.vdf"
    try:
        for ln in vdf.read_text(encoding="utf-8", errors="replace").splitlines():
            ln = ln.strip()
            if ln.startswith('"path"'):
                p = ln.split('"')[3].replace("\\\\", "\\")
                if p and p not in libs:
                    libs.append(p)
    except Exception:
        pass
    return libs


def game_root_from_exe(exe_path):
    """.../bin/win_x64/eurotrucks2.exe -> raiz da instalacao (None se o
    layout nao bater). Serve pra Steam, repack (optijuegos), portable...
    Parseia como caminho WINDOWS (PureWindowsPath) — independe do SO."""
    from pathlib import PureWindowsPath
    try:
        p = PureWindowsPath(str(exe_path))
        if p.parent.name.lower() == "win_x64" and \
                p.parent.parent.name.lower() == "bin":
            return Path(str(p.parent.parent.parent))
    except Exception:
        pass
    return None


def dir_looks_like_game(p):
    """Pasta com bin/win_x64 = instalacao do ETS2 (qualquer origem)."""
    try:
        return (Path(p) / "bin" / "win_x64").is_dir()
    except Exception:
        return False


def _running_game_root():
    """Raiz do jogo pelo PROCESSO rodando — funciona pra QUALQUER origem
    (Steam, repack tipo optijuegos, portable). None se nao achar."""
    if _os.name != "nt":
        return None
    try:
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        TH32CS_SNAPPROCESS = 0x2

        class _PE(ctypes.Structure):
            _fields_ = [("dwSize", ctypes.c_ulong), ("cntUsage", ctypes.c_ulong),
                        ("th32ProcessID", ctypes.c_ulong),
                        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                        ("th32ModuleID", ctypes.c_ulong),
                        ("cntThreads", ctypes.c_ulong),
                        ("th32ParentProcessID", ctypes.c_ulong),
                        ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", ctypes.c_ulong),
                        ("szExeFile", ctypes.c_char * 260)]
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        pe = _PE(); pe.dwSize = ctypes.sizeof(_PE)
        pid = None
        ok = k32.Process32First(snap, ctypes.byref(pe))
        while ok:
            if pe.szExeFile.decode(errors="ignore").lower() == "eurotrucks2.exe":
                pid = pe.th32ProcessID
                break
            ok = k32.Process32Next(snap, ctypes.byref(pe))
        k32.CloseHandle(snap)
        if pid is None:
            return None
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return None
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        root = None
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            root = game_root_from_exe(buf.value)
        k32.CloseHandle(h)
        return root
    except Exception:
        return None


def _iter_game_roots(starts, budget_s=600.0, log=None, now=None):
    """Varredura LITERAL do disco todo: caminha TODOS os diretorios a
    partir de `starts` procurando bin/win_x64/eurotrucks2.exe — SEM excluir
    pasta nenhuma (nem Windows, nem ocultas, nem de sistema). O unico freio
    e o teto de tempo (anti-travamento; 10 min) e erros de permissao (o SO
    nao deixa ler). Roda UMA vez so — o resultado e cacheado. Generator:
    streaming, pouca RAM."""
    import time as _time
    t0 = (now or _time.monotonic)()
    queue = list(starts)
    seen = set()
    n_dir = 0
    while queue:
        d = queue.pop()
        if d in seen:
            continue
        seen.add(d)
        n_dir += 1
        if n_dir % 20000 == 0 and log:
            log(f"[busca] {n_dir} pastas em {(_time.monotonic()-t0):.0f}s"
                f" (restam {len(queue)})")
        if (_time.monotonic() - t0) > budget_s:
            if log:
                log(f"[busca] teto de {budget_s:.0f}s atingido apos "
                    f"{n_dir} pastas")
            return
        try:
            for sub in _os.scandir(d):
                if not sub.is_dir(follow_symlinks=False):
                    continue
                child = Path(sub.path)
                if sub.name.lower() == "bin":
                    w64 = child / "win_x64"
                    if w64.is_dir() and (w64 / "eurotrucks2.exe").exists():
                        if log:
                            log(f"[busca] ACHOU: {child.parent}")
                        yield child.parent
                        return                # um jogo basta
                queue.append(child)
        except OSError:
            continue


def _all_fixed_drives():
    """Todos os discos LOCAIS do PC (A:..Z:): fixos E pen drive/removivel
    (jogo portable pode estar em qualquer um). Sem CD-ROM/rede (travariam)."""
    if _os.name != "nt":
        return []
    out = []
    try:
        import ctypes as _ct
        k32 = _ct.windll.kernel32
        bits = k32.GetLogicalDrives()
        for i in range(26):
            if not (bits >> i) & 1:
                continue
            letter = chr(65 + i) + ":\\"
            dt = k32.GetDriveTypeW(letter)
            if dt in (2, 3):            # 2=removivel (USB), 3=fixo
                out.append(Path(letter))
        if out:
            return out
    except Exception:
        pass
    return [Path(c + ":\\") for c in "CDEFG"]     # plano B


def _scan_all_disks(log=print, budget_s=600.0):
    """Busca LITERAL no disco todo: todos os arquivos/pastas de todos os
    discos locais (fixos + pen drive), sem excluir nada."""
    drives = _all_fixed_drives()
    if log:
        log(f"[busca] varredura LITERAL do disco todo em: "
            f"{', '.join(str(d) for d in drives)} (sem excluir pastas)")
    return list(_iter_game_roots(drives, budget_s=budget_s, log=log))


def _game_hints():
    """ULTIMO CASO: analisa onde o JOGO deixa rastros — atalhos (.lnk da
    Area de Trabalho/Menu Iniciar) e entradas de desinstalacao do registro
    (repacks costumam se registrar). Retorna raizes candidatas."""
    out = []
    if _os.name != "nt":
        return out
    # 1) atalhos .lnk apontando para eurotrucks2.exe
    try:
        import glob as _glob
        home = Path.home()
        pats = [str(home / "Desktop" / "*.lnk"),
                str(home / "OneDrive" / "Desktop" / "*.lnk"),
                r"C:\ProgramData\Microsoft\Windows\Start Menu"
                r"\Programs\**\*.lnk",
                str(home / "AppData" / "Roaming" / "Microsoft" / "Windows"
                    / "Start Menu" / "Programs" / "**" / "*.lnk")]
        for pat in pats:
            for f in _glob.glob(pat, recursive=True):
                try:
                    data = Path(f).read_bytes()
                except OSError:
                    continue
                for path in _paths_from_lnk(data):
                    root = game_root_from_exe(path)
                    if root is not None and root not in out:
                        out.append(root)
    except Exception:
        pass
    # 2) registro: entradas de desinstalacao (DisplayName/InstallLocation)
    try:
        import winreg
        bases = [(winreg.HKEY_LOCAL_MACHINE,
                  r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
                 (winreg.HKEY_LOCAL_MACHINE,
                  r"Software\Wow6432Node\Microsoft\Windows\CurrentVersion"
                  r"\Uninstall"),
                 (winreg.HKEY_CURRENT_USER,
                  r"Software\Microsoft\Windows\CurrentVersion\Uninstall")]
        for hive, path in bases:
            try:
                key = winreg.OpenKey(hive, path)
            except OSError:
                continue
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i); i += 1
                except OSError:
                    break
                try:
                    with winreg.OpenKey(key, sub) as k:
                        vals = {}
                        for v in ("DisplayName", "InstallLocation",
                                  "DisplayIcon", "UninstallString"):
                            try:
                                vals[v] = winreg.QueryValueEx(k, v)[0]
                            except OSError:
                                pass
                        blob = " ".join(str(v) for v in vals.values()).lower()
                        if "euro truck" not in blob and "ets2" not in blob:
                            continue
                        for cand in (vals.get("InstallLocation"),
                                     vals.get("DisplayIcon"),
                                     vals.get("UninstallString")):
                            if not cand:
                                continue
                            root = game_root_from_exe(str(cand))
                            if root is None and ":" in str(cand):
                                d = Path(str(cand).split('"')[0]
                                         if '"' in str(cand) else str(cand))
                                root = d if dir_looks_like_game(d) else None
                            if root is not None and root not in out:
                                out.append(root)
                except OSError:
                    continue
    except Exception:
        pass
    return out


def _paths_from_lnk(data):
    """Extrai caminhos ...eurotrucks2.exe dos bytes de um atalho .lnk
    (paths ficam em ANSI e UTF-16 dentro do binario)."""
    import re
    out = []
    for m in re.finditer(rb"[A-Za-z]:[\\/][\x20-\x7e]{2,220}?eurotrucks2"
                         rb"\.exe", data, re.I):
        out.append(m.group(0).decode("latin-1"))
    for off in (0, 1):                       # UTF-16: alinhamento par/impar
        try:
            t = data[off:].decode("utf-16-le", errors="ignore")
        except Exception:
            continue
        for m in re.finditer(r"[A-Za-z]:[\\/][\x20-\x7e]{2,220}?eurotrucks2"
                             r"\.exe", t, re.I):
            out.append(m.group(0))
    return out


def _default_locations():
    """Config PADRAO (ultimo recurso): lugares mais comuns."""
    home = Path.home()
    return [Path(r"C:\Program Files\Euro Truck Simulator 2"),
            Path(r"C:\Program Files (x86)\Euro Truck Simulator 2"),
            home / "Desktop" / "Euro Truck Simulator 2",
            home / "Downloads" / "Euro Truck Simulator 2",
            Path(r"C:\Games"), Path(r"C:\Jogos"),
            Path(r"D:\Games"), Path(r"D:\Jogos")]


def _scan_common_roots():
    """Varredura rapida por instalacoes ALTERNATIVAS (repacks tipo
    optijuegos): pastas de jogos comuns em todos os drives fixos, ate
    profundidade 3 (filtrando pelo nome: euro/ets2/truck)."""
    if _os.name != "nt":
        return []
    import glob as _glob
    hits, seen = [], set()
    home = Path.home()
    bases = [home / "Desktop", home / "Downloads", home / "Documents",
             Path(r"C:\Games"), Path(r"C:\Jogos"), Path(r"C:\Program Files"),
             Path(r"C:\Program Files (x86)"), Path("C:/"), Path("D:/"),
             Path("E:/"), Path("F:/"), Path(r"D:\Games"), Path(r"D:\Jogos")]

    def _try(d):
        if d in seen:
            return
        seen.add(d)
        if dir_looks_like_game(d):
            hits.append(Path(d))
            return
        try:                              # 1 nivel a mais (repack aninhado)
            for sub in _os.scandir(d):
                if sub.is_dir() and dir_looks_like_game(sub.path):
                    hits.append(Path(sub.path))
        except OSError:
            pass

    for base in bases:
        for pat in (str(base / "*"), str(base / "*" / "*")):
            try:
                for d in _glob.glob(pat):
                    dl = d.lower()
                    if "euro" in dl or "ets2" in dl or "truck" in dl:
                        _try(d)
            except Exception:
                continue
    return hits


_STATE_FILENAME = "ets2-ai-state.json"


def _state_file(state_file=None):
    """Arquivo de estado ao lado do .exe (CWD)."""
    return Path(state_file) if state_file else Path(_STATE_FILENAME)


def load_game_state(state_file=None):
    try:
        return _json.loads(_state_file(state_file).read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_game_state(st, state_file=None):
    try:
        p = _state_file(state_file)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(_json.dumps(st, indent=1, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)
        return True
    except Exception:
        return False


def note_state(state_file=None, **kw):
    """Atualiza o estado a CADA execucao (telemetria usada, modo, etc.)."""
    import time as _time
    st = load_game_state(state_file)
    st.update(kw)
    st["last_seen"] = _time.time()
    save_game_state(st, state_file)


def resolve_game_dir(extra=None, log=None, state_file=None, force=False):
    """Caminho do jogo COM CACHE: a busca completa (processo > Steam > TODOS
    os discos > rastros > padrao) roda UMA unica vez e o resultado e salvo
    em ets2-ai-state.json (ao lado do .exe). Nas execucoes seguintes usa o
    caminho salvo direto — sem varrer disco de novo — e so atualiza o
    estado (last_seen/runs). Se o caminho salvo deixar de existir (jogo
    movido/desinstalado), refaz a busca UMA vez e atualiza o arquivo."""
    import time as _time
    st = load_game_state(state_file)
    gd = st.get("game_dir")
    if not force and gd and dir_looks_like_game(gd):
        st["last_seen"] = _time.time()
        st["runs"] = int(st.get("runs", 0)) + 1
        save_game_state(st, state_file)
        if log:
            log(f"[jogo] caminho SALVO (sem busca): {gd} "
                f"[{st.get('found_by', '?')}, usado {st['runs']}x]")
        return Path(gd)
    # CACHE NEGATIVO: a varredura LITERAL que ja rodou e nao achou NAO
    # repete sozinha (so com force=True, o BUSCAR DE NOVO) — mas as vias
    # BARATAS (jogo aberto, Steam, --game-dir) continuam vivas sempre.
    cheap_only = bool(st.get("scan_failed_at")) and not force
    if cheap_only and log:
        log("[jogo] varredura completa anterior nao achou o ETS2 — usando "
            "deteccao rapida (jogo aberto/Steam); BUSCAR DE NOVO refaz a "
            "varredura do disco todo")
    cand, found_by = None, "busca"
    for d in game_install_dirs(extra, log=(None if cheap_only else log),
                               literal_scan=not cheap_only):
        if dir_looks_like_game(d):
            cand = d
            if extra and Path(extra) == d:
                found_by = "--game-dir"
            elif _running_game_root() == d:
                found_by = "processo rodando"
            break
    if cand is None:
        # registra a varredura vazia: proximas execucoes pulam os 10 min de
        # busca (a descoberta por PROCESSO continua viva: basta abrir o jogo)
        novo = dict(st)
        novo["scan_failed_at"] = _time.time()
        for k in ("game_dir", "found_by", "found_at", "last_seen", "runs"):
            novo.pop(k, None)
        save_game_state(novo, state_file)
        if log:
            log("[jogo] ETS2 NAO encontrado — ABRA o jogo e toque BUSCAR "
                "(deteccao por processo e instantanea) ou BUSCAR DE NOVO "
                "(varredura completa do disco todo)")
        return None
    novo = {"game_dir": str(cand), "found_by": found_by,
            "found_at": _time.time(), "last_seen": _time.time(), "runs": 1}
    for k in ("telemetry", "pack", "mode"):        # preserva o resto
        if k in st:
            novo[k] = st[k]
    save_game_state(novo, state_file)
    if log:
        log(f"[jogo] ACHADO ({found_by}): {cand} — salvo em "
            f"{_STATE_FILENAME}; proximas execucoes NAO buscam de novo")
    return cand


def game_install_dirs(extra=None, log=None, literal_scan=True):
    """Diretorios candidatos de instalacao do ETS2 (ordem de preferencia):
    --game-dir explicito > PROCESSO rodando (qualquer origem) > Steam >
    VARREDURA LITERAL do disco todo (sem excluir nada) > rastros > padrao.

    literal_scan=False: pula a varredura de 10 min (cache negativo) e usa
    so as vias baratas — processo rodando, Steam, rastros, padrao."""
    out = []
    if extra:
        out.append(Path(extra))
    if _os.name == "nt":
        run_root = _running_game_root()
        if run_root is not None:
            out.append(run_root)
    if _os.name == "nt":
        steam = None
        try:
            import winreg
            for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE,
                               r"SOFTWARE\WOW6432Node\Valve\Steam")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        steam, _ = winreg.QueryValueEx(k, "SteamPath")
                    break
                except OSError:
                    continue
        except Exception:
            steam = None
        libs = []
        if steam:
            libs += _steam_libraries(steam)
        libs += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
        for lib in libs:
            out.append(Path(lib) / "steamapps" / "common" / "Euro Truck Simulator 2")
    if _os.name == "nt" and literal_scan:
        for gd in _scan_all_disks(log=log or print):   # TODOS os discos
            if gd not in out:
                out.append(gd)
        for gd in _game_hints():             # ultimo caso: rastros do jogo
            if gd not in out:
                out.append(gd)
    for gd in _default_locations():          # config padrao (fim da linha)
        if gd not in out:
            out.append(gd)
    return out


def plugin_dll_path(game_dir):
    return Path(game_dir) / "bin" / "win_x64" / "plugins" / DLL_NAME


def find_bundled_dll():
    """DLL empacotada no .exe (PyInstaller) ou no repo (tools/)."""
    cands = []
    if hasattr(sys, "_MEIPASS"):
        cands.append(Path(sys._MEIPASS) / DLL_NAME)
    here = Path(__file__).resolve().parent
    cands += [here.parent / "tools" / DLL_NAME, here.parent.parent / "tools" / DLL_NAME]
    for c in cands:
        if c.exists():
            return c
    return None


def install_plugin(game_dir, dll_src=None):
    """Copia a DLL (MIT, RenCloud) para a pasta de plugins do jogo."""
    dll_src = Path(dll_src) if dll_src else find_bundled_dll()
    if dll_src is None or not dll_src.exists():
        raise RuntimeError("DLL de telemetria nao encontrada no pacote")
    dst = plugin_dll_path(game_dir)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(dll_src, dst)
    return dst


def plugin_installed(game_dir=None):
    """Pasta do jogo onde o plugin ja esta instalado (None se nao estiver)."""
    for gd in game_install_dirs(game_dir):
        if plugin_dll_path(gd).exists():
            return gd
    return None


def ensure_plugin(log=print, game_dir=None, force=False):
    """Instalacao 100% AUTOMATICA da telemetria (nada manual):

    1. acha a pasta do jogo (caminho salvo -> processo rodando -> Steam ->
       VARREDURA LITERAL do disco todo, igual a descoberta dos controles);
    2. copia a DLL RenCloud (MIT) EMBUTIDA no .exe para
       <jogo>/bin/win_x64/plugins/  (local oficial do plugin);
    3. confere tamanho e retorna o estado.

    Idempotente e barata quando o caminho ja esta salvo. Retorna dict
    {game_dir, dll, agora_instalou} ou None se o jogo nao foi achado.
    """
    gd = game_dir or resolve_game_dir(log=log, force=force)
    if gd is None:
        return None
    gd = Path(gd)
    if not dir_looks_like_game(gd):
        log(f"[dll] {gd} nao tem bin/win_x64 — ignorando")
        return None
    dll_src = find_bundled_dll()
    if dll_src is None:
        log("[dll] DLL nao vem embutida neste pacote (build do repo?)")
        return None
    dst = plugin_dll_path(gd)
    want = dll_src.stat().st_size
    if dst.exists() and dst.stat().st_size == want:
        return {"game_dir": str(gd), "dll": str(dst),
                "agora_instalou": False}
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(dll_src, dst)
    except OSError as e:
        log(f"[dll] falhou ao instalar em {dst}: {e}")
        return None
    ok = dst.exists() and dst.stat().st_size == want
    if not ok:
        log(f"[dll] instalada mas verificacao falhou: {dst}")
        return None
    log(f"[dll] telemetria AUTO-INSTALADA: {dst} — se o ETS2 estiver "
        "aberto, REINICIE o jogo 1x (o plugin carrega na abertura)")
    return {"game_dir": str(gd), "dll": str(dst), "agora_instalou": True}
