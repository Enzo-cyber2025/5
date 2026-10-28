"""Resume o build do executável em JSON (convenção `.delivery/` do repositório).

O CI não consegue me mostrar os logs direto, então cada fase escreve em
`build.log` com marcadores `== FASE: nome ==` e este script transforma isso
num JSON versionado em `.delivery/raceai-exe-build.json`.
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import time


def read_log(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def split_phases(log: str) -> dict:
    phases = {}
    current = "preparação"
    phases[current] = []
    for line in log.splitlines():
        m = re.match(r"==\s*FASE:\s*(.+?)\s*==", line)
        if m:
            current = m.group(1).strip().lower()
            phases.setdefault(current, [])
            continue
        phases.setdefault(current, []).append(line)
    return {k: "\n".join(v).strip() for k, v in phases.items()}


def dir_size(path: str) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / (1024 * 1024)


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    repo = os.path.dirname(root)
    log_path = os.path.join(root, "build.log")
    log = read_log(log_path)
    phases = split_phases(log)

    dist = os.path.join(root, "dist", "RaceAI2D")
    exe = os.path.join(dist, "RaceAI2D.exe")
    console_exe = os.path.join(dist, "RaceAI2D-console.exe")
    package = os.path.join(root, "package")

    zips = []
    if os.path.isdir(package):
        for f in sorted(os.listdir(package)):
            p = os.path.join(package, f)
            zips.append({"arquivo": f, "mb": round(os.path.getsize(p) / (1024 * 1024), 1)})

    def failed(name: str) -> bool:
        txt = phases.get(name, "")
        return bool(re.search(r"(Traceback|FALHA|failed|Error:|error CS|exit code 1)",
                              txt, re.IGNORECASE))

    def ok(name: str, extra: bool = True) -> bool:
        txt = phases.get(name, "")
        if not txt.strip():
            return False                     # fase nem chegou a rodar
        return extra and not failed(name)

    status = {
        "dependências": ok("dependências"),
        "testes": ok("testes", "testes passaram" in phases.get("testes", "")),
        "build": os.path.isfile(exe),
        "smoke_test": ok("smoke test", "AUTOTESTE OK" in phases.get("smoke test", "")),
        "pacote": bool(zips),
    }

    versions = {}
    for key, pat in (("python", r"python (\S+)"), ("numpy", r"numpy (\S+)"),
                     ("pygame", r"pygame (\S+)"), ("torch", r"torch (\S+)"),
                     ("directml", r"DirectML ok: (.+)")):
        m = re.search(pat, phases.get("versões", "") + "\n" + phases.get("smoke test", ""))
        if m:
            versions[key] = m.group(1).strip()

    tests_txt = phases.get("testes", "")
    m = re.search(r"(\d+)/(\d+) testes passaram", tests_txt)
    tests = {"passaram": int(m.group(1)), "total": int(m.group(2))} if m else {}

    bench = []
    for line in phases.get("smoke test", "").splitlines():
        if re.search(r"(ms|\dx)\s", line) and ("cpu" in line.lower() or "dml" in line.lower()
                                               or "torch" in line.lower()):
            bench.append(line.strip())

    data = {
        "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "plataforma": f"{platform.system()} {platform.release()}",
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "commit": os.environ.get("GITHUB_SHA", ""),
        "branch": os.environ.get("GITHUB_REF_NAME", ""),
        "status": status,
        "sucesso": all(status.values()),
        "versões": versions,
        "testes": tests,
        "executável": {
            "principal": os.path.basename(exe),
            "existe": os.path.isfile(exe),
            "console": os.path.isfile(console_exe),
            "pasta_mb": round(dir_size(dist), 1) if os.path.isdir(dist) else 0.0,
        },
        "pacotes_zip": zips,
        "benchmark_linhas": bench[-6:],
        "fases": {k: v[-4000:] for k, v in phases.items()},
    }

    out_dir = os.path.join(repo, ".delivery")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "raceai-exe-build.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(json.dumps({k: data[k] for k in
                      ("sucesso", "status", "versões", "testes", "executável",
                       "pacotes_zip")}, indent=2, ensure_ascii=False))
    print(f"resumo em {os.path.relpath(out, repo)}")
    return 0 if data["sucesso"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
