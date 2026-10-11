"""VouchNet: entity embeddings + shared trunk + per-class risk heads + legitimacy head, and an
autoencoder (trained on honest invoices only) whose reconstruction error is the anomaly score."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch
from torch import nn

from vouch.domain import RISK_CLASSES

HEADS = [c.value for c in RISK_CLASSES] + ["legitimacy"]


class VouchNet(nn.Module):
    def __init__(self, n_numeric: int, cardinalities: list[int], emb_dim: int = 4, hidden: int = 64):
        super().__init__()
        self.embeddings = nn.ModuleList(
            nn.Embedding(card + 1, emb_dim) for card in cardinalities
        )  # +1: unknown
        width = n_numeric + emb_dim * len(cardinalities)
        self.trunk = nn.Sequential(
            nn.Linear(width, hidden), nn.ReLU(), nn.Dropout(0.1), nn.Linear(hidden, hidden), nn.ReLU()
        )
        self.heads = nn.Linear(hidden, len(HEADS))
        self.encoder = nn.Sequential(nn.Linear(n_numeric, 16), nn.ReLU(), nn.Linear(16, 6))
        self.decoder = nn.Sequential(nn.Linear(6, 16), nn.ReLU(), nn.Linear(16, n_numeric))

    def embed(self, cats: torch.Tensor) -> torch.Tensor:
        return torch.cat([emb(cats[:, i]) for i, emb in enumerate(self.embeddings)], dim=1)

    def forward(self, x: torch.Tensor, cats: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        logits = self.heads(self.trunk(torch.cat([x, self.embed(cats)], dim=1)))
        recon = self.decoder(self.encoder(x))
        return logits, recon


class Bundle:
    """Everything needed to serve the model; pickled into the registry (torch tensors as state_dict)."""

    def __init__(self, state: dict[str, Any]):
        self.state = state
        self.feature_names: list[str] = state["feature_names"]
        self.categorical_names: list[str] = state["categorical_names"]
        self.vocab: dict[str, dict[str, int]] = state["vocab"]
        self.mean = np.asarray(state["mean"], dtype=np.float32)
        self.std = np.asarray(state["std"], dtype=np.float32)
        self.recon_quantiles = np.asarray(state["recon_quantiles"], dtype=np.float32)
        self.thresholds: dict[str, float] = state["thresholds"]
        self.background = np.asarray(state["background"], dtype=np.float32)
        self.net = VouchNet(
            len(self.feature_names),
            [len(self.vocab[c]) for c in self.categorical_names],
            **state.get("arch", {}),
        )
        self.net.load_state_dict(state["weights"])
        self.net.eval()

    def encode_cats(self, rows: list[dict[str, str]]) -> np.ndarray:
        return np.array(
            [
                [self.vocab[c].get(r.get(c, ""), len(self.vocab[c])) for c in self.categorical_names]
                for r in rows
            ],
            dtype=np.int64,
        )

    @torch.no_grad()
    def predict(self, x_raw: np.ndarray, cats: np.ndarray) -> dict[str, np.ndarray]:
        x = torch.from_numpy((np.asarray(x_raw, dtype=np.float32) - self.mean) / self.std)
        c = torch.from_numpy(np.asarray(cats, dtype=np.int64))
        logits, recon = self.net(x, c)
        probs = torch.sigmoid(logits).numpy()
        err = ((recon - x) ** 2).mean(dim=1).numpy()
        anomaly = np.searchsorted(self.recon_quantiles, err) / len(self.recon_quantiles)
        out = {h: probs[:, i] for i, h in enumerate(HEADS)}
        out["anomaly"] = anomaly.astype(np.float32)
        return out
