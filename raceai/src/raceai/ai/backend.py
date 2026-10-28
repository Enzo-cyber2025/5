"""Backends de inferência: torch (CPU / DirectML / CUDA) e numpy (fallback).

A otimização importante: **cada agente tem pesos próprios** (é uma evolução,
não um único modelo). Em vez de N forwards minúsculos, empilhamos os pesos de
todos os indivíduos num tensor (B, out, in) e fazemos um único `matmul`
em batch — assim a GPU Intel UHD 605 recebe um kernel grande por camada.
"""
from __future__ import annotations

import os
import time

import numpy as np

from .policy import PolicySpec, genome_to_layers

TORCH_IMPORT_ERROR = ""


def dml_disabled() -> bool:
    """Permite desligar o DirectML (RACEAI_NO_DML=1) se o driver travar."""
    return os.environ.get("RACEAI_NO_DML", "").strip().lower() not in ("", "0", "false", "no")


def torch_available() -> bool:
    global TORCH_IMPORT_ERROR
    try:
        import torch  # noqa: F401
        return True
    except Exception as exc:  # pragma: no cover - depende do ambiente
        TORCH_IMPORT_ERROR = str(exc)
        return False


def list_devices(prefer: str = "auto") -> list[tuple[str, str]]:
    """Devolve [(id, descrição)] dos backends disponíveis nesta máquina."""
    opts: list[tuple[str, str]] = [("cpu", "CPU (numpy — sempre disponível)")]
    try:
        import torch
        opts.append(("torch-cpu", f"CPU (PyTorch {torch.__version__})"))
        if torch.cuda.is_available():
            opts.append(("cuda", f"CUDA — {torch.cuda.get_device_name(0)}"))
        if dml_disabled():
            opts.append(("dml", "DirectML desligado por RACEAI_NO_DML"))
            raise RuntimeError("dml desabilitado")
        try:
            import torch_directml
            d = torch_directml.device()
            name = str(d)
            try:
                name = torch_directml.device_name(0) or name
            except Exception:
                pass
            opts.append(("dml", f"DirectML (GPU) — {name}"))
        except Exception as exc:
            opts.append(("dml", f"DirectML indisponível ({type(exc).__name__})"))

    except Exception as exc:
        opts.append(("torch-cpu", f"PyTorch indisponível ({type(exc).__name__})"))
    return opts


def resolve_device(prefer: str = "auto", verbose: bool = False) -> tuple[str, str]:
    """Escolhe o backend. Retorna (id, descrição)."""
    prefer = (prefer or "auto").lower()
    available = {k: v for k, v in list_devices(prefer)}

    def pick(candidates, fallback="cpu"):
        for c in candidates:
            if c in available and "indisponível" not in available[c].lower() \
                    and "indisponible" not in available[c].lower():
                return c
        return fallback

    if prefer in ("cpu", "numpy"):
        return "cpu", available.get("cpu", "CPU (numpy)")
    if prefer == "torch-cpu":
        return "torch-cpu", available.get("torch-cpu", "CPU (PyTorch)")
    if prefer == "cuda":
        return pick(["cuda"], "cpu"), available.get(prefer, "")
    if prefer == "dml":
        return pick(["dml"], "cpu"), available.get("dml", "")
    # automático: CUDA > DirectML > torch CPU > numpy
    return pick(["cuda", "dml", "torch-cpu"], "cpu"), ""


class NumpyBackend:
    """Backend CPU puro (sem PyTorch instalado)."""

    name = "cpu"

    def __init__(self, spec: PolicySpec, n_agents: int = 1):
        self.spec = spec
        self.device_id = "cpu"
        self.device_desc = "CPU (numpy)"
        self.W: list[np.ndarray] = []
        self.b: list[np.ndarray] = []
        self.last_ms = 0.0
        self._build(n_agents)

    def _build(self, n_agents: int):
        rng = np.random.default_rng(0)
        dims = [self.spec.obs_dim, *self.spec.hidden, self.spec.act_dim]
        self.W = [np.zeros((n_agents, dims[i + 1], dims[i]), dtype=np.float32)
                  for i in range(len(dims) - 1)]
        self.b = [np.zeros((n_agents, 1, dims[i + 1]), dtype=np.float32)
                  for i in range(len(dims) - 1)]

    def set_population(self, genomes: list[np.ndarray]):
        n = len(genomes)
        if n == 0:
            return
        if self.W[0].shape[0] != n:
            self._build(n)
        layers = [genome_to_layers(self.spec, g) for g in genomes]
        for li in range(len(self.W)):
            self.W[li] = np.stack([np.asarray(l[li][0], dtype=np.float32) for l in layers])
            self.b[li] = np.stack([np.asarray(l[li][1], dtype=np.float32) for l in layers])[:, None, :]

    def predict(self, obs: np.ndarray, indices: np.ndarray | None = None) -> np.ndarray:
        if obs.shape[0] == 0:
            return np.zeros((0, self.spec.act_dim), dtype=np.float32)
        t0 = time.perf_counter()
        idx = indices if indices is not None else np.arange(obs.shape[0])
        x = np.asarray(obs, dtype=np.float32)[:, None, :]
        for li in range(len(self.W)):
            W = self.W[li][idx]
            b = self.b[li][idx]
            x = x @ np.ascontiguousarray(W.transpose(0, 2, 1)) + b
            x = np.tanh(x)
        self.last_ms = (time.perf_counter() - t0) * 1000.0
        return x[:, 0, :].astype(np.float32)

    def warmup(self, obs_dim: int):
        self.predict(np.zeros((1, obs_dim), dtype=np.float32), np.zeros(1, dtype=int))


class TorchBackend:
    """Backend PyTorch: roda em CPU, CUDA ou DirectML (Intel/AMD no Windows)."""

    name = "torch"

    def __init__(self, spec: PolicySpec, n_agents: int = 1, device_id: str = "torch-cpu"):
        import torch
        self.torch = torch
        self.spec = spec
        self.device_id = device_id
        if device_id == "cuda" and torch.cuda.is_available():
            self.device = torch.device("cuda")
            self.device_desc = f"CUDA — {torch.cuda.get_device_name(0)}"
        elif device_id == "dml":
            import torch_directml
            self.device = torch_directml.device()
            try:
                self.device_desc = f"DirectML (GPU) — {torch_directml.device_name(0)}"
            except Exception:
                self.device_desc = f"DirectML (GPU) — {self.device}"
        else:
            self.device = torch.device("cpu")
            self.device_desc = f"CPU (PyTorch {torch.__version__})"
            self.device_id = "torch-cpu"
        self.W: list = []
        self.b: list = []
        self.last_ms = 0.0
        self._obs_buf = None
        self._build(n_agents)

    def _build(self, n_agents: int):
        torch = self.torch
        dims = [self.spec.obs_dim, *self.spec.hidden, self.spec.act_dim]
        self.W = [torch.zeros((n_agents, dims[i + 1], dims[i]), dtype=torch.float32,
                              device=self.device)
                  for i in range(len(dims) - 1)]
        self.b = [torch.zeros((n_agents, 1, dims[i + 1]), dtype=torch.float32,
                              device=self.device)
                  for i in range(len(dims) - 1)]
        self._obs_buf = torch.zeros((n_agents, self.spec.obs_dim), dtype=torch.float32,
                                    device=self.device)

    def set_population(self, genomes: list[np.ndarray]):
        import torch
        n = len(genomes)
        if n == 0:
            return
        if self.W[0].shape[0] != n:
            self._build(n)
        layers = [genome_to_layers(self.spec, g) for g in genomes]
        with torch.no_grad():
            for li in range(len(self.W)):
                w_np = np.stack([np.asarray(l[li][0], dtype=np.float32) for l in layers])
                b_np = np.stack([np.asarray(l[li][1], dtype=np.float32) for l in layers])
                self.W[li].copy_(torch.from_numpy(np.ascontiguousarray(w_np)).to(self.device))
                # bias: (B, saida) -> (B, 1, saida) antes de copiar
                b_t = torch.from_numpy(np.ascontiguousarray(b_np)).to(self.device).unsqueeze(1)
                self.b[li].copy_(b_t)

    def predict(self, obs: np.ndarray, indices: np.ndarray | None = None) -> np.ndarray:
        torch = self.torch
        if obs.shape[0] == 0:
            return np.zeros((0, self.spec.act_dim), dtype=np.float32)
        t0 = time.perf_counter()
        idx = indices if indices is not None else np.arange(obs.shape[0])
        bsz = len(idx)
        if self._obs_buf is None or self._obs_buf.shape[0] < bsz:
            self._obs_buf = torch.zeros((bsz, self.spec.obs_dim), dtype=torch.float32,
                                        device=self.device)
        obs_t = torch.from_numpy(np.ascontiguousarray(obs, dtype=np.float32))
        buf = self._obs_buf[:bsz]
        if buf.device.type == "cpu" and obs_t.device.type == "cpu":
            buf.copy_(obs_t)
        else:
            buf.copy_(obs_t.to(buf.device))
        x = buf.unsqueeze(1)
        with torch.no_grad():
            for li in range(len(self.W)):
                W = self.W[li][idx].transpose(1, 2)
                bb = self.b[li][idx]
                x = torch.matmul(x, W) + bb
                x = torch.tanh(x)
        out = x.squeeze(1)
        self.last_ms = (time.perf_counter() - t0) * 1000.0
        return out.detach().to("cpu").numpy().astype(np.float32)

    def warmup(self, obs_dim: int):
        try:
            self.predict(np.zeros((1, obs_dim), dtype=np.float32), np.zeros(1, dtype=int))
            self.predict(np.zeros((min(8, max(1, self.W[0].shape[0])), obs_dim), dtype=np.float32),
                         np.arange(min(8, max(1, self.W[0].shape[0]))))
        except Exception:
            pass


def create_backend(spec: PolicySpec, n_agents: int = 1, device_id: str = "auto"):
    """Cria o melhor backend disponível para o device pedido."""
    if device_id in (None, "", "auto"):
        device_id, _ = resolve_device("auto")
    if device_id == "cpu" or device_id == "numpy":
        return NumpyBackend(spec, n_agents)
    if torch_available():
        try:
            return TorchBackend(spec, n_agents, device_id)
        except Exception:
            return NumpyBackend(spec, n_agents)
    return NumpyBackend(spec, n_agents)
