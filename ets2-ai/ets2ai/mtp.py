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


# --------------------------------------------------------------------------- #
# PONTE POR ARQUIVOS (MTP): a IA roda no APK, sem porta TCP e sem Depuracao
# --------------------------------------------------------------------------- #
class MtpError(Exception):
    pass


class ShellMtpStorage:
    """Pasta do celular acessivel pelo PC via MTP (Shell COM) — o mesmo
    canal que o Explorador de Arquivos usa para copiar musicas/fotos.
    Nenhuma porta TCP e aberta; nada e instalado no celular."""

    def __init__(self, sub_path=("ETS2AI",), shell=None):
        self.shell = shell or _shell_app()
        if self.shell is None:
            raise MtpError("MTP indisponivel (so Windows com pywin32)")
        self.folder = self._resolve(sub_path)

    def _resolve(self, parts):
        ns = self.shell.NameSpace(17)             # Este Computador
        phone = None
        for it in ns.Items():
            try:
                if it.IsFolder and any(h in (it.Name or "").lower()
                                       for h in _PHONE_HINTS):
                    phone = it
                    break
            except Exception:
                continue
        if phone is None:
            raise MtpError("celular MTP nao encontrado (conecte o cabo e "
                           "escolha 'Transferir arquivos')")
        folder = self.shell.NameSpace(phone.Self.Path)
        if folder is None:
            raise MtpError("armazenamento do celular inacessivel")
        for p in parts:
            nxt = None
            for it in folder.Items():
                if (it.Name or "").lower() == p.lower():
                    nxt = it
                    break
            if nxt is None:
                try:
                    folder.NewFolder(p)
                    continue
                except Exception:
                    raise MtpError(f"pasta '{p}' inacessivel no celular")
            sub = self.shell.NameSpace(nxt.Self.Path)
            if sub is None:
                raise MtpError(f"sem acesso a '{p}'")
            folder = sub
        return folder

    def write(self, name, text):
        """Copia um arquivo do PC para o celular (sobrescreve em silencio)."""
        import tempfile
        tmp = Path(tempfile.gettempdir()) / f"ets2ai_mtp_{name}"
        tmp.write_text(text, encoding="utf-8")
        self.folder.CopyHere(str(tmp), 4 | 16 | 512)   # no-UI, yes-to-all

    def read(self, name, seen_mark=None, timeout=1.2):
        """Le um arquivo do celular (retorna (texto, marca) ou (None, marca)
        se inalterado). marca = ModifyDate do item (mudou = arquivo novo)."""
        import tempfile
        import time as _time
        item = None
        for it in self.folder.Items():
            if (it.Name or "").lower() == name.lower():
                item = it
                break
        if item is None:
            return None, seen_mark
        try:
            mark = str(item.ModifyDate)
        except Exception:
            mark = ""
        if seen_mark is not None and mark == seen_mark:
            return None, mark          # nao mudou desde a ultima leitura
        d = Path(tempfile.gettempdir()) / "ets2ai_mtp_in"
        d.mkdir(exist_ok=True)
        dst = d / name
        if dst.exists():
            dst.unlink()
        dst_folder = self.shell.NameSpace(str(d))
        if dst_folder is None:
            return None, mark
        dst_folder.CopyHere(item, 4 | 16 | 512)
        t0 = _time.monotonic()
        while not dst.exists() and _time.monotonic() - t0 < timeout:
            _time.sleep(0.05)
        if not dst.exists():
            return None, mark
        try:
            return dst.read_text(encoding="utf-8", errors="replace"), mark
        except Exception:
            return None, mark


class MtpChannel:
    """Canal PC -> APK por arquivos no celular (MTP).

    Protocolo (uma linha por arquivo, sobrescrito a cada ciclo):
      estado.txt  (PC  -> celular): S,<seq>,<campos do protocolo S...>
      comando.txt (celular -> PC) : C,<seq>,<steer>,<throttle>,<brake>
    <seq> casa pergunta e resposta. Storage injetavel para testes.
    """

    STATE_FILE = "estado.txt"
    CMD_FILE = "comando.txt"

    def __init__(self, storage=None):
        self.storage = storage          # None = MTP real (so Windows)
        self._seq = 0
        self._cmd = None                # (steer, thr, brk, seq_answered)
        self._cmd_t = 0.0
        self._cmd_mark = None
        self._last_send = 0.0
        self._last_poll = 0.0

    def open(self):
        if self.storage is None:
            self.storage = ShellMtpStorage()
        return True

    # ---- PC -> celular ----
    def send_state(self, fields, min_period=0.30):
        """fields: valores do protocolo S (speed, offset, hdg, curvs, ...).
        Throttle interno: MTP nao gosta de dezenas de gravacoes por segundo."""
        import time as _time
        now = _time.monotonic()
        if now - self._last_send < min_period and self._seq > 0:
            return self._seq
        self._last_send = now
        self._seq += 1
        line = "S," + str(self._seq) + "," + ",".join(
            f"{v:.4f}" if isinstance(v, float) else
            (",".join(f"{c:.6f}" for c in v) if isinstance(v, (list, tuple))
             else str(v)) for v in fields)
        self.storage.write(self.STATE_FILE, line + "\n")
        return self._seq

    # ---- celular -> PC ----
    def poll_cmd(self, min_period=0.15):
        import time as _time
        now = _time.monotonic()
        if now - self._last_poll < min_period:
            return self._cmd
        self._last_poll = now
        text, mark = self.storage.read(self.CMD_FILE, self._cmd_mark)
        if not text:
            return self._cmd
        self._cmd_mark = mark
        try:
            parts = text.strip().split(",")
            if parts[0] == "C" and len(parts) >= 5:
                self._cmd = (float(parts[2]), float(parts[3]),
                             float(parts[4]), int(parts[1]))
                self._cmd_t = now
        except (ValueError, IndexError):
            pass
        return self._cmd

    def fresh_cmd(self, max_age=2.0, max_lag=3):
        """Comando valido: recente e resposta a um estado nao muito antigo."""
        import time as _time
        if self._cmd is None:
            return None
        steer, thr, brk, seq = self._cmd
        if _time.monotonic() - self._cmd_t > max_age:
            return None
        if self._seq - seq > max_lag:
            return None
        return (steer, thr, brk)
