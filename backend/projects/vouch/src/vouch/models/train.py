"""Train VouchNet on the seeded synthetic world (`make train-vouch`, CPU, well under a minute).

- Train/validation: one synthetic world (seed 11), split by *vendor* so no vendor is in both.
- Held-out test: a second world generated with a different seed (99): unseen vendors, unseen rings.
- Writes the bundle to the model registry and `projects/vouch/MODEL_CARD.md` with per-class
  precision/recall and the false-positive (hold) rate on honest and honest-but-unusual vendors.
"""

from __future__ import annotations

import argparse
import random
import time
from pathlib import Path
from typing import Any

import numpy as np

from hm_ml_common import ModelRegistry
from vouch.config import get_settings
from vouch.dataset import Row, build_rows
from vouch.domain import RISK_CLASSES, RiskClass
from vouch.features import CATEGORICAL_FEATURES, NUMERIC_FEATURES
from vouch.synth import generate_world

TRAIN_SEED, TEST_SEED = 11, 99
CARD_PATH = Path(__file__).resolve().parents[2] / "MODEL_CARD.md"


def _arrays(rows: list[Row]) -> tuple[np.ndarray, list[dict[str, str]], np.ndarray, np.ndarray]:
    x = np.array([[r.numeric[n] for n in NUMERIC_FEATURES] for r in rows], dtype=np.float32)
    cats = [r.categorical for r in rows]
    y = np.array(
        [
            [float(r.label.risk_class == c) for c in RISK_CLASSES]
            + [float(r.label.risk_class == RiskClass.HONEST)]
            for r in rows
        ],
        dtype=np.float32,
    )
    w = np.array([3.0 if r.label.honest_unusual else 1.0 for r in rows], dtype=np.float32)
    return x, cats, y, w


def train(
    registry: ModelRegistry | None = None,
    seed: int = 0,
    n_train_vendors: int = 2400,
    n_test_vendors: int = 1000,
    epochs: int = 60,
    write_card: bool = True,
) -> str:
    import torch
    from torch import nn

    from vouch.models.net import HEADS, Bundle, VouchNet

    t0 = time.time()
    torch.manual_seed(seed)
    np.random.seed(seed)
    rows = build_rows(generate_world(TRAIN_SEED + seed, n_train_vendors))
    test_rows = build_rows(generate_world(TEST_SEED + seed, n_test_vendors))

    vendor_ids = sorted({r.invoice.vendor_id for r in rows})
    random.Random(seed).shuffle(vendor_ids)
    val_vendors = set(vendor_ids[: len(vendor_ids) // 5])
    tr = [r for r in rows if r.invoice.vendor_id not in val_vendors]
    va = [r for r in rows if r.invoice.vendor_id in val_vendors]

    x_tr, c_tr, y_tr, w_tr = _arrays(tr)
    mean, std = x_tr.mean(0), x_tr.std(0) + 1e-6
    vocab = {c: {v: i for i, v in enumerate(sorted({r[c] for r in c_tr}))} for c in CATEGORICAL_FEATURES}
    arch = {"emb_dim": 4, "hidden": 64}
    net = VouchNet(len(NUMERIC_FEATURES), [len(vocab[c]) for c in CATEGORICAL_FEATURES], **arch)

    def enc(cats: list[dict[str, str]]) -> torch.Tensor:
        return torch.tensor([[vocab[c].get(r[c], len(vocab[c])) for c in CATEGORICAL_FEATURES] for r in cats])

    X = torch.from_numpy((x_tr - mean) / std)
    C, Y, W = enc(c_tr), torch.from_numpy(y_tr), torch.from_numpy(w_tr)
    honest = Y[:, -1] > 0.5
    opt = torch.optim.Adam(net.parameters(), lr=3e-3, weight_decay=1e-4)
    bce = nn.BCEWithLogitsLoss(reduction="none")
    for _epoch in range(epochs):
        net.train()
        perm = torch.randperm(len(X))
        for start in range(0, len(X), 256):
            idx = perm[start : start + 256]
            logits, recon = net(X[idx], C[idx])
            target = Y[idx] * 0.94 + 0.03  # label smoothing keeps probabilities calibrated away from 0/1
            cls_loss = (bce(logits, target).mean(1) * W[idx]).mean()
            h = honest[idx]
            ae_loss = ((recon[h] - X[idx][h]) ** 2).mean() if h.any() else torch.tensor(0.0)
            loss = cls_loss + 0.5 * ae_loss
            opt.zero_grad()
            loss.backward()
            opt.step()

    net.eval()
    with torch.no_grad():
        _, recon = net(X[honest], C[honest])
        errs = ((recon - X[honest]) ** 2).mean(1).numpy()
    state: dict[str, Any] = {
        "feature_names": NUMERIC_FEATURES,
        "categorical_names": CATEGORICAL_FEATURES,
        "vocab": vocab,
        "mean": mean.tolist(),
        "std": std.tolist(),
        "recon_quantiles": np.quantile(errs, np.linspace(0, 1, 201)[1:-1]).tolist(),
        "thresholds": {h: 0.5 for h in HEADS},
        "background": x_tr[
            np.random.default_rng(seed).choice(len(x_tr), size=min(600, len(x_tr)), replace=False)
        ].tolist(),
        "weights": {k: v.detach().clone() for k, v in net.state_dict().items()},
        "arch": arch,
    }
    bundle = Bundle(state)
    metrics = evaluate(bundle, test_rows)
    metrics["val"] = evaluate(bundle, va)["per_class"]
    metrics["train_seconds"] = round(time.time() - t0, 1)
    metrics["n_train"], metrics["n_val"], metrics["n_test"] = len(tr), len(va), len(test_rows)

    registry = registry or ModelRegistry(get_settings().model_registry_dir)
    name = get_settings().model_name
    version = registry.save(
        name,
        state,
        metrics=_flat(metrics),
        params={"algo": "VouchNet", "epochs": epochs, "seed": seed, **arch},
    )
    if write_card:
        CARD_PATH.write_text(model_card(name, version, metrics))
    pc = metrics["per_class"]
    print(
        f"saved {name}:{version} in {metrics['train_seconds']}s | "
        + " ".join(f"{k}: P={v['precision']:.2f} R={v['recall']:.2f}" for k, v in pc.items())
        + f" | honest hold rate={metrics['system']['honest_hold_rate']:.3f}"
    )
    return version


def _flat(metrics: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for cls, m in metrics["per_class"].items():
        for k, v in m.items():
            out[f"{cls}_{k}"] = float(v)
    for k, v in metrics["system"].items():
        out[f"system_{k}"] = float(v)
    return out


def evaluate(bundle: Any, rows: list[Row]) -> dict[str, Any]:
    """Model-level per-class metrics plus system-level hold rates with the real policy."""
    from hm_ml_common.metrics import roc_auc
    from vouch.cards import PaymentCard
    from vouch.domain import Lane, ModelScores
    from vouch.kernel import Limits
    from vouch.policy import build_policy, evaluate_card

    x = np.array([[r.numeric[n] for n in NUMERIC_FEATURES] for r in rows], dtype=np.float32)
    out = bundle.predict(x, bundle.encode_cats([r.categorical for r in rows]))
    per_class: dict[str, dict[str, float]] = {}
    for cls in RISK_CLASSES:
        y = np.array([r.label.risk_class == cls for r in rows])
        p = out[cls.value]
        pred = p >= 0.5
        tp, fp, fn = int((pred & y).sum()), int((pred & ~y).sum()), int((~pred & y).sum())
        per_class[cls.value] = {
            "precision": tp / max(tp + fp, 1),
            "recall": tp / max(tp + fn, 1),
            "roc_auc": float(roc_auc(y.astype(int), p)) if 0 < y.sum() < len(y) else float("nan"),
            "support": int(y.sum()),
        }

    policy, limits = build_policy(Limits()), Limits()
    holds = {"honest": [0, 0], "honest_unusual": [0, 0], "bad": [0, 0]}
    fast = {"honest": 0}
    for i, r in enumerate(rows):
        risk = {c.value: float(out[c.value][i]) for c in RISK_CLASSES}
        scores = ModelScores(
            risk=risk,
            anomaly=float(out["anomaly"][i]),
            legitimacy=float(out["legitimacy"][i]),
            top_class=max(risk, key=risk.get),
            model_version="eval",
            scorer="eval",
        )
        from dataclasses import asdict

        card = PaymentCard(
            id=r.invoice.id,
            run_id="eval",
            invoice=r.invoice,
            vendor=r.vendor,
            payable_cents=r.invoice.amount_cents,
            checks=asdict(r.checks),
            flags=r.checks.flags(),
            scores=scores,
        )
        outcome = evaluate_card(policy, card)
        held = outcome.lane == Lane.HOLD
        if r.label.risk_class == RiskClass.HONEST:
            holds["honest"][0] += held
            holds["honest"][1] += 1
            fast["honest"] += outcome.lane == Lane.FAST_PAY
            if r.label.honest_unusual:
                holds["honest_unusual"][0] += held
                holds["honest_unusual"][1] += 1
        else:
            holds["bad"][0] += held
            holds["bad"][1] += 1
    system = {
        "honest_hold_rate": holds["honest"][0] / max(holds["honest"][1], 1),
        "honest_unusual_hold_rate": holds["honest_unusual"][0] / max(holds["honest_unusual"][1], 1),
        "bad_actor_catch_rate": holds["bad"][0] / max(holds["bad"][1], 1),
        "honest_fast_pay_rate": fast["honest"] / max(holds["honest"][1], 1),
        "n_honest": holds["honest"][1],
        "n_honest_unusual": holds["honest_unusual"][1],
        "n_bad": holds["bad"][1],
    }
    _ = limits
    return {"per_class": per_class, "system": system}


def model_card(name: str, version: str, m: dict[str, Any]) -> str:
    pc, sysm = m["per_class"], m["system"]
    rows = "\n".join(
        f"| {cls} | {v['precision']:.3f} | {v['recall']:.3f} | {v['roc_auc']:.3f} | {v['support']} |"
        for cls, v in pc.items()
    )
    return f"""# Model card: {name} ({version})

Generated by `make train-vouch` (vouch/models/train.py). Do not edit by hand.

## What it is
VouchNet, a small PyTorch model trained from scratch on CPU in {m["train_seconds"]}s:
- Entity embeddings (dim 4) for vendor country, category, bank country, and the AP clerk who submitted the invoice.
- Shared 2-layer MLP trunk with four sigmoid heads: `ato_bec`, `insider`, `fake_vendor` risk, plus `legitimacy`.
- Autoencoder over the numeric features, trained on honest invoices only. Its reconstruction error, as a
  percentile of honest training error, is the `anomaly` score.
- Graph signal for rings: features from the vendor-attribute graph (vendors linked by shared bank account,
  tax id, phone, address, or non-public email domain): shared-attribute degrees, connected-component size,
  share of new vendors in the component, and one round of parameter-free message passing (mean identity
  red flags of linked vendors).
- LIME explanations per card: on the dominant risk head, or on the legitimacy head for clean cards.

## Data
Seeded synthetic payables world (vouch/synth.py): vendors, invoices, bank accounts, addresses, phones,
tax ids, payment history. Bad actors: ATO/BEC (bank or contact changed, urgency, lookalike remit email),
insider abuse (duplicates, split invoices under the approval limit, creeping amounts, no PO/delivery),
fake/synthetic vendors (invalid tax ids, VOIP phones, virtual addresses, rings sharing attributes).
Honest-but-unusual vendors (new small vendors, confirmed bank changes, seasonal spikes, shared business-park
addresses) are oversampled 3x in the loss so false positives are measured and penalised.

- Train / validation: world seed {TRAIN_SEED}, split by vendor (train {m["n_train"]} invoices, validation {m["n_val"]}).
- **Held-out test: separate world seed {TEST_SEED} ({m["n_test"]} invoices), unseen vendors and rings.**

## Held-out test metrics (model heads, threshold 0.5)
| class | precision | recall | ROC-AUC | support |
|---|---|---|---|---|
{rows}

## System-level outcomes on the held-out test (kernel checks + model + policy)
| metric | value |
|---|---|
| bad-actor invoices put on HOLD | {sysm["bad_actor_catch_rate"]:.1%} (n={sysm["n_bad"]}) |
| **honest invoices put on HOLD (false-positive rate)** | **{sysm["honest_hold_rate"]:.1%}** (n={sysm["n_honest"]}) |
| honest-but-unusual invoices put on HOLD | {sysm["honest_unusual_hold_rate"]:.1%} (n={sysm["n_honest_unusual"]}) |
| honest invoices routed to the fast-pay lane | {sysm["honest_fast_pay_rate"]:.1%} |

A HOLD is never a denial: every hold has a resolution path (out-of-band confirmation, owner review, appeal).
Honest vendors whose bank change was already confirmed out-of-band are not held. The fast-pay share is low
because the fast-pay limit ($2,500) is below most synthetic invoice amounts.

Reading the numbers: ATO/BEC is near-perfect because a bank-detail change that nobody confirmed is an explicit
kernel signal. The model earns its keep on insider and fake-vendor patterns and, above all, on the
legitimacy head that keeps honest-but-unusual vendors (new, small, seasonal) out of the hold queue.

## Limitations
- Synthetic data only. The generator encodes our assumptions about fraud patterns, so these metrics measure
  how well the model learns those patterns, not real-world performance.
- Identity checks (tax id checksum, VOIP lookup, virtual address) are stand-ins for TIN matching, carrier
  lookup and address-verification APIs.
- The clerk embedding can learn "this clerk is risky"; in production that needs governance (it is a
  signal for review, never an automatic action against an employee).
- Thresholds are fixed by policy (high risk >= 0.70 with legitimacy < 0.60), not tuned per customer.
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    train(epochs=args.epochs, seed=args.seed)


if __name__ == "__main__":
    main()
