"""Destilacao da politica oficial ([290]x13, 1,02M parametros) numa rede NANO
para PC fraco (Pentium N5030).

Por que: a rede oficial varre ~4 MB de pesos por inferencia; no N5030 isso da
~208 inf/s = ~9,6% de 1 nucleo a 20 Hz — acima do orcamento (<1% do chip).
Uma rede nano (~18-28 mil parametros, cabe no cache L2) imita a oficial na
MESMA distribuicao de treino (vector_gen) e roda milhares de inf/s.

Regras de honestidade:
  - a rede OFICIAL continua sendo a unica entrega (.pt / APK / TFLite);
  - a nano so e usada quando a oficial nao cabe no orcamento DA MAQUINA
    (medido em runtime pelo bridge, nunca prometido no papel);
  - a nano so e publicada se passar os GATES (fidelidade + malha fechada);
    se nao passar, o bridge cai no celular (cabo, sem depuracao) como antes.

Determinismo: sementes fixas + numpy 2.2.6 (igual ao CI) => mesma maquina, mesmos
pesos; entre maquinas so micro-arredondamentos de BLAS mudam (os gates sao
re-avaliados onde a nano treina, entao o resultado publicado e sempre auto-consistente).
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from . import vector_gen
from .contract import (ACTIONS, FEATURES, LOSS_TARGET, N_IN, N_OUT, SEED,
                       load_weights, save_weights)
from .model import forward, mse, train
from .train import closed_loop_eval

# --------------------------------------------------------------------------- #
# Configuracao (tudo fixo p/ determinismo)
# --------------------------------------------------------------------------- #
NANO_HIDDEN = [160, 160]      # ~28,3 mil parametros (36x menor; cabe no L2)
NANO_SEED = 4242              # init do aluno
TRAIN_SEED = 77700160         # embaralhamento por epoca do train()

DATA_SEED = 777               # stream de TREINO da destilacao
VAL_SEED = 888                # stream de validacao (best-epoch do train)
EVAL_SEED = 999               # stream de AVALIACAO (nunca visto)
BOX_SEED_TRAIN_R, BOX_SEED_TRAIN_S, BOX_SEED_VAL = 101, 102, 103
BOX_SEED_EVAL = 104

N_STREAM, N_BOX_REAL, N_BOX_SIM = 400_000, 80_000, 40_000
VAL_STREAM, VAL_BOX = 32_768, 16_384
EVAL_STREAM, EVAL_BOX = 65_536, 16_384
EPOCHS, BATCH, LR = 240, 512, 2.5e-3
CL_ROADS = 6                  # estradas da malha fechada (gate)

# gates de publicacao (valores calibrados nos experimentos de 07/10; ver
# tests/test_distill.py — o MSE oficial-vs-especialista e ~0.0026)
GATE = {
    "mse_stream_max": 0.006,       # aluno-vs-oficial na distribuicao real
    "p999_steer_stream_max": 0.35,
    "mse_box_max": 0.035,          # caixa uniforme do jogo real (radar=1.0)
    "sign_ok_stream_min": 0.995,   # mesmo sinal de volante onde |steer|>0.2
    "sign_ok_box_min": 0.95,
    "closed_loop_equiv": True,     # mesmos desfechos nas CL_ROADS estradas
    "closed_loop_quality": True,   # nano tambem passa os gates da oficial
}

QUICK = dict(                    # modo rapido p/ testes (toy teacher)
    n_stream=6_000, n_box_real=1_500, n_box_sim=750,
    val_stream=4_096, val_box=2_048,
    eval_stream=6_000, eval_box=2_048,
    epochs=20, hidden=[16, 16], cl_roads=2,
)


# --------------------------------------------------------------------------- #
# Dados
# --------------------------------------------------------------------------- #
def _stream_rows(seed, n):
    """Primeiras `n` linhas do gerador vetorial (deterministico sob `seed`)."""
    xs, got = [], 0
    for x, _y in vector_gen.stream(seed):
        xs.append(x)
        got += len(x)
        if got >= n:
            break
    return np.concatenate(xs)[:n].astype(np.float32)


def _stream_rows_expert(seed, n):
    """(x, y_especialista) — para medir aluno-vs-especialista."""
    xs, ys, got = [], [], 0
    for x, y in vector_gen.stream(seed):
        xs.append(x)
        ys.append(y)
        got += len(x)
        if got >= n:
            break
    k = min(n, len(np.concatenate(xs)))
    return (np.concatenate(xs)[:k].astype(np.float32),
            np.concatenate(ys)[:k].astype(np.float32))


def _box(n, radar_lo, radar_hi, seed):
    """Amostras uniformes na CAIXA REAL do jogo (features clampeadas do
    practice.features_from; radar sempre 1.0 no jogo real — SDK nao expoe)."""
    r = np.random.default_rng(seed)
    x = np.empty((n, N_IN), dtype=np.float32)
    x[:, 0] = r.uniform(0.0, 1.44, n)            # speed (ate 36 m/s) / 25
    x[:, 1] = r.uniform(-1.35, 1.35, n)          # offset +-4.6 m / 3.5
    x[:, 2] = r.uniform(-1.2, 1.2, n)            # heading +-0.72 rad / 0.6
    x[:, 3:8] = r.uniform(-1.0, 1.0, (n, 5))     # curvaturas / 0.05
    x[:, 8] = r.uniform(0.3, 1.0, n)             # speed_limit
    x[:, 9] = r.uniform(0.0, 1.0, n)             # fuel
    x[:, 10] = r.uniform(0.0, 1.0, n)            # fatigue
    x[:, 11] = r.uniform(0.0, 1.0, n)            # job_dist
    x[:, 12] = r.uniform(radar_lo, radar_hi, n)  # radar
    return x


def _label(x, layers, batch=65536):
    """Saida do PROFESSOR em lotes (mesma matematica do deploy)."""
    return np.concatenate(
        [forward(x[i:i + batch], layers) for i in range(0, len(x), batch)]
    ).astype(np.float32)


def _init_student(sizes, seed=NANO_SEED):
    """He init (tanh) para arquitetura customizada (contract.init_layers so
    cria a arquitetura oficial)."""
    r = np.random.default_rng(seed)
    sizes = [N_IN] + list(sizes) + [N_OUT]
    out = []
    for i in range(len(sizes) - 1):
        fi, fo = sizes[i], sizes[i + 1]
        out.append(((r.standard_normal((fi, fo)) * np.sqrt(1.0 / fi))
                    .astype(np.float32), np.zeros(fo, dtype=np.float32)))
    return out


def _clamp_b(a):
    return np.stack([np.clip(a[:, 0], -1, 1), np.clip(a[:, 1], 0, 1),
                     np.clip(a[:, 2], 0, 1)], axis=1)


# --------------------------------------------------------------------------- #
# Destilacao + avaliacao
# --------------------------------------------------------------------------- #
def distill(teacher, quick=False):
    """Treina a nano p/ imitar o professor. Retorna (layers, report)."""
    cfg = QUICK if quick else dict(
        n_stream=N_STREAM, n_box_real=N_BOX_REAL, n_box_sim=N_BOX_SIM,
        val_stream=VAL_STREAM, val_box=VAL_BOX,
        eval_stream=EVAL_STREAM, eval_box=EVAL_BOX,
        epochs=EPOCHS, hidden=NANO_HIDDEN, cl_roads=CL_ROADS,
    )
    t0 = time.time()
    xtr = np.concatenate([
        _stream_rows(DATA_SEED, cfg["n_stream"]),
        _box(cfg["n_box_real"], 1.0, 1.0, BOX_SEED_TRAIN_R),   # jogo real
        _box(cfg["n_box_sim"], 0.0, 6.0, BOX_SEED_TRAIN_S),    # sim/demo
    ])
    ytr = _label(xtr, teacher)
    xva = np.concatenate([
        _stream_rows(VAL_SEED, cfg["val_stream"]),
        _box(cfg["val_box"], 1.0, 1.0, BOX_SEED_VAL),
    ])
    yva = _label(xva, teacher)
    student, hist = train(
        xtr, ytr, epochs=cfg["epochs"], batch=BATCH, lr=LR, seed=TRAIN_SEED,
        x_val=xva, y_val=yva, start_layers=_init_student(cfg["hidden"]),
        verbose=False,
    )
    report = evaluate(student, teacher, quick=quick)
    report["train_seconds"] = round(time.time() - t0, 1)
    report["train_val_mse"] = float(hist[-1][1])
    report["config"] = {k: (list(v) if isinstance(v, list) else v)
                        for k, v in cfg.items()}
    return student, report


def evaluate(student, teacher, quick=False):
    """Fidelidade aluno-vs-professor na distribuicao real (stream), na caixa
    do jogo real, vs ESPECIALISTA, e MALHA FECHADA nas mesmas estradas."""
    cfg = QUICK if quick else dict(eval_stream=EVAL_STREAM,
                                   eval_box=EVAL_BOX, cl_roads=CL_ROADS)
    # stream (distribuicao real de treino) + especialista
    xs, y_exp = _stream_rows_expert(EVAL_SEED, cfg["eval_stream"])
    y_tea = _label(xs, teacher)
    y_stu = _label(xs, student)
    rep = _compare(y_stu, y_tea)
    rep_exp = _compare(y_stu, _clamp_b(y_exp))
    rep_tea_exp = _compare(y_tea, _clamp_b(y_exp))
    # caixa do jogo real (radar = 1.0)
    xb = _box(cfg["eval_box"], 1.0, 1.0, BOX_SEED_EVAL)
    rep_box = _compare(_label(xb, student), _label(xb, teacher))

    # malha fechada: mesmas estradas/sementes para os dois
    cl_tea, _ = closed_loop_eval(teacher, n_roads=cfg["cl_roads"])
    cl_stu, _ = closed_loop_eval(student, n_roads=cfg["cl_roads"])
    equiv = (cl_tea["finish_rate"] == cl_stu["finish_rate"]
             and cl_tea["dock_rate"] == cl_stu["dock_rate"]
             and abs(cl_tea["in_lane_pct"] - cl_stu["in_lane_pct"]) < 0.005
             and abs(cl_tea["km_total"] - cl_stu["km_total"])
             < 0.01 * max(cl_tea["km_total"], 1e-9))
    quality = (cl_stu["finish_rate"] >= 2 / 3 and cl_stu["dock_rate"] >= 2 / 3
               and cl_stu["in_lane_pct"] > 0.95)

    return {
        "mse_stream": rep["mse"], "p999_steer_stream": rep["p999_steer"],
        "max_dsteer_stream": rep["max_dsteer"],
        "max_dbrake_stream": rep["max_dbrake"],
        "sign_ok_stream": rep["sign_ok"],
        "mse_box_real": rep_box["mse"],
        "p999_steer_box": rep_box["p999_steer"],
        "max_dsteer_box": rep_box["max_dsteer"],
        "sign_ok_box": rep_box["sign_ok"],
        "mse_vs_expert_nano": rep_exp["mse"],
        "mse_vs_expert_teacher": rep_tea_exp["mse"],
        "closed_loop_teacher": cl_tea, "closed_loop_nano": cl_stu,
        "closed_loop_equiv": bool(equiv),
        "closed_loop_quality": bool(quality),
    }


def _compare(pred, target):
    p, t = _clamp_b(pred), _clamp_b(target)
    d = np.abs(p - t)
    m = np.abs(t[:, 0]) > 0.2
    return {
        "mse": float(mse(p, t)),
        "p999_steer": float(np.quantile(d[:, 0], 0.999)),
        "max_dsteer": float(d[:, 0].max()),
        "max_dbrake": float(d[:, 2].max()),
        "sign_ok": float((np.sign(p[m, 0]) == np.sign(t[m, 0])).mean())
        if m.any() else 1.0,
    }


def gate(report):
    """(ok, motivos) — publica a nano so com fidelidade comprovada."""
    reasons = []
    if report["mse_stream"] > GATE["mse_stream_max"]:
        reasons.append(f"mse_stream {report['mse_stream']:.4f} > "
                       f"{GATE['mse_stream_max']}")
    if report["p999_steer_stream"] > GATE["p999_steer_stream_max"]:
        reasons.append(f"p999_steer_stream {report['p999_steer_stream']:.3f} > "
                       f"{GATE['p999_steer_stream_max']}")
    if report["mse_box_real"] > GATE["mse_box_max"]:
        reasons.append(f"mse_box {report['mse_box_real']:.4f} > "
                       f"{GATE['mse_box_max']}")
    if report["sign_ok_stream"] < GATE["sign_ok_stream_min"]:
        reasons.append(f"sign_ok_stream {report['sign_ok_stream']:.4f} < "
                       f"{GATE['sign_ok_stream_min']}")
    if report["sign_ok_box"] < GATE["sign_ok_box_min"]:
        reasons.append(f"sign_ok_box {report['sign_ok_box']:.4f} < "
                       f"{GATE['sign_ok_box_min']}")
    if GATE["closed_loop_equiv"] and not report["closed_loop_equiv"]:
        reasons.append("malha fechada divergiu do professor")
    if GATE["closed_loop_quality"] and not report["closed_loop_quality"]:
        reasons.append("malha fechada da nano abaixo dos gates da oficial")
    return (not reasons), reasons


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--weights", default="artifacts/model-weights.json",
                    help="pesos OFICIAIS (professor)")
    ap.add_argument("--out", default="artifacts/model-nano.json",
                    help="saida da nano (so e escrita se passar nos gates)")
    ap.add_argument("--report", default=None,
                    help="JSON com o relatorio completo de fidelidade")
    ap.add_argument("--quick", action="store_true",
                    help="modo rapido (testes; NAO usar para publicar)")
    args = ap.parse_args(argv)

    teacher, tmeta = load_weights(args.weights)
    print(f"[distill] professor: hidden={tmeta['hidden'][:3]}... "
          f"({sum(w.size + b.size for w, b in teacher):,} params, "
          f"loss {tmeta['final_loss']:.6f})", flush=True)
    student, report = distill(teacher, quick=args.quick)
    ok, reasons = gate(report)
    report["gate_ok"] = ok
    report["gate_reasons"] = reasons
    report["teacher"] = {"hidden": tmeta["hidden"],
                         "final_loss": tmeta["final_loss"]}

    print(f"[distill] nano {report['config']['hidden']} "
          f"({sum(w.size + b.size for w, b in student):,} params) em "
          f"{report['train_seconds']:.0f}s", flush=True)
    print(f"[distill] stream : mse {report['mse_stream']:.6f} "
          f"(professor-vs-especialista: {report['mse_vs_expert_teacher']:.6f}) "
          f"p999|dst| {report['p999_steer_stream']:.3f} "
          f"max|dst| {report['max_dsteer_stream']:.3f} "
          f"sinal {report['sign_ok_stream']*100:.2f}%", flush=True)
    print(f"[distill] caixa  : mse {report['mse_box_real']:.6f} "
          f"sinal {report['sign_ok_box']*100:.2f}%", flush=True)
    print(f"[distill] malha  : equiv={report['closed_loop_equiv']} "
          f"nano finish {report['closed_loop_nano']['finish_rate']*100:.0f}% "
          f"dock {report['closed_loop_nano']['dock_rate']*100:.0f}% "
          f"faixa {report['closed_loop_nano']['in_lane_pct']*100:.1f}%",
          flush=True)

    out = Path(args.out)
    if ok:
        meta = {
            "features": FEATURES, "actions": ACTIONS,
            "hidden": report["config"]["hidden"], "seed": NANO_SEED,
            "loss_target": LOSS_TARGET, "epochs": report["config"]["epochs"],
            "samples": int(sum(report["config"][k] for k in
                               ("n_stream", "n_box_real", "n_box_sim"))),
            "final_loss": report["mse_stream"],   # MSE vs rede oficial
            "dtype": "float32", "nano": True,
            "distilled_from": {"hidden": tmeta["hidden"],
                               "final_loss": tmeta["final_loss"]},
            "distill": {k: report[k] for k in (
                "mse_stream", "p999_steer_stream", "sign_ok_stream",
                "mse_box_real", "sign_ok_box", "mse_vs_expert_nano",
                "mse_vs_expert_teacher", "closed_loop_equiv")},
        }
        save_weights(out, student, meta)
        print(f"[distill] NANO_SHIPPED=yes -> {out}", flush=True)
    else:
        # nunca deixa uma nano velha casada com pesos novos
        if out.exists():
            out.unlink()
            print(f"[distill] removida nano antiga: {out}", flush=True)
        print("[distill] NANO_SHIPPED=no — " + "; ".join(reasons), flush=True)
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2),
                                     encoding="utf-8")
        print(f"[distill] relatorio: {args.report}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
