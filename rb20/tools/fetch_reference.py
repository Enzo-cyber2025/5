"""
fetch_reference.py -- best-effort inspection of the external RB20 reference mod.

The user supplied https://modsfire.com/RcgUC30KVzcd5Nr?rf=39204 (a 126 MB
`redbull-rb20-f1.zip`, which REQUIRES CSP). This script runs on the GitHub
Actions runner (which has general internet access), downloads it if the host
allows it, and writes a STRUCTURE REPORT only.

STRICT RULES:
  * Nothing from the reference is ever copied into content/cars/arb_rb20/.
  * Nothing from the reference is committed or shipped in the ZIP.
  * All CSP-only files found are recorded so we can be sure NOT to use them.
  * Failure to download is non-fatal: the build continues with our own model.

The report is a build artifact, not a game file.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import struct
import urllib.parse
import urllib.request
import zipfile

PAGE = "https://modsfire.com/RcgUC30KVzcd5Nr?rf=39204"
CANDIDATES = [
    PAGE,
    PAGE + "&download=1",
    "https://modsfire.com/get-link/RcgUC30KVzcd5Nr",
    "https://modsfire.com/link/RcgUC30KVzcd5Nr",
    "https://modsfire.com/d/RcgUC30KVzcd5Nr",
]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
CSP_MARKERS = ("ext_config.ini", ".lua", "extension/", "data.acd",
               "extended-2", "extendedV", "REQUIRED_VERSION", "_emissive",
               "wing_controller.ini", "RainFX", "AC_RAIN")

# Licensed, actually-downloadable vanilla reference: Kunos' own F1 template,
# GPL-3.0. Only PATH NAMES are inspected, never file contents or binaries.
GH_REPO = "javirs200/acCar"
KUNOS_PREFIX = "EXAMPLE/formula_k/"


def get(url, timeout=90):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/zip,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.geturl()


def looks_like_archive(b):
    return b[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"Rar!", b"7z\xbc\xaf")


def find_links(html, base):
    out = []
    for m in re.finditer(r'(?:href|action|data-url)\s*=\s*["\']([^"\']+)',
                         html, re.I):
        u = urllib.parse.urljoin(base, m.group(1))
        if any(k in u.lower() for k in ("download", "get-link", "/d/",
                                        ".zip", "/file/", "generate")):
            out.append(u)
    return list(dict.fromkeys(out))[:12]


def kn5_info(blob):
    if len(blob) < 12 or blob[:6] != b"sc6969":
        return None
    (ver,) = struct.unpack_from("<i", blob, 6)
    return {"version": ver, "bytes": len(blob)}


def inspect_zip(blob, temp_dir):
    info = {"archive": "zip", "file_count": 0, "top_level": [],
            "car_folders": [], "kn5": [], "csp_markers": [],
            "sample_files": [], "data_files": []}
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = z.namelist()
    info["file_count"] = len(names)
    info["top_level"] = sorted({n.split("/")[0] for n in names if "/" in n})[:30]
    info["car_folders"] = sorted({"/".join(n.split("/")[:4]) for n in names
                                  if "/cars/" in n})[:20]
    info["csp_markers"] = sorted({m for m in CSP_MARKERS
                                  if any(m.lower() in n.lower() for n in names)})
    info["sample_files"] = [n for n in names if n.count("/") <= 4][:120]
    info["data_files"] = sorted({n.split("/")[-1] for n in names
                                 if "/data/" in n})[:80]
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for n in names:
            if not n.lower().endswith(".kn5"):
                continue
            try:
                head = z.read(n)[:16]
                k = kn5_info(head + b"\0" * 32)
                if k:
                    k["name"] = n
                    k["bytes"] = z.getinfo(n).file_size
                    info["kn5"].append(k)
            except Exception:
                pass
            if len(info["kn5"]) >= 12:
                break
    return info


def kunos_structure():
    """Fetch the real vanilla F1 car tree (path names only) as a licensed
    structural reference. This always works from an Actions runner."""
    out = {"repo": GH_REPO, "license": "GPL-3.0", "fetched": False,
           "default_branch": "", "file_count": 0, "files": [],
           "directories": [], "data_files": [], "kn5": [],
           "animations": [], "csp_markers": [], "reason": ""}
    try:
        meta, _ = get("https://api.github.com/repos/" + GH_REPO, timeout=30)
        branch = json.loads(meta)["default_branch"]
        out["default_branch"] = branch
        raw, _ = get("https://api.github.com/repos/%s/git/trees/%s?recursive=1"
                     % (GH_REPO, branch), timeout=60)
        items = json.loads(raw)["tree"]
        files = sorted(i["path"] for i in items
                       if i["type"] == "blob" and i["path"].startswith(KUNOS_PREFIX))
        out["files"] = [f[len(KUNOS_PREFIX):] for f in files]
        out["file_count"] = len(files)
        out["directories"] = sorted({f.rsplit("/", 1)[0] for f in out["files"]
                                     if "/" in f} | {"<raiz>"})
        out["data_files"] = sorted(f.split("/")[-1] for f in out["files"]
                                   if f.startswith("data/"))
        out["kn5"] = [f for f in out["files"] if f.endswith(".kn5")]
        out["animations"] = [f for f in out["files"]
                             if f.startswith("animations/")]
        out["csp_markers"] = sorted({m for m in CSP_MARKERS
                                     if any(m.lower() in f.lower()
                                            for f in out["files"])})
        out["fetched"] = True
    except Exception as e:
        out["reason"] = str(e)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=PAGE)
    ap.add_argument("--out", required=True)       # JSON report (artifact)
    ap.add_argument("--markdown", default="")     # optional human summary
    args = ap.parse_args()

    report = {"requested_url": args.url, "status": "unavailable",
              "reason": "", "reference_only": True,
              "copied_into_mod": False, "requires_csp": True,
              "policy": ("External mod is used ONLY to inspect folder/file "
                         "structure and node naming. No mesh, texture, sound, "
                         "config or binary from it is shipped or committed. "
                         "All CSP-only files are explicitly excluded.")}

    urls = [args.url] + [u for u in CANDIDATES if u != args.url]
    html_pages = []
    blob = None
    got_from = None
    for u in urls:
        try:
            body, final = get(u)
            if looks_like_archive(body):
                blob, got_from = body, final
                break
            if b"<html" in body[:2000].lower() or b"<!doctype" in body[:2000].lower():
                html_pages.append((final, body.decode("utf-8", "ignore")))
        except Exception as e:
            report.setdefault("attempt_errors", []).append("%s: %s" % (u, e))

    # Follow any download-looking links found on the ModsFire page(s).
    if blob is None:
        extra = []
        for base, html in html_pages:
            extra += find_links(html, base)
        for u in list(dict.fromkeys(extra))[:10]:
            try:
                body, final = get(u, timeout=60)
                if looks_like_archive(body):
                    blob, got_from = body, final
                    break
            except Exception as e:
                report.setdefault("attempt_errors", []).append("%s: %s" % (u, e))

    if blob is not None:
        try:
            if blob[:2] == b"PK":
                report["status"] = "inspected"
                report["download_url"] = got_from
                report["archive_bytes"] = len(blob)
                report["structure"] = inspect_zip(blob, os.path.dirname(args.out))
            else:
                report["status"] = "archive_format_unsupported"
                report["archive_bytes"] = len(blob)
                report["reason"] = ("Reference is RAR/7z; no archive tool in "
                                    "this step. Structure not inspected.")
        except Exception as e:
            report["status"] = "inspection_failed"
            report["reason"] = str(e)
    else:
        report["reason"] = ("ModsFire serves a two-step/premium 'Generate Link' "
                            "page; no direct ZIP could be fetched from the "
                            "runner. This step is best-effort and non-blocking. "
                            "The build does NOT depend on it.")

    report["kunos_reference"] = kunos_structure()

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")

    if args.markdown:
        lines = ["# Referência externa (somente inspeção)", "",
                 "- URL: `%s`" % args.url,
                 "- Status: **%s**" % report["status"],
                 "- Exige CSP: **sim** (por isso nenhum arquivo dele é usado).",
                 "- Copiado para o mod: **não**.", "",
                 report["policy"], "",
                 "- Motivo: %s" % (report.get("reason") or "n/a")]
        st = report.get("structure")
        if st:
            lines += ["", "## Estrutura observada no mod externo", "",
                      "- Arquivos: %d" % st["file_count"],
                      "- Pastas de carro: %s" % ", ".join(st["car_folders"]),
                      "- Arquivos em `data/`: %s" % ", ".join(st["data_files"][:40]),
                      "- Marcadores CSP encontrados: %s" %
                      (", ".join(st["csp_markers"]) or "nenhum"),
                      "- KN5: %s" % json.dumps(st["kn5"][:6])]

        ku = report["kunos_reference"]
        lines += ["", "---", "",
                  "## Estrutura real de referência: Kunos `formula_k`", "",
                  "Fonte licenciada e **efetivamente consultada** via API do "
                  "GitHub: `%s` (branch `%s`, %s). Apenas **nomes de "
                  "arquivos/pastas** são lidos - nenhum binário, textura, som "
                  "ou `.kn5` é copiado." %
                  (ku["repo"], ku["default_branch"] or "?", ku["license"]), ""]
        if ku["fetched"]:
            lines += ["- **%d arquivos** em `%s`" % (ku["file_count"], KUNOS_PREFIX),
                      "- Pastas: %s" % ", ".join("`%s`" % d for d in ku["directories"]),
                      "- KN5: %s" % ", ".join("`%s`" % f for f in ku["kn5"]),
                      "- `animations/`: %s" %
                      ", ".join("`%s`" % f.split("/")[-1] for f in ku["animations"]),
                      "- Marcadores CSP: %s" %
                      (", ".join(ku["csp_markers"]) or "**nenhum** (100% vanilla)"),
                      "", "### Árvore completa (nomes relativos)", "", "```text"]
            lines += ku["files"]
            lines += ["```", "",
                      "O nosso `content/cars/arb_rb20/` espelha essa árvore. "
                      "Diferenças deliberadas: sem `driver_base_pos.knh`, "
                      "`data/flames.ini`/`texture/flames/*`, "
                      "`data/analog_instruments.ini` e `animations/shift.ksanim` "
                      "(formatos auto-carregados que não podemos validar sem o "
                      "AC e que foram removidos na correção de crash) e sem o "
                      "banco FMOD `.bank` proprietário. Nenhum arquivo CSP.", ""]
        else:
            lines += ["- Falha ao consultar a API: %s" % ku["reason"], ""]
        with open(args.markdown, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    print("reference report:", report["status"], "-", report.get("reason", ""))
    print("  copied_into_mod =", report["copied_into_mod"])


if __name__ == "__main__":
    main()
