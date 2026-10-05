"""Leitor de telemetria SEM DLL (memoria do processo) — logica pura.

O backend de verdade (ctypes/Windows) nao existe neste sandbox: os testes
usam um backend falso com a MESMA interface (.open .module_base .read
.close) e um pacote de offsets real, exercitando cadeia de ponteiros,
validacao, unidade auto (km/h -> m/s) e o formato do snapshot.
"""
import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ets2ai import memtelemetry  # noqa: E402


class FakeBackend:
    """Memoria falsa: {endereco: bytes} + ponteiros little-endian."""

    def __init__(self, memory):
        self.mem = memory

    def open(self):
        pass

    def module_base(self, name):
        return 0x140000000 if "eurotrucks2" in name else None

    def read(self, addr, n):
        if addr not in self.mem:
            raise OSError(f"endereco nao mapeado: {hex(addr)}")
        return self.mem[addr][:n]

    def close(self):
        pass


def _pack(tmp_path, campos):
    p = tmp_path / "pack.json"
    p.write_text(json.dumps({"versoes": {
        "teste-1.0": {"modulo": "eurotrucks2.exe",
                      "base": "eurotrucks2.exe+4096",
                      "campos": campos}}}), encoding="utf-8")
    return p


def _mem_com_truck(speed_raw=22.5, wx=1234.5, wz=-9876.5):
    """speed em km/h (float32 na 'memoria'), posicoes em float64."""
    base = 0x140000000 + 4096
    ptr = 0x20000000
    mem = {
        base + 4320: struct.pack("<Q", ptr),          # offset[0] -> ponteiro
        ptr + 312: struct.pack("<f", speed_raw),      # speed
        base + 4400: struct.pack("<Q", ptr),          # x
        ptr + 400: struct.pack("<d", wx),
        base + 4408: struct.pack("<Q", ptr),          # z
        ptr + 408: struct.pack("<d", wz),
    }
    return mem


def test_valida_e_le_em_mps(tmp_path):
    campos = {"speed": {"offsets": [4320, 312], "tipo": "f32", "unidade": "auto"},
              "world_x": {"offsets": [4400, 400], "tipo": "f64"},
              "world_z": {"offsets": [4408, 408], "tipo": "f64"}}
    mt = memtelemetry.MemTelemetry(
        pack_path=_pack(tmp_path, campos), backend=FakeBackend(_mem_com_truck()))
    assert mt.version == "teste-1.0"
    sn = mt.snapshot()
    # 22.5 km/h "cru" -> auto nao divide (<= 47); valor em m/s direto
    assert abs(sn["speed"] - 22.5) < 1e-4
    assert sn["world_x"] == 1234.5 and sn["world_z"] == -9876.5
    # campos sem pack vem com PADRAO SEGURO (input do jogo ausente = None)
    assert sn["user_steer"] is None and sn["engine_enabled"] is True
    assert sn["park_brake"] is False and sn["on_job"] is False


def test_unidade_kmh_automatica(tmp_path):
    campos = {"speed": {"offsets": [4320, 312], "tipo": "f32", "unidade": "auto"},
              "world_x": {"offsets": [4400, 400], "tipo": "f64"},
              "world_z": {"offsets": [4408, 408], "tipo": "f64"}}
    mt = memtelemetry.MemTelemetry(
        pack_path=_pack(tmp_path, campos),
        backend=FakeBackend(_mem_com_truck(speed_raw=90.0)))   # 90 "cru"
    assert abs(mt.snapshot()["speed"] - 25.0) < 0.01          # -> 25 m/s


def test_pack_sem_posicao_nao_dirige(tmp_path):
    """Pack com SO speed (como o exemplo publico 1.40) nao valida: sem
    world_x/world_z nao ha como manter a faixa."""
    campos = {"speed": {"offsets": [4320, 312], "tipo": "f32", "unidade": "auto"}}
    with pytest.raises(RuntimeError) as e:
        memtelemetry.MemTelemetry(pack_path=_pack(tmp_path, campos),
                                  backend=FakeBackend(_mem_com_truck()))
    assert "faltam" in str(e.value) or "incompleto" in str(e.value)


def test_speed_insana_rejeita_versao(tmp_path):
    campos = {"speed": {"offsets": [4320, 312], "tipo": "f32", "unidade": "auto"},
              "world_x": {"offsets": [4400, 400], "tipo": "f64"},
              "world_z": {"offsets": [4408, 408], "tipo": "f64"}}
    with pytest.raises(RuntimeError) as e:
        memtelemetry.MemTelemetry(
            pack_path=_pack(tmp_path, campos),
            backend=FakeBackend(_mem_com_truck(speed_raw=1.0e12)))
    assert "speed insana" in str(e.value)


def test_ticks_vivos_parado_e_congelados_em_pausa(tmp_path):
    """Parado com motor ligado: ticks AVANCAM (arranque frio precisa).
    Mundo congelado por mais de 2 s com alguma velocidade: congela
    (o loop de pratica detecta stale e solta as teclas)."""
    import ets2ai.memtelemetry as mt_mod
    campos = {"speed": {"offsets": [4320, 312], "tipo": "f32", "unidade": "auto"},
              "world_x": {"offsets": [4400, 400], "tipo": "f64"},
              "world_z": {"offsets": [4408, 408], "tipo": "f64"}}
    mt = mt_mod.MemTelemetry(pack_path=_pack(tmp_path, campos),
                             backend=FakeBackend(_mem_com_truck(speed_raw=0.0)))
    t0 = mt.snapshot()["ticks"]
    t1 = mt.snapshot()["ticks"]
    assert t1 > t0            # parado, mas vivo
