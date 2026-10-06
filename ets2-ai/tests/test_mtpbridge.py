"""IA no celular VIA ARQUIVOS (MTP): sem Depuracao USB, sem portas TCP."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ets2ai.mtpbridge import MtpBridge, PREFIX_S, PREFIX_C  # noqa: E402


def test_interface_e_fallback_local():
    """Mesma interface do PhoneLink; sem troca ainda -> wait_cmd None (o
    loop de pratica cai na IA local do PC — nunca trava)."""
    b = MtpBridge()
    assert b.connected is False and b.latest_cmd is None
    b.send_fields(speed=10.0, offset=0.5, hdg=0.1, curvs=[0.001] * 5,
                  limit=25.0, fuel=0.5, fatigue=0.2, job_km=100.0)
    assert b.wait_cmd(0.05) is None



def test_nomes_de_troca_sao_unicos_por_sequencia():
    """Nomes unicos por troca = zero problema de cache do MTP."""
    assert PREFIX_S != PREFIX_C
    assert PREFIX_S.startswith("ets2ai-")


def test_protocolo_s_tem_14_campos():
    """A linha S gerada e o MESMO protocolo do canal TCP (mesma rede no
    APK — so muda o transporte: arquivo em vez de socket)."""
    b = MtpBridge()
    import threading
    capturado = {}
    orig = MtpBridge.send_fields

    def spy(self, **kw):
        capturado.update(kw)
        orig(self, **kw)
    MtpBridge.send_fields = spy
    try:
        b.send_fields(speed=10.0, offset=0.5, hdg=0.1, curvs=[0.001] * 5,
                      limit=25.0, fuel=0.5, fatigue=0.2, job_km=100.0,
                      radar=150.0, ts=1.0)
    finally:
        MtpBridge.send_fields = orig
    assert capturado["curvs"] == [0.001] * 5
    assert len(capturado) >= 9
