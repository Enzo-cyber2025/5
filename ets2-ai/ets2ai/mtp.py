"""Celular pelo cabo USB SEM Depuracao USB e SEM portas TCP (modo simples).

O celular conectado em modo 'Transferencia de arquivos' (MTP — padrao ao
espetar o cabo) aparece no Windows como uma pasta do Computador. Aqui so
DETECTAMOS a presenca dele (nome do aparelho) — nenhum servidor TCP e
aberto, nenhuma porta criada, nada instalado no celular. Nesse modo a IA
roda no PROPRIO PC (numpy) e o APK vira o painel: mostra CONECTADO quando
o cabo esta espetado (deteccao propria do Android).

Quem quiser o cerebro-no-celular (GPU): cabo com Depuracao USB (tunel
adb, localhost) ou --rede; nada disso e preciso para dirigir.
"""
import sys

_PHONE_HINTS = ("phone", "android", "mtp", "ptp", "celular", "tablet",
                "samsung", "xiaomi", "motorola", "realme", "pocophone",
                "oneplus", "huawei", "asus", "nokia", "oppo", "vivo")


def _shell_app():
    """Dispatch('Shell.Application') — so Windows com pywin32."""
    if sys.platform != "win32":
        return None
    try:
        import pythoncom                      # noqa: F401
        from win32com.client import Dispatch
        return Dispatch("Shell.Application")
    except Exception:
        return None


def phone_name_via_mtp(shell=None):
    """Nome do celular MTP conectado (None se nao houver).

    Varre o namespace 'Este Computador' (17) procurando pastas cujo nome
    pareca um aparelho Android. So leitura — nada e escrito no celular.
    """
    shell = shell or _shell_app()
    if shell is None:
        return None
    try:
        ns = shell.NameSpace(17)
        for item in ns.Items():
            try:
                if not item.IsFolder:
                    continue
                nome = (item.Name or "").lower()
                if any(h in nome for h in _PHONE_HINTS):
                    return item.Name
            except Exception:
                continue
    except Exception:
        return None
    return None
