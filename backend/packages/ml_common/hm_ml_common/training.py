"""PyTorch training utilities (requires the `ml` extra). CPU-friendly defaults for a laptop or small VM."""

from __future__ import annotations

import copy
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

log = logging.getLogger(__name__)


def set_seed(seed: int = 0) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def get_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def make_loader(X: np.ndarray, y: np.ndarray, batch_size: int = 256, shuffle: bool = True) -> DataLoader:
    ds = TensorDataset(torch.as_tensor(X, dtype=torch.float32), torch.as_tensor(y, dtype=torch.long))
    return DataLoader(ds, batch_size=batch_size, shuffle=shuffle)


class TabularMLP(nn.Module):
    """Small baseline classifier for tabular features."""

    def __init__(
        self, in_features: int, hidden: tuple[int, ...] = (64, 32), n_classes: int = 2, dropout: float = 0.1
    ):
        super().__init__()
        layers: list[nn.Module] = []
        prev = in_features
        for h in hidden:
            layers += [nn.Linear(prev, h), nn.ReLU(), nn.Dropout(dropout)]
            prev = h
        layers.append(nn.Linear(prev, n_classes))
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


@dataclass
class TrainHistory:
    train_loss: list[float] = field(default_factory=list)
    val_loss: list[float] = field(default_factory=list)
    best_epoch: int = -1


def _epoch(model: nn.Module, loader: DataLoader, loss_fn: nn.Module, device: torch.device, opt=None) -> float:
    model.train(opt is not None)
    total, n = 0.0, 0
    with torch.set_grad_enabled(opt is not None):
        for xb, yb in loader:
            xb, yb = xb.to(device), yb.to(device)
            loss = loss_fn(model(xb), yb)
            if opt is not None:
                opt.zero_grad()
                loss.backward()
                opt.step()
            total += loss.item() * len(yb)
            n += len(yb)
    return total / max(n, 1)


def train_classifier(
    model: nn.Module,
    train_loader: DataLoader,
    val_loader: DataLoader | None = None,
    *,
    epochs: int = 20,
    lr: float = 1e-3,
    weight_decay: float = 0.0,
    class_weights: list[float] | None = None,
    patience: int = 5,
    device: torch.device | None = None,
    on_epoch: Callable[[int, float, float | None], None] | None = None,
) -> TrainHistory:
    """Adam + cross-entropy with early stopping on val loss; restores the best weights."""
    device = device or get_device()
    model.to(device)
    weight = torch.tensor(class_weights, dtype=torch.float32, device=device) if class_weights else None
    loss_fn = nn.CrossEntropyLoss(weight=weight)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    history = TrainHistory()
    best_loss, best_state, stale = float("inf"), copy.deepcopy(model.state_dict()), 0

    for epoch in range(epochs):
        tr = _epoch(model, train_loader, loss_fn, device, opt)
        va = _epoch(model, val_loader, loss_fn, device) if val_loader is not None else None
        history.train_loss.append(tr)
        if va is not None:
            history.val_loss.append(va)
        log.info("epoch %d train_loss=%.4f val_loss=%s", epoch, tr, f"{va:.4f}" if va is not None else "-")
        if on_epoch:
            on_epoch(epoch, tr, va)
        monitored = va if va is not None else tr
        if monitored < best_loss - 1e-5:
            best_loss, best_state, stale, history.best_epoch = (
                monitored,
                copy.deepcopy(model.state_dict()),
                0,
                epoch,
            )
        else:
            stale += 1
            if stale >= patience:
                break

    model.load_state_dict(best_state)
    model.eval()
    return history


def predict_proba_fn(
    model: nn.Module, device: torch.device | None = None
) -> Callable[[np.ndarray], np.ndarray]:
    """numpy-in / numpy-out probability function: plug straight into TabularExplainer.explain()."""
    device = device or next(model.parameters()).device

    def predict(X: np.ndarray) -> np.ndarray:
        model.eval()
        with torch.no_grad():
            logits = model(torch.as_tensor(np.asarray(X), dtype=torch.float32, device=device))
            return torch.softmax(logits, dim=-1).cpu().numpy()

    return predict
