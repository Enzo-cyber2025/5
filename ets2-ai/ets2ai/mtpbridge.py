"""IA no CELULAR sem Depuracao USB e SEM porta TCP: canal por ARQUIVOS.

O cabo em modo 'Transferir arquivos' (MTP) deixa o PC ler/gravar arquivos
na pasta Download do celular (COM do Windows — nenhum servidor, nenhuma
porta). Protocolo de arquivos com numeros de sequencia (nomes unicos por
troca = zero problema de cache do MTP):

  PC  -> celular:  Download/ets2ai-s{seq}.txt   (linha S: estado)
  celular -> PC:   Download/ets2ai-c{seq}.txt   (linha C: comando da IA)

O APK roda a inferencia (mesma rede) e responde; o PC injeta o ultimo
comando recebido a 20 Hz entre atualizacoes (~2-4 Hz via arquivo). Se o
comando ficar velho, o loop de pratica cai na IA local do PC (fallback ja
existente). Interface identica a PhoneLink: send_fields()/wait_cmd().
"""
import os
import sys
import tempfile
import threading
import time

PREFIX_S = "ets2ai-s"
PREFIX_C = "ets2ai-c"


class _ComMtp:
    """Acesso MTP via Shell COM (so Windows)."""

    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("MTP exige Windows")
        import pythoncom                      # noqa: F401
        from win32com.client import Dispatch
        pythoncom.CoInitialize()
        self.shell = Dispatch("Shell.Application")
        self.download = None

    def _storage_folders(self):
        """Pastas de armazenamento do celular (namespace 'Este Computador')."""
        ns = self.shell.NameSpace(17)
        for item in ns.Items():
            try:
                if not item.IsFolder:
                    continue
                nome = (item.Name or "").lower()
                hints = ("phone", "android", "mtp", "celular", "samsung",
                         "xiaomi", "motorola", "realme", "pocophone",
                         "oneplus", "huawei", "asus", "nokia", "oppo",
                         "vivo", "tablet")
                if any(h in nome for h in hints):
                    yield self.shell.NameSpace(item)
            except Exception:
                continue

    def open_download(self):
        """Pasta Download do primeiro celular MTP conectado."""
        for storage in self._storage_folders():
            for sub in storage.Items():
                try:
                    if sub.IsFolder and sub.Name.lower() == "download":
                        self.download = self.shell.NameSpace(sub)
                        return self.download is not None
                except Exception:
                    continue
        return False

    def push(self, name, text):
        """Grava um arquivo texto no celular (CopyHere + espera confirmar)."""
        tmpdir = tempfile.mkdtemp(prefix="ets2ai-mtp-")
        tmp = os.path.join(tmpdir, name)
        with open(tmp, "w", encoding="ascii", errors="replace") as f:
            f.write(text)
        self.download.CopyHere(tmp)
        limite = time.monotonic() + 8.0
        while time.monotonic() < limite:
            if self.download.ParseName(name) is not None:
                return True
            time.sleep(0.05)
        return False

    def pull(self, name, timeout_s):
        """Le um arquivo do celular (CopyHere para temp + le). None se nao
        aparecer em timeout_s."""
        limite = time.monotonic() + timeout_s
        while time.monotonic() < limite:
            item = self.download.ParseName(name)
            if item is not None:
                tmpdir = tempfile.mkdtemp(prefix="ets2ai-mtp-")
                dst = os.path.join(tmpdir, name)
                self.download.CopyHere(item)
                t2 = time.monotonic() + 8.0
                while time.monotonic() < t2:
                    if os.path.exists(dst):
                        try:
                            with open(dst, encoding="ascii",
                                      errors="replace") as f:
                                return f.read().strip()
                        except OSError:
                            pass
                    time.sleep(0.05)
                return None
            time.sleep(0.06)
        return None


class MtpBridge(threading.Thread):
    """Canal PC<->celular por arquivos MTP — IA roda no CELULAR.

    Mesma interface do PhoneLink: start()/send_fields(**kw)/wait_cmd(t)/
    connected/latest_cmd/rtt_ms. Sem porta TCP nenhuma; sem Depuracao USB.
    """

    def __init__(self, exchange_hz=4.0):
        super().__init__(daemon=True)
        self.connected = False
        self.latest_cmd = None
        self.last_recv = 0.0
        self.rtt_ms = -1.0
        self._send_hz = exchange_hz
        self._pending = None          # linha S aguardando troca
        self._seq = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._mtp = None

    # ---------------- interface PhoneLink ---------------- #
    def send_fields(self, speed, offset, hdg, curvs, limit, fuel, fatigue,
                    job_km, radar=150.0, ts=None):
        ts = ts if ts is not None else time.time()
        linha = ("S," + ",".join([
            f"{speed:.4f}", f"{offset:.4f}", f"{hdg:.4f}",
            ",".join(f"{(0.0 if c is None else float(c)):.6f}"
                     for c in curvs),
            f"{limit:.2f}", f"{fuel:.4f}", f"{fatigue:.4f}",
            f"{job_km:.4f}", f"{radar:.1f}", f"{ts * 1000.0:.0f}"]) + "\n")
        with self._lock:
            self._pending = linha

    def wait_cmd(self, timeout=0.30):
        """Ultimo comando (steer, throttle, brake) se fresco; None cai no
        fallback local do PC."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if self.latest_cmd is not None and \
                    time.time() - self.last_recv < 1.2:
                return self.latest_cmd
            time.sleep(0.03)
        return None

    def stop(self):
        self._stop.set()

    # ---------------- laco de troca ---------------- #
    def run(self):
        try:
            self._mtp = _ComMtp()
            if not self._mtp.open_download():
                raise RuntimeError("celular MTP nao encontrado (conecte o "
                                   "cabo em modo 'Transferir arquivos')")
            self.connected = True
        except Exception:
            self.connected = False
            return
        period = 1.0 / max(0.5, self._send_hz)
        while not self._stop.is_set():
            t0 = time.monotonic()
            with self._lock:
                linha = self._pending
                self._pending = None
            if linha is not None:
                self._seq += 1
                try:
                    ok = self._mtp.push(f"{PREFIX_S}{self._seq}.txt", linha)
                    if ok:
                        resp = self._mtp.pull(f"{PREFIX_C}{self._seq}.txt",
                                              timeout_s=period)
                        if resp and resp.startswith("C,"):
                            p = resp.split(",")
                            if len(p) >= 4:
                                self.latest_cmd = (float(p[1]), float(p[2]),
                                                   float(p[3]))
                                self.last_recv = time.time()
                                self.rtt_ms = max(
                                    0.0, 1000.0 * (period -
                                                   (time.monotonic() - t0)))
                except Exception:
                    self.connected = False
                    return
            # cadencia (troca leva o proprio tempo; so evita ferver)
            resto = period - (time.monotonic() - t0)
            if resto > 0:
                time.sleep(resto)
