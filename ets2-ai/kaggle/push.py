#!/usr/bin/env python3
"""Push the training kernel to Kaggle, wait, download and validate output.

Runs INSIDE GitHub Actions with the repo checked out. Credentials come from
the repository secrets KAGGLE_USERNAME / KAGGLE_KEY (never from chat, never
committed). If the secrets are not configured the script exits with code 2
and the workflow shows a warning and stays green (local training in
train-verify remains the source of truth).

Flow:
  1. build kernel.py (same code/seed as repo) -> .cache/kaggle-kernel/
  2. kaggle kernels push
  3. poll kaggle kernels status until COMPLETE/ERROR (default timeout 900 s)
  4. kaggle kernels output -> .cache/kaggle-out/
  5. quality gates on the Kaggle-trained weights (same as local CI)
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

SLUG_SUFFIX = "ets2ai-train"


_user = ["enzoaimv"]


def sh(*args, **kw):
    print("$", " ".join(str(a) for a in args), flush=True)
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, **kw)


def _discover_username():
    """Username da conta do token (CLI 2.x autentica sem username, mas o push
    exige owner/slug). Descoberta: kernels list --mine (o owner aparece no ref
    de cada kernel)."""
    import re
    r = sh("kaggle", "kernels", "list", "--mine", "--page-size", "20")
    out = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)\s", out)
    if m:
        print(f"[kaggle] username descoberto via kernels list --mine: {m.group(1)}")
        return m.group(1)
    return None


CKPT_SLUG = "ets2ai-checkpoint"
CHAIN_TARGET = 500_000_000_000          # 500 bilhoes de AMOSTRAS acumuladas (~1,25 bi de km)


def _ck_dir():
    d = ROOT / ".cache" / "kaggle-ckpt"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _dataset_exists(user):
    r = sh("kaggle", "datasets", "list", "--mine", "--page-size", "50")
    return f"{user}/{CKPT_SLUG}".lower() in (r.stdout + r.stderr).lower()


def _write_ds_metadata(d):
    (d / "dataset-metadata.json").write_text(json.dumps({
        "id": f"{_user[0]}/{CKPT_SLUG}",
        "title": CKPT_SLUG,
        "is_private": "true",
        "licenses": [{"name": "CC0-1.0"}],
    }), encoding="utf-8")


def _seed_checkpoint(user):
    """Cria o dataset de checkpoint com os pesos canonicos atuais."""
    d = _ck_dir()
    src = ROOT / "artifacts" / "model-weights.json"
    if not src.exists():
        print("[chain] sem pesos canonicos para semear o checkpoint")
        return False
    import shutil
    shutil.copyfile(src, d / "model-weights.json")
    m = ROOT / "artifacts" / "metrics.json"
    if m.exists():
        shutil.copyfile(m, d / "metrics.json")
    _write_ds_metadata(d)
    r = sh("kaggle", "datasets", "create", "-p", d)
    print(r.stdout or r.stderr)
    return r.returncode == 0


def _version_checkpoint(user, msg):
    d = _ck_dir()
    _write_ds_metadata(d)
    r = sh("kaggle", "datasets", "version", "-p", d, "-m", msg)
    print(r.stdout or r.stderr)
    return r.returncode == 0


LEDGER = ROOT / ".chain-sessions.json"
WEEK_CAP_H = 28.5          # teto semanal com folga vs 30 h do Kaggle


def _week_ledger():
    """(horas orcadas nos ultimos 7 dias, entrada mais antiga na janela)."""
    import time as _t
    try:
        ent = json.loads(LEDGER.read_text())
    except Exception:
        return 0.0, None
    now = _t.time()
    ent = [e for e in ent if now - e.get("t", 0) < 7 * 86400]
    used = sum(e.get("sec", 0) for e in ent) / 3600.0
    oldest = min((e["t"] for e in ent), default=None)
    return used, oldest


def chain(user):
    """Empurra a proxima sessao da cadeia (NAO espera: sessao de ~12 h).

    Governador de cota: soma o orcamento das sessoes dos ultimos 7 dias
    (ledger .chain-sessions.json) e nunca deixa a semana passar de
    WEEK_CAP_H horas. Sem orcamento suficiente, imprime CHAIN_WAIT_H=N
    (horas ate tentar de novo) e sai 0 — o workflow agenda o retry."""
    global _user
    _user = user
    if not _dataset_exists(user):
        print(f"[chain] dataset {user}/{CKPT_SLUG} nao existe — semeando...")
        if not _seed_checkpoint(user):
            print("::warning::falha ao criar o dataset de checkpoint")
            return 1
    kdir = ROOT / ".cache" / "kaggle-kernel"
    kdir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(HERE))
    import build_kernel
    used_h, oldest = _week_ledger()
    requested_h = float(os.environ.get("ETS2AI_MAX_SECONDS", "41400")) / 3600.0
    remaining_h = WEEK_CAP_H - used_h
    if remaining_h < 2.0:
        import time as _t
        wait_h = 12.0 if oldest is None else \
            max(1.0, (oldest + 7 * 86400 - _t.time()) / 3600.0 + 1.0)
        wait_h = min(wait_h, 11.5)
        print(f"CHAIN_WAIT_H={wait_h:.1f}")
        print(f"[chain] governador de cota: {used_h:.1f} h nos ultimos 7 dias, "
              f"restam {remaining_h:.1f} h — aguardando {wait_h:.1f} h")
        return 0
    budget_sec = int(min(requested_h, remaining_h) * 3600)
    print(f"[chain] governador de cota: {used_h:.1f} h nos ultimos 7 dias | "
          f"sessao de {budget_sec/3600:.1f} h (pedido {requested_h:.1f} h)")
    src = build_kernel.build()
    # O kernel roda no Kaggle SEM estas variaveis de ambiente — assamos o
    # orcamento da cadeia DENTRO do script (a sessao de 11,5 h so acontece
    # se o teto de amostras/tempo vier gravado, nao do env do runner).
    _samples = int(os.environ.get("ETS2AI_SAMPLES", "15000000000"))
    _max_sec = budget_sec
    src = src.replace('_os.environ.get("ETS2AI_SAMPLES", "1000000000")',
                      str(_samples))
    src = src.replace('_os.environ.get("ETS2AI_MAX_SECONDS", "10800")',
                      str(_max_sec))
    print(f"[chain] orcamento gravado no kernel: {_samples:,} amostras, "
          f"{_max_sec/3600:.1f} h")
    (kdir / "kernel.py").write_text(src, encoding="utf-8")
    (kdir / "kernel-metadata.json").write_text(json.dumps({
        "id": f"{user}/{SLUG_SUFFIX}",
        "title": "ets2ai-train",
        "code_file": "kernel.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": "true",
        "enable_gpu": "true",
        "machine_shape": "NvidiaTeslaT4",
        "enable_internet": "false",
        "dataset_sources": [f"{user}/{CKPT_SLUG}"],
    }), encoding="utf-8")
    r = sh("kaggle", "kernels", "push", "-p", kdir)
    print(r.stdout or r.stderr)
    if r.returncode != 0:
        out = (r.stdout + r.stderr).lower()
        if "quota" in out or "limit" in out:
            print("[chain] sem cota de GPU agora — a proxima janela agendada "
                  "tenta de novo (automatico)")
            return 0
        return 1
    import time as _t
    try:
        ent = json.loads(LEDGER.read_text()) if LEDGER.exists() else []
    except Exception:
        ent = []
    ent.append({"t": _t.time(), "sec": budget_sec})
    LEDGER.write_text(json.dumps(ent[-40:], indent=1), encoding="utf-8")
    print(f"[chain] SESSAO EMPURRADA: https://www.kaggle.com/code/{user}/{SLUG_SUFFIX}")
    print("[chain] ~12 h de 2x T4; a colheita acontece na proxima janela "
          "agendada (--harvest)")
    return 0


def harvest(user):
    """Baixa a sessao anterior; se os gates passarem, versiona o checkpoint.

    Escreve .cache/cumulative.txt com o total acumulado (ou 'RUNNING' se a
    sessao ainda estiver rodando, 'NONE' se nao houver saida nova).
    """
    global _user
    _user = user
    slug = f"{user}/{SLUG_SUFFIX}"
    r = sh("kaggle", "kernels", "status", slug)
    out = (r.stdout + r.stderr).lower()
    if "running" in out or "queued" in out:
        print(f"[harvest] sessao anterior ainda em execucao — colheremos depois")
        (ROOT / ".cache").mkdir(exist_ok=True)
        (ROOT / ".cache" / "cumulative.txt").write_text("RUNNING\n")
        return 0
    outdir = ROOT / ".cache" / "kaggle-out"
    outdir.mkdir(parents=True, exist_ok=True)
    r = sh("kaggle", "kernels", "output", slug, "-p", outdir)
    print(r.stdout or r.stderr)
    weights = outdir / "model-weights.json"
    if r.returncode != 0 or not weights.exists():
        print("[harvest] sem saida para colher")
        (ROOT / ".cache" / "cumulative.txt").write_text("NONE\n")
        return 0
    import json as _j
    metrics = outdir / "metrics.json"
    cum = 0
    if metrics.exists():
        try:
            cum = int(_j.loads(metrics.read_text())["cumulative_samples"])
        except Exception:
            cum = 0
    if cum <= 0:
        try:
            cum = int(_j.loads(weights.read_text())["meta"]["samples"])
        except Exception:
            cum = 0
    print(f"[harvest] acumulado ate agora: {cum:,} amostras "
          f"({cum / CHAIN_TARGET * 100:.1f}% de {CHAIN_TARGET:,})")
    _rds = sh("kaggle", "datasets", "status", f"{user}/{CKPT_SLUG}")
    print("[harvest] checkpoint dataset:", (_rds.stdout or _rds.stderr).strip()[:200])
    # PROVA ANTI-REPETICAO: a sessao colhida tem que ter semente/impressao
    # digital DIFERENTES das ja registradas no repo (a semente avanca com o
    # acumulado — nenhuma sessao treina nos mesmos dados de novo).
    try:
        _m = _j.loads(metrics.read_text())
        _repo = _j.loads((ROOT / "artifacts" / "metrics.json").read_text())
        print(f"[harvest] PROVA anti-repeticao: seed desta sessao "
              f"{_m.get('data_seed', '?')} | impressao digital "
              f"{_m.get('data_fingerprint', '?') or '(pre-v0.4.7)'} | "
              f"seed anterior no repo {_repo.get('data_seed', '?')}")
        if _m.get("data_seed") is not None and _m.get("data_seed") == _repo.get("data_seed"):
            print("::warning::MESMA SEED DA SESSAO ANTERIOR — repeticao de dados!")
    except Exception as _e:
        print(f"[harvest] (metrics sem prova anti-repeticao ainda: {_e.__class__.__name__})")
    # gates (mesmo padrao do fluxo principal)
    import numpy as np
    from ets2ai.contract import load_weights, LOSS_TARGET
    from ets2ai.train import closed_loop_eval
    layers, meta = load_weights(weights)
    loss = meta["final_loss"]
    agg, _ = closed_loop_eval(layers, n_roads=3)
    print(f"[harvest] loss {loss:.5f} | {agg['finish_rate']*100:.0f}% rotas | "
          f"{agg['in_lane_pct']*100:.1f}% faixa | dock {agg['dock_rate']*100:.0f}%")
    ok = (loss <= LOSS_TARGET and agg["finish_rate"] >= 2 / 3
          and agg["in_lane_pct"] > 0.95 and agg["dock_rate"] >= 2 / 3)
    (ROOT / ".cache" / "cumulative.txt").write_text(f"{cum}\n")
    if not ok:
        print("::warning::gates FALHARAM — checkpoint NAO versionado "
              "(a proxima sessao retoma do ultimo ponto bom)")
        return 1
    if not _dataset_exists(user):
        # normal na primeira janela: o --chain cria o dataset na sequencia
        print("[harvest] dataset de checkpoint ainda nao existe — sera "
              "criado pelo --chain agora; pesos validados ficam em "
              ".cache/kaggle-out")
        return 0
    import shutil
    d = _ck_dir()
    shutil.copyfile(weights, d / "model-weights.json")
    if metrics.exists():
        shutil.copyfile(metrics, d / "metrics.json")
    if not _version_checkpoint(user, f"cadeia: {cum:,} amostras acumuladas"):
        return 1
    print(f"[harvest] checkpoint versionado: {user}/{CKPT_SLUG} ({cum:,})")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--epochs", type=int, default=320)
    ap.add_argument("--gpu", action="store_true",
                    help="executar o kernel com GPU T4 x2 do Kaggle")
    ap.add_argument("--slug-only", action="store_true",
                    help="imprime user/slug do kernel e sai (nao empurra)")
    ap.add_argument("--chain", action="store_true",
                    help="CADEIA 500B: garante o dataset de checkpoint, empurra"
                         " o kernel (sessao longa) e sai SEM esperar (a colheita"
                         " e feita com --harvest)")
    ap.add_argument("--harvest", action="store_true",
                    help="colhe a sessao anterior (se completa), valida os gates"
                         " e versiona o dataset de checkpoint")
    args = ap.parse_args()

    key = os.environ.get("KAGGLE_KEY", "").strip()
    token = os.environ.get("KAGGLE_API_TOKEN", "").strip() or key
    user = os.environ.get("KAGGLE_USERNAME", "").strip()
    if not token:
        print("::warning::Secret KAGGLE_KEY nao configurado.")
        print("Para treinar no Kaggle: repo Settings > Secrets and variables > Actions >")
        print("  KAGGLE_KEY = seu token (kaggle.com > Settings > API > Create)")
        print("O token NUNCA deve ser colado em chat/commit — apenas em secrets.")
        return 2
    # CLI 2.x: autenticacao por ACCESS TOKEN (Bearer); KAGGLE_USERNAME/KEY
    # legado nao funciona mais. O mesmo valor do secret alimenta os dois.
    os.environ["KAGGLE_API_TOKEN"] = token
    if not user:
        print("[kaggle] KAGGLE_USERNAME ausente: derivando do token...")
        user = _discover_username() or ""
    if not user:
        print("::warning::Nao foi possivel descobrir o username do token.")
        print("Crie o secret KAGGLE_USERNAME (seu usuario Kaggle) ou rode um")
        print("notebook qualquer na conta uma vez (kernels list --mine).")
        return 2
    os.environ["KAGGLE_USERNAME"] = user

    if args.slug_only:
        print(f"{user}/{SLUG_SUFFIX}")
        return 0

    if args.harvest:
        return harvest(user)
    if args.chain:
        return chain(user)

    kdir = ROOT / ".cache" / "kaggle-kernel"
    kdir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(HERE))
    import build_kernel
    used_h, oldest = _week_ledger()
    requested_h = float(os.environ.get("ETS2AI_MAX_SECONDS", "41400")) / 3600.0
    remaining_h = WEEK_CAP_H - used_h
    if remaining_h < 2.0:
        import time as _t
        wait_h = 12.0 if oldest is None else \
            max(1.0, (oldest + 7 * 86400 - _t.time()) / 3600.0 + 1.0)
        wait_h = min(wait_h, 11.5)
        print(f"CHAIN_WAIT_H={wait_h:.1f}")
        print(f"[chain] governador de cota: {used_h:.1f} h nos ultimos 7 dias, "
              f"restam {remaining_h:.1f} h — aguardando {wait_h:.1f} h")
        return 0
    budget_sec = int(min(requested_h, remaining_h) * 3600)
    print(f"[chain] governador de cota: {used_h:.1f} h nos ultimos 7 dias | "
          f"sessao de {budget_sec/3600:.1f} h (pedido {requested_h:.1f} h)")
    src = build_kernel.build()
    # O kernel roda no Kaggle SEM estas variaveis de ambiente — assamos o
    # orcamento da cadeia DENTRO do script (a sessao de 11,5 h so acontece
    # se o teto de amostras/tempo vier gravado, nao do env do runner).
    _samples = int(os.environ.get("ETS2AI_SAMPLES", "15000000000"))
    _max_sec = budget_sec
    src = src.replace('_os.environ.get("ETS2AI_SAMPLES", "1000000000")',
                      str(_samples))
    src = src.replace('_os.environ.get("ETS2AI_MAX_SECONDS", "10800")',
                      str(_max_sec))
    print(f"[chain] orcamento gravado no kernel: {_samples:,} amostras, "
          f"{_max_sec/3600:.1f} h")
    (kdir / "kernel.py").write_text(src, encoding="utf-8")
    slug = f"{user}/{SLUG_SUFFIX}"
    (kdir / "kernel-metadata.json").write_text(json.dumps({
        "id": slug,
        "title": "ets2ai-train",   # deve resolver no mesmo slug do id
        "code_file": "kernel.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": "true",
        "enable_gpu": "true" if args.gpu else "false",
        "machine_shape": "NvidiaTeslaT4" if args.gpu else "",
        "enable_internet": "false",
    }), encoding="utf-8")

    r = sh("kaggle", "kernels", "push", "-p", kdir)
    print(r.stdout or r.stderr)
    if r.returncode != 0:
        # descobre o username real da conta do token (kernels list --mine)
        r2 = sh("kaggle", "kernels", "list", "--mine", "--page-size", "5")
        out2 = (r2.stdout or "") + (r2.stderr or "")
        print("[kaggle] kernels list --mine:", out2.strip()[:400])
        print(f"::warning::kaggle kernels push falhou: {r.stderr.strip()[:300]}")
        return 1

    print(f"[kaggle] kernel empurrado: {slug}")
    print(f"[kaggle] notebook ativo: https://www.kaggle.com/code/{slug}")
    print("[kaggle] aguardando execucao (GPU T4 x2, FP64)...")
    deadline = time.time() + args.timeout
    status = "unknown"
    while time.time() < deadline:
        time.sleep(30)
        r = sh("kaggle", "kernels", "status", slug)
        out = (r.stdout + r.stderr).lower()
        if "complete" in out and "notcomplete" not in out and "running" not in out:
            status = "complete"
            break
        if "error" in out or "cancel" in out:
            status = "error"
            break
        if (int(deadline - time.time()) % 300) < 30:
            print(f"[kaggle] status: {out.strip()[:120]}")
    if status != "complete":
        print(f"::warning::kernel nao concluiu a tempo (status: {status})")
        return 1

    outdir = ROOT / ".cache" / "kaggle-out"
    outdir.mkdir(parents=True, exist_ok=True)
    r = sh("kaggle", "kernels", "output", slug, "-p", outdir)
    print(r.stdout or r.stderr)
    weights = outdir / "model-weights.json"
    if r.returncode != 0 or not weights.exists():
        print("::warning::saida do kernel nao encontrada")
        return 1

    # ---- quality gates on the KAGGLE-trained weights (same as local CI) ----
    import numpy as np
    from ets2ai.contract import load_weights, LOSS_TARGET
    from ets2ai.train import closed_loop_eval
    layers, meta = load_weights(weights)
    loss = meta["final_loss"]
    agg, _ = closed_loop_eval(layers, n_roads=3)
    print(f"[kaggle] pesos validados: loss {loss:.5f} | "
          f"{agg['finish_rate']*100:.0f}% rotas | {agg['in_lane_pct']*100:.0f}% faixa | "
          f"radares {agg['radar_compliance']*100:.0f}%")
    ok = (loss <= LOSS_TARGET and agg["finish_rate"] >= 2 / 3
          and agg["in_lane_pct"] > 0.95 and agg["dock_rate"] >= 2 / 3)
    print("[kaggle] GATES: " + ("OK — treino no Kaggle reproduz a qualidade" if ok
                                else "FALHOU — mantendo pesos do treino local"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
