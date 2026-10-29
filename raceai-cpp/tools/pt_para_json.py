#!/usr/bin/env python3
# pt_para_json.py — converte um modelo treinado na versão Python do RaceAI 2D
# (arquivo .pt do PyTorch, ou o .npz de fallback) para o formato .json que o
# jogo em C++ carrega.
#
# Por quê: a versão em C++ não depende do PyTorch (roda direto no Pentium
# N5030, sem CUDA), então ela usa o próprio formato JSON. Este script faz a
# ponte: você treina na versão Python e aproveita o modelo no executável.
#
# Uso:
#     python pt_para_json.py modelo.pt              -> modelo.raceai.json
#     python pt_para_json.py modelo.pt saida.json
#     python pt_para_json.py --self-test            -> testa sem PyTorch
#
# Requer PyTorch instalado apenas para ler .pt (para .npz basta o NumPy).
# Rode este script no computador onde você treinou o modelo, e copie só o
# .json gerado para a pasta do jogo.
import json
import os
import sys


def _camadas_de_state_dict(state):
    """Tira as matrizes de um state_dict {'0.weight': W, '0.bias': b, ...}."""
    pares = {}
    for chave, tensor in state.items():
        chave = chave.replace("module.", "")
        if "." not in chave:
            continue
        i, tipo = chave.rsplit(".", 1)
        if tipo not in ("weight", "bias"):
            continue
        pares.setdefault(int(i) if i.isdigit() else i, {})[tipo] = tensor
    camadas = []
    for i in sorted(pares, key=lambda k: (str(type(k)), k)):
        par = pares[i]
        if "weight" in par and "bias" in par:
            camadas.append((par["weight"], par["bias"]))
    return camadas


def _achatar(camadas):
    """Genoma no layout do jogo: por camada, matriz (linha = neurônio de saída)
    e depois o bias."""
    pesos = []
    for W, b in camadas:
        W = _para_lista(W)          # shape (saida, entrada)
        pesos.extend(W)             # linha por linha = neurônio de saída
        pesos.extend(_para_lista(b))
    return pesos


def _para_lista(tensor):
    if hasattr(tensor, "detach"):
        tensor = tensor.detach()
    if hasattr(tensor, "cpu"):
        tensor = tensor.cpu()
    if hasattr(tensor, "numpy"):
        tensor = tensor.tolist()
    return _aplanar(tensor)


def _aplanar(x):
    if isinstance(x, (list, tuple)):
        if x and isinstance(x[0], (list, tuple)):
            saida = []
            for linha in x:
                saida.extend(_aplanar(linha))
            return saida
        return [float(v) for v in x]
    return [float(x)]


def _dims(camadas):
    obs_dim = len(camadas[0][0][0]) if isinstance(camadas[0][0][0], (list, tuple)) \
        else int(len(_aplanar(camadas[0][0])) / len(_aplanar(camadas[0][1])))
    hidden = [len(_aplanar(b)) for _, b in camadas[:-1]]
    act_dim = len(_aplanar(camadas[-1][1]))
    return obs_dim, hidden, act_dim


def de_pt(caminho):
    try:
        import torch
    except ImportError:
        raise SystemExit(
            "PyTorch não está instalado aqui.\n"
            "Abra este .pt na versão Python do RaceAI e exporte como .npz "
            "(ela faz isso sozinha quando o PyTorch falta), ou rode este "
            "script no computador onde treinou o modelo.")
    dados = torch.load(caminho, map_location="cpu", weights_only=False)
    state = dados.get("state_dict") if isinstance(dados, dict) else dados
    if state is None:
        raise SystemExit("arquivo .pt sem 'state_dict'")
    camadas = _camadas_de_state_dict(state)
    meta = dados.get("meta", {}) if isinstance(dados, dict) else {}
    return camadas, meta


def de_npz(caminho):
    import numpy as np
    with np.load(caminho, allow_pickle=False) as z:
        nomes = [n for n in z.files if n != "meta_json"]
        nomes.sort(key=lambda n: int(n) if n.isdigit() else 1 << 30)
        arrays = [z[n] for n in nomes]
        meta = {}
        if "meta_json" in z.files:
            meta = json.loads(bytes(z["meta_json"]).decode("utf-8"))
    camadas = [(arrays[i], arrays[i + 1]) for i in range(0, len(arrays) - 1, 2)]
    return camadas, meta


def salvar_json(caminho, camadas, meta):
    obs_dim, hidden, act_dim = _dims(camadas)
    pesos = _achatar(camadas)
    modelo = {
        "obs_dim": obs_dim,
        "act_dim": act_dim,
        "hidden": hidden,
        "weights": pesos,
        "meta": {
            "origem": "convertido da versão Python",
            "topologia": "%d->%s->%d" % (obs_dim, "-".join(str(h) for h in hidden), act_dim),
        },
    }
    if isinstance(meta, dict):
        for k in ("track", "car", "generation", "fitness", "best_loss",
                  "best_error_pct", "best_distance", "obs_dim"):
            if k in meta:
                v = meta[k]
                try:
                    modelo["meta"][k] = float(v)
                except (TypeError, ValueError):
                    modelo["meta"][k] = str(v)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(modelo, f)
    return obs_dim, hidden, act_dim, len(pesos)


def auto_teste(saida="modelo.raceai.json"):
    """Gera um modelo aleatório sem PyTorch/NumPy e salva: serve para provar
    que o JSON sai no formato que o jogo aceita."""
    import random
    rng = random.Random(7)
    dims = [24, 64, 64, 2]
    camadas = []
    for i in range(len(dims) - 1):
        n_in, n_out = dims[i], dims[i + 1]
        W = [[rng.uniform(-0.3, 0.3) for _ in range(n_in)] for _ in range(n_out)]
        b = [0.0] * n_out
        camadas.append((W, b))
    return salvar_json(saida, camadas, {"track": "kartodromo", "car": "kart"})


def main(argv):
    args = [a for a in argv[1:] if a != "--self-test"]
    if "--self-test" in argv[1:]:
        saida = args[0] if args else "modelo.raceai.json"
        obs, hidden, act, n = auto_teste(saida)
        print("gerado %s: %d->%s->%d (%d pesos)" % (saida, obs, hidden, act, n))
        print("abra no jogo em C++ (Treinamento > Carregar modelo) para conferir.")
        return 0

    if not args:
        print(__doc__)
        return 2
    entrada = args[0]
    saida = args[1] if len(args) > 1 else os.path.splitext(entrada)[0] + ".raceai.json"
    if not os.path.exists(entrada):
        print("arquivo não encontrado: %s" % entrada)
        return 2
    ext = os.path.splitext(entrada)[1].lower()
    if ext == ".pt":
        camadas, meta = de_pt(entrada)
    elif ext == ".npz":
        camadas, meta = de_npz(entrada)
    else:
        print("use um .pt ou .npz da versão Python (ou rode --self-test)")
        return 2
    if not camadas:
        print("nenhuma camada encontrada em %s" % entrada)
        return 2
    obs, hidden, act, n = salvar_json(saida, camadas, meta)
    print("convertido: %s" % saida)
    print("  topologia %d->%s->%d, %d pesos" % (obs, "-".join(map(str, hidden)), act, n))
    print("  carregue no jogo em C++ em Treinamento > Carregar modelo")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
