#!/usr/bin/env python3
"""Baixa TRACES REAIS de ETS2 do Hugging Face e calibra a IA (job traces-hf).

Dataset publico: yinhuankuang/rl-game-traces-euro-truck-simulator-2
(cada sessao tem macroEvents.jsonl com os eventos de teclado/mouse de
um humano jogando ETS2). Aqui nos:
  1. baixamos o macroEvents.jsonl de algumas sessoes (~8 MB cada);
  2. extraimos o timing REAL (holds por tecla, rajadas de Enter, gaps);
  3. salvamos ets2ai/dados/traces-hf.json (a IA usa via ets2ai.traces);
  4. descobrimos o schema do parquet grande da sessao (leitura REMOTA
     por range — so o footer + a menor coluna, sem baixar 4 GB);
  5. printamos tudo no log do job (descoberta iterativa).

Deterministico: sem timestamps no JSON (evita loop de commits [skip ci]).
"""

import json
import pathlib
import sys
import urllib.parse
import urllib.request

AQUI = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))

from ets2ai import traces  # noqa: E402

BASE = ("https://huggingface.co/datasets/yinhuankuang/"
        "rl-game-traces-euro-truck-simulator-2/resolve/main")
SESSOES = [
    "2026_05_03_12_23_04",
    "2026_05_03_15_19_25",
    "2026_05_03_17_12_22",
    "2026_05_03_20_32_57",
    "2026_05_04_06_19_43",
    "2026_05_04_07_58_00",
]
SAIDA = AQUI.parent / "ets2ai" / "dados" / traces.ARQUIVO
CACHE = pathlib.Path("/tmp/traces-hf")


def baixar(url, destino, tentativas=3):
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.is_file() and destino.stat().st_size > 0:
        return destino
    for i in range(tentativas):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "ets2-ai-traces/1.0"})
            with urllib.request.urlopen(req, timeout=180) as r, \
                    open(destino, "wb") as f:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
            return destino
        except Exception as e:  # noqa: BLE001 — rede e CDN, tenta de novo
            print(f"[traces] tentativa {i + 1}/{tentativas} falhou: {e}")
    raise RuntimeError(f"nao consegui baixar {url}")


def carregar_eventos():
    eventos = []
    for s in SESSOES:
        arq = baixar(f"{BASE}/{s}/macroEvents.jsonl", CACHE / f"{s}.jsonl")
        with open(arq, encoding="utf-8", errors="replace") as f:
            evs = traces.parse_eventos(f)
        print(f"[traces] {s}: {len(evs)} eventos "
              f"({sum(1 for e in evs if e.get('keyCode') is not None)} teclado)")
        eventos += evs
    return eventos


class HTTPRange:
    """File-like seekable sobre HTTP por Range (p/ ler footer do parquet)."""

    def __init__(self, url):
        self.url = url
        self.pos = 0
        self.len = None
        self.closed = False   # pyarrow exige (run 38174907081)

    def _head_len(self):
        req = urllib.request.Request(self.url, method="HEAD",
                                     headers={"User-Agent": "ets2-ai/1.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return int(r.headers["Content-Length"])

    def seekable(self):
        return True

    def readable(self):
        return True

    def seek(self, p, whence=0):
        if self.len is None:
            self.len = self._head_len()
        if whence == 0:
            self.pos = p
        elif whence == 2:
            self.pos = self.len + p
        else:
            self.pos += p
        return self.pos

    def tell(self):
        return self.pos

    def read(self, n=-1):
        if self.len is None:
            self.len = self._head_len()
        if n is None or n < 0:
            n = self.len - self.pos
        if n <= 0 or self.pos >= self.len:
            return b""
        req = urllib.request.Request(
            self.url, headers={"Range": f"bytes={self.pos}-{self.pos + n - 1}",
                               "User-Agent": "ets2-ai/1.0"})
        with urllib.request.urlopen(req, timeout=180) as r:
            d = r.read()
        self.pos += len(d)
        return d


def descobrir_parquet():
    """Le SO o footer do parquet de 4 GB (schema + contagens) por range."""
    try:
        import pyarrow.parquet as pq
    except ImportError:
        print("[parquet] pyarrow ausente — schema nao lido nesta run")
        return
    s = SESSOES[0]
    nome = urllib.parse.quote(f"{s}_欧洲卡车模拟2_刘靖.parquet")
    url = f"{BASE}/{s}/{nome}"
    try:
        pf = pq.ParquetFile(HTTPRange(url))
        md = pf.metadata
        print(f"[parquet] {md.num_rows} linhas, {md.num_columns} colunas, "
              f"{md.num_row_groups} row groups")
        print("[parquet] colunas:")
        esq = pf.schema_arrow
        menor, tam_menor = None, None
        for i, campo in enumerate(esq):
            print(f"  {campo.name}: {campo.type}")
            try:
                tam = md.row_group(0).column(i).total_compressed_size
                if tam_menor is None or tam < tam_menor:
                    menor, tam_menor = i, tam
            except Exception:  # noqa: BLE001
                pass
        if menor is not None and tam_menor <= 8 << 20:
            print(f"[parquet] amostra da menor coluna "
                  f"({esq[menor].name}, {tam_menor} B):")
            tab = pf.read_row_group(0, columns=[esq[menor].name])
            for v in tab.column(0).to_pylist()[:5]:
                print(f"  {str(v)[:200]}")
    except Exception as e:  # noqa: BLE001 — descoberta, nao derruba o job
        print(f"[parquet] leitura remota falhou: {e}")


def main():
    eventos = carregar_eventos()
    cal = traces.calibrar(eventos)
    print(f"[traces] TOTAL: {cal['n_eventos']} eventos, "
          f"{cal['n_teclado']} de teclado, tipos={cal['tipos']}")
    print("[traces] top teclas (codigo: n, hold p10/p50/p90 s):")
    for kc, info in sorted(cal["teclas"].items(),
                           key=lambda kv: -kv[1]["n"])[:20]:
        print(f"  {kc:>4}: n={info['n']:>5}  "
              f"{info['hold_p10']:.3f}/{info['hold_p50']:.3f}/"
              f"{info['hold_p90']:.3f}")
    print(f"[traces] hold p50 global: {cal['hold_p50_global']} s | "
          f"menu gap p50: {cal['menu_gap_p50']} s | "
          f"janelas de Enter: {cal['n_janelas_enter']}")
    for j in cal["enter_janelas_exemplo"][:5]:
        print(f"[traces] rajada de Enter: {j}")
    antiguo = SAIDA.read_text(encoding="utf-8") if SAIDA.is_file() else None
    novo = json.dumps(cal, sort_keys=True, ensure_ascii=False, indent=1)
    if novo.strip() == (antiguo or "").strip():
        print("[traces] calibracao inalterada — nada a committar")
    else:
        traces.salvar(cal, SAIDA)
        print(f"[traces] calibracao salva em {SAIDA} "
              f"({len(novo)} bytes) — o job committa")
    descobrir_parquet()
    print("[traces] TAP_HOLD da IA agora: "
          f"{traces.tap_hold(traces.carregar() or cal)} s | "
          f"MENU_GAP: {traces.menu_gap(traces.carregar() or cal)} s")


if __name__ == "__main__":
    main()
