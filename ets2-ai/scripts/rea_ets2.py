#!/usr/bin/env python3
"""REA (Reverse Engineer Anything) — engenharia reversa dos binarios REAIS
da DEMO OFICIAL do ETS2 (baixada e instalada pelo CI, nunca executada aqui).

Extrai e CATEGORIZA (tudo estatico, sem rodar o jogo):

  1. strings ASCII e UTF-16LE dos 2 exes (win_x64 e win_x86);
  2. opcoes de linha de comando ("-nointro", "-rdevice", ...);
  3. nomes de canais do SDK de telemetria ("truck.*", "game.*", "job.*",
     "navigation.*", "info.*") — o que a DLL universal precisa registrar;
  4. nome da memoria compartilhada ("SCSTelemetry") e caminho de plugins;
  5. renderers (d3d11/dxgi/opengl32/vulkan) presentes nos binarios;
  6. formato dos arquivos .scs (sao ZIPs) — entradas, compressao;
  7. DLLs de telemetria do banco (exports via dumpbin, se houver).

Saida: ci-logs/rea/relatorio.md + achados.json (commitados no repo).

Uso:  python rea_ets2.py --demo C:\\ets2demo --out ci-logs/rea
"""
import argparse
import json
import re
import zipfile
from collections import Counter
from pathlib import Path

MIN_STR = 6


def extract_strings(data: bytes):
    """ASCII e UTF-16LE imprimiveis >= MIN_STR chars."""
    ascii_re = re.compile(rb"[\x20-\x7e]{%d,}" % MIN_STR)
    utf16_re = re.compile(rb"(?:[\x20-\x7e]\x00){%d,}" % MIN_STR)
    out = set()
    for m in ascii_re.finditer(data):
        out.add(m.group().decode("ascii", "replace"))
    for m in utf16_re.finditer(data):
        out.add(m.group().decode("utf-16-le", "replace"))
    return out


def categorize(strings):
    """Classifica as strings em categorias ACIONAVEIS pelo projeto."""
    cats = {}

    # opcoes de linha de comando: "-palavra" isolada
    opts = set()
    for s in strings:
        for m in re.finditer(r"(?<![\w])-[a-z][a-z0-9_]{2,24}\b", s):
            opts.add(m.group())
    cats["opcoes_linha_de_comando"] = sorted(opts)

    # canais do SDK de telemetria
    canais = set()
    for s in strings:
        for m in re.finditer(
                r"\b(truck|game|job|navigation|info|player|trailer|hshifter)"
                r"\.[a-z0-9_.]{2,40}\b", s):
            canais.add(m.group())
    cats["canais_sdk_telemetria"] = sorted(canais)

    # memoria compartilhada + plugins
    cats["memoria_compartilhada"] = sorted(
        s for s in strings if "SCSTelemetry" in s or "CreateFileMapping" in s)
    cats["plugins"] = sorted(
        s for s in strings if re.search(r"plugin", s, re.I))[:80]

    # renderers / graficos
    rend = set()
    for s in strings:
        for tok in ("d3d11", "d3d9", "dxgi", "opengl32", "wgl", "vulkan",
                    "glcore", "-rdevice", "llvmpipe", "lavapipe", "directx"):
            if tok in s.lower():
                rend.add(s.strip()[:120])
    cats["renderers_graficos"] = sorted(rend)[:120]

    # versoes embutidas
    vers = set()
    for s in strings:
        for m in re.finditer(r"\b1\.\d{1,2}\.\d{1,2}(\.\d)?[a-z]?\b", s):
            vers.add(m.group())
    cats["versoes_embutidas"] = sorted(vers)[:60]

    # Discord/steam/online — contexto geral
    cats["steam_drm"] = sorted(
        s for s in strings if re.search(r"steam_api|SteamAPI|app_id", s)
    )[:40]

    return cats


def analyze_scs(demo: Path):
    """Arquivos .scs sao arquivos ZIP — documenta o formato."""
    out = []
    for scs in sorted(demo.glob("*.scs")) + sorted(demo.glob("base/*.scs")):
        try:
            with zipfile.ZipFile(scs) as z:
                names = z.namelist()
                comp = Counter(i.compress_type for i in z.infolist())
                sample = [n for n in names[:24]]
                out.append({
                    "arquivo": scs.name,
                    "tamanho_mb": round(scs.stat().st_size / 1e6, 1),
                    "entradas": len(names),
                    "compressao": {"0=store": comp.get(0, 0),
                                   "8=deflate": comp.get(8, 0)},
                    "amostra_de_pastas": sorted({
                        n.split("/")[0] for n in names if "/" in n})[:20],
                    "primeiros_arquivos": sample,
                })
        except Exception as e:
            out.append({"arquivo": scs.name, "erro": str(e)[:120]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", required=True, help="pasta do jogo instalado")
    ap.add_argument("--out", required=True, help="pasta do relatorio")
    ap.add_argument("--max-md", type=int, default=60,
                    help="max de itens por categoria no relatorio")
    args = ap.parse_args()

    demo = Path(args.demo)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    exes = {
        "x64": demo / "bin" / "win_x64" / "eurotrucks2.exe",
        "x86": demo / "bin" / "win_x86" / "eurotrucks2.exe",
    }
    achados = {"exes": {}, "scs": [], "categorias": {}}
    all_strings = set()

    for tag, exe in exes.items():
        if not exe.exists():
            achados["exes"][tag] = {"ausente": True}
            continue
        data = exe.read_bytes()
        strs = extract_strings(data)
        all_strings |= strs
        achados["exes"][tag] = {
            "tamanho_mb": round(len(data) / 1e6, 1),
            "strings_extraidas": len(strs),
        }
        print(f"[rea] {tag}: {len(data)/1e6:.1f} MB, {len(strs):,} strings")

    achados["categorias"] = categorize(all_strings)
    achados["scs"] = analyze_scs(demo)

    (outdir / "achados.json").write_text(
        json.dumps(achados, indent=1, ensure_ascii=False), encoding="utf-8")

    # ---------------- relatorio.md ----------------
    md = ["# Engenharia reversa (REA) — DEMO OFICIAL do ETS2",
          "",
          "Analise ESTATICA dos binarios reais (o jogo nao foi executado).",
          "Fonte: instalador oficial SCS (AppID 231120).", ""]
    md += ["## Exes", "", "| exe | tamanho | strings |", "|---|---|---|"]
    for tag, info in achados["exes"].items():
        if "ausente" in info:
            md.append(f"| {tag} | (ausente) | - |")
        else:
            md.append(f"| {tag} | {info['tamanho_mb']} MB | "
                      f"{info['strings_extraidas']:,} |")

    titulos = {
        "opcoes_linha_de_comando": "Opcoes de linha de comando (candidatas)",
        "canais_sdk_telemetria": "Canais do SDK de telemetria no binario",
        "memoria_compartilhada": "Memoria compartilhada / mapping",
        "plugins": "Strings com 'plugin'",
        "renderers_graficos": "Renderers e graficos",
        "versoes_embutidas": "Versoes embutidas",
        "steam_drm": "Steam / DRM",
    }
    for cat, titulo in titulos.items():
        itens = achados["categorias"].get(cat, [])[:args.max_md]
        md += ["", f"## {titulo} ({len(achados['categorias'].get(cat, []))})",
               ""]
        if not itens:
            md.append("(nada encontrado)")
        for it in itens:
            md.append(f"- `{it}`")

    md += ["", "## Arquivos .scs (formato ZIP)", ""]
    if achados["scs"]:
        md.append("| arquivo | MB | entradas | compressao | pastas |")
        md.append("|---|---|---|---|---|")
        for s in achados["scs"]:
            if "erro" in s:
                md.append(f"| {s['arquivo']} | ERRO: {s['erro']} | | | |")
                continue
            pastas = ", ".join(s["amostra_de_pastas"][:8])
            md.append(f"| {s['arquivo']} | {s['tamanho_mb']} | "
                      f"{s['entradas']:,} | {s['compressao']} | {pastas} |")
    else:
        md.append("(nenhum .scs encontrado)")

    (outdir / "relatorio.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"[rea] relatorio: {outdir / 'relatorio.md'}")
    print(f"[rea] opcoes: {len(achados['categorias'].get('opcoes_linha_de_comando', []))} | "
          f"canais: {len(achados['categorias'].get('canais_sdk_telemetria', []))} | "
          f"SCSTelemetry: "
          f"{len(achados['categorias'].get('memoria_compartilhada', []))}")


if __name__ == "__main__":
    main()
